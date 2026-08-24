"""
app/api/seo_content_admin.py
─────────────────────────────
Admin endpoints for the SEO content writer pipeline.

Routes (all require X-API-Key admin auth):
  POST /api/v1/admin/seo-content/generate
      Trigger SeoContentWriterAgent for a given keyword + language.
      Creates a P3 ApprovalRequest (action: seo_content_writer.publish).
      Once Anthony approves, website_deploy publishes to WordPress.

  GET  /api/v1/admin/seo-content/approvals
      List pending (or all) SEO content approval requests.
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.portal_auth import require_admin
from klara.rarv.runtime import get_db
from klara.rarv.runtime import AgentContext
from app.agents.registry import registry
from klara.rarv.runtime import get_settings
from klara.rarv.approval import ApprovalRequest, ApprovalStatus

logger = structlog.get_logger(__name__)
router = APIRouter()

_VALID_LANGUAGES     = {"en", "de"}
_VALID_CONTENT_TYPES = {"blog_post", "service_page", "faq"}


# ── Request / Response schemas ────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    keyword: str
    language: str = "en"
    content_type: str = "blog_post"
    word_count: int = 800

    @field_validator("keyword")
    @classmethod
    def keyword_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("keyword must not be empty")
        return v.strip()

    @field_validator("language")
    @classmethod
    def language_valid(cls, v: str) -> str:
        if v not in _VALID_LANGUAGES:
            raise ValueError(f"language must be one of {_VALID_LANGUAGES}")
        return v

    @field_validator("content_type")
    @classmethod
    def content_type_valid(cls, v: str) -> str:
        if v not in _VALID_CONTENT_TYPES:
            raise ValueError(f"content_type must be one of {_VALID_CONTENT_TYPES}")
        return v

    @field_validator("word_count")
    @classmethod
    def word_count_range(cls, v: int) -> int:
        if not 200 <= v <= 2500:
            raise ValueError("word_count must be between 200 and 2500")
        return v


# ── Generate ──────────────────────────────────────────────────────────────────

@router.post("/generate", dependencies=[Depends(require_admin)])
async def generate_seo_content(
    body: GenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger SeoContentWriterAgent for the given keyword.

    The agent calls Claude to draft the post, then creates a P3 ApprovalRequest
    (action: seo_content_writer.publish) so Anthony can review and approve
    before it goes live on WordPress.

    Returns the approval_id immediately — content is in approval payload.
    """
    settings = get_settings()
    context = AgentContext(
        db=db,
        settings=settings,
        conversation_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        lead_id=None,
    )

    agent = registry.get("seo_content_writer")

    logger.info(
        "seo_content_admin.generate_requested",
        keyword=body.keyword,
        language=body.language,
        content_type=body.content_type,
        word_count=body.word_count,
    )

    result = await agent(context, {
        "keyword":      body.keyword,
        "language":     body.language,
        "content_type": body.content_type,
        "word_count":   body.word_count,
    })

    if not result.success and not result.approval_required:
        logger.error(
            "seo_content_admin.generate_failed",
            keyword=body.keyword,
            error=result.error,
        )
        raise HTTPException(status_code=500, detail=result.error or "Content generation failed.")

    approval_id = result.approval_id or (
        result.output.get("approval_id") if result.output else None
    )

    logger.info(
        "seo_content_admin.queued",
        keyword=body.keyword,
        language=body.language,
        approval_id=approval_id,
    )

    return {
        "status": "queued_for_approval",
        "keyword": body.keyword,
        "language": body.language,
        "content_type": body.content_type,
        "approval_id": approval_id,
        "note": "Review and approve at /admin → Approvals dashboard.",
    }


# ── List approvals ────────────────────────────────────────────────────────────

@router.get("/approvals", dependencies=[Depends(require_admin)])
async def list_seo_approvals(
    status_filter: Optional[str] = Query("pending", description="pending|approved|rejected"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List SEO content approval requests."""
    q = (
        select(ApprovalRequest)
        .where(ApprovalRequest.action_name == "seo_content_writer.publish")
        .order_by(ApprovalRequest.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        q = q.where(ApprovalRequest.status == status_filter)

    result = await db.execute(q)
    approvals = result.scalars().all()

    import json
    def _parse(a: ApprovalRequest) -> dict:
        try:
            payload = json.loads(a.payload) if isinstance(a.payload, str) else (a.payload or {})
        except Exception:
            payload = {}
        return {
            "approval_id":  str(a.id),
            "keyword":      payload.get("keyword", ""),
            "language":     payload.get("language", ""),
            "content_type": payload.get("content_type", ""),
            "title":        payload.get("title", ""),
            "meta":         payload.get("meta", ""),
            "status":       a.status,
            "created_at":   a.created_at.isoformat() if a.created_at else None,
        }

    return {
        "total": len(approvals),
        "status_filter": status_filter,
        "approvals": [_parse(a) for a in approvals],
    }


# ── Retry ─────────────────────────────────────────────────────────────────────

@router.post("/retry/{approval_id}", dependencies=[Depends(require_admin)])
async def retry_seo_publish(
    approval_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Re-dispatch an already-approved SEO content approval to the Celery worker.

    Use when execute_approved_action previously failed (e.g. before the
    create_post fix was deployed).  The approval must have status='approved'
    and action_name='seo_content_writer.publish'.
    """
    import uuid as _uuid
    result = await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    )
    approval = result.scalar_one_or_none()

    if not approval:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found.")
    if approval.action_name != "seo_content_writer.publish":
        raise HTTPException(
            status_code=400,
            detail=f"Approval '{approval_id}' is not an SEO content approval (action: {approval.action_name}).",
        )
    if approval.status not in ("approved", "pending"):
        raise HTTPException(
            status_code=400,
            detail=f"Approval '{approval_id}' has status '{approval.status}' — only approved/pending can be retried.",
        )

    from app.tasks.execute_approved_action import execute_approved_action as _exec_task
    _exec_task.delay(approval_id)

    logger.info(
        "seo_content_admin.retry_dispatched",
        approval_id=approval_id,
        action=approval.action_name,
        status=approval.status,
    )

    return {
        "status":      "dispatched",
        "approval_id": approval_id,
        "note":        "execute_approved_action task queued. Check worker logs for result.",
    }
