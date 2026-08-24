"""
app/tasks/prospect_leads.py
─────────────────────────────
Celery periodic task: prospect new leads via Apollo and queue outreach drafts.

Schedule: weekdays (Mon–Fri) at 08:00 Europe/Berlin (configured in celery_app.py).

Flow:
  1. LeadProspectorAgent queries Apollo for ICP-matched Berlin contacts.
  2. Deduplicates against existing ProspectedLead and inbound Lead tables.
  3. Persists new ProspectedLead records (up to PROSPECTING_DAILY_LIMIT).
  4. For each new prospect, ProspectingOutreachAgent drafts a cold email via
     Claude and queues a P3 ApprovalRequest for Anthony to review.
  5. Anthony approves via the dashboard → email sent via Resend.

Exits cleanly (no partial records, no exceptions raised to Celery) if:
  - Apollo API key is missing / placeholder
  - Daily limit already reached
  - Apollo API is unavailable
  - No new unique prospects are found
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import structlog

from app.tasks.celery_app import celery_app
from app.config import get_settings
from app.database import db_context

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="app.tasks.prospect_leads.run_prospecting",
    bind=True,
    max_retries=0,  # do not auto-retry — wait for next scheduled run
)
def run_prospecting(self, triggered_by: str = "celery_beat"):
    """
    Celery task entry point (synchronous wrapper around async implementation).

    Args:
        triggered_by: 'celery_beat' or 'admin_api' — for logging only.
    """
    try:
        # asyncio.run() required: get_event_loop() is deprecated/raises in Python 3.12 worker threads
        asyncio.run(_prospect_and_queue(triggered_by=triggered_by))
    except Exception as exc:
        logger.error(
            "prospect_leads.task_failed",
            triggered_by=triggered_by,
            error=str(exc),
            exc_info=True,
        )
        # Do NOT re-raise — log and let the next scheduled run handle it


async def _prospect_and_queue(triggered_by: str) -> dict:
    """Async implementation — runs inside Celery worker's event loop."""
    from app.agents.base import AgentContext
    from app.agents.lead_prospector import LeadProspectorAgent
    from app.agents.registry import registry

    settings = get_settings()
    started_at = datetime.now(timezone.utc)

    logger.info(
        "prospect_leads.started",
        triggered_by=triggered_by,
        daily_limit=settings.prospecting_daily_limit,
        apollo_configured=settings.apollo_configured,
        started_at=started_at.isoformat(),
    )

    queued_count = 0
    failed_count = 0

    async with db_context() as db:
        # conversation_id/request_id/lead_id required by AgentContext; sweep has no specific lead
        context = AgentContext(
            db=db,
            settings=settings,
            conversation_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
            lead_id=None,
        )

        # ── 1. Prospect via Apollo ─────────────────────────────────────────
        prospector = LeadProspectorAgent()
        new_prospects = await prospector.run(context)

        if not new_prospects:
            logger.info("prospect_leads.no_new_prospects", triggered_by=triggered_by)
            return {"new_prospects": 0, "queued": 0, "failed": 0}

        logger.info(
            "prospect_leads.new_prospects_found",
            count=len(new_prospects),
        )

        # ── 2. Draft outreach email for each prospect ─────────────────────
        outreach_agent = registry.get("prospecting_outreach")

        for prospect in new_prospects:
            try:
                result = await outreach_agent.run(
                    context,
                    {"prospect_id": str(prospect.id)},
                )
                if result.success and result.output.get("status") == "outreach_queued":
                    queued_count += 1
                    logger.info(
                        "prospect_leads.queued",
                        approval_id=result.output.get("approval_id"),
                        domain=prospect.domain,
                        company=prospect.company_name,
                    )
                else:
                    failed_count += 1
                    logger.warning(
                        "prospect_leads.draft_failed",
                        domain=prospect.domain,
                        company=prospect.company_name,
                        error=result.error,
                    )
            except Exception as exc:
                failed_count += 1
                logger.error(
                    "prospect_leads.outreach_exception",
                    domain=prospect.domain,
                    error=str(exc),
                    exc_info=True,
                )

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    logger.info(
        "prospect_leads.done",
        new_prospects=len(new_prospects),
        queued=queued_count,
        failed=failed_count,
        elapsed_seconds=round(elapsed, 1),
    )

    return {
        "new_prospects": len(new_prospects),
        "queued": queued_count,
        "failed": failed_count,
        "elapsed_seconds": elapsed,
    }
