"""
app/tasks/invoice_reminder.py
──────────────────────────────
Celery task: daily sweep for overdue invoices → queue P3 payment reminders.

Schedule: weekdays 09:00 CET (beat_schedule in celery_app.py)
Agent:     invoice_reminder (P3)

The agent sweeps loki_invoices for rows where:
  - status IN ('sent', 'unpaid')
  - due_date < today
  - reminder_sent_at IS NULL OR reminder_sent_at <= now - 14 days
  - reminder_count < 3

For each overdue invoice the agent builds a bilingual HTML reminder email
and queues it for Anthony's P3 approval before delivery.  The task itself
is idempotent: the agent stamps reminder_sent_at on each processed invoice
so re-running during the same day is a no-op for already-queued invoices.
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


@celery_app.task(
    name="app.tasks.invoice_reminder.sweep_overdue_invoices",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def sweep_overdue_invoices(self) -> dict:
    """
    Sweep loki_invoices for overdue rows and queue a P3 reminder for each.

    Returns a dict with keys: queued (int), errors (list[str] | None).
    Retries up to 2 times on unexpected errors with a 5-minute backoff.
    """
    log = logger.bind(task="invoice_reminder")
    log.info("invoice_reminder.task_start")

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
            agent = registry.get("invoice_reminder")
            if not agent:
                log.error("invoice_reminder.agent_not_found")
                return {"status": "error", "detail": "invoice_reminder agent not registered"}

            # No payload → triggers daily sweep mode inside the agent
            result = await agent(context, {})
            log.info("invoice_reminder.task_complete", output=result.output)
            return result.output

    try:
        return asyncio.run(_run())
    except Exception as exc:
        log.error("invoice_reminder.task_error", error=str(exc))
        raise self.retry(exc=exc)
