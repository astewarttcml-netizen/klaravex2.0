"""
app/tasks/celery_klaravex.py
──────────────────────────────
Single Celery application for the Klaravex stack.

This is the canonical beat scheduler. loki_beat has been removed.
Tasks route to the 'default' queue (loki_worker) or 'klaravex' queue
(klaravex_worker) depending on the task.

Redis DBs: broker=1, results=2 (shared with loki_worker intentionally —
same worker pool, same result backend).
"""
from celery import Celery
from celery.schedules import crontab
from celery.signals import task_prerun, worker_process_init
from datetime import timedelta

from app.config import get_settings


@worker_process_init.connect
def reset_db_pool_after_fork(**kwargs):
    import app.database as _db
    _db._engine = None
    _db._session_factory = None


@task_prerun.connect
def reset_db_pool_before_task(**kwargs):
    import app.database as _db
    _db._engine = None
    _db._session_factory = None


settings = get_settings()

celery_klaravex = Celery(
    "klaravex_agents",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        # ── Klaravex-specific ─────────────────────────────────────────────────
        "app.tasks.mailbox_poll",
        # ── Core ──────────────────────────────────────────────────────────────
        "app.tasks.execute_approved_action",
        "app.tasks.daily_report",
        # ── Prospecting ───────────────────────────────────────────────────────
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
        # ── Phase 7: Reporting + market intelligence ───────────────────────────
        "app.tasks.phase7_tasks",
        # ── Approval notifications ─────────────────────────────────────────────
        "app.tasks.approval_notifier",
        # ── RARV journal team ──────────────────────────────────────────────────
        "app.tasks.rarv_heartbeat",
        "app.tasks.rarv_rebuild",
        "app.tasks.rarv_lint",
        # Klaravex-side wrappers: same logic, registered on celery_klaravex
        # so klaravex_worker can execute them against Azure klaravex-db-r2.
        "app.tasks.rarv_heartbeat_klaravex",
        "app.tasks.rarv_rebuild_klaravex",
        # ── Ad campaign pipeline ───────────────────────────────────────────────────────
        "app.tasks.ad_tasks",
    ],
)

celery_klaravex.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Berlin",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    task_routes={
        # ── Klaravex queue ────────────────────────────────────────────────────
        "app.tasks.mailbox_poll.*":              {"queue": "klaravex"},
        # ── Default queue (loki_worker handles) ──────────────────────────────
        "app.tasks.execute_approved_action.*":  {"queue": "approvals"},
        "app.tasks.daily_report.*":             {"queue": "default"},
        "app.tasks.weekly_growth_advisor.*":    {"queue": "default"},
        "app.tasks.prospect_leads.*":           {"queue": "default"},
        "app.tasks.research_prospect.*":        {"queue": "default"},
        "app.tasks.followup.*":                 {"queue": "default"},
        "app.tasks.outreach_followup.*":        {"queue": "default"},
        "app.tasks.invoice_monthly.*":          {"queue": "default"},
        "app.tasks.health_check_sweep.*":       {"queue": "default"},
        "app.tasks.autonomy_promotion_sweep.*": {"queue": "default"},
        "app.tasks.llm_budget_alarm.*":         {"queue": "default"},
        "app.tasks.approval_expiry.*":          {"queue": "default"},
        "app.tasks.daily_digest.*":             {"queue": "default"},
        "app.tasks.critical_webhook_bridge.*":  {"queue": "default"},
        "app.tasks.quality_sampler.*":          {"queue": "default"},
        "app.tasks.smoke_test_sweep.*":         {"queue": "default"},
        "app.tasks.client_expansion_sweep.*":   {"queue": "default"},
        "app.tasks.linkedin_drafts_sweep.*":    {"queue": "default"},
        "app.tasks.reactivation.*":             {"queue": "default"},
        "app.tasks.batch7_sweeps.*":            {"queue": "default"},
        "app.tasks.proposal_followup.*":        {"queue": "default"},
        "app.tasks.pipeline_reporter.*":        {"queue": "default"},
        "app.tasks.seo_content.*":              {"queue": "default"},
        "app.tasks.social_media.*":             {"queue": "default"},
        "app.tasks.social_report.*":            {"queue": "default"},
        "app.tasks.invoice_reminder.*":         {"queue": "default"},
        "app.tasks.phase7_tasks.*":             {"queue": "default"},
        "app.tasks.approval_notifier.*":        {"queue": "default"},
        "app.tasks.rarv_heartbeat.*":           {"queue": "default"},
        "app.tasks.rarv_rebuild.*":             {"queue": "default"},
        "app.tasks.rarv_lint.*":                {"queue": "default"},
        "klaravex.tasks.rarv_heartbeat.*":      {"queue": "default"},
        "klaravex.tasks.rarv_rebuild.*":        {"queue": "default"},
    },
    beat_schedule={
        # ── Klaravex: mailbox poll every 2 min ───────────────────────────────
        "klaravex-mailbox-poll-2m": {
            "task": "app.tasks.mailbox_poll.poll_support_mailbox",
            "schedule": 120,
            "options": {"queue": "klaravex"},
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
        # ── Outbound Day-3 follow-up: DISABLED 2026-08-17 ────────────────────
        # Smartlead auto-sends followups — this task created redundant approvals.
        # "outreach-followup-hourly": {
        #     "task": "app.tasks.outreach_followup.run_outreach_followup",
        #     "schedule": crontab(minute=15),
        #     "options": {"queue": "default"},
        # },
        # ── Monthly invoice sweep — 1st of month 09:00 CET ───────────────────
        "invoice-monthly-sweep": {
            "task": "app.tasks.invoice_monthly.run_monthly_invoice_sweep",
            "schedule": crontab(hour=9, minute=0, day_of_month="1"),
            "options": {"queue": "default"},
        },
        # ── Contract renewal sweep — Wednesdays 09:00 CET ────────────────────
        "contract-renewal-weekly": {
            "task": "app.tasks.batch7_sweeps.run_contract_renewal",
            "schedule": crontab(hour=9, minute=0, day_of_week="3"),
            "options": {"queue": "default"},
        },
        # ── Weekly intelligence sweep — Mondays 07:00 CET ────────────────────
        "weekly-intelligence-sweep": {
            "task": "app.tasks.batch7_sweeps.run_weekly_intelligence",
            "schedule": crontab(hour=7, minute=0, day_of_week="1"),
            "options": {"queue": "default"},
        },
        # ── External service health check — daily 06:00 CET ──────────────────
        "health-check-sweep-daily": {
            "task": "app.tasks.health_check_sweep.run_health_check_sweep",
            "schedule": crontab(hour=6, minute=0),
            "options": {"queue": "default"},
        },
        # ── Autonomy promotion sweep — nightly 03:00 CET ─────────────────────
        "autonomy-promotion-sweep-nightly": {
            "task": "app.tasks.autonomy_promotion_sweep.run_autonomy_promotion_sweep",
            "schedule": crontab(hour=3, minute=0),
            "options": {"queue": "default"},
        },
        # ── LLM daily budget alarm — 23:00 CET ───────────────────────────────
        "llm-budget-alarm-daily": {
            "task": "app.tasks.llm_budget_alarm.run_budget_check",
            "schedule": crontab(hour=23, minute=0),
            "options": {"queue": "default"},
        },
        # ── Approval expiry sweep — 04:00 CET ────────────────────────────────
        "approval-expiry-daily": {
            "task": "app.tasks.approval_expiry.run_approval_expiry_sweep",
            "schedule": crontab(hour=4, minute=0),
            "options": {"queue": "default"},
        },
        # ── Daily digest — 08:00 CET ──────────────────────────────────────────
        "daily-digest-08": {
            "task": "app.tasks.daily_digest.run_daily_digest",
            "schedule": crontab(hour=8, minute=0),
            "options": {"queue": "default"},
        },
        # ── Critical event webhook — every 15 min ────────────────────────────
        "critical-webhook-bridge-15m": {
            "task": "app.tasks.critical_webhook_bridge.run_webhook_bridge",
            "schedule": crontab(minute="*/15"),
            "options": {"queue": "default"},
        },
        # ── LLM-as-judge sampling — daily 04:30 CET ──────────────────────────
        "quality-sampler-daily": {
            "task": "app.tasks.quality_sampler.run_quality_sampler",
            "schedule": crontab(hour=4, minute=30),
            "options": {"queue": "default"},
        },
        # ── Daily smoke tests — 05:00 CET ─────────────────────────────────────
        "smoke-test-sweep-daily": {
            "task": "app.tasks.smoke_test_sweep.run_smoke_tests",
            "schedule": crontab(hour=5, minute=0),
            "options": {"queue": "default"},
        },
        # ── Lead reactivation — daily 10:00 CET ──────────────────────────────
        "reactivation-daily": {
            "task": "reactivation",
            "schedule": crontab(hour=10, minute=0),
            "options": {"queue": "default"},
            "kwargs": {"triggered_by": "beat"},
        },
        # ── Client expansion sweep — Mondays 11:00 CET ───────────────────────
        "client-expansion-sweep-weekly": {
            "task": "app.tasks.client_expansion_sweep.run_expansion_sweep",
            "schedule": crontab(hour=11, minute=0, day_of_week="1"),
            "options": {"queue": "default"},
        },
        # ── LinkedIn drafts sweep — daily 12:00 CET ───────────────────────────
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
        # ── Pipeline reporter — Monday 08:30 CET ──────────────────────────────
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
        # ── Social report — daily 08:00 CET ──────────────────────────────────
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
        # This is the SOLE trigger for social draft generation (n8n's
        # generate-eu/us-social-drafts triggers are gated off).
        #
        # The celery app's global timezone is Europe/Berlin (see timezone= above),
        # and Celery crontab has no per-entry timezone override, so these
        # hours are Berlin-time computed to land on 09:00 ET / 09:00 PT.
        # Computed for current US daylight time (EDT=UTC-4, PDT=UTC-7) against
        # Berlin's CEST (UTC+2): 09:00 ET -> 15:00 Berlin, 09:00 PT -> 18:00
        # Berlin. CAVEAT: US and EU DST transition on different dates (~1-2
        # weeks apart, twice a year) — during those windows this drifts by up
        # to 1 hour until the next transition aligns them again.
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
        # ── Invoice reminder — weekdays 09:00 CET ────────────────────────────
        "invoice-reminder-daily": {
            "task": "app.tasks.invoice_reminder.sweep_overdue_invoices",
            "schedule": crontab(hour=9, minute=0, day_of_week="1-5"),
            "options": {"queue": "default"},
        },
        # ── Weekly report + lead scoring refresh ─────────────────────────────
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
        # ── Batch 7 sweeps ────────────────────────────────────────────────────
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
        # ── RARV journal team (klaravex-side — reads Azure klaravex-db-r2) ────
        "rarv-heartbeat-30m": {
            "task": "klaravex.tasks.rarv_heartbeat.run_heartbeat",
            "schedule": crontab(minute="*/30"),
            "options": {"queue": "default"},
        },
        "rarv-nightly-rebuild-0200-berlin": {
            "task": "klaravex.tasks.rarv_rebuild.run_nightly_rebuild",
            "schedule": crontab(hour=2, minute=0),
            "options": {"queue": "default"},
        },
        "rarv-monthly-rebuild-0400-berlin-day1": {
            "task": "klaravex.tasks.rarv_rebuild.run_monthly_rebuild",
            "schedule": crontab(hour=4, minute=0, day_of_month=1),
            "options": {"queue": "default"},
        },
        "rarv-lint-weekly-sunday-2000-berlin": {
            "task": "app.tasks.rarv_lint.run_weekly_lint",
            "schedule": crontab(hour=20, minute=0, day_of_week=0),
            "options": {"queue": "default"},
        },
        # ── Ad campaign monitoring ───────────────────────────────────────────────────────
        # Daily budget check — alerts if spend approaches 90% of budget
        "ad-budget-check-daily": {
            "task": "app.tasks.ad_tasks.run_ad_budget_check",
            "schedule": crontab(hour=9, minute=0),
            "options": {"queue": "default"},
        },
        # Weekly optimization recommendations
        "ad-optimization-weekly": {
            "task": "app.tasks.ad_tasks.run_ad_optimization",
            "schedule": crontab(hour=10, minute=0, day_of_week=1),
            "options": {"queue": "default"},
        },
        # Weekly performance reporting
        "ad-reporting-weekly": {
            "task": "app.tasks.ad_tasks.run_ad_reporting",
            "schedule": crontab(hour=8, minute=0, day_of_week=1),
            "options": {"queue": "default"},
        },
    },
)
