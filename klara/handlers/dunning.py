"""
Klaravex Dunning Agent — handles failed Stripe payment events.

Exported handler functions called by stripe_webhook.py:

    handle_invoice_payment_failed(event)      — invoice.payment_failed
    handle_subscription_past_due(event)        — customer.subscription.past_due
    handle_subscription_unpaid(event)          — customer.subscription.unpaid

Each handler:
  1. Extracts customer details from the Stripe event.
  2. Looks up / upserts the client in klaravex_clients.
  3. Creates a klaravex_tickets row with appropriate severity/status.
  4. Sends a transactional email via M365 Graph (dunning emails go to existing
     clients per the prospect-vs-client routing policy; see CLAUDE.md).
  5. Sends a Twilio SMS if the client has a phone on record.
  6. Updates client metadata (payment_failed_count, last_payment_failure).

For unpaid (≥3 failures):
  - Sends final-notice email.
  - Creates a P2 / escalated ticket.
  - Calls lib.escalation.escalate() — manual review, no auto-suspend.

Required env vars:
    DATABASE_URL
    MS_GRAPH_TENANT_ID / MS_GRAPH_CLIENT_ID / MS_GRAPH_CLIENT_SECRET / MS_GRAPH_SENDER_EMAIL
    TWILIO_ACCOUNT_SID
    TWILIO_AUTH_TOKEN
    TWILIO_FROM_NUMBER      default: +14243486010
    ANTHONY_ALERT_EMAIL     default: astewart@klaravex.com
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import asyncpg

from .lib import escalation as escalation_lib
from .lib import tickets as tickets_lib
from .lib.db import normalize_dsn
from .lib.email import send_email

log = logging.getLogger("klaravex.dunning")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.environ.get("TWILIO_FROM_NUMBER", "+14243486010")
ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")

PAYMENT_UPDATE_URL = "https://klaravex.com/portal/billing/"


# ---------------------------------------------------------------------------
# Low-level send helpers
# ---------------------------------------------------------------------------

async def _send_resend_email(to: str, subject: str, body: str) -> bool:
    """Send a transactional dunning email via M365 Graph.

    Function name retained for call-site compatibility; the actual transport
    moved from Resend to M365 Graph on 2026-06-25 (Resend account deleted).
    send_email() never raises — Graph backend failures are logged and
    swallowed, so this returns True regardless. Callers expecting a real
    delivery signal should check Graph logs.
    """
    try:
        await send_email(to=to, subject=subject, body=body)
        log.info("dunning email sent to=%s subject=%r", to, subject)
        return True
    except Exception as exc:
        log.warning("dunning email exception to=%s: %s", to, exc)
        return False


async def _send_sms(to: str, body: str) -> bool:
    """Delegates to the gated lib.sms helper so SMS_ENABLED is honored centrally."""
    from .lib.sms import send_sms as _gated
    ok, _err = await _gated(to, body, source="dunning")
    return ok


# ---------------------------------------------------------------------------
# Client helpers
# ---------------------------------------------------------------------------

async def _lookup_client(email: str) -> dict[str, Any] | None:
    """Fetch client row from klaravex_clients by email. Returns None if not found."""
    if not DATABASE_URL:
        return None
    try:
        conn = await asyncpg.connect(normalize_dsn(DATABASE_URL))
        try:
            row = await conn.fetchrow(
                "SELECT id, name, phone, segment, metadata FROM klaravex_clients WHERE email = $1",
                email.lower(),
            )
            return dict(row) if row else None
        finally:
            await conn.close()
    except Exception as exc:
        log.warning("client lookup failed for %s: %s", email, exc)
        return None


async def _update_client_payment_metadata(email: str) -> None:
    """Increment payment_failed_count and record last_payment_failure timestamp."""
    if not DATABASE_URL:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        conn = await asyncpg.connect(normalize_dsn(DATABASE_URL))
        try:
            # Fetch existing metadata to merge safely.
            row = await conn.fetchrow(
                "SELECT metadata FROM klaravex_clients WHERE email = $1",
                email.lower(),
            )
            if not row:
                return
            existing: dict[str, Any] = json.loads(row["metadata"] or "{}")
            failed_count = int(existing.get("payment_failed_count", 0)) + 1
            patch = {
                "payment_failed_count": failed_count,
                "last_payment_failure": now_iso,
            }
            await conn.execute(
                """
                UPDATE klaravex_clients
                   SET metadata = metadata || $2::jsonb,
                       updated_at = now()
                 WHERE email = $1
                """,
                email.lower(),
                json.dumps(patch),
            )
            log.info(
                "payment metadata updated email=%s failed_count=%d",
                email,
                failed_count,
            )
        finally:
            await conn.close()
    except Exception as exc:
        log.warning("payment metadata update failed for %s: %s", email, exc)


# ---------------------------------------------------------------------------
# Stripe event data extraction
# ---------------------------------------------------------------------------

def _extract_invoice_details(event: dict[str, Any]) -> dict[str, Any]:
    """
    Extract customer email, amount, and invoice URL from a Stripe invoice event.

    Returns a dict with keys: email, amount_str, invoice_url, stripe_customer_id.
    """
    obj = event["data"]["object"]
    email = (
        obj.get("customer_email")
        or obj.get("customer_details", {}).get("email")
        or obj.get("receipt_email")
        or ""
    )
    amount_due = obj.get("amount_due") or obj.get("amount_remaining") or 0
    amount_str = f"${amount_due / 100:.2f}" if isinstance(amount_due, int) else "—"
    invoice_url = (
        obj.get("hosted_invoice_url")
        or obj.get("invoice_pdf")
        or PAYMENT_UPDATE_URL
    )
    stripe_customer_id = obj.get("customer") or None
    return {
        "email":               email,
        "amount_str":          amount_str,
        "invoice_url":         invoice_url,
        "stripe_customer_id":  stripe_customer_id,
        "stripe_invoice_id":   obj.get("id"),
        "stripe_event_id":     event.get("id"),
    }


def _extract_subscription_details(event: dict[str, Any]) -> dict[str, Any]:
    """
    Extract customer email from a Stripe subscription event.

    Stripe subscription objects do not carry customer_email directly — we get
    the customer ID and look up via the object's customer field.  The email
    in metadata is the best we can do without an extra Stripe API call; the
    dunning agent falls back to a DB lookup by stripe_customer_id.
    """
    obj = event["data"]["object"]
    # Some subscription events embed a customer expand or metadata email.
    meta = obj.get("metadata") or {}
    email = meta.get("customer_email") or meta.get("email") or ""
    stripe_customer_id = obj.get("customer") or None
    return {
        "email":              email,
        "stripe_customer_id": stripe_customer_id,
        "stripe_sub_id":      obj.get("id"),
        "stripe_event_id":    event.get("id"),
    }


async def _resolve_email_for_subscription(
    details: dict[str, Any],
) -> str:
    """
    Try to resolve customer email for subscription events.

    Stripe subscription objects rarely embed the email.  We try in order:
      1. Email in event metadata.
      2. klaravex_clients lookup by stripe_customer_id.
    Returns '' if not resolvable.
    """
    if details["email"]:
        return details["email"]

    stripe_cid = details.get("stripe_customer_id")
    if not stripe_cid or not DATABASE_URL:
        return ""

    try:
        conn = await asyncpg.connect(normalize_dsn(DATABASE_URL))
        try:
            row = await conn.fetchrow(
                "SELECT email FROM klaravex_clients WHERE stripe_customer_id = $1",
                stripe_cid,
            )
            return row["email"] if row else ""
        finally:
            await conn.close()
    except Exception as exc:
        log.warning("stripe_customer_id email lookup failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Shared dunning action: create ticket + notify client + update metadata
# ---------------------------------------------------------------------------

async def _run_dunning_action(
    *,
    email: str,
    stripe_customer_id: str | None,
    ticket_severity: str,          # "standard" | "high" | "emergency"
    ticket_status: str,            # "open" | "escalated"
    ticket_subject: str,
    ticket_summary: str,
    ticket_workflow_state: str,    # custom workflow label stored in workflow_state
    email_subject: str,
    email_body: str,
    sms_body: str,
    stripe_meta: dict[str, Any],
    escalate: bool = False,
    escalation_summary: str = "",
) -> dict[str, Any]:
    """
    Shared dunning flow:
      1. Upsert client record.
      2. Create ticket.
      3. Send client email (M365 Graph).
      4. Send client SMS if phone on record (Twilio).
      5. Update client payment metadata.
      6. Optionally escalate.
    """
    segment = "consumer"
    client_phone: str | None = None

    if email:
        client = await _lookup_client(email)
        if client:
            segment = client.get("segment") or "consumer"
            meta = client.get("metadata") or {}
            if isinstance(meta, str):
                meta = json.loads(meta)
            client_phone = meta.get("phone") or client.get("phone") or None

        # Ensure client row exists.
        try:
            await tickets_lib.get_or_create_client(
                email,
                segment=segment,
                stripe_customer_id=stripe_customer_id,
            )
        except Exception as exc:
            log.warning("get_or_create_client failed for %s: %s", email, exc)

    # Create ticket.
    ticket_id: str | None = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=email,
            subject=ticket_subject,
            severity=ticket_severity,
            status=ticket_status,
            source="stripe",
            summary=ticket_summary,
            archetype="A1",
            workflow_state=ticket_workflow_state,
            metadata={
                **stripe_meta,
                "dunning": True,
            },
            initial_event={
                "at": datetime.now(timezone.utc).isoformat(),
                "type": ticket_workflow_state,
                "source": "stripe",
                **stripe_meta,
            },
            segment_hint=segment,
        )
        log.info(
            "dunning ticket created id=%s severity=%s workflow=%s",
            ticket_id,
            ticket_severity,
            ticket_workflow_state,
        )
    except Exception as exc:
        log.warning("dunning ticket creation failed for %s: %s", email, exc)

    # Send client email.
    email_sent = False
    if email:
        email_sent = await _send_resend_email(email, email_subject, email_body)

    # Send SMS if phone known.
    sms_sent = False
    if client_phone:
        sms_sent = await _send_sms(client_phone, sms_body)

    # Update payment metadata.
    if email:
        await _update_client_payment_metadata(email)

    # Escalate if requested.
    escalation_id: str | None = None
    if escalate and ticket_id and email:
        try:
            result = await escalation_lib.escalate(
                ticket_id=ticket_id,
                client_email=email,
                severity=ticket_severity,
                summary=escalation_summary or ticket_summary,
                attempted="Dunning final-notice email sent",
                recommended="Review account and contact client to reactivate",
            )
            escalation_id = result.get("escalation_id")
        except Exception as exc:
            log.warning("escalation failed for ticket %s: %s", ticket_id, exc)

    return {
        "ticket_id":     ticket_id,
        "escalation_id": escalation_id,
        "email_sent":    email_sent,
        "sms_sent":      sms_sent,
    }


# ---------------------------------------------------------------------------
# Public event handlers
# ---------------------------------------------------------------------------

async def handle_invoice_payment_failed(event: dict[str, Any]) -> dict[str, Any]:
    """
    Handle invoice.payment_failed — payment attempt failed on an active subscription.

    Creates a P3 ticket (severity=standard), sends a firm payment-update request
    with a 3-day warning, and bumps the failure counter on the client record.
    """
    details = _extract_invoice_details(event)
    email = details["email"]

    if not email:
        log.warning("invoice.payment_failed: no customer email in event %s", details["stripe_event_id"])
        return {"skipped": True, "reason": "no_email"}

    log.info("dunning: invoice.payment_failed email=%s amount=%s", email, details["amount_str"])

    email_body = (
        f"Hi,\n\n"
        f"We were unable to process the payment of {details['amount_str']} "
        f"for your Klaravex subscription.\n\n"
        f"Please update your payment method to keep your service active:\n"
        f"{details['invoice_url']}\n\n"
        f"If this is not resolved within 3 days, your service will be paused "
        f"and you may lose access to active monitoring and support.\n\n"
        f"If you believe this is an error or need assistance, reply to this email "
        f"or contact us at support@klaravex.com.\n\n"
        f"Klaravex Support\nsupport@klaravex.com"
    )

    sms_body = (
        f"Klaravex: Payment of {details['amount_str']} failed. "
        f"Update your payment method to keep your service active: {details['invoice_url']}"
    )

    return await _run_dunning_action(
        email=email,
        stripe_customer_id=details["stripe_customer_id"],
        ticket_severity="standard",
        ticket_status="open",
        ticket_subject="Payment failed — action required",
        ticket_summary=f"Invoice payment of {details['amount_str']} failed. Invoice: {details['invoice_url']}",
        ticket_workflow_state="payment_failed",
        email_subject="Action required: Your Klaravex payment couldn't be processed",
        email_body=email_body,
        sms_body=sms_body,
        stripe_meta={
            "stripe_event_id":   details["stripe_event_id"],
            "stripe_invoice_id": details["stripe_invoice_id"],
            "amount_str":        details["amount_str"],
            "invoice_url":       details["invoice_url"],
        },
    )


async def handle_subscription_past_due(event: dict[str, Any]) -> dict[str, Any]:
    """
    Handle customer.subscription.past_due — first soft reminder.

    Softer tone than invoice.payment_failed; this is the first dunning touch
    for subscriptions that missed their renewal date.
    """
    details = _extract_subscription_details(event)
    email = await _resolve_email_for_subscription(details)

    if not email:
        log.warning(
            "customer.subscription.past_due: cannot resolve email for customer=%s event=%s",
            details["stripe_customer_id"],
            details["stripe_event_id"],
        )
        return {"skipped": True, "reason": "no_email"}

    log.info("dunning: subscription.past_due email=%s", email)

    email_body = (
        f"Hi,\n\n"
        f"Your Klaravex subscription is now past due.\n\n"
        f"This is a friendly reminder to update your payment method so your service "
        f"continues without interruption:\n"
        f"{PAYMENT_UPDATE_URL}\n\n"
        f"If you have already updated your payment details, please disregard this message.\n\n"
        f"Questions? Contact us at support@klaravex.com — we're happy to help.\n\n"
        f"Klaravex Support\nsupport@klaravex.com"
    )

    sms_body = (
        "Klaravex: Your subscription is past due. "
        f"Update your payment details to keep your service active: {PAYMENT_UPDATE_URL}"
    )

    return await _run_dunning_action(
        email=email,
        stripe_customer_id=details["stripe_customer_id"],
        ticket_severity="standard",
        ticket_status="open",
        ticket_subject="Subscription past due — first reminder",
        ticket_summary="Subscription moved to past_due. First dunning reminder sent.",
        ticket_workflow_state="subscription_past_due",
        email_subject="Reminder: Your Klaravex subscription is past due",
        email_body=email_body,
        sms_body=sms_body,
        stripe_meta={
            "stripe_event_id": details["stripe_event_id"],
            "stripe_sub_id":   details["stripe_sub_id"],
        },
    )


async def handle_subscription_unpaid(event: dict[str, Any]) -> dict[str, Any]:
    """
    Handle customer.subscription.unpaid — final notice after multiple failures.

    Creates a P2 ticket (severity=high), sends final-notice email, and escalates
    to Anthony for manual review. Service is NOT suspended automatically.
    """
    details = _extract_subscription_details(event)
    email = await _resolve_email_for_subscription(details)

    if not email:
        log.warning(
            "customer.subscription.unpaid: cannot resolve email for customer=%s event=%s",
            details["stripe_customer_id"],
            details["stripe_event_id"],
        )
        return {"skipped": True, "reason": "no_email"}

    log.info("dunning: subscription.unpaid (final notice) email=%s", email)

    email_body = (
        f"Hi,\n\n"
        f"Your Klaravex subscription has been paused due to non-payment after "
        f"multiple unsuccessful billing attempts.\n\n"
        f"Your active monitoring, AI support, and managed security services are "
        f"currently on hold.\n\n"
        f"To reactivate your subscription and restore full service, please contact us:\n"
        f"  Email: support@klaravex.com\n"
        f"  Billing portal: {PAYMENT_UPDATE_URL}\n\n"
        f"We understand things happen — we're here to help you get back online.\n\n"
        f"Klaravex Support\nsupport@klaravex.com"
    )

    sms_body = (
        "Klaravex: Your subscription has been paused due to non-payment. "
        f"Contact support@klaravex.com or visit {PAYMENT_UPDATE_URL} to reactivate."
    )

    return await _run_dunning_action(
        email=email,
        stripe_customer_id=details["stripe_customer_id"],
        ticket_severity="high",
        ticket_status="escalated",
        ticket_subject="Subscription paused — non-payment (final notice sent)",
        ticket_summary=(
            "Subscription moved to unpaid after multiple payment failures. "
            "Final-notice email sent. Awaiting Anthony review before any suspension."
        ),
        ticket_workflow_state="subscription_paused",
        email_subject="Your Klaravex subscription has been paused",
        email_body=email_body,
        sms_body=sms_body,
        stripe_meta={
            "stripe_event_id": details["stripe_event_id"],
            "stripe_sub_id":   details["stripe_sub_id"],
        },
        escalate=True,
        escalation_summary=(
            f"Subscription unpaid for {email}. Final-notice email delivered. "
            "Review account and decide whether to suspend or offer payment plan."
        ),
    )
