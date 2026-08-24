"""
app/tasks/platform_message_agent_tasks.py

Celery tasks for the freelance-platform auto-reply agent (phase A: draft mode,
Freelancer.com only).

Tasks:
  poll_freelancer_com_messages   - Every 15 minutes weekdays 8-20 CET.
                                    Runs FreelancerComMessageScoutAgent to
                                    fetch new messages from FL.com.
  generate_platform_message_drafts - Runs 2 minutes after each poll.
                                     Runs PlatformMessageReplyDraftAgent to
                                     produce Claude-drafted replies.

Both tasks are idempotent and safe to invoke manually via `celery call`.
"""
from __future__ import annotations

import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(name="app.tasks.platform_message_agent_tasks.poll_freelancer_com_messages", bind=True)
def poll_freelancer_com_messages(self, **kwargs):
    """Fetch new messages from Freelancer.com API into klaravex_platform_messages."""
    import asyncio
    from app.database import db_context
    from app.config import get_settings
    from app.agents.base import AgentContext
    from app.agents.freelancer_com_message_scout import FreelancerComMessageScoutAgent

    async def _run():
        settings = get_settings()
        async with db_context() as db:
            ctx = AgentContext(db=db, settings=settings)
            agent = FreelancerComMessageScoutAgent()
            result = await agent.run(ctx, dict(kwargs) if kwargs else {})
            if result.success:
                logger.info(
                    "platform_message_agent.poll_complete",
                    **(result.output or {}),
                )
            else:
                logger.error("platform_message_agent.poll_failed", error=result.error)
            return result.output

    return asyncio.run(_run())


@shared_task(name="app.tasks.platform_message_agent_tasks.generate_platform_message_drafts", bind=True)
def generate_platform_message_drafts(self, **kwargs):
    """Generate Claude-drafted replies for new inbound platform messages."""
    import asyncio
    from app.database import db_context
    from app.config import get_settings
    from app.agents.base import AgentContext
    from app.agents.platform_message_reply_draft import PlatformMessageReplyDraftAgent

    async def _run():
        settings = get_settings()
        async with db_context() as db:
            ctx = AgentContext(db=db, settings=settings)
            agent = PlatformMessageReplyDraftAgent()
            result = await agent.run(ctx, dict(kwargs) if kwargs else {})
            if result.success:
                logger.info(
                    "platform_message_agent.draft_complete",
                    **(result.output or {}),
                )
            else:
                logger.error("platform_message_agent.draft_failed", error=result.error)
            return result.output

    return asyncio.run(_run())
