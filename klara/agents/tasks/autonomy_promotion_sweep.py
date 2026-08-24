"""
app/tasks/autonomy_promotion_sweep.py
──────────────────────────────────────
phase19-010 — Daily Celery beat task for the autonomy promotion runner.

Replaces the phase8-002 snapshot-based sweep (which proposed a promotion
the moment metrics passed the green-gate on any single day). The new
behaviour requires GREEN_STREAK_DAYS_REQUIRED (=14) consecutive days of
status_color='green' from autonomy_metrics BEFORE emitting a P4
ApprovalRequest. The streak state lives in autonomy_streaks (migration
0069).

Schedule: nightly 03:00 Europe/Berlin (wiring preserved from phase8-002
in app/tasks/celery_app.py).

Reads autonomy_metrics (phase3-003), projects each row to
(agent_name, status_color), and hands off to
klara.rarv.runtime.autonomy_promotion_runner.run_promotion_sweep.

The streak logic + promotion-request creation lives in the service
module so it stays unit-testable without Celery.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from klara.rarv.runtime import db_context
from klara.rarv.runtime.autonomy_promotion_runner import run_promotion_sweep
from klara.rarv.runtime import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="app.tasks.autonomy_promotion_sweep.run_autonomy_promotion_sweep",
    bind=True,
    max_retries=2,
    default_retry_delay=600,
)
def run_autonomy_promotion_sweep(self):
    """Celery entry point — synchronous wrapper."""
    try:
        result = asyncio.run(_run())
        logger.info("autonomy_promotion.task_complete", **{
            k: v for k, v in result.items() if k != "promoted_agents"
        }, promoted_count=len(result.get("promoted_agents", [])))
        return result
    except Exception as exc:
        logger.error("autonomy_promotion.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _run() -> dict:
    """
    Read today's autonomy_metrics, project to (agent_name, status_color)
    tuples, run the sweep, and commit.
    """
    # Lazy import to avoid a circular: reports_admin imports services, which
    # might in turn import tasks.
    from app.api.reports_admin import autonomy_metrics

    now = datetime.now(timezone.utc)
    async with db_context() as db:
        metrics = await autonomy_metrics(days=30, db=db)
        agent_status = [
            (a["agent_name"], a["status_color"])
            for a in metrics.get("agents", [])
        ]
        summary = await run_promotion_sweep(db, agent_status, now=now)
        await db.commit()

    return summary
