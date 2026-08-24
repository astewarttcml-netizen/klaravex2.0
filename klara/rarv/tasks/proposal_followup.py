"""
app/tasks/proposal_followup.py
────────────────────────────────
Celery task: sweep proposals with no client response and queue follow-up drafts.

Schedule: every 6 hours (beat_schedule in celery_app.py)
Agent:     ProposalFollowupAgent (P3)
"""
import asyncio
import uuid

import structlog

from app.tasks.celery_app import celery_app
from app.config import get_settings
from app.database import db_context

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="app.tasks.proposal_followup.run_proposal_followup",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def run_proposal_followup(self):
    """Celery entry point — synchronous wrapper."""
    try:
        # asyncio.run() required: get_event_loop() is deprecated/raises in Python 3.12 worker threads
        asyncio.run(_run())
    except Exception as exc:
        logger.error("proposal_followup.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _run() -> dict:
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
        agent = registry.get("proposal_followup")
        result = await agent(context, {})

    if not result.success:
        raise RuntimeError(f"ProposalFollowupAgent failed: {result.error}")

    logger.info("proposal_followup.task_complete", output=result.output)
    return result.output
