"""
app/tasks/daily_digest.py
──────────────────────────
phase10-003 — daily 08:00 CET digest email to Anthony.

Aggregates yesterday's state across funnel + cost + ops + approvals
into a single HTML email. Idempotent: only sends once per calendar date
(checked via AuditLog event_type='daily_digest.sent').
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import structlog
from celery import shared_task
from sqlalchemy import func, select

from app.config import get_settings
from app.database import db_context
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.audit import AuditLog
from app.models.lead import Lead, LeadStatus
from app.models.llm_call import LlmCall

logger = structlog.get_logger(__name__)


@shared_task(
    bind=True,
    name="app.tasks.daily_digest.run_daily_digest",
    max_retries=2,
    default_retry_delay=600,
)
def run_daily_digest(self):
    try:
        result = asyncio.run(_run())
        logger.info("daily_digest.complete", **result)
        return result
    except Exception as exc:
        logger.error("daily_digest.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _run() -> dict:
    settings = get_settings()
    today = datetime.now(timezone.utc).date()
    yesterday_start = datetime.combine(today - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    today_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)

    async with db_context() as db:
        # Idempotency: did we already send today?
        already_sent_q = await db.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.event_type == "daily_digest.sent",
                AuditLog.created_at >= today_start,
            )
        )
        if int(already_sent_q.scalar() or 0) > 0:
            return {"skipped": "already_sent_today"}

        pending_q = await db.execute(
            select(func.count(ApprovalRequest.id)).where(
                ApprovalRequest.status == ApprovalStatus.pending.value,
            )
        )
        pending_total = int(pending_q.scalar() or 0)

        leads_added_q = await db.execute(
            select(func.count(Lead.id)).where(
                Lead.created_at >= yesterday_start,
                Lead.created_at < today_start,
            )
        )
        leads_added = int(leads_added_q.scalar() or 0)

        deals_won_q = await db.execute(
            select(func.count(Lead.id)).where(
                Lead.status == LeadStatus.won.value,
                Lead.updated_at >= yesterday_start,
                Lead.updated_at < today_start,
            )
        )
        deals_won = int(deals_won_q.scalar() or 0)

        llm_cost_q = await db.execute(
            select(func.coalesce(func.sum(LlmCall.cost_eur), 0)).where(
                LlmCall.called_at >= yesterday_start,
                LlmCall.called_at < today_start,
            )
        )
        llm_cost_eur = float(llm_cost_q.scalar() or 0.0)

        # Build minimal HTML body
        date_label = (today - timedelta(days=1)).isoformat()
        body_html = (
            f"<h2>Klaravex — Daily digest for {date_label}</h2>"
            f"<ul>"
            f"<li>Pending approvals: <strong>{pending_total}</strong></li>"
            f"<li>New leads yesterday: <strong>{leads_added}</strong></li>"
            f"<li>Deals won yesterday: <strong>{deals_won}</strong></li>"
            f"<li>LLM spend yesterday: <strong>&euro;{llm_cost_eur:.4f}</strong></li>"
            f"</ul>"
            f'<p><a href="https://api.klaravex.com/admin">Open admin dashboard &rarr;</a></p>'
        )
        body_text = (
            f"Daily digest for {date_label}\n"
            f"  Pending approvals: {pending_total}\n"
            f"  New leads yesterday: {leads_added}\n"
            f"  Deals won yesterday: {deals_won}\n"
            f"  LLM spend yesterday: EUR {llm_cost_eur:.4f}\n"
        )

        sent = False
        admin_email = getattr(settings, "approval_notify_email", None)
        if admin_email:
            try:
                from app.services.email_sender import send_transactional_email
                sent = await send_transactional_email(
                    settings,
                    to_email=admin_email,
                    to_name="Anthony",
                    subject=f"Klara AI daily digest — {date_label}",
                    body_html=body_html,
                    body_text=body_text,
                )
            except Exception as exc:
                logger.error("daily_digest.send_failed", error=str(exc))

        audit = AuditLog(
            id=str(uuid4()),
            event_type="daily_digest.sent",
            action_name="daily_digest",
            details=json.dumps({
                "date": date_label,
                "pending_approvals": pending_total,
                "leads_added": leads_added,
                "deals_won": deals_won,
                "llm_cost_eur": llm_cost_eur,
                "sent": sent,
                "to_email": admin_email or "",
            }),
        )
        db.add(audit)

    return {
        "sent": sent,
        "date": date_label,
        "pending_approvals": pending_total,
        "leads_added": leads_added,
        "deals_won": deals_won,
        "llm_cost_eur": llm_cost_eur,
    }
