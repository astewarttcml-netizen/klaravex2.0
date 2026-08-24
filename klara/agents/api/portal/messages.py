"""
app/api/portal/messages.py
───────────────────────────
Per-project message thread — client-facing endpoints (portal-231).

  GET  /api/v1/portal/projects/{id}/messages   — list thread (oldest→newest)
  POST /api/v1/portal/projects/{id}/messages   — client posts a message

Authorization: every query is filtered by client.id from the JWT.
A client cannot read or post to another client's project thread.

Pagination: offset-based, oldest-first (natural chat order). Use
`limit` + `offset` to scroll through history. `has_more` tells the
frontend whether an older page exists.

Email notification: when the client posts, Klara AI emails Anthony
(OWNER_EMAIL from settings) so he knows there's a new message waiting.
Notification failures are logged but never propagate to the client.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import get_settings
from app.core.portal_auth import get_current_portal_client
from klara.rarv.runtime import get_db
from klara.rarv.portal import Client, Project
from klara.rarv.project_message import ProjectMessage, SENDER_CLIENT
from klara.rarv.runtime.email_sender import send_email

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    id: str
    project_id: str
    sender_type: str        # 'client' | 'admin'
    sender_name: str
    body: str
    is_read: bool           # from the client's perspective
    created_at: str


class MessageListResponse(BaseModel):
    project_id: str
    items: List[MessageResponse]
    count: int
    has_more: bool
    unread_count: int       # admin messages the client hasn't read yet


class PostMessageRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=10_000)


class PostMessageResponse(BaseModel):
    id: str
    project_id: str
    sender_type: str
    sender_name: str
    body: str
    created_at: str


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _get_project_for_client(
    project_id: str, client: Client, db: AsyncSession
) -> Project:
    """Load project, enforcing ownership. Raises 404 on miss or wrong client."""
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.client_id == client.id,
        )
    )
    project: Project | None = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    return project


def _to_response(msg: ProjectMessage) -> MessageResponse:
    # From the client's perspective, a message is 'read' if:
    # - they sent it (they obviously saw it), or
    # - it was sent by admin and read_by_client_at is set.
    is_read = msg.sender_type == SENDER_CLIENT or msg.read_by_client_at is not None
    return MessageResponse(
        id=msg.id,
        project_id=msg.project_id,
        sender_type=msg.sender_type,
        sender_name=msg.sender_name,
        body=msg.body,
        is_read=is_read,
        created_at=msg.created_at.isoformat(),
    )


async def _notify_admin_new_message(
    project_title: str, client_name: str, body: str
) -> None:
    """Email Anthony that the client posted a new message. Fire-and-forget."""
    settings = get_settings()
    owner_email = getattr(settings, "owner_email", None) or getattr(
        settings, "alert_email", None
    )
    if not owner_email:
        logger.warning(
            "portal.messages.notify_admin.skipped",
            reason="owner_email not configured",
        )
        return

    snippet = body[:300] + ("…" if len(body) > 300 else "")
    await send_email(
        settings,
        to_email=owner_email,
        to_name="Anthony",
        subject=f"[Client Portal] New message — {project_title}",
        body_html=(
            f"<p><strong>{client_name}</strong> sent a new message in "
            f"project <em>{project_title}</em>:</p>"
            f"<blockquote>{snippet}</blockquote>"
            f"<p>Log in to the admin panel to reply.</p>"
        ),
        body_text=(
            f"{client_name} sent a new message in '{project_title}':\n\n"
            f"{snippet}\n\nLog in to the admin panel to reply."
        ),
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get(
    "/{project_id}/messages",
    response_model=MessageListResponse,
    summary="List project message thread",
)
async def list_messages(
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the message thread for a project, oldest-first (natural chat order).

    Also marks all admin messages as read by the client — calling this
    endpoint is the "open thread" action.

    `unread_count` in the response reflects the count BEFORE marking, so the
    frontend can show a badge transition ("3 unread → all read").
    """
    project = await _get_project_for_client(project_id, client, db)

    # Count unread admin messages before marking them read
    unread_result = await db.execute(
        select(ProjectMessage).where(
            ProjectMessage.project_id == project_id,
            ProjectMessage.client_id == client.id,
            ProjectMessage.sender_type == "admin",
            ProjectMessage.read_by_client_at.is_(None),
        )
    )
    unread_msgs = list(unread_result.scalars().all())
    unread_count = len(unread_msgs)

    # Mark those admin messages as read
    now = datetime.now(timezone.utc)
    for msg in unread_msgs:
        msg.read_by_client_at = now

    # Fetch one extra to compute has_more
    result = await db.execute(
        select(ProjectMessage)
        .where(
            ProjectMessage.project_id == project_id,
            ProjectMessage.client_id == client.id,
        )
        .order_by(ProjectMessage.created_at.asc())
        .limit(limit + 1)
        .offset(offset)
    )
    all_rows: list[ProjectMessage] = list(result.scalars().all())
    has_more = len(all_rows) > limit
    page = all_rows[:limit]

    if unread_msgs:
        await db.commit()

    logger.info(
        "portal.messages.listed",
        client_id=client.id,
        project_id=project_id,
        count=len(page),
        unread_marked=unread_count,
    )
    return MessageListResponse(
        project_id=project_id,
        items=[_to_response(m) for m in page],
        count=len(page),
        has_more=has_more,
        unread_count=unread_count,
    )


@router.post(
    "/{project_id}/messages",
    response_model=PostMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Post a message to the project thread",
)
async def post_message(
    project_id: str,
    req: PostMessageRequest,
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Client posts a new message to the project thread.

    On success:
    - Message is persisted with sender_type='client'.
    - Anthony receives a notification email (best-effort — failure is logged
      but never surfaces as an error to the client).
    """
    project = await _get_project_for_client(project_id, client, db)

    msg = ProjectMessage(
        project_id=project_id,
        client_id=client.id,
        sender_type=SENDER_CLIENT,
        sender_name=client.name,
        body=req.body.strip(),
        # Client authored it — mark it as read from the client side immediately
        read_by_client_at=datetime.now(timezone.utc),
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    logger.info(
        "portal.messages.posted",
        client_id=client.id,
        project_id=project_id,
        message_id=msg.id,
        body_length=len(req.body),
    )

    # Fire-and-forget notification — never let email failure break the response
    try:
        await _notify_admin_new_message(
            project_title=project.title,
            client_name=client.name,
            body=req.body,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "portal.messages.notify_admin.failed",
            error=str(exc),
            project_id=project_id,
        )

    return PostMessageResponse(
        id=msg.id,
        project_id=msg.project_id,
        sender_type=msg.sender_type,
        sender_name=msg.sender_name,
        body=msg.body,
        created_at=msg.created_at.isoformat(),
    )
