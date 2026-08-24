"""
app/tasks/client_expansion_sweep.py
────────────────────────────────────
phase18-004 — weekly expansion sweep.

Mondays 11:00 CET. For every won client with onboarding_sent_at >=90 days
ago, fires upsell_opportunity. Idempotent — won't refire for the same
lead within a 30-day window (tracked via AuditLog).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import structlog
from celery import shared_task
from sqlalchemy import and_, func, select

from klara.rarv.runtime import get_settings
from klara.rarv.runtime import db_context
from klara.rarv.audit import AuditLog
from klara.rarv.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)

MIN_DAYS_SINCE_ONBOARDING = 90
DEDUP_WINDOW_DAYS = 30


@shared_task(
    bind=True,
    name="app.tasks.client_expansion_sweep.run_expansion_sweep",
    max_retries=2,
    default_retry_delay=600,
)
def run_expansion_sweep(self):
    try:
        result = asyncio.run(_sweep())
        logger.info("client_expansion_sweep.complete", **result)
        return result
    except Exception as exc:
        logger.error("client_expansion_sweep.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _sweep() -> dict:
    from klara.rarv.runtime import AgentContext
    from app.agents.registry import registry

    settings = get_settings()
    now = datetime.now(timezone.utc)
    onboarding_cutoff = now - timedelta(days=MIN_DAYS_SINCE_ONBOARDING)
    dedup_cutoff = now - timedelta(days=DEDUP_WINDOW_DAYS)

    fired = 0
    skipped_dup = 0

    async with db_context() as db:
        # Won clients onboarded >=90 days ago
        rows = await db.execute(
            select(Lead).where(
                Lead.status == LeadStatus.won.value,
                Lead.onboarding_sent_at.is_not(None),
                Lead.onboarding_sent_at <= onboarding_cutoff,
            )
        )
        candidates = list(rows.scalars().all())

        agent = None
        try:
            agent = registry.get("upsell_opportunity")
        except KeyError:
            logger.warning("client_expansion_sweep.agent_missing")
            return {"candidates": len(candidates), "fired": 0, "skipped_dup": 0, "error": "upsell_opportunity not registered"}

        for lead in candidates:
            # Idempotency: skip if upsell already fired for this lead in the dedup window
            dup_q = await db.execute(
                select(func.count(AuditLog.id)).where(
                    AuditLog.event_type == "client_expansion.upsell_fired",
                    AuditLog.lead_id == lead.id,
                    AuditLog.created_at >= dedup_cutoff,
                )
            )
            if int(dup_q.scalar() or 0) > 0:
                skipped_dup += 1
                continue

            try:
                ctx = AgentContext(db=db, settings=settings, lead_id=lead.id)
                result = await agent(ctx, {"lead_id": lead.id})
                # Record the firing regardless of agent result — we only want to
                # avoid re-evaluating the same client every Monday
                db.add(AuditLog(
                    id=str(uuid4()),
                    event_type="client_expansion.upsell_fired",
                    agent_name="upsell_opportunity",
                    action_name="weekly_expansion_sweep",
                    lead_id=lead.id,
                    details=json.dumps({
                        "success": bool(result.success),
                        "error": result.error,
                    }),
                ))
                fired += 1
            except Exception as exc:
                logger.warning(
                    "client_expansion_sweep.agent_error",
                    lead_id=lead.id,
                    error=str(exc),
                )

    return {
        "candidates": len(candidates),
        "fired": fired,
        "skipped_dup": skipped_dup,
    }
