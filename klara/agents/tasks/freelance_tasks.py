"""
app/tasks/freelance_tasks.py
──────────────────────────────
Celery tasks for the freelance platform pipeline.

Tasks:
  run_platform_scan        — Every 2h (08:00-20:00 CET weekdays)
                             Runs FreelanceScoutAgent across all 4 platforms.

  run_bid_strategy         — 30 minutes after each scan completes (and on-demand)
                             Runs BidStrategyAgent against all new projects.

  run_bid_submission       — Every 30 minutes (08:00-20:00 CET weekdays)
                             Runs PlatformBidSubmitterAgent to submit queued bids.

  check_bid_outcomes       — Every 4 hours
                             Placeholder for future bid status polling via APIs.
                             Currently just logs summary stats.

  run_fm_cookie_renewal    — Every 5 days
                             Renews the Freelancermap.de session cookie before
                             the 7-day REMEMBERME expiry.  Stores result in
                             Redis (fm:session_cookie).  Sends admin email on
                             failure so manual renewal can be triggered.
"""
from __future__ import annotations

import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(name="app.tasks.freelance_tasks.run_platform_scan", bind=True)
def run_platform_scan(self, platforms: list[str] | None = None, **kwargs):
    """
    Scan all configured freelance platforms for new matching projects.
    Runs FreelanceScoutAgent → creates FreelanceProject records.
    """
    import asyncio
    from klara.rarv.runtime import db_context
    from klara.rarv.runtime import get_settings
    from klara.rarv.runtime import AgentContext
    from app.agents.freelance_scout import FreelanceScoutAgent

    async def _run():
        settings = get_settings()
        async with db_context() as db:
            ctx = AgentContext(db=db, settings=settings)
            agent = FreelanceScoutAgent()
            result = await agent.run(
                ctx,
                {"platforms": platforms} if platforms else {},
            )
            if result.success:
                logger.info(
                    "freelance_task.scan_complete",
                    discovered=result.output.get("discovered", 0),
                    skipped=result.output.get("skipped_duplicate", 0),
                    platforms=result.output.get("platforms", {}),
                )
            else:
                logger.error(
                    "freelance_task.scan_failed",
                    error=result.error,
                )
            return result.output

    return asyncio.run(_run())


@shared_task(name="app.tasks.freelance_tasks.run_bid_strategy", bind=True)
def run_bid_strategy(self, **kwargs):
    """
    Score new FreelanceProject records and generate bid cover letters.
    Runs BidStrategyAgent — creates PlatformBid records for qualifying projects.
    """
    import asyncio
    from klara.rarv.runtime import db_context
    from klara.rarv.runtime import get_settings
    from klara.rarv.runtime import AgentContext
    from app.agents.bid_strategist import BidStrategyAgent

    async def _run():
        settings = get_settings()
        async with db_context() as db:
            ctx = AgentContext(db=db, settings=settings)
            agent = BidStrategyAgent()
            result = await agent.run(ctx, {})
            if result.success:
                logger.info(
                    "freelance_task.bid_strategy_complete",
                    scored=result.output.get("scored", 0),
                    bids_queued=result.output.get("bids_queued", 0),
                    ignored=result.output.get("ignored", 0),
                    errors=result.output.get("errors", 0),
                )
            else:
                logger.error(
                    "freelance_task.bid_strategy_failed",
                    error=result.error,
                )
            return result.output

    return asyncio.run(_run())


@shared_task(name="app.tasks.freelance_tasks.run_bid_submission", bind=True)
def run_bid_submission(self, **kwargs):
    """
    Submit queued bids to platforms (with daily cap guard).
    Freelancer.com via API; Upwork/PPH/Guru via manual-required email to Anthony.
    """
    import asyncio
    from klara.rarv.runtime import db_context
    from klara.rarv.runtime import get_settings
    from klara.rarv.runtime import AgentContext
    from app.agents.platform_bid_submitter import PlatformBidSubmitterAgent

    async def _run():
        settings = get_settings()
        async with db_context() as db:
            ctx = AgentContext(db=db, settings=settings)
            agent = PlatformBidSubmitterAgent()
            result = await agent.run(ctx, {})
            if result.success:
                logger.info(
                    "freelance_task.bid_submission_complete",
                    submitted=result.output.get("submitted", 0),
                    manual_required=result.output.get("manual_required", 0),
                    skipped_cap=result.output.get("skipped_cap", 0),
                    errors=result.output.get("errors", 0),
                )
            else:
                logger.error(
                    "freelance_task.bid_submission_failed",
                    error=result.error,
                )
            return result.output

    return asyncio.run(_run())


@shared_task(name="app.tasks.freelance_tasks.run_fm_cookie_renewal", bind=True)
def run_fm_cookie_renewal(self, **kwargs):
    """
    Log in to freelancermap.de and refresh the session cookie in Redis.

    Scheduled every 5 days so the 7-day REMEMBERME token is always renewed
    with a 2-day safety buffer.  On failure, sends an admin email so Anthony
    can trigger a manual renewal before bids start failing.
    """
    import asyncio
    from klara.rarv.runtime import get_settings
    from app.tasks.fm_cookie_renewer import login_freelancermap, store_fm_cookie_in_redis

    async def _run():
        settings = get_settings()
        ok, cookie, error = await login_freelancermap(settings)

        if ok:
            await store_fm_cookie_in_redis(cookie, settings.redis_url)
            logger.info("freelance_task.fm_cookie_renewed", cookie_length=len(cookie))
            return {"ok": True, "cookie_length": len(cookie)}
        else:
            logger.error("freelance_task.fm_cookie_renewal_failed", error=error)
            # Notify Anthony so manual renewal can happen before bids start failing
            try:
                from klara.rarv.runtime.email_sender import send_transactional_email
                await send_transactional_email(
                    settings,
                    to_email=getattr(settings, "admin_email", "astewart.tcml@gmail.com"),
                    to_name="Anthony",
                    subject="[Klaravex] Freelancermap cookie renewal FAILED — manual action needed",
                    body_html=(
                        "<p>The automatic Freelancermap.de session cookie renewal failed.</p>"
                        f"<p><strong>Error:</strong> {error}</p>"
                        "<p>Bids will start failing within the next 2 days. "
                        "Please log in manually at freelancermap.de to generate a fresh cookie, "
                        "then update <code>FREELANCERMAP_SESSION_COOKIE</code> in "
                        "<code>/opt/loki-agents/.env</code> and run "
                        "<code>docker compose up -d --force-recreate worker</code>.</p>"
                        "<p><small>Klaravex</small></p>"
                    ),
                    body_text=(
                        f"Freelancermap cookie renewal failed: {error}\n\n"
                        "Manual renewal required — bids will start failing within 2 days.\n"
                        "Log in at freelancermap.de, copy the new cookies into "
                        "/opt/loki-agents/.env (FREELANCERMAP_SESSION_COOKIE), then:\n"
                        "docker compose up -d --force-recreate worker"
                    ),
                )
            except Exception as mail_exc:
                logger.error("freelance_task.fm_cookie_alert_failed", error=str(mail_exc))
            return {"ok": False, "error": error}

    return asyncio.run(_run())


@shared_task(name="app.tasks.freelance_tasks.check_bid_outcomes", bind=True)
def check_bid_outcomes(self, **kwargs):
    """
    Placeholder for bid outcome polling.
    Currently logs pipeline stats. Future: poll Freelancer.com API for bid status updates.
    """
    import asyncio
    from klara.rarv.runtime import db_context
    from klara.rarv.runtime import get_settings
    from sqlalchemy import func, select
    from klara.rarv.platform_bid import PlatformBid
    from klara.rarv.freelance_project import FreelanceProject

    async def _run():
        async with db_context() as db:
            bid_q = await db.execute(
                select(PlatformBid.status, func.count(PlatformBid.id))
                .group_by(PlatformBid.status)
            )
            bid_stats = {row[0]: row[1] for row in bid_q.all()}

            proj_q = await db.execute(
                select(FreelanceProject.status, func.count(FreelanceProject.id))
                .group_by(FreelanceProject.status)
            )
            proj_stats = {row[0]: row[1] for row in proj_q.all()}

            logger.info(
                "freelance_task.pipeline_stats",
                bids=bid_stats,
                projects=proj_stats,
            )
            return {"bids": bid_stats, "projects": proj_stats}

    return asyncio.run(_run())
