"""
app/tasks/seo_content.py
─────────────────────────
Celery task: generate a weekly SEO blog post draft.

Schedule: Mondays 06:30 Europe/Berlin (see celery_app.py beat schedule).
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


@celery_app.task(name="seo_content", bind=True, max_retries=2, default_retry_delay=300)
def run_seo_content(self, triggered_by: str = "beat"):
    """Generate and draft a weekly SEO blog post draft."""
    log = logger.bind(task="seo_content", triggered_by=triggered_by)
    log.info("seo_content.task_start")

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
            agent = registry.get("seo_content_writer")
            if not agent:
                log.error("seo_content.agent_not_found")
                return {"error": "seo_content_writer agent not registered"}

            result = await agent(context, {})
            if result.success or result.approval_required:
                log.info("seo_content.task_complete",
                         status=result.output.get("status", "needs_approval") if result.output else "needs_approval")
            else:
                log.error("seo_content.task_failed", error=result.error)
            return result.output

    try:
        return asyncio.run(_run())
    except Exception as exc:
        log.error("seo_content.task_error", error=str(exc))
        raise self.retry(exc=exc)
