"""
app/api/messages_admin.py
──────────────────────────
Admin-only endpoints for the per-project message thread (portal-231).

  GET  /api/v1/admin/messages            — inbox: projects with unread client msgs
  GET  /api/v1/admin/messages/{project_id} — full thread; marks client msgs read
  POST /api/v1/admin/messages/{project_id} — admin posts a reply

Authorization: X-API-Key (verify_api_key dependency).

Design:
- GET /{project_id} is the "open thread" action from the admin side.  All
  unread client messages are marked read_by_admin_at = now() in the same
  request so badge counts are accurate on refresh.
- POST sends a fire-and-forget email to the client so they know a reply is
  waiting.  Email failure is logged but never bubbles up to the caller.
- The inbox (GET /) returns one row per project that has client messages
  Anthony hasn't read yet — sorted by oldest unread first so the most
  urgent thread floats to the top.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import verify_api_key
from app.database import get_db
from app.models.portal import Client, Project
from app.models.project_message import ProjectMessage, SENDER_ADMIN, SENDER_CLIENT
from app.services.email_sender import send_transactional_email

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────────

class AdminMessageResponse(BaseModel):
    id: str
    project_id: str
    client_id: str
    sender_type: str
    sender_name: str
    body: str
    read_by_client_at: Optional[str]
    read_by_admin_at: Optional[str]
    created_at: str


class AdminThreadResponse(BaseModel):
    project_id: str
    project_title: str
    client_id: str
    client_name: str
    client_email: str
    items: List[AdminMessageResponse]
    count: int
    has_more: bool
    unread_by_admin: int    # count before marking (for UI transition)


class AdminInboxItem(BaseModel):
    project_id: str
    project_title: str
    client_id: str
    client_name: str
    unread_count: int
    last_message_at: str    # ISO timestamp of the oldest unread client message


class AdminPostRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=10_000)


class AdminPostResponse(BaseModel):
    id: str
    project_id: str
    sender_type: str
    sender_name: str
    body: str
    created_at: str


# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_admin_response(msg: ProjectMessage) -> AdminMessageResponse:
    return AdminMessageResponse(
        id=msg.id,
        project_id=msg.project_id,
        client_id=msg.client_id,
        sender_type=msg.sender_type,
        sender_name=msg.sender_name,
        body=msg.body,
        read_by_client_at=(
            msg.read_by_client_at.isoformat() if msg.read_by_client_at else None
        ),
        read_by_admin_at=(
            msg.read_by_admin_at.isoformat() if msg.read_by_admin_at else None
        ),
        created_at=msg.created_at.isoformat(),
    )


async def _load_project_with_client(
    project_id: str, db: AsyncSession
) -> tuple[Project, Client]:
    """Load a project and its owning client. Raises 404 if either is missing."""
    project_result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project: Project | None = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    client_result = await db.execute(
        select(Client).where(Client.id == project.client_id)
    )
    client: Client | None = client_result.scalar_one_or_none()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found.",
        )

    return project, client


async def _notify_client_admin_replied(
    client_email: str,
    client_name: str,
    project_title: str,
    body: str,
) -> None:
    """Email the client that Anthony has replied. Fire-and-forget."""
    settings = get_settings()
    snippet = body[:300] + ("…" if len(body) > 300 else "")
    portal_url = getattr(settings, "portal_url", None) or "https://klaravex.de/portal"
    await send_transactional_email(
        settings,
        to_email=client_email,
        to_name=client_name,
        subject=f"[Klaravex] New message — {project_title}",
        body_html=(
            f"<p>Hi <strong>{client_name}</strong>,</p>"
            f"<p>Anthony has posted a new message in project "
            f"<em>{project_title}</em>:</p>"
            f"<blockquote>{snippet}</blockquote>"
            f"<p><a href=\"{portal_url}\">Log in to the portal to view and reply.</a></p>"
        ),
        body_text=(
            f"Hi {client_name},\n\n"
            f"Anthony has posted a new message in project '{project_title}':\n\n"
            f"{snippet}\n\n"
            f"Log in to the portal to view and reply: {portal_url}"
        ),
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=List[AdminInboxItem],
    dependencies=[Depends(verify_api_key)],
    summary="Inbox — projects with unread client messages",
)
async def list_unread_inbox(
    db: AsyncSession = Depends(get_db),
):
    """
    Return one entry per project that has client messages admin hasn't read yet.

    Sorted by the oldest unread message per project (most overdue first) so
    the admin can triage systematically.
    """
    # Grab all unread-by-admin client messages with project + client info
    result = await db.execute(
        select(ProjectMessage, Project, Client)
        .join(Project, Project.id == ProjectMessage.project_id)
        .join(Client, Client.id == ProjectMessage.client_id)
        .where(
            ProjectMessage.sender_type == SENDER_CLIENT,
            ProjectMessage.read_by_admin_at.is_(None),
        )
        .order_by(ProjectMessage.created_at.asc())
    )
    rows = result.all()

    # Aggregate by project_id
    seen: dict[str, AdminInboxItem] = {}
    for msg, project, client in rows:
        if msg.project_id not in seen:
            seen[msg.project_id] = AdminInboxItem(
                project_id=project.id,
                project_title=project.title,
                client_id=client.id,
                client_name=client.name,
                unread_count=0,
                last_message_at=msg.created_at.isoformat(),
            )
        item = seen[msg.project_id]
        # Build a new object since Pydantic models are immutable by default
        seen[msg.project_id] = AdminInboxItem(
            project_id=item.project_id,
            project_title=item.project_title,
            client_id=item.client_id,
            client_name=item.client_name,
            unread_count=item.unread_count + 1,
            last_message_at=item.last_message_at,  # oldest stays (sorted asc)
        )

    inbox = list(seen.values())
    logger.info("admin.messages.inbox.listed", unread_projects=len(inbox))
    return inbox


@router.get(
    "/{project_id}",
    response_model=AdminThreadResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Full message thread for a project (marks client msgs read)",
)
async def get_project_thread(
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the full message thread for a project, oldest-first.

    Marks all unread client messages as read_by_admin_at = now() in the same
    request — this is the "open thread" action from the admin side.
    `unread_by_admin` reflects the count BEFORE marking.
    """
    project, client = await _load_project_with_client(project_id, db)

    # Count unread client messages before marking
    unread_result = await db.execute(
        select(ProjectMessage).where(
            ProjectMessage.project_id == project_id,
            ProjectMessage.sender_type == SENDER_CLIENT,
            ProjectMessage.read_by_admin_at.is_(None),
        )
    )
    unread_msgs = list(unread_result.scalars().all())
    unread_count = len(unread_msgs)

    # Mark them read
    now = datetime.now(timezone.utc)
    for msg in unread_msgs:
        msg.read_by_admin_at = now

    # Fetch page (oldest-first, +1 for has_more)
    result = await db.execute(
        select(ProjectMessage)
        .where(ProjectMessage.project_id == project_id)
        .order_by(ProjectMessage.created_at.asc())
        .limit(limit + 1)
        .offset(offset)
    )
    all_rows = list(result.scalars().all())
    has_more = len(all_rows) > limit
    page = all_rows[:limit]

    if unread_msgs:
        await db.commit()

    logger.info(
        "admin.messages.thread.viewed",
        project_id=project_id,
        count=len(page),
        unread_marked=unread_count,
    )
    return AdminThreadResponse(
        project_id=project.id,
        project_title=project.title,
        client_id=client.id,
        client_name=client.name,
        client_email=client.email,
        items=[_to_admin_response(m) for m in page],
        count=len(page),
        has_more=has_more,
        unread_by_admin=unread_count,
    )


@router.post(
    "/{project_id}",
    response_model=AdminPostResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key)],
    summary="Post an admin reply to a project thread",
)
async def post_admin_reply(
    project_id: str,
    req: AdminPostRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Anthony posts a reply to a project's message thread.

    On success:
    - Message persisted with sender_type='admin', sender_name='Anthony'.
    - Client receives a notification email (best-effort — failure is logged
      but never surfaces as an error to the admin).
    """
    project, client = await _load_project_with_client(project_id, db)

    msg = ProjectMessage(
        project_id=project_id,
        client_id=project.client_id,
        sender_type=SENDER_ADMIN,
        sender_name="Anthony",  # Always admin's name; expand if multi-admin later
        body=req.body.strip(),
        # Admin-authored: mark as read from admin side immediately
        read_by_admin_at=datetime.now(timezone.utc),
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    logger.info(
        "admin.messages.reply.posted",
        project_id=project_id,
        message_id=msg.id,
        body_length=len(req.body),
        client_id=client.id,
    )

    # Fire-and-forget notification to client
    try:
        await _notify_client_admin_replied(
            client_email=client.email,
            client_name=client.name,
            project_title=project.title,
            body=req.body,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "admin.messages.notify_client.failed",
            error=str(exc),
            project_id=project_id,
        )

    return AdminPostResponse(
        id=msg.id,
        project_id=msg.project_id,
        sender_type=msg.sender_type,
        sender_name=msg.sender_name,
        body=msg.body,
        created_at=msg.created_at.isoformat(),
    )
