"""
app/tasks/celery_app.py
────────────────────────
Celery application instance.

Queues:
  default   — general background work (GDPR cleanup, email notifications)
  approvals — executes agent actions after human approval
"""
from datetime import timedelta

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_prerun, worker_process_init
from klara.rarv.runtime import get_settings


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

celery_app = Celery(
    "loki_agents",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        # ── Core ──────────────────────────────────────────────────────────────
        "app.tasks.gdpr_cleanup",
        "app.tasks.execute_approved_action",
        "app.tasks.daily_report",
        # ── Phase 3: Bilingual Outreach System ────────────────────────────────
        "app.celery_tasks",
        # ── Prospecting (Phase 4.5) ───────────────────────────────────────────
        "app.tasks.prospect_leads",
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
        # ── Phase 7: Reporting + market intelligence ───────────────────────────
        "app.tasks.phase7_tasks",
        # ── Approval notifications ─────────────────────────────────────────────
        "app.tasks.approval_notifier",
        # ── RARV journal team (single write path to vault) ─────────────────────
        "klara.rarv.tasks.rarv_heartbeat",
        "klara.rarv.tasks.rarv_rebuild",
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
        # ── Phase 3: Bilingual Outreach System ────────────────────────────────
        "app.celery_tasks.language_detection":           {"queue": "default"},
        "app.celery_tasks.consent_validation":           {"queue": "default"},
        "app.celery_tasks.bilingual_outreach_generation":   {"queue": "email_generation"},
        "app.celery_tasks.bilingual_proposal_generation":   {"queue": "proposal_generation"},
        "app.celery_tasks.bilingual_report_aggregation":    {"queue": "reporting"},
        # ── Existing routes ───────────────────────────────────────────────────
        "app.tasks.execute_approved_action.*": {"queue": "approvals"},
        "app.tasks.daily_report.*":            {"queue": "default"},
        "app.tasks.gdpr_cleanup.*":            {"queue": "default"},
        "app.tasks.weekly_growth_advisor.*":   {"queue": "default"},
        "app.tasks.prospect_leads.*":          {"queue": "default"},
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
        "app.tasks.phase7_tasks.*":            {"queue": "default"},
        "app.tasks.approval_notifier.*":       {"queue": "default"},
        "klara.rarv.tasks.rarv_heartbeat.*":          {"queue": "default"},
        "klara.rarv.tasks.rarv_rebuild.*":            {"queue": "default"},
    },
    beat_schedule={
        # ── Maintenance ───────────────────────────────────────────────────────
        "gdpr-cleanup-daily": {
            "task": "app.tasks.gdpr_cleanup.anonymise_expired_leads",
            "schedule": 86400,
        },
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
        # ── Prospecting: weekdays 08:00 CET ───────────────────────────────────
        "prospect-leads-daily": {
            "task": "app.tasks.prospect_leads.run_prospecting",
            "schedule": crontab(hour=8, minute=0, day_of_week="1-5"),
            "options": {"queue": "default"},
            "kwargs": {"triggered_by": "celery_beat"},
        },
        # ── Follow-up nurture: every hour ─────────────────────────────────────
        "send-followup-emails-hourly": {
            "task": "app.tasks.followup.send_followup_emails",
            "schedule": crontab(minute=0),
            "options": {"queue": "default"},
        },
        # ── Outbound Day-3 follow-up: every hour (offset :15) ────────────────
        "outreach-followup-hourly": {
            "task": "app.tasks.outreach_followup.run_outreach_followup",
            "schedule": crontab(minute=15),
            "options": {"queue": "default"},
        },
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
        # ── SEO content draft: Monday 06:30 CET ──────────────────────────────
        "seo-content-weekly": {
            "task": "seo_content",
            "schedule": crontab(hour=6, minute=30, day_of_week="1"),
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
        # ── Social media: weekly drafts Mon/Wed/Fri 09:00 CET ────────────────
        "generate-weekly-social-drafts": {
            "task": "app.tasks.social_media.generate_weekly_social_drafts",
            "schedule": crontab(hour=9, minute=0, day_of_week="1,3,5"),
            "options": {"queue": "default"},
        },
        # ── Invoice reminder: weekdays 09:00 CET ─────────────────────────────
        "invoice-reminder-daily": {
            "task": "app.tasks.invoice_reminder.sweep_overdue_invoices",
            "schedule": crontab(hour=9, minute=0, day_of_week="1-5"),
            "options": {"queue": "default"},
        },
        # ── Freelance platform pipeline ───────────────────────────────────────
        "freelance-platform-scan-2h": {
            "task": "app.tasks.freelance_tasks.run_platform_scan",
            "schedule": crontab(minute=0, hour="8,10,12,14,16,18,20", day_of_week="1-5"),
            "options": {"queue": "default"},
        },
        "freelance-bid-strategy-30m": {
            "task": "app.tasks.freelance_tasks.run_bid_strategy",
            "schedule": crontab(minute=30, hour="8,10,12,14,16,18,20", day_of_week="1-5"),
            "options": {"queue": "default"},
        },
        "freelance-bid-submission-30m": {
            "task": "app.tasks.freelance_tasks.run_bid_submission",
            "schedule": crontab(minute="0,30", hour="8-20", day_of_week="1-5"),
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
        "rarv-heartbeat-30m": {
            "task": "klara.rarv.tasks.rarv_heartbeat.run_heartbeat",
            "schedule": crontab(minute="*/30"),
            "options": {"queue": "default"},
        },
        "rarv-nightly-rebuild-0200-berlin": {
            "task": "klara.rarv.tasks.rarv_rebuild.run_nightly_rebuild",
            "schedule": crontab(hour=2, minute=0),
            "options": {"queue": "default"},
        },
        "rarv-monthly-rebuild-0400-berlin-day1": {
            "task": "klara.rarv.tasks.rarv_rebuild.run_monthly_rebuild",
            "schedule": crontab(hour=4, minute=0, day_of_month=1),
            "options": {"queue": "default"},
        },
    },
)
