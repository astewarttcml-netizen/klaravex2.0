"""
app/tasks/pipeline_reporter.py
────────────────────────────────
Celery task: send weekly pipeline digest email to Anthony.

Schedule: Monday 08:30 Europe/Berlin (beat_schedule in celery_app.py)
Agent:     PipelineReporterAgent (P1)
"""
import asyncio
import uuid

import structlog

from klara.rarv.runtime import celery_app
from klara.rarv.runtime import get_settings
from klara.rarv.runtime import db_context

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="app.tasks.pipeline_reporter.run_pipeline_reporter",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def run_pipeline_reporter(self):
    """Celery entry point — synchronous wrapper."""
    try:
        # asyncio.run() required: get_event_loop() is deprecated/raises in Python 3.12 worker threads
        asyncio.run(_run())
    except Exception as exc:
        logger.error("pipeline_reporter.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _run() -> dict:
    from klara.rarv.runtime import AgentContext
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
        agent = registry.get("pipeline_reporter")
        result = await agent(context, {})

    if not result.success:
        raise RuntimeError(f"PipelineReporterAgent failed: {result.error}")

    logger.info("pipeline_reporter.task_complete", output=result.output)
    return result.output
