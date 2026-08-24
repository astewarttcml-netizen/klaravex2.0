"""
app/tasks/social_media.py
────────────────────────
Celery tasks for social media operations.

Scheduling (n8n via beat_trigger.py — no Celery beat)
──────────────────────────────────────────────────────
  route_qualified_social_posts     every 15 min (n8n)
  generate-us-social-drafts        Mon–Fri 15:00 Berlin — US/NA clients    ← LIVE
  publish_scheduled_posts          pending platform API integration
  collect_daily_analytics_task     pending platform API integration
  generate_weekly_digest           pending platform API integration

Implementation status
─────────────────────
  route_qualified_social_posts      — LIVE: sweeps recently-won leads, calls SocialMediaManagerAgent
  generate_weekly_social_drafts     — LIVE: called by US n8n trigger with market="us"
  publish_scheduled_posts           — pending platform API integration
  collect_daily_analytics_task      — pending platform API integration
  generate_weekly_digest            — pending platform API integration
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# route_qualified_social_posts — LIVE
# ──────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.tasks.social_media.route_qualified_social_posts",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
)
def route_qualified_social_posts(self: Any) -> dict[str, Any]:
    """
    Sweep leads that moved to status='won' in the last 24 hours and queue
    a social post bundle for each via SocialMediaManagerAgent (P3 approval).

    The agent generates copy for all 5 platforms using claude-haiku and enqueues
    a single ApprovalRequest with action_name='social_media_manager.publish'.
    The human reviewer approves/rejects in the admin dashboard — no direct
    publishing happens here.
    """
    try:
        result = asyncio.run(_route_qualified())
        return result
    except Exception as exc:
        logger.error("social_media.route_qualified_social_posts.error", error=str(exc))
        try:
            import asyncio as _asyncio
            from app.services.pipeline_alert import pipeline_alert
            _asyncio.run(pipeline_alert(
                "socials", "route_error", "critical",
                f"route_qualified_social_posts failed (will retry): {exc}"
            ))
        except Exception:
            pass
        raise self.retry(exc=exc)


async def _route_qualified() -> dict[str, Any]:
    from app.config import get_settings
    from app.database import db_context
    from app.models.lead import Lead, LeadStatus
    from app.agents.base import AgentContext
    from app.agents.registry import registry
    from sqlalchemy import select

    settings = get_settings()
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    queued = 0
    errors = 0

    async with db_context() as db:
        result = await db.execute(
            select(Lead).where(
                Lead.status == LeadStatus.won,
                Lead.updated_at >= cutoff,
            )
        )
        leads = result.scalars().all()

        if not leads:
            logger.info("social_media.route_qualified.no_new_won_leads")
            return {"status": "ok", "queued": 0, "errors": 0}

        agent = registry.get("social_media_manager")

        for lead in leads:
            try:
                context = AgentContext(
                    db=db,
                    settings=settings,
                    lead_id=lead.id,
                    conversation_id=uuid.uuid4(),
                    request_id=uuid.uuid4(),
                )
                payload: dict[str, Any] = {"lead_id": str(lead.id)}
                res = await agent(context, payload)

                if res.success or res.approval_required:
                    queued += 1
                    logger.info(
                        "social_media.route_qualified.queued",
                        lead_id=str(lead.id),
                        needs_approval=res.approval_required,
                    )
                else:
                    errors += 1
                    logger.warning(
                        "social_media.route_qualified.agent_failed",
                        lead_id=str(lead.id),
                        message=res.message,
                    )

            except Exception as exc:
                errors += 1
                logger.error(
                    "social_media.route_qualified.lead_error",
                    lead_id=str(lead.id),
                    error=str(exc),
                )

    logger.info(
        "social_media.route_qualified.complete",
        leads_processed=len(leads),
        queued=queued,
        errors=errors,
    )
    if errors > 0:
        try:
            from app.services.pipeline_alert import pipeline_alert
            await pipeline_alert(
                "socials", "route_qualified_errors", "warning",
                f"route_qualified completed with {errors} errors — "
                f"leads={len(leads)}, queued={queued}"
            )
        except Exception:
            pass
    return {"status": "ok", "queued": queued, "errors": errors}


# ──────────────────────────────────────────────────────────────────────────────
# generate_weekly_social_drafts — LIVE
# Beat: Mon / Wed / Fri  09:00 CET
# ──────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.tasks.social_media.generate_social_drafts",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def generate_social_drafts(self: Any, market: str = "us") -> dict[str, Any]:
    """
    Triggered Mon–Fri by n8n at 15:00 Berlin (09:00 ET) with market="us"
    for US/NA clients (LinkedIn/Twitter/Facebook/Reddit).

    For each run:
      1. Generate platform-specific topics via Claude
      2. Generate drafts for the relevant platform set
      3. Queue one ApprovalRequest (bundled multi-platform payload)

    Anthony reviews in the admin dashboard and approves/rejects individually.
    """
    try:
        result = asyncio.run(_generate_weekly_drafts(market=market))
        return result
    except Exception as exc:
        logger.error("social_media.generate_weekly_social_drafts.error", error=str(exc), market=market)
        try:
            import asyncio as _asyncio
            from app.services.pipeline_alert import pipeline_alert
            _asyncio.run(pipeline_alert(
                "socials", "draft_error", "critical",
                f"generate_social_drafts failed (will retry): {exc}"
            ))
        except Exception:
            pass
        raise self.retry(exc=exc)


async def _generate_weekly_drafts(market: str = "us") -> dict[str, Any]:
    from app.config import get_settings
    from app.database import db_context
    from app.agents.base import AgentContext
    from app.agents.registry import registry
    from app.agents.social_media_manager import SocialMediaManagerAgent

    settings = get_settings()
    approval_ids: list[str] = []
    errors = 0

    region = "United States / North America"

    platform_topics = await SocialMediaManagerAgent.generate_platform_topics(
        api_key=settings.anthropic_api_key,
        market=market,
    )
    logger.info(
        "social_media.weekly_drafts.platform_topics",
        market=market,
        topics={p: t[:60] for p, t in platform_topics.items()},
    )

    agent = registry.get("social_media_manager")

    # Build content brief from RSS feeds + prospect research + vault data
    content_brief = {}
    try:
        from app.services.social_feed_pipeline import build_content_brief, brief_to_prompt_context
        content_brief = await build_content_brief()
        news_context = brief_to_prompt_context(content_brief)
        logger.info("social_media.content_brief_built",
                     headlines=len(content_brief.get("headlines", [])),
                     research=len(content_brief.get("prospect_research_findings", [])))
    except Exception as exc:
        news_context = ""
        logger.warning("social_media.content_brief_failed", error=str(exc)[:100])

    async with db_context() as db:
        try:
            context = AgentContext(
                db=db,
                settings=settings,
                conversation_id=uuid.uuid4(),
                request_id=uuid.uuid4(),
            )
            res = await agent(
                context,
                {
                    "platform_topics": platform_topics,
                    "platforms":       list(platform_topics.keys()),
                    "market":          market,
                    "region":          region,
                    "news_context":    news_context,
                    "content_brief":   content_brief,
                },
            )

            if res.approval_required or res.success:
                approval_id = getattr(res, "approval_id", None) or "unknown"
                approval_ids.append(approval_id)
                logger.info(
                    "social_media.weekly_drafts.queued",
                    approval_id=approval_id,
                    platforms=list(platform_topics.keys()),
                )
            else:
                errors += 1
                logger.warning(
                    "social_media.weekly_drafts.agent_failed",
                    message=res.error,
                )

        except Exception as exc:
            errors += 1
            logger.error(
                "social_media.weekly_drafts.error",
                error=str(exc),
            )

    logger.info(
        "social_media.weekly_drafts.complete",
        platforms_processed=len(platform_topics),
        approval_items=len(approval_ids),
        errors=errors,
    )
    try:
        from app.services.pipeline_alert import pipeline_alert
        await pipeline_alert(
            "socials", "daily_summary", "info",
            f"Social drafts: {len(platform_topics)} platforms, "
            f"{len(approval_ids)} approval items, {errors} errors"
        )
    except Exception:
        pass
    return {
        "status":            "ok",
        "platforms_processed": len(platform_topics),
        "approval_items":    len(approval_ids),
        "approval_ids":      approval_ids,
        "errors":            errors,
    }


# ──────────────────────────────────────────────────────────────────────────────
# publish_scheduled_posts — LIVE (platform API integration complete)
# ──────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.tasks.social_media.publish_scheduled_posts",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def publish_scheduled_posts(self: Any) -> dict[str, Any]:
    """
    Publish approved posts at scheduled times.

    Reads approved posts from klaravex_social_drafts with status='approved'
    and scheduled_for <= now(), then publishes to each platform via the
    direct API integration (LinkedIn, X/Twitter, Facebook).

    Includes a brand-voice pre-flight check before publishing.
    """
    try:
        result = asyncio.run(_publish_scheduled())
        return result
    except Exception as exc:
        logger.error("social_media.publish_scheduled_posts.error", error=str(exc))
        try:
            import asyncio as _asyncio
            from app.services.pipeline_alert import pipeline_alert
            _asyncio.run(pipeline_alert(
                "socials", "publish_error", "critical",
                f"publish_scheduled_posts failed (will retry): {exc}"
            ))
        except Exception:
            pass
        raise self.retry(exc=exc)


async def _publish_scheduled() -> dict[str, Any]:
    """
    Core logic for publish_scheduled_posts.

    1. Query DB for approved drafts that are due (status='approved',
       scheduled_for <= now()).
    2. Run brand-voice pre-flight check on each draft.
    3. Publish via social_publisher.publish_all().
    4. Update draft status to 'published' or 'failed'.
    """
    from app.config import get_settings
    from app.database import db_context
    from app.services.social_publisher import publish_all, PublishResult
    from app.services.social_quality_gate import assess_social_post_quality

    settings = get_settings()
    published_count = 0
    failed_count = 0
    skipped_count = 0

    async with db_context() as db:
        from sqlalchemy import select
        from app.models.social_draft import SocialDraft, SocialDraftStatus

        now = datetime.now(tz=timezone.utc)
        result = await db.execute(
            select(SocialDraft).where(
                SocialDraft.status == SocialDraftStatus.approved,
                SocialDraft.scheduled_for <= now,
            )
        )
        drafts = result.scalars().all()

        if not drafts:
            logger.info("social_media.publish_scheduled.no_due_drafts")
            return {"status": "ok", "published": 0, "failed": 0, "skipped": 0}

        # Group drafts by platform and collect for batch publish
        drafts_by_platform: dict[str, list[SocialDraft]] = {}
        for draft in drafts:
            platform = draft.platform or ""
            if platform not in drafts_by_platform:
                drafts_by_platform[platform] = []
            drafts_by_platform[platform].append(draft)

        # Process each platform's drafts
        for platform, platform_drafts in drafts_by_platform.items():
            for draft in platform_drafts:
                # ── Brand-voice pre-flight check ──────────────────────────────
                try:
                    quality = await assess_social_post_quality(
                        settings=settings,
                        campaign_json='{}',
                        platform=platform,
                        topic=draft.topic or "",
                        draft_text=draft.content or "",
                    )
                    if not quality.ok:
                        logger.warning(
                            "social_media.publish_scheduled.brand_voice_rejected",
                            draft_id=str(draft.id),
                            platform=platform,
                            issues=quality.issues,
                        )
                        draft.status = SocialDraftStatus.rejected
                        draft.error = f"brand_voice_rejected: {quality.issues}"
                        skipped_count += 1
                        continue
                except Exception as exc:
                    logger.warning(
                        "social_media.publish_scheduled.quality_gate_error",
                        draft_id=str(draft.id),
                        error=str(exc),
                    )
                    # Continue to publish attempt even if quality gate errors

                # ── Publish via social_publisher ──────────────────────────────
                try:
                    publish_results: list[PublishResult] = await publish_all(
                        drafts={platform: draft.content or ""},
                        platforms=[platform],
                        settings=settings,
                    )
                    result = publish_results[0] if publish_results else None

                    if result and result.success:
                        draft.status = SocialDraftStatus.published
                        draft.post_id = result.post_id
                        draft.post_url = result.post_url
                        published_count += 1
                        logger.info(
                            "social_media.publish_scheduled.published",
                            draft_id=str(draft.id),
                            platform=platform,
                            post_url=result.post_url,
                        )
                    else:
                        error_msg = result.error if result else "unknown publish failure"
                        draft.status = SocialDraftStatus.failed
                        draft.error = error_msg
                        failed_count += 1
                        logger.warning(
                            "social_media.publish_scheduled.failed",
                            draft_id=str(draft.id),
                            platform=platform,
                            error=error_msg,
                        )
                except Exception as exc:
                    draft.status = SocialDraftStatus.failed
                    draft.error = str(exc)[:500]
                    failed_count += 1
                    logger.error(
                        "social_media.publish_scheduled.exception",
                        draft_id=str(draft.id),
                        platform=platform,
                        error=str(exc),
                    )

        await db.commit()

    logger.info(
        "social_media.publish_scheduled.complete",
        total=len(drafts),
        published=published_count,
        failed=failed_count,
        skipped=skipped_count,
    )

    # Notify if there were failures
    if failed_count > 0:
        try:
            from app.services.pipeline_alert import pipeline_alert
            await pipeline_alert(
                "socials", "publish_failures", "warning",
                f"publish_scheduled_posts: {failed_count} failures, "
                f"{published_count} published, {skipped_count} skipped"
            )
        except Exception:
            pass

    return {
        "status": "ok",
        "published": published_count,
        "failed": failed_count,
        "skipped": skipped_count,
    }


# ──────────────────────────────────────────────────────────────────────────────
# collect_daily_analytics_task — pending platform API integration
# ──────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.tasks.social_media.collect_daily_analytics_task",
    bind=True,
    max_retries=0,
)
def collect_daily_analytics_task(self: Any) -> dict[str, Any]:
    """
    Collect post impressions, clicks, and engagement from social platforms.

    No-op until platform API integration is complete.
    """
    logger.info(
        "social_media.collect_daily_analytics_task.noop",
        reason="platform API integration pending",
    )
    return {"status": "noop", "reason": "platform_api_pending"}


# ──────────────────────────────────────────────────────────────────────────────
# generate_weekly_digest — pending platform API integration
# ──────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.tasks.social_media.generate_weekly_digest",
    bind=True,
    max_retries=0,
)
def generate_weekly_digest(self: Any) -> dict[str, Any]:
    """
    Compile weekly analytics into a digest and include in the Monday pipeline report.

    No-op until platform API integration is complete.
    """
    logger.info(
        "social_media.generate_weekly_digest.noop",
        reason="platform API integration pending",
    )
    return {"status": "noop", "reason": "platform_api_pending"}
