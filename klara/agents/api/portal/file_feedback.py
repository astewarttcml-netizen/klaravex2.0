"""
app/api/portal/file_feedback.py
────────────────────────────────
Client-facing thumbs-up/down + comment on delivered or approved files
(portal-242).

Routes are mounted under /api/v1/portal/files/{file_id}/feedback so they
sit alongside the existing list/download endpoints — keeps the URL shape
predictable for the portal frontend.

  GET  /api/v1/portal/files/{file_id}/feedback   — fetch this client's review
  PUT  /api/v1/portal/files/{file_id}/feedback   — create-or-update (upsert)
  DELETE /api/v1/portal/files/{file_id}/feedback — withdraw the review

A review is only allowed on files visible to the portal — drafts are not
reviewable. Re-submitting on a file the client has already rated updates
the existing row in place; there is exactly one review per (file, client).
"""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.portal_auth import get_current_portal_client
from app.database import get_db
from app.models.audit import AuditLog
from app.models.file_review import FileRating, FileReview
from app.models.portal import CLIENT_VISIBLE_FILE_LABELS, Client, ClientFile

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class FeedbackPayload(BaseModel):
    rating: FileRating = Field(
        ..., description="Thumbs-up ('up') or thumbs-down ('down')."
    )
    comment: Optional[str] = Field(
        None,
        max_length=2_000,
        description="Optional free-text feedback. Trimmed; empty becomes null.",
    )


class FeedbackResponse(BaseModel):
    file_id: str
    rating: str
    comment: Optional[str]
    created_at: str
    updated_at: str


def _to_response(review: FileReview) -> FeedbackResponse:
    return FeedbackResponse(
        file_id=review.file_id,
        rating=review.rating,
        comment=review.comment,
        created_at=review.created_at.isoformat(),
        updated_at=review.updated_at.isoformat(),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _load_visible_file_or_404(
    db: AsyncSession, file_id: str, client: Client
) -> ClientFile:
    """
    Load the file iff it belongs to the client AND is in a client-visible
    label. Drafts and other clients' files share the 404 response so the
    endpoint cannot be used to probe for hidden ids.
    """
    result = await db.execute(
        select(ClientFile).where(
            ClientFile.id == file_id,
            ClientFile.client_id == client.id,
            ClientFile.label.in_(CLIENT_VISIBLE_FILE_LABELS),
        )
    )
    cf: ClientFile | None = result.scalar_one_or_none()
    if cf is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found.",
        )
    return cf


async def _load_existing_review(
    db: AsyncSession, file_id: str, client_id: str
) -> FileReview | None:
    result = await db.execute(
        select(FileReview).where(
            FileReview.file_id == file_id,
            FileReview.client_id == client_id,
        )
    )
    return result.scalar_one_or_none()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "/{file_id}/feedback",
    response_model=Optional[FeedbackResponse],
    summary="Get this client's feedback on a file",
)
async def get_feedback(
    file_id: str,
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the authenticated client's existing review for the file, or
    null if they haven't left one yet. Returns 404 if the file is not
    visible to this client (wrong owner, draft, or doesn't exist).
    """
    await _load_visible_file_or_404(db, file_id, client)
    review = await _load_existing_review(db, file_id, client.id)
    if review is None:
        return None
    return _to_response(review)


@router.put(
    "/{file_id}/feedback",
    response_model=FeedbackResponse,
    summary="Submit or update feedback on a file",
)
async def upsert_feedback(
    file_id: str,
    payload: FeedbackPayload,
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Create or update the authenticated client's review for the file.

    Idempotent: PUT-ing the same payload twice yields a single row whose
    updated_at moves forward on the second call.
    """
    await _load_visible_file_or_404(db, file_id, client)

    # Normalise comment: empty / whitespace-only becomes NULL so the DB
    # never carries blank rows that would render as visible empty bubbles.
    comment = (payload.comment or "").strip() or None

    review = await _load_existing_review(db, file_id, client.id)
    is_new = review is None
    previous_rating = None if is_new else review.rating
    if review is None:
        review = FileReview(
            file_id=file_id,
            client_id=client.id,
            rating=payload.rating.value,
            comment=comment,
        )
        db.add(review)
    else:
        review.rating = payload.rating.value
        review.comment = comment

    db.add(
        AuditLog(
            event_type="portal.file_feedback_submitted",
            agent_name="portal_files",
            details=(
                f"client_id={client.id} file_id={file_id} "
                f"rating={review.rating} previous_rating={previous_rating} "
                f"new={is_new}"
            ),
            success=True,
        )
    )

    await db.commit()
    await db.refresh(review)

    logger.info(
        "portal.file_feedback",
        file_id=file_id,
        client_id=client.id,
        rating=review.rating,
        new=is_new,
    )
    return _to_response(review)


@router.delete(
    "/{file_id}/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Withdraw feedback on a file",
)
async def delete_feedback(
    file_id: str,
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove the authenticated client's review for the file, if any.

    Returns 204 whether or not a review existed — the post-condition
    (no review for this client on this file) is the same either way,
    and clients shouldn't need to special-case the "already gone" path.
    """
    await _load_visible_file_or_404(db, file_id, client)
    review = await _load_existing_review(db, file_id, client.id)
    if review is not None:
        await db.delete(review)
        db.add(
            AuditLog(
                event_type="portal.file_feedback_withdrawn",
                agent_name="portal_files",
                details=f"client_id={client.id} file_id={file_id}",
                success=True,
            )
        )
        await db.commit()
        logger.info(
            "portal.file_feedback_withdrawn",
            file_id=file_id,
            client_id=client.id,
        )
    return None
