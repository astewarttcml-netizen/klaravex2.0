"""
Next-batch customer lifecycle automations.

Each function is idempotent — designed to be called from cron without
worrying about double-execution. Tracking columns added in migration 016.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from .db import get_pool
from .email import send_email

log = logging.getLogger("klaravex.lifecycle_extras")

PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")
ANTHONY_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
SLA_HOURS = {
    "emergency": 1,   # P1
    "high":      4,   # P2
    "standard":  24,  # P3
    "low":       72,  # P4
}


# ── 1. Dunning auto-resume ────────────────────────────────────────────────────

async def handle_invoice_paid_recovery(event: dict) -> dict:
    """Called from stripe_webhook on invoice.paid. If the customer was in
    payment_failed state, clear it and email a thank-you recovery note."""
    obj = event.get("data", {}).get("object") or {}
    customer_id = obj.get("customer")
    if not customer_id:
        return {"action": "skip", "reason": "no_customer"}
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, email, name, metadata
              FROM klaravex_clients WHERE stripe_customer_id=$1
            """,
            customer_id,
        )
        if not row:
            return {"action": "skip", "reason": "no_client_record"}
        meta = row["metadata"] or {}
        failed_count = int((meta or {}).get("payment_failed_count") or 0)
        if failed_count == 0:
            return {"action": "skip", "reason": "no_prior_failure"}
        # Recovery — reset the failure counter, stamp recovery time
        new_meta = {**meta, "payment_failed_count": 0,
                    "last_payment_recovery_at": datetime.now(tz=timezone.utc).isoformat()}
        await conn.execute(
            "UPDATE klaravex_clients SET metadata=$1::jsonb, updated_at=now() WHERE id=$2",
            __import__("json").dumps(new_meta), row["id"],
        )
    # Recovery email
    name = row["name"] or "there"
    body = (
        f"Hi {name},\n\n"
        f"Thanks — your payment went through and your Klaravex subscription is "
        f"back in good standing. Nothing else to do on your end.\n\n"
        f"If something changes again, you can update your payment method any time:\n"
        f"  {PORTAL_BASE_URL}/portal/subscription\n\n"
        f"— The Klaravex Team\n"
    )
    try:
        await send_email(to=row["email"], subject="Your Klaravex subscription is back to normal", body=body)
    except Exception as exc:
        log.warning("dunning recovery email failed for %s: %s", row["email"], exc)
    return {"action": "recovered", "email": row["email"], "prior_failures": failed_count}


# ── 2. SLA escalation timer ───────────────────────────────────────────────────

async def scan_sla_breaches() -> dict:
    """Find open tickets past their SLA threshold and escalate to Anthony."""
    pool = await get_pool()
    now = datetime.now(tz=timezone.utc)
    escalated = []

    async with pool.acquire() as conn:
        for severity, hours in SLA_HOURS.items():
            cutoff = now - timedelta(hours=hours)
            rows = await conn.fetch(
                """
                SELECT id::text, subject, client_email, severity, source, sku, created_at
                  FROM klaravex_tickets
                 WHERE status='open' AND severity=$1
                   AND created_at <= $2
                   AND sla_escalated_at IS NULL
                 ORDER BY created_at ASC LIMIT 50
                """,
                severity, cutoff,
            )
            for r in rows:
                age_h = (now - r["created_at"]).total_seconds() / 3600
                try:
                    await send_email(
                        to=ANTHONY_EMAIL,
                        subject=f"[SLA BREACH · {severity.upper()}] {r['subject'][:80]}",
                        body=(
                            f"Ticket past SLA.\n\n"
                            f"Severity: {severity}  (SLA: {hours}h)\n"
                            f"Age:      {age_h:.1f}h\n"
                            f"Client:   {r['client_email']}\n"
                            f"Subject:  {r['subject']}\n"
                            f"Source:   {r['source']}  SKU: {r['sku'] or '—'}\n\n"
                            f"Open in portal: {PORTAL_BASE_URL}/portal/tickets\n"
                        ),
                    )
                    await conn.execute(
                        "UPDATE klaravex_tickets SET sla_escalated_at=now() WHERE id=$1",
                        r["id"],
                    )
                    escalated.append({"id": r["id"], "severity": severity, "age_h": round(age_h, 1)})
                except Exception as exc:
                    log.warning("SLA escalation email failed for %s: %s", r["id"], exc)

    return {"escalated_count": len(escalated), "items": escalated}


# ── 3. First-ticket CSAT survey ───────────────────────────────────────────────

async def scan_first_ticket_csat() -> dict:
    """When a client's FIRST resolved ticket exists and we haven't surveyed,
    send a 30-second CSAT survey email."""
    pool = await get_pool()
    sent = []
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.id::text, c.email, c.name,
                   t.id::text AS ticket_id, t.subject, t.resolved_at
              FROM klaravex_clients c
              JOIN LATERAL (
                SELECT id, subject, resolved_at
                  FROM klaravex_tickets
                 WHERE client_email = c.email
                   AND status IN ('resolved','closed')
                 ORDER BY resolved_at ASC LIMIT 1
              ) t ON true
             WHERE c.csat_survey_sent_at IS NULL
               AND t.resolved_at IS NOT NULL
             LIMIT 25
        """)
        for r in rows:
            body = (
                f"Hi {r['name'] or 'there'},\n\n"
                f"Quick question — how did we do?\n\n"
                f"Your recent request \"{r['subject'][:80]}\" was resolved on "
                f"{r['resolved_at'].strftime('%B %-d')}. Reply to this email with a number 1-5:\n\n"
                f"   5  Loved it — would recommend\n"
                f"   4  Good\n"
                f"   3  OK\n"
                f"   2  Could be better\n"
                f"   1  Not what I expected\n\n"
                f"If you'd like to say more, just write back. I read every reply personally.\n\n"
                f"— Anthony\n"
                f"   Klaravex\n"
            )
            try:
                await send_email(
                    to=r["email"],
                    subject="How did Klaravex do on your first request?",
                    body=body,
                )
                await conn.execute(
                    "UPDATE klaravex_clients SET csat_survey_sent_at=now() WHERE id=$1",
                    r["id"],
                )
                sent.append(r["email"])
            except Exception as exc:
                log.warning("CSAT send failed for %s: %s", r["email"], exc)
    return {"sent_count": len(sent), "emails": sent}


# ── 4. Day-7 onboarding check-in ──────────────────────────────────────────────

async def scan_day7_onboarding_checkins() -> dict:
    """Onboarding checklists created 7+ days ago, status=active, not yet pinged.
    Sends a check-in email. If checklist <50% complete, also pings Anthony."""
    pool = await get_pool()
    cutoff_old = datetime.now(tz=timezone.utc) - timedelta(days=7)
    cutoff_new = datetime.now(tz=timezone.utc) - timedelta(days=8)  # 1-day window
    sent = []
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id::text, email, segment, tasks, completed_count, total_count
              FROM klaravex_onboarding_checklists
             WHERE status='active'
               AND day7_checkin_sent_at IS NULL
               AND created_at <= $1 AND created_at >= $2
             LIMIT 25
        """, cutoff_old, cutoff_new)
        for r in rows:
            completed = int(r["completed_count"] or 0)
            total = int(r["total_count"] or 0)
            pct = (completed / total * 100) if total else 0
            stuck = pct < 50
            body = (
                f"Hi,\n\n"
                f"One week in — how is your Klaravex onboarding going?\n\n"
                f"You've finished {completed} of {total} tasks ({pct:.0f}%).\n\n"
                f"If you got stuck on anything, reply to this email and I'll handle it.\n"
                f"If everything is humming, ignore me.\n\n"
                f"Your onboarding checklist:\n"
                f"  {PORTAL_BASE_URL}/portal/onboarding\n\n"
                f"— Anthony\n"
            )
            try:
                await send_email(
                    to=r["email"],
                    subject="One-week check-in from Klaravex",
                    body=body,
                )
                await conn.execute(
                    "UPDATE klaravex_onboarding_checklists SET day7_checkin_sent_at=now() WHERE id=$1",
                    r["id"],
                )
                sent.append({"email": r["email"], "pct": round(pct), "stuck": stuck})
                if stuck:
                    try:
                        await send_email(
                            to=ANTHONY_EMAIL,
                            subject=f"[Onboarding alert] {r['email']} stuck at {pct:.0f}%",
                            body=(
                                f"Client {r['email']} (segment={r['segment']}) is 7 days into\n"
                                f"onboarding and only {completed}/{total} tasks done.\n"
                                f"Manual reach-out recommended.\n"
                            ),
                        )
                    except Exception as exc:
                        log.warning("operator stuck-alert email failed: %s", exc)
            except Exception as exc:
                log.warning("Day-7 checkin send failed for %s: %s", r["email"], exc)
    return {"sent_count": len(sent), "items": sent}


# ── 5. Housekeeping ───────────────────────────────────────────────────────────

async def housekeeping_cleanup() -> dict:
    """Free DB space and clear stale rows. Idempotent.
       - portal_tokens: delete if expired > 30 days
       - data_export_requests: mark expired + null the file_bytes
       - marketing_actions: nothing (kept for analytics)
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        tokens_deleted = await conn.fetchval("""
            WITH d AS (
                DELETE FROM klaravex_portal_tokens
                 WHERE expires_at < now() - interval '30 days'
                 RETURNING 1
            )
            SELECT COUNT(*) FROM d
        """)
        exports_expired = await conn.fetchval("""
            WITH e AS (
                UPDATE klaravex_data_export_requests
                   SET status='expired', file_bytes=NULL
                 WHERE expires_at < now() AND file_bytes IS NOT NULL
                 RETURNING 1
            )
            SELECT COUNT(*) FROM e
        """)
        # Also: delete very old expired marketing actions to keep table small
        actions_purged = await conn.fetchval("""
            WITH p AS (
                DELETE FROM klaravex_marketing_actions
                 WHERE created_at < now() - interval '180 days'
                   AND status IN ('blocked','reverted')
                 RETURNING 1
            )
            SELECT COUNT(*) FROM p
        """)
    log.info(
        "housekeeping: tokens=%s exports=%s actions=%s",
        tokens_deleted, exports_expired, actions_purged,
    )
    return {
        "portal_tokens_deleted": int(tokens_deleted or 0),
        "data_exports_expired":  int(exports_expired or 0),
        "marketing_actions_purged": int(actions_purged or 0),
    }
