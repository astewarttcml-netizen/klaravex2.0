"""
registry_additions.py
──────────────────────
Lines to add to app/agents/registry.py — _bootstrap() function.

These are NOT standalone additions — paste them into the appropriate
sections of the existing _bootstrap() function in registry.py.

Step 1: Add imports to _bootstrap() — insert after the "Content / publishing"
        import block, before the "Reporting" block:

    # ── Product delivery agents ───────────────────────────────────────────────
    from app.agents.network_monitor_onboarding import NetworkMonitorOnboardingAgent
    from app.agents.patch_compliance_reporter import PatchComplianceReporterAgent
    from app.agents.security_scoping import SecurityScopingAgent
    from app.agents.task_automator import TaskAutomatorAgent
    from app.agents.kb_lookup import KbLookupAgent

Step 2: Add to the registration list — insert after WebsiteDeployAgent and
        TranslationSyncAgent in the for-loop, before DailyReportAgent:

    # Product delivery
    NetworkMonitorOnboardingAgent,
    PatchComplianceReporterAgent,
    SecurityScopingAgent,
    TaskAutomatorAgent,
    KbLookupAgent,

──────────────────────────────────────────────────────────────────────────────
Full diff for clarity (context lines shown with leading spaces):
──────────────────────────────────────────────────────────────────────────────

In the imports section of _bootstrap():

    # ── Content / publishing (P3) ─────────────────────────────────────────────
    from app.agents.seo_content_writer import SeoContentWriterAgent
    from app.agents.social_media_manager import SocialMediaManagerAgent
    from app.agents.website_deploy import WebsiteDeployAgent
    from app.agents.translation_sync import TranslationSyncAgent

+   # ── Product delivery agents (P2/P3) ───────────────────────────────────────
+   from app.agents.network_monitor_onboarding import NetworkMonitorOnboardingAgent
+   from app.agents.patch_compliance_reporter import PatchComplianceReporterAgent
+   from app.agents.security_scoping import SecurityScopingAgent
+   from app.agents.task_automator import TaskAutomatorAgent
+   from app.agents.kb_lookup import KbLookupAgent

    # ── Reporting ─────────────────────────────────────────────────────────────
    from app.agents.daily_report import DailyReportAgent
    from app.agents.pipeline_reporter import PipelineReporterAgent


In the registration list (for-loop):

        # Content / publishing
        SeoContentWriterAgent,
        SocialMediaManagerAgent,
        WebsiteDeployAgent,
        TranslationSyncAgent,
+       # Product delivery
+       NetworkMonitorOnboardingAgent,
+       PatchComplianceReporterAgent,
+       SecurityScopingAgent,
+       TaskAutomatorAgent,
+       KbLookupAgent,
        # Reporting
        DailyReportAgent,
        PipelineReporterAgent,
        # Orchestrator (last)
        LokiOrchestratorAgent,

──────────────────────────────────────────────────────────────────────────────
Additional Alembic migration required:
──────────────────────────────────────────────────────────────────────────────

  migrations/versions/0040_patch_reports.py
  — Creates the patch_reports table used by PatchComplianceReporterAgent.
  — Full migration SQL is embedded in the docstring of patch_compliance_reporter.py.
  — Run: alembic upgrade head

No new migrations required for the other 4 agents:
  - network_monitor_onboarding: stores packet in approval_requests.payload (JSONB)
  - security_scoping:           stores document in approval_requests.payload (JSONB)
  - task_automator:             stores checklist in approval_requests.payload (JSONB)
  - kb_lookup:                  read-only against known_problems (already deployed)

──────────────────────────────────────────────────────────────────────────────
Celery beat task required for PatchComplianceReporterAgent:
──────────────────────────────────────────────────────────────────────────────

Add to app/tasks/celery_app.py beat_schedule:

    "patch-compliance-weekly": {
        "task": "app.tasks.patch_compliance_beat.run_patch_compliance_reports",
        "schedule": crontab(hour=8, minute=0, day_of_week=1),  # Monday 08:00 UTC
        "options": {"queue": "default"},
    },

Create app/tasks/patch_compliance_beat.py:

    from app.tasks.celery_app import celery_app
    # ... standard Celery task pattern matching app/tasks/daily_report.py ...
    # Iterate all active client records, call PatchComplianceReporterAgent per client.
    # Client data (device counts, patch stats) must be sourced from Intune/WSUS
    # integration or provided via the REST API trigger instead.
"""

# This file is documentation only — no executable code.
# All agent implementations are in their respective app/agents/*.py files.
