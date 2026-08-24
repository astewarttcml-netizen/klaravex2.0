"""
app/tasks/social_report.py
──────────────────────────
Daily Celery beat task — fires at 08:00 CET every day.

Queries the audit_logs table for social.published events in the last
24 hours, groups results by platform, and emails a digest to the
consultant (astewart@klaravex.de).

Also checks whether the LinkedIn personal OAuth token is within
14 days of expiry (LINKEDIN_PERSONAL_TOKEN_EXPIRES in .env) and
prepends a warning banner to the email if so.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import structlog

from app.tasks.celery_app import celery_app
from app.config import get_settings

logger = structlog.get_logger(__name__)

REPORT_TO_EMAIL = "astewart@klaravex.de"
REPORT_TO_NAME  = "Anthony Stewart"


# ──────────────────────────────────────────────────────────────────────────────
# Celery entry point
# ──────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    name="app.tasks.social_report.send_social_report",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def send_social_report(self):
    """Daily social media activity digest."""
    import app.database as _db_module
    _db_module._engine = None
    _db_module._session_factory = None

    try:
        asyncio.run(_run_report())
    except Exception as exc:
        logger.error(
            "social_report.task_failed",
            error=str(exc),
            exc_info=True,
        )
        raise self.retry(exc=exc)


# ──────────────────────────────────────────────────────────────────────────────
# Core report logic
# ──────────────────────────────────────────────────────────────────────────────

async def _run_report():
    from sqlalchemy import select, text
    from app.database import db_context
    from app.models.audit import AuditLog
    from app.services.email_sender import send_resend_email as send_email

    settings = get_settings()
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    async with db_context() as db:
        result = await db.execute(
            select(AuditLog)
            .where(AuditLog.event_type == "social.published")
            .where(AuditLog.created_at >= since)
            .order_by(AuditLog.created_at.asc())
        )
        rows: list[AuditLog] = result.scalars().all()

    # ── Group by platform ─────────────────────────────────────────────────────
    # platform → list of detail dicts
    by_platform: dict[str, list[dict]] = {}
    for row in rows:
        try:
            details = json.loads(row.details) if row.details else {}
        except (json.JSONDecodeError, TypeError):
            details = {}

        platform = details.get("platform") or row.action_name or "unknown"
        by_platform.setdefault(platform, []).append({
            "success":   details.get("success", False),
            "post_url":  details.get("post_url"),
            "post_id":   details.get("post_id"),
            "topic":     details.get("topic", ""),
            "error":     details.get("error"),
            "timestamp": row.created_at.isoformat() if row.created_at else "",
        })

    total_posts  = len(rows)
    total_ok     = sum(1 for r in rows if json.loads(r.details or "{}").get("success"))
    total_failed = total_posts - total_ok
    date_label   = now.strftime("%A, %d %B %Y")

    # ── Token expiry check ────────────────────────────────────────────────────
    expiry_warning_html = ""
    expiry_warning_text = ""
    token_expires_str = getattr(settings, "linkedin_personal_token_expires", "")
    if token_expires_str:
        try:
            expires_dt = datetime.strptime(token_expires_str, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            days_left = (expires_dt - now).days
            if days_left <= 14:
                expiry_warning_html = (
                    f"<div style='background:#fff3cd;border:1px solid #ffc107;"
                    f"padding:12px;border-radius:4px;margin-bottom:16px'>"
                    f"<strong>⚠️  LinkedIn Personal OAuth Token expires in {days_left} day(s)"
                    f" ({token_expires_str}).</strong><br>"
                    f"Refresh it now at "
                    f"<a href='https://www.linkedin.com/developers/apps'>LinkedIn Developer Portal</a> "
                    f"then run: <code>./scripts/deploy-social-creds.sh</code>"
                    f"</div>"
                )
                expiry_warning_text = (
                    f"WARNING: LinkedIn Personal OAuth Token expires in {days_left} day(s) "
                    f"({token_expires_str}). Refresh it at the LinkedIn Developer Portal "
                    f"and re-run: ./scripts/deploy-social-creds.sh\n\n"
                )
        except ValueError:
            logger.warning("social_report.invalid_token_expires", value=token_expires_str)

    # ── Email subject ─────────────────────────────────────────────────────────
    if total_posts == 0:
        subject = f"[Klaravex] Social Report {date_label} — No posts in last 24h"
    else:
        subject = (
            f"[Klaravex] Social Report {date_label} — "
            f"{total_ok}/{total_posts} post(s) published"
        )

    # ── Build HTML body ───────────────────────────────────────────────────────
    html_parts = [
        "<div style='font-family:Arial,sans-serif;max-width:680px'>",
        expiry_warning_html,
        f"<h2 style='color:#1a1a2e'>Social Media Report — {date_label}</h2>",
        f"<p>Posts attempted in the last 24 hours: "
        f"<strong>{total_posts}</strong> "
        f"({total_ok} succeeded, {total_failed} failed)</p>",
    ]

    if total_posts == 0:
        html_parts.append(
            "<p style='color:#666'>No social posts were sent in the last 24 hours.</p>"
        )
    else:
        # Per-platform sections
        platform_labels = {
            "linkedin_company":  "LinkedIn Company Page",
            "linkedin_personal": "LinkedIn Personal Profile",
            "twitter":           "Twitter / X",
            "xing":              "XING",
            "facebook":          "Facebook",
            "instagram":         "Instagram Business Account",
        }

        for platform, items in by_platform.items():
            label = platform_labels.get(platform, platform.title())
            ok_items   = [i for i in items if i["success"]]
            fail_items = [i for i in items if not i["success"]]

            html_parts.append(
                f"<hr style='margin:20px 0'>"
                f"<h3 style='color:#1a1a2e'>{label} "
                f"<span style='font-size:14px;font-weight:normal;color:#555'>"
                f"({len(ok_items)} ok / {len(fail_items)} failed)</span></h3>"
            )

            for item in ok_items:
                url_part = (
                    f" &nbsp;→ <a href='{item['post_url']}'>{item['post_url']}</a>"
                    if item.get("post_url") else ""
                )
                html_parts.append(
                    f"<div style='background:#e8f5e9;padding:8px 12px;border-radius:4px;"
                    f"margin-bottom:6px'>"
                    f"<span style='color:#388e3c'>✓</span> "
                    f"{item.get('topic', '(no topic)')}{url_part}"
                    f"<br><small style='color:#888'>{item.get('timestamp','')}</small>"
                    f"</div>"
                )

            for item in fail_items:
                html_parts.append(
                    f"<div style='background:#fff3e0;padding:8px 12px;border-radius:4px;"
                    f"margin-bottom:6px'>"
                    f"<span style='color:#e65100'>✗</span> "
                    f"{item.get('topic', '(no topic)')} — "
                    f"<code style='font-size:12px'>{item.get('error','unknown error')}</code>"
                    f"<br><small style='color:#888'>{item.get('timestamp','')}</small>"
                    f"</div>"
                )

    html_parts.append("</div>")
    body_html = "\n".join(html_parts)

    # ── Build plain-text body ─────────────────────────────────────────────────
    text_lines = [
        expiry_warning_text,
        f"Klaravex Social Media Report — {date_label}",
        f"Posts in last 24h: {total_posts} ({total_ok} succeeded, {total_failed} failed)",
        "",
    ]

    if total_posts == 0:
        text_lines.append("No social posts were sent in the last 24 hours.")
    else:
        for platform, items in by_platform.items():
            label = platform_labels.get(platform, platform.title())  # type: ignore[name-defined]
            text_lines.append(f"--- {label} ---")
            for item in items:
                status = "OK" if item["success"] else "FAIL"
                url = f"  {item['post_url']}" if item.get("post_url") else ""
                err = f"  Error: {item['error']}" if item.get("error") else ""
                text_lines.append(f"  [{status}] {item.get('topic','(no topic)')}{url}{err}")
            text_lines.append("")

    body_text = "\n".join(text_lines)

    # ── Send ──────────────────────────────────────────────────────────────────
    sent = await send_email(
        settings,
        to_email=REPORT_TO_EMAIL,
        to_name=REPORT_TO_NAME,
        subject=subject,
        body_html=body_html,
        body_text=body_text,
    )

    logger.info(
        "social_report.sent",
        total_posts=total_posts,
        total_ok=total_ok,
        total_failed=total_failed,
        platforms=list(by_platform.keys()),
        email_sent=sent,
    )
