"""
app/tasks/batch7_sweeps.py
────────────────────────────
Celery tasks: daily sweep tasks for Batch 7 post-conversion lifecycle agents.

Schedule: daily at various times (beat_schedule in celery_app.py)

Agents covered:
  - testimonial_requester  (P3) — 7-day post-onboarding review request
  - referral_campaign      (P3) — 30-day post-win referral ask
  - cold_nurture           (P3) — 3-touch cold lead re-engagement
  - lead_enrichment        (P2) — pre-call company/tech-stack enrichment
  - client_satisfaction    (P2) — NPS survey 30 days post-kickoff
"""
import asyncio
import uuid

import structlog

from app.tasks.celery_app import celery_app
from app.config import get_settings
from app.database import db_context

logger = structlog.get_logger(__name__)


# ── Testimonial Requester ────────────────────────────────────────────────────

@celery_app.task(
    name="app.tasks.batch7_sweeps.run_testimonial_requester",
    bind=True,
    max_retries=2,
    default_retry_delay=600,
)
def run_testimonial_requester(self):
    try:
        # asyncio.run() required: get_event_loop() is deprecated/raises in Python 3.12 worker threads
        asyncio.run(_run_agent("testimonial_requester"))
    except Exception as exc:
        logger.error("testimonial_requester.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


# ── Referral Campaign ────────────────────────────────────────────────────────

@celery_app.task(
    name="app.tasks.batch7_sweeps.run_referral_campaign",
    bind=True,
    max_retries=2,
    default_retry_delay=600,
)
def run_referral_campaign(self):
    try:
        # asyncio.run() required: get_event_loop() is deprecated/raises in Python 3.12 worker threads
        asyncio.run(_run_agent("referral_campaign"))
    except Exception as exc:
        logger.error("referral_campaign.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


# ── Cold Nurture ─────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.tasks.batch7_sweeps.run_cold_nurture",
    bind=True,
    max_retries=2,
    default_retry_delay=600,
)
def run_cold_nurture(self):
    try:
        # asyncio.run() required: get_event_loop() is deprecated/raises in Python 3.12 worker threads
        asyncio.run(_run_agent("cold_nurture"))
    except Exception as exc:
        logger.error("cold_nurture.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


# ── Lead Enrichment ──────────────────────────────────────────────────────────

@celery_app.task(
    name="app.tasks.batch7_sweeps.run_lead_enrichment",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def run_lead_enrichment(self):
    try:
        # asyncio.run() required: get_event_loop() is deprecated/raises in Python 3.12 worker threads
        asyncio.run(_run_agent("lead_enrichment"))
    except Exception as exc:
        logger.error("lead_enrichment.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


# ── Client Satisfaction ──────────────────────────────────────────────────────

@celery_app.task(
    name="app.tasks.batch7_sweeps.run_client_satisfaction",
    bind=True,
    max_retries=2,
    default_retry_delay=600,
)
def run_client_satisfaction(self):
    try:
        # asyncio.run() required: get_event_loop() is deprecated/raises in Python 3.12 worker threads
        asyncio.run(_run_agent("client_satisfaction"))
    except Exception as exc:
        logger.error("client_satisfaction.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


# ── Shared runner ────────────────────────────────────────────────────────────

# ── Contract Renewal (phase6-005) ────────────────────────────────────────────

@celery_app.task(
    name="app.tasks.batch7_sweeps.run_contract_renewal",
    bind=True,
    max_retries=2,
    default_retry_delay=600,
)
def run_contract_renewal(self):
    """Phase 6-005: weekly sweep for contracts approaching renewal.

    The contract_renewal agent infers renewal windows from invoice history
    and dispatches renewal outreach with idempotency guards. We just need
    to fire it on a cadence.
    """
    try:
        asyncio.run(_run_agent("contract_renewal"))
    except Exception as exc:
        logger.error("contract_renewal.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


# ── Weekly Intelligence (phase7-003) ─────────────────────────────────────────

@celery_app.task(
    name="app.tasks.batch7_sweeps.run_weekly_intelligence",
    bind=True,
    max_retries=2,
    default_retry_delay=600,
)
def run_weekly_intelligence(self):
    """Phase 7-003: Mondays 07:00 CET. Fires three intelligence agents
    in sequence — revenue_analytics, client_health, upsell_opportunity.
    An exception in one agent does NOT prevent the others from running."""
    try:
        asyncio.run(_run_weekly_intelligence())
    except Exception as exc:
        logger.error("weekly_intelligence.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _run_weekly_intelligence() -> dict:
    results: dict[str, str] = {}
    for name in ("revenue_analytics", "client_health", "upsell_opportunity"):
        try:
            await _run_agent(name)
            results[name] = "ok"
        except Exception as exc:
            logger.error(
                "weekly_intelligence.agent_failed",
                agent=name,
                error=str(exc),
            )
            results[name] = f"failed: {exc!s}"
    logger.info("weekly_intelligence.complete", **results)
    return results


async def _run_agent(agent_name: str) -> dict:
    from app.agents.base import AgentContext
    from app.agents.registry import registry

    settings = get_settings()
    async with db_context() as db:
        # conversation_id/request_id/lead_id required by AgentContext; sweep has no specific lead
        context = AgentContext(
            db=db,
            settings=settings,
            conversation_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
            lead_id=None,
        )
        agent = registry.get(agent_name)
        if not agent:
            logger.error(f"{agent_name}.agent_not_found", agent=agent_name)
            return {"error": f"{agent_name} agent not registered"}
        result = await agent(context, {})

    if not result.success:
        raise RuntimeError(f"{agent_name} failed: {result.error}")

    logger.info(f"{agent_name}.task_complete", output=result.output)
    return result.output
