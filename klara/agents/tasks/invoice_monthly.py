"""
app/tasks/invoice_monthly.py
─────────────────────────────
phase6-002 — recurring monthly invoice sweep.

Runs on the 1st of every month at 09:00 CET via Celery beat. For each
won + contracted lead with monthly_retainer_amount > 0, it invokes the
existing invoice_generator agent (P3) which:
  - allocates the next sequential INV-YYYY-NNNN number
  - generates a German-compliant PDF
  - queues a P3 ApprovalRequest with action='invoice_generator.send_to_client'
  - returns the GeneratedInvoice id

The existing _run_invoice_send dispatch handler emails the PDF when
Anthony approves. Nothing client-facing happens without that gate.

Idempotency:
  - leads.last_invoice_at < 25 days ago → skip (can't fire twice in same month)
  - invoice_generator's own dedupe checks invoice_number sequencing
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import structlog
from celery import shared_task
from sqlalchemy import select

from app.agents.base import AgentContext
from app.agents.registry import registry
from app.config import get_settings
from app.database import db_context
from app.models.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)

# Minimum days between successive invoices for the same lead. 25 covers
# both 30-day and 31-day months — any retry within the same calendar
# month will be suppressed.
MIN_INVOICE_INTERVAL_DAYS = 25


@shared_task(bind=True, name="app.tasks.invoice_monthly.run_monthly_invoice_sweep")
def run_monthly_invoice_sweep(self):
    """Celery entry point — synchronous wrapper."""
    try:
        result = asyncio.run(_run())
        logger.info("invoice_monthly.complete", **result)
        return result
    except Exception as exc:
        logger.error("invoice_monthly.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc, countdown=300, max_retries=3)


async def _run() -> dict:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MIN_INVOICE_INTERVAL_DAYS)
    settings = get_settings()
    generated = 0
    skipped = 0
    failed = 0

    async with db_context() as db:
        rows = await db.execute(
            select(Lead).where(
                Lead.status == LeadStatus.won.value,
                Lead.contract_sent_at.is_not(None),
                Lead.monthly_retainer_amount.is_not(None),
                Lead.monthly_retainer_amount > 0,
                Lead.email.is_not(None),
            )
        )
        leads = list(rows.scalars())

        for lead in leads:
            if lead.last_invoice_at is not None and lead.last_invoice_at >= cutoff:
                skipped += 1
                continue

            try:
                ok = await _generate_for_lead(db, settings, lead, now)
                if ok:
                    lead.last_invoice_at = now
                    generated += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.error(
                    "invoice_monthly.lead_failed",
                    lead_id=lead.id,
                    error=str(exc),
                )
                failed += 1

    return {
        "candidates": len(leads),
        "generated": generated,
        "skipped_recent": skipped,
        "failed": failed,
    }


async def _generate_for_lead(db, settings, lead: Lead, now: datetime) -> bool:
    """Invoke invoice_generator for one lead. Returns True on success."""
    agent = registry.get("invoice_generator")
    ctx = AgentContext(db=db, settings=settings, lead_id=lead.id)

    month_label = now.strftime("%B %Y")
    payload = {
        "lead_id": lead.id,
        "client_name": lead.name or lead.email,
        "client_email": lead.email,
        "client_company": lead.company,
        "service_description": f"IT consulting retainer — {month_label}",
        "amount_net": float(lead.monthly_retainer_amount or Decimal("0")),
        "vat_rate": 0.0,
        "due_days": 14,
        "notes": "Monthly retainer · auto-generated · phase6-002",
    }
    result = await agent(ctx, payload)
    if not result.success and not result.approval_required:
        logger.warning(
            "invoice_monthly.agent_failed",
            lead_id=lead.id,
            error=result.error,
        )
        return False
    return True
