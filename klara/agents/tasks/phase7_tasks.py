"""
app/tasks/phase7_tasks.py
──────────────────────────
Celery beat tasks for Phase 7 agents:

  - run_weekly_report          → WeeklyReportAgent        (Monday 08:00 CET)
  - run_lead_scoring_refresh   → LeadScoringRefreshAgent  (daily 02:00 CET)
"""
from __future__ import annotations

import asyncio
import uuid

import structlog

from klara.rarv.runtime import celery_app
from klara.rarv.runtime import get_settings
from klara.rarv.runtime import db_context

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Weekly report
# ─────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.tasks.phase7_tasks.run_weekly_report",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def run_weekly_report(self, triggered_by: str = "beat") -> dict:
    """
    Celery task: generate and email the weekly business summary.
    Scheduled: every Monday 08:00 CET.
    """
    try:
        return asyncio.run(_weekly_report(triggered_by=triggered_by))
    except Exception as exc:
        logger.error("phase7.weekly_report.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _weekly_report(triggered_by: str) -> dict:
    from klara.rarv.runtime import AgentContext
    from app.agents.registry import registry

    logger.info("phase7.weekly_report.start", triggered_by=triggered_by)
    settings = get_settings()
    async with db_context() as db:
        context = AgentContext(
            db=db,
            settings=settings,
            conversation_id=str(uuid.uuid4()),
            request_id=str(uuid.uuid4()),
        )
        agent = registry.get("weekly_report")
        result = await agent(context, {})

    if not result.success:
        logger.error("phase7.weekly_report.failed", error=result.error)
        raise RuntimeError(result.error or "WeeklyReportAgent returned failure")

    out = result.output or {}
    logger.info(
        "phase7.weekly_report.complete",
        emailed=out.get("emailed"),
        week_start=out.get("week_start"),
    )
    return {"success": True, "output": out}


# ─────────────────────────────────────────────────────────────────────────────
# Lead scoring refresh
# ─────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.tasks.phase7_tasks.run_lead_scoring_refresh",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def run_lead_scoring_refresh(self, triggered_by: str = "beat") -> dict:
    """
    Celery task: re-score all active leads nightly.
    Scheduled: daily 02:00 CET.
    """
    try:
        return asyncio.run(_lead_scoring_refresh(triggered_by=triggered_by))
    except Exception as exc:
        logger.error("phase7.lead_scoring_refresh.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _lead_scoring_refresh(triggered_by: str) -> dict:
    from klara.rarv.runtime import AgentContext
    from app.agents.registry import registry

    logger.info("phase7.lead_scoring_refresh.start", triggered_by=triggered_by)
    settings = get_settings()
    async with db_context() as db:
        context = AgentContext(
            db=db,
            settings=settings,
            conversation_id=str(uuid.uuid4()),
            request_id=str(uuid.uuid4()),
        )
        agent = registry.get("lead_scoring_refresh")
        result = await agent(context, {})

    if not result.success:
        logger.error("phase7.lead_scoring_refresh.failed", error=result.error)
        raise RuntimeError(result.error or "LeadScoringRefreshAgent returned failure")

    out = result.output or {}
    logger.info(
        "phase7.lead_scoring_refresh.complete",
        total=out.get("total_leads"),
        refreshed=out.get("refreshed"),
        failed=out.get("failed"),
    )
    return {"success": True, "output": out}
