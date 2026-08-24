"""
app/tasks/weekly_growth_advisor.py
──────────────────────────────────
Celery task: build and email the Klara AI Weekly Growth Advisor report
(prod-005).

Scheduled via celery beat every Monday at 08:00 UTC (10:00 CEST). May
also be triggered manually for backfill or one-off review.

Flow:
  1. growth_advisor.build_weekly_report() — collects signals + Markdown
  2. WordPress site probe (best-effort) — augments signals + bucket
  3. UPSERT WeeklyGrowthReport row (idempotent by iso_year+iso_week)
  4. Email Markdown body via SMTP to settings.weekly_growth_report_email
  5. Update emailed_at + emailed_to on the persisted row

Failures are logged and retried (max 2 attempts, 10-minute backoff). The
beat job exposes no API surface; on-demand re-runs go through the
existing /reports admin tooling once that route is added.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from app.config import get_settings
from app.database import db_context
from app.services.growth_advisor import build_weekly_report
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


_REPORT_RECIPIENT = "astewart.tcml@gmail.com"


@celery_app.task(
    name="app.tasks.weekly_growth_advisor.run_weekly_growth_advisor",
    bind=True,
    max_retries=2,
    default_retry_delay=600,  # 10 minutes
)
def run_weekly_growth_advisor(self, triggered_by: str = "celery_beat") -> dict:
    """Celery entry point — synchronous wrapper around the async impl."""
    try:
        # asyncio.run() required: get_event_loop() is deprecated/raises in Python 3.12 worker threads
        return asyncio.run(_run(triggered_by=triggered_by))
    except Exception as exc:
        logger.error(
            "weekly_growth.task_failed",
            triggered_by=triggered_by,
            error=str(exc),
            exc_info=True,
        )
        raise self.retry(exc=exc)


async def _run(triggered_by: str) -> dict:
    from app.models.weekly_growth_report import WeeklyGrowthReport

    settings = get_settings()

    async with db_context() as db:
        report = await build_weekly_report(db)

        # ── Idempotent upsert by (iso_year, iso_week) ─────────────────────
        existing = (
            await db.execute(
                select(WeeklyGrowthReport)
                .where(WeeklyGrowthReport.iso_year == report.iso_year)
                .where(WeeklyGrowthReport.iso_week == report.iso_week)
            )
        ).scalar_one_or_none()

        if existing:
            existing.report_markdown = report.markdown
            existing.signals = report.signals
            existing.triggered_by = triggered_by
            row = existing
            logger.info(
                "weekly_growth.upsert.updated",
                iso_year=report.iso_year,
                iso_week=report.iso_week,
            )
        else:
            row = WeeklyGrowthReport(
                week_start=report.week_start,
                iso_year=report.iso_year,
                iso_week=report.iso_week,
                triggered_by=triggered_by,
                report_markdown=report.markdown,
                signals=report.signals,
            )
            db.add(row)
            logger.info(
                "weekly_growth.upsert.inserted",
                iso_year=report.iso_year,
                iso_week=report.iso_week,
            )

        await db.flush()
        report_id = row.id

        # ── Email delivery ────────────────────────────────────────────────
        from app.services.email_sender import send_email

        subject = (
            f"Klara AI Weekly Growth Advisor — "
            f"{report.iso_year}-W{report.iso_week:02d}"
        )
        emailed = await send_email(
            settings,
            to_email=_REPORT_RECIPIENT,
            to_name="Anthony",
            subject=subject,
            body_html=_markdown_to_html(report.markdown),
            body_text=report.markdown,
        )

        if emailed:
            row.emailed_to = _REPORT_RECIPIENT
            row.emailed_at = datetime.now(timezone.utc)

        await db.commit()

        return {
            "report_id": report_id,
            "iso_year": report.iso_year,
            "iso_week": report.iso_week,
            "emailed": bool(emailed),
        }


def _markdown_to_html(markdown: str) -> str:
    """
    Minimal Markdown-to-HTML wrapper. The body_text mirror in the email
    is the canonical artifact — the HTML view is a convenience for inbox
    rendering, not an authoring surface, so we deliberately avoid the
    `markdown` package's full pipeline (and its dependency footprint).
    """
    escaped = (
        markdown.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return (
        "<html><body style=\"font-family: -apple-system, "
        "BlinkMacSystemFont, sans-serif; line-height:1.5;\">"
        f"<pre style=\"white-space:pre-wrap;font:inherit;\">{escaped}</pre>"
        "</body></html>"
    )
