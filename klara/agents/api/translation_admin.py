"""
app/api/translation_admin.py
──────────────────────────────
Admin endpoints for the TranslationAgent pipeline.

Routes (all require X-API-Key admin auth):

  POST /api/v1/admin/translation/translate
      Trigger TranslationAgent for a given source WP page ID.
      Creates a P3 ApprovalRequest (action: translation_agent.publish).
      Once Anthony approves, execute_approved_action pushes the translated
      content to WordPress as a draft via WebsiteDeployAgent.

  GET  /api/v1/admin/translation/approvals
      List pending (or all) translation approval requests with content preview.

  POST /api/v1/admin/translation/retry/{approval_id}
      Re-dispatch an already-approved translation to the Celery worker.
"""
from __future__ import annotations

import json
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
from klara.rarv.approval import ApprovalRequest

logger = structlog.get_logger(__name__)
router = APIRouter()

_VALID_LANGUAGES = {"en", "de"}
_VALID_POST_TYPES = {"page", "post"}


# ── Request / Response schemas ─────────────────────────────────────────────────

class TranslateRequest(BaseModel):
    source_page_id:  int
    source_language: str = "en"
    target_language: str = "de"
    target_page_id:  Optional[int] = None   # None → create new WP draft
    post_type:       str = "post"           # only used when target_page_id is None

    @field_validator("source_language", "target_language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in _VALID_LANGUAGES:
            raise ValueError(f"language must be one of {_VALID_LANGUAGES}")
        return v

    @field_validator("post_type")
    @classmethod
    def validate_post_type(cls, v: str) -> str:
        if v not in _VALID_POST_TYPES:
            raise ValueError(f"post_type must be one of {_VALID_POST_TYPES}")
        return v

    @field_validator("source_page_id")
    @classmethod
    def validate_source_page_id(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("source_page_id must be a positive integer")
        return v


# ── Trigger translation ────────────────────────────────────────────────────────

@router.post("/translate", dependencies=[Depends(require_admin)])
async def trigger_translation(
    body: TranslateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger TranslationAgent for a given WordPress page or post.

    The agent fetches the source page from WP REST API, calls Claude to
    translate the HTML content, then creates a P3 ApprovalRequest.

    After Anthony approves at /admin → Approvals, execute_approved_action
    pushes the translated content to WordPress as a draft via WebsiteDeployAgent.

    Modes:
      - target_page_id set   → 'update_page': PATCH existing WP page as draft
      - target_page_id omitted → 'create_post': create new WP draft post/page

    Returns the approval_id immediately. Translation is complete by the time
    the response arrives (Claude call is synchronous within the request).
    """
    if body.source_language == body.target_language:
        raise HTTPException(
            status_code=400,
            detail="source_language and target_language must differ.",
        )

    settings = get_settings()
    context = AgentContext(
        db=db,
        settings=settings,
        conversation_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        lead_id=None,
    )

    agent = registry.get("translation_agent")

    logger.info(
        "translation_admin.translate_requested",
        source_page_id=body.source_page_id,
        source_language=body.source_language,
        target_language=body.target_language,
        target_page_id=body.target_page_id,
        post_type=body.post_type,
    )

    result = await agent(context, {
        "source_page_id":  body.source_page_id,
        "source_language": body.source_language,
        "target_language": body.target_language,
        "target_page_id":  body.target_page_id,
        "post_type":       body.post_type,
    })

    if not result.success and not result.approval_required:
        logger.error(
            "translation_admin.translate_failed",
            source_page_id=body.source_page_id,
            error=result.error,
        )
        raise HTTPException(status_code=500, detail=result.error or "Translation failed.")

    approval_id = result.approval_id or (
        result.output.get("approval_id") if result.output else None
    )

    mode = "update_page" if body.target_page_id else "create_post"

    logger.info(
        "translation_admin.queued",
        source_page_id=body.source_page_id,
        approval_id=approval_id,
        mode=mode,
    )

    return {
        "status":          "queued_for_approval",
        "mode":            mode,
        "source_page_id":  body.source_page_id,
        "target_page_id":  body.target_page_id,
        "source_language": body.source_language,
        "target_language": body.target_language,
        "approval_id":     approval_id,
        "note":            "Translation complete. Review and approve at /admin → Approvals.",
    }


# ── List approvals ─────────────────────────────────────────────────────────────

@router.get("/approvals", dependencies=[Depends(require_admin)])
async def list_translation_approvals(
    status_filter: Optional[str] = Query(
        "pending",
        description="Filter by status: pending | approved | rejected | all",
    ),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List TranslationAgent approval requests with content preview."""
    q = (
        select(ApprovalRequest)
        .where(ApprovalRequest.action_name == "translation_agent.publish")
        .order_by(ApprovalRequest.created_at.desc())
        .limit(limit)
    )
    if status_filter and status_filter != "all":
        q = q.where(ApprovalRequest.status == status_filter)

    result = await db.execute(q)
    approvals = result.scalars().all()

    def _parse(a: ApprovalRequest) -> dict:
        try:
            payload = json.loads(a.payload) if isinstance(a.payload, str) else (a.payload or {})
        except Exception:
            payload = {}

        translated_preview = payload.get("content_html", "")
        # Strip HTML tags for preview
        import re
        text_preview = re.sub(r"<[^>]+>", " ", translated_preview)
        text_preview = " ".join(text_preview.split())[:200]

        return {
            "approval_id":     str(a.id),
            "source_page_id":  payload.get("source_page_id"),
            "target_page_id":  payload.get("target_page_id"),
            "source_language": payload.get("source_language", ""),
            "target_language": payload.get("target_language", ""),
            "source_title":    payload.get("source_title", ""),
            "translated_title": payload.get("title", ""),
            "mode":            payload.get("mode", ""),
            "post_type":       payload.get("post_type", ""),
            "content_preview": text_preview,
            "status":          a.status,
            "created_at":      a.created_at.isoformat() if a.created_at else None,
        }

    return {
        "total":         len(approvals),
        "status_filter": status_filter,
        "approvals":     [_parse(a) for a in approvals],
    }


# ── Retry ──────────────────────────────────────────────────────────────────────

@router.post("/retry/{approval_id}", dependencies=[Depends(require_admin)])
async def retry_translation_publish(
    approval_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Re-dispatch an already-approved translation to the Celery worker.

    Use when execute_approved_action previously failed (e.g. WP API timeout).
    The approval must have status='approved' and action_name='translation_agent.publish'.
    """
    result = await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
    )
    approval = result.scalar_one_or_none()

    if not approval:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found.")
    if approval.action_name != "translation_agent.publish":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Approval '{approval_id}' is not a translation approval "
                f"(action: {approval.action_name})."
            ),
        )
    if approval.status not in ("approved", "pending"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Approval '{approval_id}' has status '{approval.status}' — "
                f"only approved/pending can be retried."
            ),
        )

    from app.tasks.execute_approved_action import execute_approved_action as _exec_task
    _exec_task.delay(approval_id)

    logger.info(
        "translation_admin.retry_dispatched",
        approval_id=approval_id,
        status=approval.status,
    )

    return {
        "status":      "dispatched",
        "approval_id": approval_id,
        "note":        "execute_approved_action task queued. Check worker logs for result.",
    }
