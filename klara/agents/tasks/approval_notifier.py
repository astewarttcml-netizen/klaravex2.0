"""
app/tasks/approval_notifier.py
────────────────────────────────
Celery beat task: notify Anthony of unreviewed pending approval requests.

  run_approval_notifier  → ApprovalNotifierAgent  (every 30 minutes)

Runs every 30 minutes so that a freshly-queued P4/P5 action reaches
Anthony's inbox within half an hour of being created.  The agent itself
is idempotent (stamps notified_at), so duplicate runs are safe.
"""
from __future__ import annotations

import asyncio
import uuid

import structlog

from klara.rarv.runtime import celery_app
from klara.rarv.runtime import get_settings
from klara.rarv.runtime import db_context

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="app.tasks.approval_notifier.run_approval_notifier",
    bind=True,
    max_retries=2,
    default_retry_delay=120,   # 2-min retry gap — notifications should be prompt
)
def run_approval_notifier(self, triggered_by: str = "beat") -> dict:
    """
    Celery task: sweep for unnotified pending approvals and email Anthony.
    Scheduled: every 30 minutes.
    """
    try:
        return asyncio.run(_approval_notifier(triggered_by=triggered_by))
    except Exception as exc:
        logger.error(
            "approval_notifier.task_failed",
            error=str(exc),
            exc_info=True,
        )
        raise self.retry(exc=exc)


async def _approval_notifier(triggered_by: str) -> dict:
    from klara.rarv.runtime import AgentContext
    from app.agents.registry import registry

    logger.info("approval_notifier.task_start", triggered_by=triggered_by)
    settings = get_settings()

    async with db_context() as db:
        context = AgentContext(
            db=db,
            settings=settings,
            conversation_id=str(uuid.uuid4()),
            request_id=str(uuid.uuid4()),
        )
        agent = registry.get("approval_notifier")
        result = await agent(context, {})

    if not result.success:
        logger.error("approval_notifier.agent_failed", error=result.error)
        raise RuntimeError(result.error or "ApprovalNotifierAgent returned failure")

    out = result.output or {}
    logger.info(
        "approval_notifier.task_complete",
        status=out.get("status"),
        notified=out.get("notified", 0),
        p5=out.get("p5", 0),
        p4=out.get("p4", 0),
        p3=out.get("p3", 0),
    )
    return {"success": True, "output": out}
