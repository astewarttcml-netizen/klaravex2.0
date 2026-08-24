"""
app/api/beat_trigger.py
=======================
POST /api/v1/admin/trigger/{task_name}

n8n calls this endpoint to fire a Celery task.
System cron calls the same endpoint 15 minutes later as a fallback.

Redis idempotency guard
-----------------------
Key:   loki:beat_last_run:{task_name}
Value: ISO timestamp of last trigger
TTL:   Per-task (see TASK_REGISTRY).  At minimum 15 min so the +15-min cron
       backup is suppressed when n8n already fired.

Response codes
--------------
200 triggered   — task dispatched
200 skipped     — idempotency guard active; already ran within TTL window
404             — task_name not in registry
401             — missing / invalid X-API-Key
422             — task dispatch failure (Celery broker unreachable)
"""
from __future__ import annotations

import datetime
from typing import Any

import redis.asyncio as aioredis
import structlog
from celery import Celery
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import get_settings
from app.core.security import verify_api_key

log = structlog.get_logger(__name__)
router = APIRouter()

# ─────────────────────────────────────────────────────────────────────────────
# Task registry
# Maps beat-schedule name → (celery_task_path, ttl_seconds, kwargs_override)
#
# TTL rules:
#   • ≥ 900 s  (15 min)  so the +15-min system-cron backup is always suppressed
#     when n8n fired successfully.
#   • < interval  so the next legitimate scheduled invocation is not blocked.
#   • For tasks with interval ≤ 20 min we accept a narrow window where the
#     cron backup may double-fire; those tasks must be idempotent.
# ─────────────────────────────────────────────────────────────────────────────

_H = 3600    # seconds per hour
_D = 86400   # seconds per day


# ── Disabled triggers (operational, not destructive) ─────────────────────────
# n8n still POSTs to these endpoints on schedule. The handler short-circuits
# with status="skipped" + reason="disabled" so the task is not dispatched to
# Celery, no LLM credits are burned, no DB rows are written.
#
# Rationale (2026-05-29): these scheduled agents have no eligible records to
# act on at this business stage (no paying clients, no won deals, no
# proposals sent, no Vapi voice flow). They were producing zero output every
# day while still consuming a Celery queue slot and a worker fork. Disable
# them at the trigger gate until the upstream data exists.
#
# Flip an entry out of this set to re-enable. The agent code stays registered
# and the trigger entry stays in TASK_REGISTRY below — only the dispatch is
# gated.
DISABLED_TRIGGERS: set[str] = {
    # No paying clients yet → nothing to invoice/remind/expand
    "invoice-monthly-sweep",
    "invoice-reminder-daily",
    "client-expansion-sweep-weekly",
    # No won deals / signed contracts → nothing to renew, follow up on, satisfy
    "contract-renewal-weekly",
    "proposal-followup-6h",
    "batch7-client-satisfaction-daily",
    # No active clients to ask for reviews / referrals
    "batch7-testimonial-requester-daily",
    "batch7-referral-campaign-daily",
    # Premature business-stage reporting (no revenue to report on)
    "generate-report-daily",
    "phase7-weekly-report",
    "pipeline-reporter-weekly",
    "weekly-growth-advisor",
    "weekly-intelligence-sweep",
    "social-report-daily",
    "daily-digest-08",
}

TASK_REGISTRY: dict[str, tuple[str, int, dict[str, Any]]] = {
    # name: (celery_task_path, ttl_seconds, extra_kwargs)

    # ── Maintenance ───────────────────────────────────────────────────────────
    "gdpr-cleanup-daily": (
        "app.tasks.gdpr_cleanup.anonymise_expired_leads", 23 * _H, {}),

    # ── Daily / weekly knowledge-base updates ─────────────────────────────────
    "generate-report-daily": (
        "app.tasks.daily_report.generate_daily_report", 23 * _H, {}),
    "weekly-growth-advisor": (
        "app.tasks.weekly_growth_advisor.run_weekly_growth_advisor", 6 * _D, {}),
    "prospect-leads-daily": (
        "app.tasks.prospect_leads.run_prospecting", 23 * _H,
        {"triggered_by": "n8n"}),
    "send-followup-emails-hourly": (
        "app.tasks.followup.send_followup_emails", 50 * 60, {}),
    "outreach-followup-hourly": (
        "app.tasks.outreach_followup.run_outreach_followup", 50 * 60, {}),
    "invoice-monthly-sweep": (
        "app.tasks.invoice_monthly.run_monthly_invoice_sweep", 27 * _D, {}),
    "contract-renewal-weekly": (
        "app.tasks.batch7_sweeps.run_contract_renewal", 6 * _D, {}),
    "weekly-intelligence-sweep": (
        "app.tasks.batch7_sweeps.run_weekly_intelligence", 6 * _D, {}),
    "health-check-sweep-daily": (
        "app.tasks.health_check_sweep.run_health_check_sweep", 23 * _H, {}),
    "autonomy-promotion-sweep-nightly": (
        "app.tasks.autonomy_promotion_sweep.run_autonomy_promotion_sweep",
        23 * _H, {}),
    "llm-budget-alarm-daily": (
        "app.tasks.llm_budget_alarm.run_budget_check", 23 * _H, {}),
    "approval-expiry-daily": (
        "app.tasks.approval_expiry.run_approval_expiry_sweep", 23 * _H, {}),
    "daily-digest-08": (
        "app.tasks.daily_digest.run_daily_digest", 23 * _H, {}),
    "critical-webhook-bridge-15m": (
        "app.tasks.critical_webhook_bridge.run_webhook_bridge", 10 * 60, {}),
    "quality-sampler-daily": (
        "app.tasks.quality_sampler.run_quality_sampler", 23 * _H, {}),
    "smoke-test-sweep-daily": (
        "app.tasks.smoke_test_sweep.run_smoke_tests", 23 * _H, {}),
    "reactivation-daily": (
        "reactivation", 23 * _H, {"triggered_by": "n8n"}),
    "client-expansion-sweep-weekly": (
        "app.tasks.client_expansion_sweep.run_expansion_sweep", 6 * _D, {}),
    "linkedin-drafts-sweep-daily": (
        "app.tasks.linkedin_drafts_sweep.run_linkedin_sweep", 23 * _H, {}),
    "proposal-followup-6h": (
        "app.tasks.proposal_followup.run_proposal_followup", 5 * _H, {}),
    "pipeline-reporter-weekly": (
        "app.tasks.pipeline_reporter.run_pipeline_reporter", 6 * _D, {}),
    "seo-content-weekly": (
        "seo_content", 6 * _D, {"triggered_by": "n8n"}),
    "social-report-daily": (
        "app.tasks.social_report.send_social_report", 23 * _H, {}),
    "route-qualified-social-posts": (
        "app.tasks.social_media.route_qualified_social_posts", 10 * 60, {}),
    # EU run: 09:00 Berlin Mon–Fri (DACH clients; includes XING)
    "generate-eu-social-drafts": (
        "app.tasks.social_media.generate_weekly_social_drafts", 2 * _D, {"market": "eu"}),
    # US run: 15:00 Berlin Mon–Fri = 09:00 ET (US/NA clients; no XING)
    "generate-us-social-drafts": (
        "app.tasks.social_media.generate_weekly_social_drafts", 2 * _D, {"market": "us"}),
    "invoice-reminder-daily": (
        "app.tasks.invoice_reminder.sweep_overdue_invoices", 23 * _H, {}),
    "freelance-platform-scan-2h": (
        "app.tasks.freelance_tasks.run_platform_scan", 110 * 60, {}),
    "freelance-bid-strategy-30m": (
        "app.tasks.freelance_tasks.run_bid_strategy", 24 * 60, {}),
    "freelance-bid-submission-30m": (
        "app.tasks.freelance_tasks.run_bid_submission", 24 * 60, {}),
    "freelance-bid-outcomes-4h": (
        "app.tasks.freelance_tasks.check_bid_outcomes", 3 * _H + 30 * 60, {}),
    # Renews the Freelancermap.de REMEMBERME cookie every 5 days (7-day expiry).
    # Stores result in Redis; sends admin email on failure.
    "freelance-fm-cookie-renewal-5d": (
        "app.tasks.freelance_tasks.run_fm_cookie_renewal", 4 * _D, {}),
    "phase7-weekly-report": (
        "app.tasks.phase7_tasks.run_weekly_report", 6 * _D,
        {"triggered_by": "n8n"}),

    # ── 2AM nightly rebuild: lead scoring refresh ─────────────────────────────
    "phase7-lead-scoring-refresh-nightly": (
        "app.tasks.phase7_tasks.run_lead_scoring_refresh", 23 * _H,
        {"triggered_by": "n8n"}),

    # ── Batch-7 sweeps ────────────────────────────────────────────────────────
    "batch7-testimonial-requester-daily": (
        "app.tasks.batch7_sweeps.run_testimonial_requester", 23 * _H, {}),
    "batch7-referral-campaign-daily": (
        "app.tasks.batch7_sweeps.run_referral_campaign", 23 * _H, {}),
    "batch7-cold-nurture-daily": (
        "app.tasks.batch7_sweeps.run_cold_nurture", 23 * _H, {}),
    "batch7-lead-enrichment-daily": (
        "app.tasks.batch7_sweeps.run_lead_enrichment", 23 * _H, {}),
    "batch7-client-satisfaction-daily": (
        "app.tasks.batch7_sweeps.run_client_satisfaction", 23 * _H, {}),

    # ── Approval notifications ────────────────────────────────────────────────
    "approval-notifier-30m": (
        "app.tasks.approval_notifier.run_approval_notifier", 24 * 60,
        {"triggered_by": "n8n"}),

    # ── RARV journal team — single write path to vault ────────────────────────
    # Fires the 4-agent pipeline: Reasoner → Writer → Reflector → Verifier.
    # Verifier git-pushes accepted notes to /opt/loki-vault (sole writer).
    "rarv-heartbeat-30m": (
        "app.tasks.rarv_heartbeat.run_heartbeat", 24 * 60, None),

    # Nightly knowledge-base rebuild (02:00 Berlin = 00:00 UTC summer / 01:00 UTC winter).
    # Concatenates trailing 30 days of daily notes → MEMORY.md → git push.
    "rarv-nightly-rebuild-0200-berlin": (
        "app.tasks.rarv_rebuild.run_nightly_rebuild", 20 * _H, None),

    # Monthly full re-derivation (04:00 Berlin on the 1st of each month).
    # Reads entire daily/ history → rebuilds knowledge/ topic tree from scratch.
    "rarv-monthly-rebuild-0400-berlin-day1": (
        "app.tasks.rarv_rebuild.run_monthly_rebuild", 27 * _D, None),

    # phase17-005 (closeout) — webhook retry sweep. Replays inbound webhooks
    # whose handlers raised, with exponential backoff (1m, 5m, 25m, 2h, 12h).
    # TTL deliberately short (240s) so a missed n8n tick gets caught by cron.
    "webhook-retry-5m": (
        "app.tasks.webhook_retry.run_webhook_retries", 240, None),
}

_REDIS_KEY_PREFIX = "loki:beat_last_run:"


# ─────────────────────────────────────────────────────────────────────────────
# Response models
# ─────────────────────────────────────────────────────────────────────────────

class TriggerResponse(BaseModel):
    status: str           # "triggered" | "skipped"
    task_name: str
    celery_task: str | None = None
    skipped_reason: str | None = None
    last_triggered_at: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_celery_app() -> Celery:
    """Import the Celery app lazily to avoid circular imports."""
    from app.tasks.celery_app import celery_app  # noqa: PLC0415
    return celery_app


async def _get_redis() -> aioredis.Redis:
    settings = get_settings()
    return aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/{task_name}",
    response_model=TriggerResponse,
    summary="Trigger a scheduled Celery task by its beat-schedule name",
    description=(
        "Called by n8n (primary) or system cron (fallback +15 min).  "
        "A Redis idempotency guard prevents double-execution within the "
        "per-task TTL window."
    ),
)
async def trigger_task(
    task_name: str,
    _api_key: str = Depends(verify_api_key),
) -> TriggerResponse:
    if task_name not in TASK_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown task '{task_name}'. "
                   f"Valid names: {sorted(TASK_REGISTRY)}",
        )

    if task_name in DISABLED_TRIGGERS:
        log.info("beat_trigger.disabled_skip", task_name=task_name)
        return TriggerResponse(
            status="skipped",
            task_name=task_name,
            celery_task=TASK_REGISTRY[task_name][0],
            skipped_reason="disabled",
            last_triggered_at=None,
        )

    celery_task_path, ttl_seconds, extra_kwargs = TASK_REGISTRY[task_name]
    redis_key = f"{_REDIS_KEY_PREFIX}{task_name}"

    # ── Idempotency check ────────────────────────────────────────────────────
    r = await _get_redis()
    last_run: str | None = await r.get(redis_key)

    if last_run is not None:
        log.info(
            "beat_trigger.skipped",
            task_name=task_name,
            last_triggered_at=last_run,
            ttl_remaining=await r.ttl(redis_key),
        )
        return TriggerResponse(
            status="skipped",
            task_name=task_name,
            celery_task=celery_task_path,
            skipped_reason="already_ran_recently",
            last_triggered_at=last_run,
        )

    # ── Dispatch ─────────────────────────────────────────────────────────────
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        celery_app = _get_celery_app()
        celery_app.send_task(celery_task_path, kwargs=extra_kwargs or None)
    except Exception as exc:
        log.error(
            "beat_trigger.dispatch_failed",
            task_name=task_name,
            celery_task=celery_task_path,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Celery dispatch failed: {exc}",
        ) from exc

    # ── Set idempotency key ───────────────────────────────────────────────────
    await r.set(redis_key, now_iso, ex=ttl_seconds)

    log.info(
        "beat_trigger.dispatched",
        task_name=task_name,
        celery_task=celery_task_path,
        ttl_seconds=ttl_seconds,
    )
    return TriggerResponse(
        status="triggered",
        task_name=task_name,
        celery_task=celery_task_path,
        last_triggered_at=now_iso,
    )
