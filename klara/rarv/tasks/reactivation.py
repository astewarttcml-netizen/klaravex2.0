"""
app/tasks/reactivation.py
──────────────────────────
Celery task: daily sweep for WARM leads to reactivate.

Schedule: daily 10:00 Europe/Berlin (see celery_app.py beat schedule).
"""
from __future__ import annotations

import asyncio
import uuid

import structlog

from app.tasks.celery_app import celery_app
from app.database import db_context
from app.config import get_settings
from app.agents.base import AgentContext
from app.agents.registry import registry

logger = structlog.get_logger(__name__)


@celery_app.task(name="reactivation", bind=True, max_retries=2, default_retry_delay=300)
def run_reactivation(self, triggered_by: str = "beat"):
    """Sweep WARM leads for re-engagement email drafts."""
    log = logger.bind(task="reactivation", triggered_by=triggered_by)
    log.info("reactivation.task_start")

    async def _run():
        settings = get_settings()
        async with db_context() as db:
            context = AgentContext(
                db=db,
                settings=settings,
                conversation_id=uuid.uuid4(),
                request_id=uuid.uuid4(),
                lead_id=None,
            )
            agent = registry.get("lead_reactivation")
            if not agent:
                log.error("reactivation.agent_not_found")
                return {"error": "lead_reactivation agent not registered"}

            result = await agent(context, {})
            log.info("reactivation.task_complete", output=result.output)
            return result.output

    try:
        return asyncio.run(_run())
    except Exception as exc:
        log.error("reactivation.task_error", error=str(exc))
        raise self.retry(exc=exc)
