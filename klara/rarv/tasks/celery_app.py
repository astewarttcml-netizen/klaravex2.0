"""
app/tasks/celery_app.py
────────────────────────
Celery application instance.

Queues:
  default   — general background work (GDPR cleanup, email notifications)
  approvals — executes agent actions after human approval
"""
from datetime import timedelta

from klara.rarv.runtime import get_settings
from klara.rarv.runtime import configure_logging

# Configure structlog BEFORE importing/registering task modules (see the
# `include=[...]` list below), mirroring app/main.py's ordering: task modules
# call structlog.get_logger() at import time, and if configuration is
# deferred, those early loggers materialize against structlog's default
# PrintLoggerFactory and get cached, which then crashes the
# `add_logger_name` processor at runtime (PrintLogger has no `.name`). Left
# unconfigured, structlog's own default ConsoleRenderer/RichTracebackFormatter
# also pretty-prints full local variables (including the Settings object) into
# logs on any unhandled task exception.
configure_logging(debug=get_settings().app_debug)

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_prerun, worker_process_init


@worker_process_init.connect
def reset_db_pool_after_fork(**kwargs):
    """
    Celery ForkPoolWorker creates child processes by forking the parent.
    The parent may hold an initialised SQLAlchemy async engine whose connection
    pool contains asyncpg futures bound to the parent's event loop.  Those
    futures are invalid in the child and cause:
        RuntimeError: Future ... attached to a different loop
    Resetting the module-level singletons here forces the child to create a
    fresh engine and pool the first time it needs the DB, using its own event
    loop (created by asyncio.run() inside each task).
    """
    import klara.rarv.runtime as _db
    _db._engine = None
    _db._session_factory = None


@task_prerun.connect
def reset_db_pool_before_task(**kwargs):
    """
    Each Celery task calls asyncio.run() which creates and then DESTROYS an
    event loop.  Any SQLAlchemy async engine created during that task is left
    bound to the now-closed loop.  The next task that runs in the same worker
    process calls asyncio.run() again (new loop), but _get_engine() returns
    the stale engine from the previous run → asyncpg raises:
        RuntimeError: Future ... attached to a different loop

    Resetting the singletons here (before every task, not just on fork) ensures
    each task always gets a fresh engine bound to its own event loop.

    worker_process_init above handles the fork case; this handles the
    multi-task-per-process case.  Both are required.
    """
    import klara.rarv.runtime as _db
    _db._engine = None
    _db._session_factory = None

settings = get_settings()

# Training data capture — intercepts all Anthropic SDK calls
import klara.rarv.runtime.llm_capture_hook  # noqa: F401

celery_app = Celery(
    "loki_agents",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        # ── Core ──────────────────────────────────────────────────────────────
        "app.tasks.execute_approved_action",
        "app.tasks.daily_report",
        # ── Prospecting (Phase 4.5) ───────────────────────────────────────────
        "app.tasks.prospect_leads",
        "app.tasks.research_prospect",
        # ── Engagement / nurture ──────────────────────────────────────────────
        "app.tasks.followup",
        "app.tasks.outreach_followup",
        # ── Phase 6: Client lifecycle ─────────────────────────────────────────
        "app.tasks.invoice_monthly",
        # ── Phase 8: Operational excellence ───────────────────────────────────
        "app.tasks.health_check_sweep",
        "app.tasks.autonomy_promotion_sweep",
        # ── Phase 9: LLM cost ────────────────────────────────────────────────
        "app.tasks.llm_budget_alarm",
        # ── Phase 10: Resilience ─────────────────────────────────────────────
        "app.tasks.approval_expiry",
        "app.tasks.daily_digest",
        # ── Phase 11: Customer-facing layer ──────────────────────────────────
        "app.tasks.critical_webhook_bridge",
        # ── Phase 12: Quality ────────────────────────────────────────────────
        "app.tasks.quality_sampler",
        # ── Phase 16: Production reliability ─────────────────────────────────
        "app.tasks.smoke_test_sweep",
        # ── Phase 18: Customer expansion ─────────────────────────────────────
        "app.tasks.client_expansion_sweep",
        # ── Phase 20: LinkedIn outreach ──────────────────────────────────────
        "app.tasks.linkedin_drafts_sweep",
        "app.tasks.reactivation",
        "app.tasks.batch7_sweeps",
        # ── Proposals ─────────────────────────────────────────────────────────
        "app.tasks.proposal_followup",
        # ── Reporting ─────────────────────────────────────────────────────────
        "app.tasks.pipeline_reporter",
        "app.tasks.weekly_growth_advisor",
        # ── Content / publishing ──────────────────────────────────────────────
        "app.tasks.seo_content",
        "app.tasks.social_media",
        "app.tasks.social_report",
        "app.tasks.invoice_reminder",
        # ── Freelance platform pipeline (Phase 5) ─────────────────────────────
        "app.tasks.freelance_tasks",
        "app.tasks.platform_message_agent_tasks",
        # ── Phase 7: Reporting + market intelligence ───────────────────────────
        "app.tasks.phase7_tasks",
        # ── Approval notifications ─────────────────────────────────────────────
        "app.tasks.approval_notifier",
        # ── RARV journal team (single write path to vault) ─────────────────────
        "klara.rarv.tasks.rarv_heartbeat",
        "klara.rarv.tasks.rarv_rebuild",
        "app.tasks.rarv_lint",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Berlin",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    task_routes={
        # ── Existing routes ───────────────────────────────────────────────────
        "app.tasks.execute_approved_action.*": {"queue": "approvals"},
        "app.tasks.daily_report.*":            {"queue": "default"},
        "app.tasks.weekly_growth_advisor.*":   {"queue": "default"},
        "app.tasks.prospect_leads.*":          {"queue": "default"},
        "app.tasks.research_prospect.*":       {"queue": "default"},
        "app.tasks.followup.*":                {"queue": "default"},
        "app.tasks.outreach_followup.*":       {"queue": "default"},
        "app.tasks.invoice_monthly.*":         {"queue": "default"},
        "app.tasks.health_check_sweep.*":      {"queue": "default"},
        "app.tasks.autonomy_promotion_sweep.*": {"queue": "default"},
        "app.tasks.llm_budget_alarm.*":        {"queue": "default"},
        "app.tasks.approval_expiry.*":         {"queue": "default"},
        "app.tasks.daily_digest.*":            {"queue": "default"},
        "app.tasks.critical_webhook_bridge.*": {"queue": "default"},
        "app.tasks.quality_sampler.*":         {"queue": "default"},
        "app.tasks.smoke_test_sweep.*":        {"queue": "default"},
        "app.tasks.client_expansion_sweep.*":  {"queue": "default"},
        "app.tasks.linkedin_drafts_sweep.*":   {"queue": "default"},
        "app.tasks.reactivation.*":            {"queue": "default"},
        "app.tasks.batch7_sweeps.*":           {"queue": "default"},
        "app.tasks.proposal_followup.*":       {"queue": "default"},
        "app.tasks.pipeline_reporter.*":       {"queue": "default"},
        "app.tasks.seo_content.*":             {"queue": "default"},
        "app.tasks.social_media.*":            {"queue": "default"},
        "app.tasks.social_report.*":           {"queue": "default"},
        "app.tasks.invoice_reminder.*":        {"queue": "default"},
        "app.tasks.freelance_tasks.*":         {"queue": "default"},
        "app.tasks.platform_message_agent_tasks.*": {"queue": "default"},
        "app.tasks.phase7_tasks.*":            {"queue": "default"},
        "app.tasks.approval_notifier.*":       {"queue": "default"},
        "klara.rarv.tasks.rarv_heartbeat.*":          {"queue": "default"},
        "klara.rarv.tasks.rarv_rebuild.*":            {"queue": "default"},
        "app.tasks.rarv_lint.*":              {"queue": "default"},
    },
    beat_schedule={
        # ── Daily report: 07:00 CET ───────────────────────────────────────────
        "generate-report-daily": {
            "task": "app.tasks.daily_report.generate_daily_report",
            "schedule": crontab(hour=7, minute=0),
        },
        # ── Weekly growth advisor: Monday 10:00 CET ───────────────────────────
        "weekly-growth-advisor": {
            "task": "app.tasks.weekly_growth_advisor.run_weekly_growth_advisor",
            "schedule": crontab(hour=10, minute=0, day_of_week="1"),
            "options": {"queue": "default"},
        },
        # ── Prospecting: DAILY 08:00 CET (iter-66 T-LEADS-DAILY 2026-07-14) ───────────────────────────────────
        "prospect-leads-daily": {
            "task": "app.tasks.prospect_leads.run_prospecting",
            "schedule": crontab(hour=8, minute=0),
            "options": {"queue": "default"},
            "kwargs": {"triggered_by": "celery_beat"},
        },
        # ── Follow-up nurture: every hour ─────────────────────────────────────
        "send-followup-emails-hourly": {
            "task": "app.tasks.followup.send_followup_emails",
            "schedule": crontab(minute=0),
            "options": {"queue": "default"},
        },
        # ── Outbound Day-3 follow-up: DISABLED 2026-08-17 ────────────────────
        # Smartlead auto-sends followups — this task created redundant approvals.
        # "outreach-followup-hourly": {
        #     "task": "app.tasks.outreach_followup.run_outreach_followup",
        #     "schedule": crontab(minute=15),
        #     "options": {"queue": "default"},
        # },
        # ── Phase 6-002: monthly invoice sweep — 1st of month 09:00 CET ──────
        "invoice-monthly-sweep": {
            "task": "app.tasks.invoice_monthly.run_monthly_invoice_sweep",
            "schedule": crontab(hour=9, minute=0, day_of_month="1"),
            "options": {"queue": "default"},
        },
        # ── Phase 6-005: contract renewal sweep — Wednesdays 09:00 CET ───────
        "contract-renewal-weekly": {
            "task": "app.tasks.batch7_sweeps.run_contract_renewal",
            "schedule": crontab(hour=9, minute=0, day_of_week="3"),
            "options": {"queue": "default"},
        },
        # ── Phase 7-003: weekly intelligence sweep — Mondays 07:00 CET ───────
        "weekly-intelligence-sweep": {
            "task": "app.tasks.batch7_sweeps.run_weekly_intelligence",
            "schedule": crontab(hour=7, minute=0, day_of_week="1"),
            "options": {"queue": "default"},
        },
        # ── Phase 8-003: external service health check — daily 06:00 CET ─────
        "health-check-sweep-daily": {
            "task": "app.tasks.health_check_sweep.run_health_check_sweep",
            "schedule": crontab(hour=6, minute=0),
            "options": {"queue": "default"},
        },
        # ── Phase 8-002: autonomy promotion sweep — nightly 03:00 CET ────────
        "autonomy-promotion-sweep-nightly": {
            "task": "app.tasks.autonomy_promotion_sweep.run_autonomy_promotion_sweep",
            "schedule": crontab(hour=3, minute=0),
            "options": {"queue": "default"},
        },
        # ── Phase 9-003: LLM daily budget alarm — 23:00 CET ──────────────────
        "llm-budget-alarm-daily": {
            "task": "app.tasks.llm_budget_alarm.run_budget_check",
            "schedule": crontab(hour=23, minute=0),
            "options": {"queue": "default"},
        },
        # ── Phase 10-002: approval expiry sweep — 04:00 CET ──────────────────
        "approval-expiry-daily": {
            "task": "app.tasks.approval_expiry.run_approval_expiry_sweep",
            "schedule": crontab(hour=4, minute=0),
            "options": {"queue": "default"},
        },
        # ── Phase 10-003: daily digest — 08:00 CET ───────────────────────────
        "daily-digest-08": {
            "task": "app.tasks.daily_digest.run_daily_digest",
            "schedule": crontab(hour=8, minute=0),
            "options": {"queue": "default"},
        },
        # ── Phase 11-005: critical event webhook — every 15min ───────────────
        "critical-webhook-bridge-15m": {
            "task": "app.tasks.critical_webhook_bridge.run_webhook_bridge",
            "schedule": crontab(minute="*/15"),
            "options": {"queue": "default"},
        },
        # ── Phase 12-003: LLM-as-judge sampling — daily 04:30 CET ────────────
        "quality-sampler-daily": {
            "task": "app.tasks.quality_sampler.run_quality_sampler",
            "schedule": crontab(hour=4, minute=30),
            "options": {"queue": "default"},
        },
        # ── Phase 16-003: daily smoke tests — 05:00 CET ──────────────────────
        "smoke-test-sweep-daily": {
            "task": "app.tasks.smoke_test_sweep.run_smoke_tests",
            "schedule": crontab(hour=5, minute=0),
            "options": {"queue": "default"},
        },
        # ── Lead reactivation sweep: daily 10:00 CET ──────────────────────────
        "reactivation-daily": {
            "task": "reactivation",
            "schedule": crontab(hour=10, minute=0),
            "options": {"queue": "default"},
            "kwargs": {"triggered_by": "beat"},
        },
        # ── Phase 18-004: client expansion sweep — Mondays 11:00 CET ─────────
        "client-expansion-sweep-weekly": {
            "task": "app.tasks.client_expansion_sweep.run_expansion_sweep",
            "schedule": crontab(hour=11, minute=0, day_of_week="1"),
            "options": {"queue": "default"},
        },
        # ── Phase 20-005: LinkedIn drafts sweep — daily 12:00 CET ────────────
        "linkedin-drafts-sweep-daily": {
            "task": "app.tasks.linkedin_drafts_sweep.run_linkedin_sweep",
            "schedule": crontab(hour=12, minute=0),
            "options": {"queue": "default"},
        },
        # ── Proposal follow-up: every 6 hours ────────────────────────────────
        "proposal-followup-6h": {
            "task": "app.tasks.proposal_followup.run_proposal_followup",
            "schedule": crontab(minute=0, hour="0,6,12,18"),
            "options": {"queue": "default"},
        },
        # ── Pipeline reporter: Monday 08:30 CET ───────────────────────────────
        "pipeline-reporter-weekly": {
            "task": "app.tasks.pipeline_reporter.run_pipeline_reporter",
            "schedule": crontab(hour=8, minute=30, day_of_week="1"),
            "options": {"queue": "default"},
        },
        # ── SEO content draft: daily 06:30 CET ───────────────────────────────
        "seo-content-daily": {
            "task": "app.tasks.seo_content.run_seo_content",
            "schedule": crontab(hour=6, minute=30),
            "options": {"queue": "default"},
            "kwargs": {"triggered_by": "beat"},
        },
        # ── Social report: daily 08:00 CET ───────────────────────────────────
        "social-report-daily": {
            "task": "app.tasks.social_report.send_social_report",
            "schedule": crontab(hour=8, minute=0),
            "options": {"queue": "default"},
        },
        # ── Social media: route new wins every 15 min ────────────────────────
        "route-qualified-social-posts": {
            "task": "app.tasks.social_media.route_qualified_social_posts",
            "schedule": 900,
            "options": {"queue": "default"},
        },
        # ── Social media: 2x/day US-timed (2026-07-19, Anthony directive) ────────
        # Klaravex is US-only — post once for East Coast, once for West Coast.
        # This is now the SOLE trigger for social draft generation (n8n's
        # generate-eu/us-social-drafts triggers are gated off in
        # app/api/beat_trigger.py's DISABLED_TRIGGERS — see that comment).
        #
        # celery_app's global timezone is Europe/Berlin (see timezone= above),
        # and Celery crontab has no per-entry timezone override, so these
        # hours are Berlin-time computed to land on 09:00 ET / 09:00 PT.
        # Computed for current US daylight time (EDT=UTC-4, PDT=UTC-7) against
        # Berlin's CEST (UTC+2): 09:00 ET -> 15:00 Berlin, 09:00 PT -> 18:00
        # Berlin. CAVEAT: US and EU DST transition on different dates (~1-2
        # weeks apart, twice a year) — during those windows this drifts by up
        # to 1 hour until the next transition aligns them again. Not worth a
        # timezone-library fix for a ±1hr/few-weeks-a-year drift; revisit if
        # it ever actually matters.
        # ── Social: 2x/day per platform, east+west coast coverage ──────────
        "generate-social-morning": {
            "task": "app.tasks.social_media.generate_social_drafts",
            "schedule": crontab(hour=12, minute=30),  # 08:30 EDT — draft before 9am publish
            "kwargs": {"market": "us"},
            "options": {"queue": "default"},
        },
        "publish-social-morning": {
            "task": "app.tasks.social_media.publish_scheduled_posts",
            "schedule": crontab(hour=13, minute=0),  # 09:00 EDT — east coast morning
            "options": {"queue": "default"},
        },
        "generate-social-afternoon": {
            "task": "app.tasks.social_media.generate_social_drafts",
            "schedule": crontab(hour=18, minute=30),  # 14:30 EDT — draft before 3pm publish
            "kwargs": {"market": "us"},
            "options": {"queue": "default"},
        },
        "publish-social-afternoon": {
            "task": "app.tasks.social_media.publish_scheduled_posts",
            "schedule": crontab(hour=19, minute=0),  # 15:00 EDT — west coast lunch
            "options": {"queue": "default"},
        },
        # ── Invoice reminder: weekdays 09:00 CET ─────────────────────────────
        "invoice-reminder-daily": {
            "task": "app.tasks.invoice_reminder.sweep_overdue_invoices",
            "schedule": crontab(hour=9, minute=0, day_of_week="1-5"),
            "options": {"queue": "default"},
        },
        # ── Freelance platform pipeline ───────────────────────────────────────
        # Runs 24/7 (2026-07-19, Anthony directive: "it should run daily ...
        # not just during the week ... it should always been running", then
        # "i think im losing bids because of this can we [do] 24 hours" —
        # the 8am-8pm window meant a project posted overnight sat unbid for
        # up to ~12h while competitors moved first. day_of_week="1-5" AND the
        # 8-20 hour window are both gone now; same 2h/30m/15m intervals,
        # just spread across all 24 hours instead of a 12h business window.
        "freelance-platform-scan-2h": {
            "task": "app.tasks.freelance_tasks.run_platform_scan",
            "schedule": crontab(minute=0, hour="*/2"),
            "options": {"queue": "default"},
        },
        "freelance-bid-strategy-30m": {
            "task": "app.tasks.freelance_tasks.run_bid_strategy",
            "schedule": crontab(minute=30, hour="*/2"),
            "options": {"queue": "default"},
        },
        "freelance-bid-submission-30m": {
            "task": "app.tasks.freelance_tasks.run_bid_submission",
            "schedule": crontab(minute="0,30"),
            "options": {"queue": "default"},
        },
        "freelance-bid-outcomes-4h": {
            "task": "app.tasks.freelance_tasks.check_bid_outcomes",
            "schedule": crontab(minute=0, hour="0,4,8,12,16,20"),
            "options": {"queue": "default"},
        },
        # Renew every 5 days — REMEMBERME expires in 7 days, giving a 2-day buffer
        "freelance-fm-cookie-renewal-5d": {
            "task": "app.tasks.freelance_tasks.run_fm_cookie_renewal",
            "schedule": timedelta(days=5),
            "options": {"queue": "default"},
        },
        # ── Freelance-platform auto-reply agent (phase A, draft mode) ────────
        "freelance-message-poll-15m": {
            "task": "app.tasks.platform_message_agent_tasks.poll_freelancer_com_messages",
            "schedule": crontab(minute="*/15"),
            "options": {"queue": "default"},
        },
        "freelance-message-drafts-15m": {
            "task": "app.tasks.platform_message_agent_tasks.generate_platform_message_drafts",
            "schedule": crontab(minute="2,17,32,47"),
            "options": {"queue": "default"},
        },
        # ── Phase 7: Weekly report + lead scoring refresh ────────────────────
        "phase7-weekly-report": {
            "task": "app.tasks.phase7_tasks.run_weekly_report",
            "schedule": crontab(hour=8, minute=0, day_of_week="1"),
            "options": {"queue": "default"},
            "kwargs": {"triggered_by": "beat"},
        },
        "phase7-lead-scoring-refresh-nightly": {
            "task": "app.tasks.phase7_tasks.run_lead_scoring_refresh",
            "schedule": crontab(hour=2, minute=0),
            "options": {"queue": "default"},
            "kwargs": {"triggered_by": "beat"},
        },
        # ── Batch 7 sweep tasks ───────────────────────────────────────────────
        "batch7-testimonial-requester-daily": {
            "task": "app.tasks.batch7_sweeps.run_testimonial_requester",
            "schedule": crontab(hour=9, minute=0),
            "options": {"queue": "default"},
        },
        "batch7-referral-campaign-daily": {
            "task": "app.tasks.batch7_sweeps.run_referral_campaign",
            "schedule": crontab(hour=11, minute=0),
            "options": {"queue": "default"},
        },
        "batch7-cold-nurture-daily": {
            "task": "app.tasks.batch7_sweeps.run_cold_nurture",
            "schedule": crontab(hour=9, minute=30),
            "options": {"queue": "default"},
        },
        "batch7-lead-enrichment-daily": {
            "task": "app.tasks.batch7_sweeps.run_lead_enrichment",
            "schedule": crontab(hour=8, minute=15, day_of_week="1-5"),
            "options": {"queue": "default"},
        },
        "batch7-client-satisfaction-daily": {
            "task": "app.tasks.batch7_sweeps.run_client_satisfaction",
            "schedule": crontab(hour=10, minute=0),
            "options": {"queue": "default"},
        },
        # ── Approval notifications — every 30 min ────────────────────────────
        "approval-notifier-30m": {
            "task": "app.tasks.approval_notifier.run_approval_notifier",
            "schedule": crontab(minute="0,30"),
            "options": {"queue": "default"},
            "kwargs": {"triggered_by": "beat"},
        },
        # ── RARV journal team ─────────────────────────────────────────────────
        "rarv-heartbeat-15m": {
            "task": "klara.rarv.tasks.rarv_heartbeat.run_heartbeat",
            "schedule": crontab(minute="*/15"),
            "options": {"queue": "default"},
        },
        "rarv-rebuild-4h": {
            "task": "klara.rarv.tasks.rarv_rebuild.run_nightly_rebuild",
            "schedule": crontab(minute=0, hour="*/4"),
            "options": {"queue": "default"},
        },
        "rarv-monthly-rebuild-0400-berlin-day1": {
            "task": "klara.rarv.tasks.rarv_rebuild.run_monthly_rebuild",
            "schedule": crontab(hour=4, minute=0, day_of_month=1),
            "options": {"queue": "default"},
        },
        "rarv-lint-weekly-sunday-2000-berlin": {
            "task": "app.tasks.rarv_lint.run_weekly_lint",
            "schedule": crontab(hour=20, minute=0, day_of_week=0),
            "options": {"queue": "default"},
        },
    },
)
