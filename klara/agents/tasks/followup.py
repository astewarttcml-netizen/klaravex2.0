"""
app/tasks/followup.py
──────────────────────
Celery task: send follow-up emails to leads that booked but haven't responded.

Schedule: top of every hour (beat_schedule in celery_app.py)
Agent:     followup_nurture (P2)

The agent sweeps qualified leads where booking_email_sent_at is set but
followup_sent_at is NULL and the configurable delay (default 3 days) has elapsed.
"""
from __future__ import annotations

import asyncio
import uuid

import structlog

from klara.rarv.runtime import celery_app
from klara.rarv.runtime import db_context
from klara.rarv.runtime import get_settings
from klara.rarv.runtime import AgentContext
from app.agents.registry import registry

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="app.tasks.followup.send_followup_emails",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def send_followup_emails(self) -> dict:
    """Sweep qualified leads and send follow-up emails where due."""
    log = logger.bind(task="followup")
    log.info("followup.task_start")

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
            agent = registry.get("followup_nurture")
            result = await agent(context, {})
            log.info("followup.task_complete", output=result.output)
            return result.output

    try:
        return asyncio.run(_run())
    except Exception as exc:
        log.error("followup.task_error", error=str(exc))
        raise self.retry(exc=exc)
