"""
app/api/portal_files_admin.py
──────────────────────────────
Admin-only endpoints for managing ClientFile lifecycle labels (portal-241)
and viewing client file reviews / feedback (portal-242).

  GET   /api/v1/admin/files                      — list files including drafts
  PATCH /api/v1/admin/files/{id}/label           — promote / demote a file
  GET   /api/v1/admin/files/feedback             — list all reviews (filterable)
  GET   /api/v1/admin/files/{id}/feedback        — list reviews for one file

Label promotion side-effect:
  When a file is promoted to "approved" or "delivered", PortalNotifierAgent
  (P2) is invoked automatically to email the client that a new file is ready.
  The notification fires after the label is committed; a notification failure
  does NOT roll back the label change (the label update is the primary action).
"""
from __future__ import annotations

import uuid as _uuid
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import AgentContext
from app.agents.registry import registry
from klara.rarv.runtime import get_settings, Settings
from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.file_review import FileRating, FileReview
from klara.rarv.portal import ClientFile, FileLabel

logger = structlog.get_logger(__name__)

router = APIRouter()

# Labels that warrant an outbound client notification.
_NOTIFY_ON_LABELS = {FileLabel.approved.value, FileLabel.delivered.value}


# ── Schemas ───────────────────────────────────────────────────────────────────

class FileLabelUpdate(BaseModel):
    label: FileLabel = Field(
        ...,
        description="New lifecycle label: draft, approved, or delivered.",
    )
    notify_url: Optional[str] = Field(
        None,
        description=(
            "Public URL the client can use to view/download this file in the portal. "
            "If omitted, a generic portal dashboard URL is used in the notification."
        ),
    )
    notify_notes: Optional[str] = Field(
        None,
        max_length=500,
        description="Optional short message included in the notification email.",
    )


class AdminFileItem(BaseModel):
    id: str
    client_id: str
    project_id: Optional[str]
    title: str
    label: str
    original_filename: Optional[str]
    uploaded_at: str
    notification_sent: Optional[bool] = None
    # file_path intentionally omitted even from admin responses —
    # path management happens out-of-band (sftp / scp).


class FeedbackAdminItem(BaseModel):
    """A single client review as seen by admin — includes client_id."""
    id: str
    file_id: str
    client_id: str
    rating: str
    comment: Optional[str]
    created_at: str
    updated_at: str


def _review_to_admin(r: FileReview) -> FeedbackAdminItem:
    return FeedbackAdminItem(
        id=r.id,
        file_id=r.file_id,
        client_id=r.client_id,
        rating=r.rating,
        comment=r.comment,
        created_at=r.created_at.isoformat(),
        updated_at=r.updated_at.isoformat(),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=List[AdminFileItem],
    dependencies=[Depends(verify_api_key)],
    summary="List all client files (admin, includes drafts)",
)
async def list_all_files(
    client_id: Optional[str] = Query(None, description="Filter by client UUID."),
    label: Optional[FileLabel] = Query(None, description="Filter by lifecycle label."),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(ClientFile).order_by(ClientFile.uploaded_at.desc())
    if client_id:
        query = query.where(ClientFile.client_id == client_id)
    if label is not None:
        query = query.where(ClientFile.label == label.value)
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    rows = result.scalars().all()
    return [
        AdminFileItem(
            id=f.id,
            client_id=f.client_id,
            project_id=f.project_id,
            title=f.title,
            label=f.label,
            original_filename=f.original_filename,
            uploaded_at=f.uploaded_at.isoformat(),
        )
        for f in rows
    ]


@router.patch(
    "/{file_id}/label",
    response_model=AdminFileItem,
    dependencies=[Depends(verify_api_key)],
    summary="Set the lifecycle label on a client file",
)
async def set_file_label(
    file_id: str,
    req: FileLabelUpdate,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Promote or demote a client file's lifecycle label.

    When the new label is "approved" or "delivered", PortalNotifierAgent (P2)
    is called automatically to send the client an email notifying them the file
    is available.  Supply notify_url (the portal download link) and optionally
    notify_notes for a personalised message.

    Notification failure is logged but does NOT roll back the label change.
    The response includes notification_sent: true/false so the caller can
    surface a warning in the admin UI if the email bounced.
    """
    result = await db.execute(select(ClientFile).where(ClientFile.id == file_id))
    cf: ClientFile | None = result.scalar_one_or_none()
    if cf is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found.",
        )

    previous_label = cf.label
    cf.label = req.label.value
    await db.commit()
    await db.refresh(cf)

    logger.info(
        "portal.file_label_changed",
        file_id=file_id,
        client_id=cf.client_id,
        previous_label=previous_label,
        new_label=cf.label,
    )

    # ── Portal notification on promotion to client-visible label ──────────────
    notification_sent: Optional[bool] = None
    new_label_val = req.label.value

    if new_label_val in _NOTIFY_ON_LABELS and new_label_val != previous_label:
        # Only fire if the label is actually changing TO a notifiable state.
        notification_sent = False
        try:
            agent = registry.get("portal_notifier")
            if agent:
                # Determine action label from the transition
                action = "uploaded" if previous_label == FileLabel.draft.value else "updated"

                # Build a portal file URL: use provided notify_url or fall back to
                # the generic portal dashboard (client can find it there).
                file_url = req.notify_url or "https://klaravex.de/portal"

                context = AgentContext(
                    db=db,
                    settings=settings,
                    conversation_id=_uuid.uuid4(),
                    request_id=_uuid.uuid4(),
                )
                notify_result = await agent(context, {
                    "client_id": cf.client_id,
                    "filename": cf.original_filename or cf.title,
                    "file_url": file_url,
                    "action": action,
                    "notes": req.notify_notes or "",
                })
                if notify_result.success:
                    notification_sent = True
                    logger.info(
                        "portal.file_notification_sent",
                        file_id=file_id,
                        client_id=cf.client_id,
                        label=new_label_val,
                    )
                else:
                    logger.warning(
                        "portal.file_notification_failed",
                        file_id=file_id,
                        client_id=cf.client_id,
                        error=notify_result.error,
                    )
        except Exception as exc:
            # Notification failure must never break the label update.
            logger.error(
                "portal.file_notification_error",
                file_id=file_id,
                client_id=cf.client_id,
                error=str(exc),
            )

    return AdminFileItem(
        id=cf.id,
        client_id=cf.client_id,
        project_id=cf.project_id,
        title=cf.title,
        label=cf.label,
        original_filename=cf.original_filename,
        uploaded_at=cf.uploaded_at.isoformat(),
        notification_sent=notification_sent,
    )


# ── Feedback (reviews) admin endpoints ────────────────────────────────────────

@router.get(
    "/feedback",
    response_model=List[FeedbackAdminItem],
    dependencies=[Depends(verify_api_key)],
    summary="List all client file reviews (admin, filterable)",
)
async def list_all_feedback(
    file_id: Optional[str] = Query(None, description="Filter to one file."),
    client_id: Optional[str] = Query(None, description="Filter to one client."),
    rating: Optional[FileRating] = Query(None, description="Filter by rating."),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Return all client file reviews across all files and clients.

    All three query parameters are optional and combinable.
    """
    query = select(FileReview).order_by(FileReview.created_at.desc())
    if file_id:
        query = query.where(FileReview.file_id == file_id)
    if client_id:
        query = query.where(FileReview.client_id == client_id)
    if rating is not None:
        query = query.where(FileReview.rating == rating.value)
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    rows = result.scalars().all()

    logger.info("admin.feedback.listed", count=len(rows))
    return [_review_to_admin(r) for r in rows]


@router.get(
    "/{file_id}/feedback",
    response_model=List[FeedbackAdminItem],
    dependencies=[Depends(verify_api_key)],
    summary="List all reviews for a specific file (admin)",
)
async def list_file_feedback(
    file_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Return all client reviews for one specific file.

    Returns 404 if the file does not exist (regardless of label).
    """
    # Verify the file exists before returning reviews so the 404 is clean.
    file_result = await db.execute(
        select(ClientFile).where(ClientFile.id == file_id)
    )
    if file_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found.",
        )

    review_result = await db.execute(
        select(FileReview)
        .where(FileReview.file_id == file_id)
        .order_by(FileReview.created_at.desc())
    )
    rows = review_result.scalars().all()

    logger.info("admin.feedback.per_file.listed", file_id=file_id, count=len(rows))
    return [_review_to_admin(r) for r in rows]
