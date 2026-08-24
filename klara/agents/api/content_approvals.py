"""
app/api/content_approvals.py
──────────────────────────────
Approval queue endpoints for public-page publish requests.

Routes (all under /api/v1/approvals/content):
  GET  /api/v1/approvals/content          — list pending content approvals (admin only)
  GET  /api/v1/approvals/content/{id}     — get content approval detail with diff
  POST /api/v1/approvals/content/{id}/approve  — publish revision
  POST /api/v1/approvals/content/{id}/reject   — reject with reason

All write endpoints and the list endpoint require the require_admin dependency.
The admin dependency accepts either a portal JWT with admin role OR the
management API key (X-API-Key header) — consistent with other admin routes.
"""
from __future__ import annotations

import json
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.portal_auth import require_admin
from klara.rarv.runtime import get_db
from klara.rarv.approval import ApprovalRequest, ApprovalStatus
from klara.rarv.audit import AuditLog
from klara.rarv.content_tracking import ContentPage, ContentRevision
from klara.rarv.runtime.content_audit import ContentAuditService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/content", tags=["content-approvals"])


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response schemas
# ─────────────────────────────────────────────────────────────────────────────

class RejectBody(BaseModel):
    reason: str
    rejected_by: str = "admin"


class ApproveBody(BaseModel):
    approved_by: str = "admin"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _get_content_approval_or_404(
    approval_id: str, db: AsyncSession
) -> ApprovalRequest:
    """Fetch an ApprovalRequest that is for a publish_content action or 404."""
    result = await db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.action_name == "publish_content",
        )
    )
    approval = result.scalar_one_or_none()
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Content approval not found.",
        )
    return approval


def _parse_payload(approval: ApprovalRequest) -> dict:
    try:
        return (
            json.loads(approval.payload)
            if isinstance(approval.payload, str)
            else (approval.payload or {})
        )
    except (json.JSONDecodeError, TypeError):
        return {}


def _approval_list_item(approval: ApprovalRequest, payload: dict) -> dict:
    return {
        "approval_id": approval.id,
        "page_id": payload.get("page_id"),
        "page_title": payload.get("page_title"),
        "page_slug": payload.get("page_slug"),
        "change_type": payload.get("change_type"),
        "rationale": payload.get("rationale"),
        "diff_summary": payload.get("diff_summary"),
        "submitted_at": approval.created_at.isoformat(),
        "author_agent": approval.requested_by_agent,
        "status": approval.status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "",
    summary="List pending content approvals",
    dependencies=[Depends(require_admin)],
)
async def list_content_approvals(
    status_filter: str = "pending",
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """
    Return a list of content approval requests with their diff summaries.

    Defaults to showing pending approvals; pass ?status_filter=approved|rejected
    to see historical records.
    """
    query = (
        select(ApprovalRequest)
        .where(
            ApprovalRequest.action_name == "publish_content",
            ApprovalRequest.status == status_filter,
        )
        .order_by(ApprovalRequest.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    approvals = result.scalars().all()

    return [_approval_list_item(a, _parse_payload(a)) for a in approvals]


@router.get(
    "/{approval_id}",
    summary="Get content approval detail with full diff",
    dependencies=[Depends(require_admin)],
)
async def get_content_approval(
    approval_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Return full approval detail including original_content and proposed_content
    so the reviewer can display a complete before/after diff.
    """
    approval = await _get_content_approval_or_404(approval_id, db)
    payload = _parse_payload(approval)

    detail = _approval_list_item(approval, payload)
    detail.update(
        {
            "original_content": payload.get("original_content"),
            "proposed_content": payload.get("proposed_content"),
            "bilingual_warnings": payload.get("bilingual_warnings", []),
            "revision_id": payload.get("revision_id"),
            "reviewed_by": approval.reviewed_by,
            "review_note": approval.review_note,
            "reviewed_at": (
                approval.reviewed_at.isoformat() if approval.reviewed_at else None
            ),
            "expires_at": (
                approval.expires_at.isoformat() if approval.expires_at else None
            ),
        }
    )
    return detail


@router.post(
    "/{approval_id}/approve",
    summary="Approve content revision — publishes it",
    dependencies=[Depends(require_admin)],
)
async def approve_content(
    approval_id: str,
    body: ApproveBody = ApproveBody(),
    db: AsyncSession = Depends(get_db),
):
    """
    Approve a pending content revision.

    Calls ContentAuditService.publish_revision() then marks the
    ApprovalRequest as approved.  Logs approval.content_approved.
    """
    approval = await _get_content_approval_or_404(approval_id, db)

    if approval.status != ApprovalStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Approval is already {approval.status!r}.",
        )

    payload = _parse_payload(approval)
    revision_id: Optional[str] = payload.get("revision_id")
    if not revision_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Approval payload is missing revision_id.",
        )

    svc = ContentAuditService(db)
    try:
        published_content = await svc.publish_revision(
            revision_id=revision_id, approved_by=body.approved_by
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )

    # Mark approval record
    from datetime import datetime, timezone
    approval.status = ApprovalStatus.approved
    approval.reviewed_by = body.approved_by
    approval.reviewed_at = datetime.now(timezone.utc)
    db.add(approval)

    # Audit log
    audit = AuditLog(
        event_type="approval.content_approved",
        agent_name="content_approvals_api",
        action_name="publish_content",
        approval_id=approval_id,
        details=json.dumps(
            {
                "revision_id": revision_id,
                "page_id": payload.get("page_id"),
                "page_slug": payload.get("page_slug"),
                "change_type": payload.get("change_type"),
                "approved_by": body.approved_by,
            },
            ensure_ascii=False,
        ),
        success=True,
    )
    db.add(audit)

    logger.info(
        "approval.content_approved",
        approval_id=approval_id,
        revision_id=revision_id,
        approved_by=body.approved_by,
    )

    return {
        "status": "approved",
        "approval_id": approval_id,
        "revision_id": revision_id,
        "page_id": payload.get("page_id"),
        "content_length": len(published_content),
    }


@router.post(
    "/{approval_id}/reject",
    summary="Reject content revision",
    dependencies=[Depends(require_admin)],
)
async def reject_content(
    approval_id: str,
    body: RejectBody,
    db: AsyncSession = Depends(get_db),
):
    """
    Reject a pending content revision.

    Calls ContentAuditService.reject_revision() then marks the
    ApprovalRequest as rejected.  Logs approval.content_rejected.

    Body: { "reason": "...", "rejected_by": "..." }
    """
    approval = await _get_content_approval_or_404(approval_id, db)

    if approval.status != ApprovalStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Approval is already {approval.status!r}.",
        )

    payload = _parse_payload(approval)
    revision_id: Optional[str] = payload.get("revision_id")
    if not revision_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Approval payload is missing revision_id.",
        )

    svc = ContentAuditService(db)
    try:
        await svc.reject_revision(
            revision_id=revision_id,
            rejected_by=body.rejected_by,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )

    # Mark approval record
    from datetime import datetime, timezone
    approval.status = ApprovalStatus.rejected
    approval.reviewed_by = body.rejected_by
    approval.review_note = body.reason
    approval.reviewed_at = datetime.now(timezone.utc)
    db.add(approval)

    # Audit log
    audit = AuditLog(
        event_type="approval.content_rejected",
        agent_name="content_approvals_api",
        action_name="publish_content",
        approval_id=approval_id,
        details=json.dumps(
            {
                "revision_id": revision_id,
                "page_id": payload.get("page_id"),
                "page_slug": payload.get("page_slug"),
                "change_type": payload.get("change_type"),
                "rejected_by": body.rejected_by,
                "reason": body.reason,
            },
            ensure_ascii=False,
        ),
        success=True,
    )
    db.add(audit)

    logger.info(
        "approval.content_rejected",
        approval_id=approval_id,
        revision_id=revision_id,
        rejected_by=body.rejected_by,
        reason=body.reason,
    )

    return {
        "status": "rejected",
        "approval_id": approval_id,
        "revision_id": revision_id,
    }
