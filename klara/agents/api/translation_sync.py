"""
app/api/translation_sync.py
─────────────────────────────
Admin endpoints for the TranslationSyncAgent.

All endpoints require X-API-Key authentication.

Routes (mounted at /api/v1/admin/translation-sync):
  POST /audit   — trigger a fresh scan of all /de/ pages
  GET  /results — return flagged blocks from the latest audit run
"""
from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from klara.rarv.runtime import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── 1. Trigger audit ──────────────────────────────────────────────────────────

@router.post(
    "/audit",
    dependencies=[Depends(verify_api_key)],
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_translation_audit(
    db: AsyncSession = Depends(get_db),
):
    """
    Run a full scan of all /de/ pages immediately.

    The scan is executed in-request (not via Celery) because it is a
    short-lived read-only operation (~5 seconds across 5 pages).
    Returns a summary once complete.
    """
    from app.agents.translation_sync import TranslationSyncAgent
    from klara.rarv.runtime import AgentContext
    from klara.rarv.runtime import get_settings

    settings = get_settings()
    context = AgentContext(
        db=db,
        settings=settings,
        request_id=None,
    )

    agent = TranslationSyncAgent()
    result = await agent.run(context, {})

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error or "Translation audit failed.",
        )

    logger.info(
        "translation_sync.audit_triggered",
        audit_run_id=result.output.get("audit_run_id"),
        flagged=result.output.get("flagged_blocks"),
    )

    return {
        "status": "completed",
        **result.output,
    }


# ── 2. Retrieve latest results ────────────────────────────────────────────────

@router.get("/results", dependencies=[Depends(verify_api_key)])
async def get_translation_audit_results(
    flagged_only: bool = Query(
        default=True,
        description="If true, return only flagged (untranslated) blocks.",
    ),
    limit: int = Query(default=200, ge=1, le=1000),
    audit_run_id: str | None = Query(
        default=None,
        description=(
            "UUID of a specific audit run. "
            "Omit to return results from the most recent run."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return per-block results from the latest (or a specified) audit run.

    When audit_run_id is omitted the endpoint identifies the most recent
    run by taking the MAX(detected_at) across the table and returning all
    rows from that run.
    """
    from klara.rarv.translation_audit import TranslationAuditEntry
    from sqlalchemy import func

    # ── Resolve the target run ────────────────────────────────────────────────
    if audit_run_id:
        # Validate UUID format — avoids a silent empty result on typos
        try:
            UUID(audit_run_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"audit_run_id is not a valid UUID: {audit_run_id!r}",
            )
        target_run_id = audit_run_id
    else:
        # Find the most recently inserted audit_run_id
        latest_row = (
            await db.execute(
                select(TranslationAuditEntry.audit_run_id)
                .order_by(TranslationAuditEntry.detected_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if not latest_row:
            return {
                "audit_run_id": None,
                "count": 0,
                "items": [],
                "message": "No audit runs found. POST /audit to run a scan.",
            }

        target_run_id = latest_row

    # ── Query blocks for the resolved run ─────────────────────────────────────
    stmt = select(TranslationAuditEntry).where(
        TranslationAuditEntry.audit_run_id == target_run_id
    )
    if flagged_only:
        stmt = stmt.where(TranslationAuditEntry.flagged.is_(True))

    stmt = stmt.order_by(
        TranslationAuditEntry.page_url,
        TranslationAuditEntry.detected_at,
    ).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()

    return {
        "audit_run_id": target_run_id,
        "flagged_only": flagged_only,
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "page_url": r.page_url,
                "block_tag": r.block_tag,
                "block_text_snippet": r.block_text_snippet,
                "english_word_count": r.english_word_count,
                "german_indicator_count": r.german_indicator_count,
                "flagged": r.flagged,
                "detected_at": r.detected_at.isoformat(),
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            }
            for r in rows
        ],
    }
