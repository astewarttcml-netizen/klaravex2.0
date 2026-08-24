"""
Client-facing monthly executive report.

Sends a per-client digest with:
  - Plan info + total monthly spend
  - Tickets opened / resolved / open over the period
  - Mean time to resolution (MTTR)
  - Escalations to senior engineer
  - Block hours used / remaining (B2B only)
  - 1-2 sentence narrative + recommendation

Different copy for consumer vs B2B. B2B gets SLA + compliance hooks.

Callable from:
  - cron/monthly_ops_report.py (extend to also send per-client)
  - /api/v1/internal/reports/client-monthly  (manual trigger / test)
  - /api/v1/internal/reports/client-monthly/all (scheduled fan-out)
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import stripe

from .db import get_pool
from .email import send_email

log = logging.getLogger("klaravex.client_monthly_report")

PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")
REPORT_SUPPORT_EMAIL = os.environ.get("REPORT_SUPPORT_EMAIL", "support@klaravex.com")
SLA_TARGET_HOURS = {
    "emergency": 1,    # P1 → respond/resolve within 1 hour
    "high":      4,    # P2 → 4 hours
    "standard":  24,   # P3 → 1 business day
    "low":       72,   # P4 → 3 business days
}


async def _client_metrics(email: str, since: datetime) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        client_row = await conn.fetchrow(
            "SELECT id, name, segment, stripe_customer_id FROM klaravex_clients WHERE email=$1",
            email.lower(),
        )
        if not client_row:
            return {}

        ticket_row = await conn.fetchrow(
            """
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE severity='emergency') AS p1,
              COUNT(*) FILTER (WHERE severity='high')      AS p2,
              COUNT(*) FILTER (WHERE severity='standard')  AS p3,
              COUNT(*) FILTER (WHERE severity='low')       AS p4,
              COUNT(*) FILTER (WHERE status IN ('resolved','closed')) AS resolved,
              COUNT(*) FILTER (WHERE status='open')        AS still_open,
              COUNT(*) FILTER (WHERE status='escalated')   AS escalated,
              COALESCE(
                AVG(EXTRACT(EPOCH FROM (resolved_at - created_at))/3600.0)
                  FILTER (WHERE resolved_at IS NOT NULL AND status IN ('resolved','closed')),
                0
              ) AS mttr_hours,
              COUNT(*) FILTER (WHERE
                resolved_at IS NOT NULL
                AND status IN ('resolved','closed')
                AND EXTRACT(EPOCH FROM (resolved_at - created_at))/3600.0 <=
                  CASE severity
                    WHEN 'emergency' THEN 1.0
                    WHEN 'high'      THEN 4.0
                    WHEN 'standard'  THEN 24.0
                    WHEN 'low'       THEN 72.0
                    ELSE 24.0
                  END
              ) AS sla_met
            FROM klaravex_tickets
            WHERE client_email=$1 AND created_at >= $2
            """,
            email.lower(), since,
        )

        hours_balance = await conn.fetchval(
            """
            SELECT COALESCE(SUM(delta_hours), 0)
            FROM klaravex_hours_ledger WHERE client_id=$1
            """,
            client_row["id"],
        )
        hours_used_period = await conn.fetchval(
            """
            SELECT COALESCE(SUM(-delta_hours), 0)
            FROM klaravex_hours_ledger
            WHERE client_id=$1 AND delta_hours < 0 AND created_at >= $2
            """,
            client_row["id"], since,
        )

    return {
        "client_id": str(client_row["id"]),
        "name": client_row["name"],
        "segment": client_row["segment"],
        "stripe_customer_id": client_row["stripe_customer_id"],
        "tickets": {
            "total":     int(ticket_row["total"] or 0),
            "p1":        int(ticket_row["p1"] or 0),
            "p2":        int(ticket_row["p2"] or 0),
            "p3":        int(ticket_row["p3"] or 0),
            "p4":        int(ticket_row["p4"] or 0),
            "resolved":  int(ticket_row["resolved"] or 0),
            "still_open":int(ticket_row["still_open"] or 0),
            "escalated": int(ticket_row["escalated"] or 0),
            "mttr_hours":round(float(ticket_row["mttr_hours"] or 0), 1),
            "sla_met":   int(ticket_row["sla_met"] or 0),
        },
        "hours_balance":      round(float(hours_balance or 0), 1),
        "hours_used_period":  round(float(hours_used_period or 0), 1),
    }


def _format_b2b_body(name: str, metrics: dict, plan_summary: str, period_label: str) -> str:
    t = metrics["tickets"]
    resolved = t["resolved"]
    sla_met = t["sla_met"]
    sla_pct = (sla_met / resolved * 100) if resolved else 100.0
    mttr = t["mttr_hours"]

    if t["total"] == 0:
        narrative = "Quiet month. No tickets opened — that's a good sign your infrastructure is stable."
    elif t["p1"] == 0 and t["p2"] == 0:
        narrative = f"Clean operational month. {t['resolved']} tickets resolved in an average of {mttr:.1f} hours. No P1/P2 incidents."
    elif t["escalated"] > 0:
        narrative = f"{t['total']} tickets handled, {t['escalated']} escalated to senior engineer. SLA met on {sla_pct:.0f}% of resolved cases."
    else:
        narrative = f"{t['total']} tickets handled this month. AI resolved {t['resolved'] - t['escalated']} without human escalation; MTTR {mttr:.1f}h."

    body = (
        f"Hi {name},\n\n"
        f"Here's your {period_label} Klaravex executive summary.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  YOUR SERVICE\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  {plan_summary}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  THIS MONTH AT A GLANCE\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  Total tickets:       {t['total']}\n"
        f"  Resolved:            {t['resolved']}\n"
        f"  Open:                {t['still_open']}\n"
        f"  Escalated to engineer: {t['escalated']}\n"
        f"  Mean time to resolve: {mttr:.1f} hours\n"
        f"  SLA compliance:      {sla_pct:.0f}%\n\n"
        f"  By severity:\n"
        f"    P1 (emergency):   {t['p1']}\n"
        f"    P2 (high):        {t['p2']}\n"
        f"    P3 (standard):    {t['p3']}\n"
        f"    P4 (low):         {t['p4']}\n\n"
    )
    if metrics.get("hours_balance", 0) or metrics.get("hours_used_period", 0):
        body += (
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"  BLOCK HOURS\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"  Used this period:    {metrics['hours_used_period']:.1f}h\n"
            f"  Remaining balance:   {metrics['hours_balance']:.1f}h\n\n"
        )
    body += (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  WHAT IT MEANS\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  {narrative}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  YOUR PORTAL\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  Full ticket history, hours ledger, knowledge base:\n"
        f"    {PORTAL_BASE_URL}/portal/\n\n"
        f"  Questions about this report? Reply to this email or reach\n"
        f"  {REPORT_SUPPORT_EMAIL}.\n\n"
        f"— The Klaravex Team\n"
    )
    return body


def _format_consumer_body(name: str, metrics: dict, plan_summary: str, period_label: str) -> str:
    t = metrics["tickets"]
    if t["total"] == 0:
        narrative = "No support requests this month. If everything's running smoothly, great. If you've been holding back questions, we're here — chat with Klara AI anytime."
    else:
        narrative = (
            f"You opened {t['total']} {'request' if t['total']==1 else 'requests'} this month, "
            f"{t['resolved']} resolved in an average of {t['mttr_hours']:.1f} hours."
        )

    body = (
        f"Hi {name},\n\n"
        f"Quick {period_label} recap from Klaravex.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  YOUR MEMBERSHIP\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  {plan_summary}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  THIS MONTH\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  Requests opened:     {t['total']}\n"
        f"  Resolved:            {t['resolved']}\n"
        f"  Still open:          {t['still_open']}\n"
        f"  Avg time to resolve: {t['mttr_hours']:.1f} hours\n\n"
        f"  {narrative}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  YOUR PORTAL\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  Chat with Klara AI, see past requests, manage your plan:\n"
        f"    {PORTAL_BASE_URL}/portal/\n\n"
        f"— The Klaravex Team\n"
    )
    return body


async def _plan_summary_for(stripe_customer_id: Optional[str]) -> str:
    """Build a one-line summary of customer's active subscriptions."""
    if not stripe_customer_id:
        return "Your Klaravex plan"
    try:
        resp = stripe.Subscription.list(customer=stripe_customer_id, status="active", limit=20,
                                         expand=["data.items.data.price"])
        subs = list(resp.data) if hasattr(resp, "data") else list(resp)
        plans = []
        total = 0.0
        for sub in subs:
            sd = sub.to_dict() if hasattr(sub, "to_dict") else dict(sub)
            for item in (sd.get("items") or {}).get("data") or []:
                price = item.get("price") or {}
                amt = int(price.get("unit_amount") or 0) / 100.0
                total += amt
                prod = price.get("product")
                if isinstance(prod, str):
                    try:
                        po = stripe.Product.retrieve(prod)
                        pd = po.to_dict() if hasattr(po, "to_dict") else dict(po)
                        plans.append(pd.get("name") or "Klaravex")
                    except Exception:
                        plans.append("Klaravex")
                else:
                    plans.append("Klaravex")
        if not plans:
            return "Your Klaravex plan"
        return f"{', '.join(plans)} — ${total:.0f}/mo total"
    except Exception as exc:
        log.warning("plan summary failed for %s: %s", stripe_customer_id, exc)
        return "Your Klaravex plan"


async def send_client_monthly_report(
    email: str,
    *,
    days: int = 30,
) -> dict[str, object]:
    """Send a single client their monthly digest."""
    since = datetime.now(tz=timezone.utc) - timedelta(days=days)
    metrics = await _client_metrics(email, since)
    if not metrics:
        return {"sent": False, "reason": "client_not_found"}

    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    plan_summary = await _plan_summary_for(metrics.get("stripe_customer_id"))
    name = metrics.get("name") or "there"
    period_label = f"past {days}-day"
    segment = metrics.get("segment") or "consumer"

    if segment == "b2b":
        body = _format_b2b_body(name, metrics, plan_summary, period_label)
        subject = f"Your Klaravex {period_label} executive summary"
    else:
        body = _format_consumer_body(name, metrics, plan_summary, period_label)
        subject = f"Your Klaravex {period_label} recap"

    try:
        await send_email(to=email, subject=subject, body=body)
        log.info("monthly report sent to %s (segment=%s)", email, segment)
        return {"sent": True, "segment": segment, "tickets_total": metrics["tickets"]["total"]}
    except Exception as exc:
        log.exception("monthly report send failed for %s: %s", email, exc)
        return {"sent": False, "reason": f"email_error: {exc}"}


async def send_monthly_reports_to_all_clients(days: int = 30) -> dict[str, int]:
    """Fan-out: send digest to every client with an email + stripe_customer_id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT email FROM klaravex_clients
            WHERE email IS NOT NULL AND email <> ''
              AND stripe_customer_id IS NOT NULL
            ORDER BY created_at DESC
            """
        )

    sent = 0
    skipped = 0
    errors = 0
    for r in rows:
        try:
            result = await send_client_monthly_report(r["email"], days=days)
            if result.get("sent"):
                sent += 1
            else:
                skipped += 1
        except Exception as exc:
            log.warning("fan-out error for %s: %s", r["email"], exc)
            errors += 1
    return {"sent": sent, "skipped": skipped, "errors": errors, "total_clients": len(rows)}
