"""
app/tasks/linkedin_drafts_sweep.py
───────────────────────────────────
phase20-005 — daily sweep that queues LinkedIn drafts.

Targets prospects who:
  - have contact_linkedin set
  - have outreach_sent_at >= 14 days ago
  - have replied_at NULL (no email reply yet)
  - have no existing linkedin_drafts row (UNIQUE FK enforces this anyway)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from celery import shared_task
from sqlalchemy import and_, select

from app.config import get_settings
from app.database import db_context
from app.models.linkedin_draft import LinkedinDraft
from app.models.prospected_lead import ProspectedLead

logger = structlog.get_logger(__name__)

EMAIL_WAIT_DAYS = 14


@shared_task(
    bind=True,
    name="app.tasks.linkedin_drafts_sweep.run_linkedin_sweep",
    max_retries=2,
    default_retry_delay=600,
)
def run_linkedin_sweep(self):
    try:
        result = asyncio.run(_sweep())
        logger.info("linkedin_drafts_sweep.complete", **result)
        return result
    except Exception as exc:
        logger.error("linkedin_drafts_sweep.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _sweep() -> dict:
    from app.agents.base import AgentContext
    from app.agents.registry import registry

    settings = get_settings()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=EMAIL_WAIT_DAYS)

    queued = 0
    skipped = 0

    async with db_context() as db:
        rows = await db.execute(
            select(ProspectedLead).where(
                ProspectedLead.contact_linkedin.is_not(None),
                ProspectedLead.outreach_sent_at.is_not(None),
                ProspectedLead.outreach_sent_at <= cutoff,
                ProspectedLead.replied_at.is_(None),
            )
        )
        candidates = list(rows.scalars().all())

        # Get prospect IDs that already have a draft
        existing_q = await db.execute(select(LinkedinDraft.prospected_lead_id))
        already_drafted = {r[0] for r in existing_q.all()}

        agent = None
        try:
            agent = registry.get("linkedin_outreach")
        except KeyError:
            return {"candidates": len(candidates), "queued": 0, "error": "linkedin_outreach not registered"}

        for prospect in candidates:
            if prospect.id in already_drafted:
                skipped += 1
                continue
            ctx = AgentContext(db=db, settings=settings, lead_id=prospect.id)
            try:
                await agent(ctx, {"prospect_id": prospect.id})
                queued += 1
            except Exception as exc:
                logger.warning(
                    "linkedin_drafts_sweep.agent_failed",
                    prospect_id=prospect.id, error=str(exc),
                )

    return {
        "candidates": len(candidates),
        "queued": queued,
        "skipped_existing": skipped,
    }
