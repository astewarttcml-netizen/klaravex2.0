"""A3 archetype — Foundation tier lifecycle (first B2B managed-service tier).

Handles the four phases of a Foundation subscription:

  1. Onboarding    (customer.subscription.created, sku=foundation*)
  2. Monthly ops   (invoice.paid, sku=foundation*)
  3. Incident      (called from atera_webhook / chat handlers, not Stripe)
  4. Offboarding   (customer.subscription.deleted, sku=foundation*)

Entry points called from stripe_webhook._dispatch_event():
    handle_subscription_created(event)   → Day-0 onboarding
    handle_invoice_paid(event)           → monthly patch/report/QBR cycle
    handle_subscription_deleted(event)   → offboarding sequence

All functions are idempotent. Re-running on a duplicate Stripe event is safe.

SKUs matched (Foundation + co-managed variant + annual):
    foundation, foundation-annual, foundation-comanaged
"""

import logging
import os
from typing import Any, Optional

import stripe

from .db import get_pool
from .email import send_email
from .escalation import escalate
from . import onboarding as onboarding_lib
from . import tickets as tickets_lib

log = logging.getLogger("klaravex.b2b_foundation")

# ── constants ──────────────────────────────────────────────────────────────────

FOUNDATION_SKUS: frozenset[str] = frozenset({
    "foundation",
    "foundation-annual",
    "foundation-comanaged",
})

PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "support@klaravex.com")
ANTHONY_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
CALENDLY_QBR_URL = os.environ.get("CALENDLY_QBR_URL", "")        # set once available

# Day-0 onboarding checklist specific to Foundation tier (A3.2).
# Items marked owner=client must be completed by the client;
# owner=klaravex are provisioned by Klaravex after intake is complete.
_FOUNDATION_ONBOARDING_TASKS: list[dict[str, Any]] = [
    # Client items
    {"key": "msa_sow_signed",       "title": "MSA + SOW signed and countersigned",                       "owner": "client",   "done": False},
    {"key": "primary_contact",      "title": "Designate a single point of contact (SPOC)",               "owner": "client",   "done": False},
    {"key": "employee_list",        "title": "Submit employee list (name, email, role, device)",         "owner": "client",   "done": False},
    {"key": "escalation_contacts",  "title": "Provide primary + after-hours escalation contacts",        "owner": "client",   "done": False},
    {"key": "m365_gdap",            "title": "Approve GDAP request for M365 tenant",                     "owner": "client",   "done": False},
    {"key": "tools_inventory",      "title": "Share existing tools inventory (RMM, EDR, backup, ITSM)", "owner": "client",   "done": False},
    {"key": "baa_signed",           "title": "BAA signed (required if healthcare / HIPAA scope)",        "owner": "client",   "done": False},
    # Klaravex items
    {"key": "atera_tenant",         "title": "Provision Atera tenant + RMM agents on all endpoints",     "owner": "klaravex", "done": False},
    {"key": "monitoring_active",    "title": "Monitoring + alerting confirmed end-to-end",               "owner": "klaravex", "done": False},
    {"key": "baseline_scan",        "title": "Baseline security scan completed",                         "owner": "klaravex", "done": False},
    {"key": "patch_policy",         "title": "Patch management policy applied (Atera)",                  "owner": "klaravex", "done": False},
    {"key": "loki_concierge",       "title": "Klara AI Concierge instance provisioned for client",           "owner": "klaravex", "done": False},
]


# ── helpers ────────────────────────────────────────────────────────────────────

def _is_foundation_sku(sku: Optional[str]) -> bool:
    if not sku:
        return False
    return sku.lower() in FOUNDATION_SKUS


def _sku_from_subscription(sub_obj: dict) -> Optional[str]:
    """Extract SKU from a Stripe subscription object (metadata preferred)."""
    meta = sub_obj.get("metadata") or {}
    if meta.get("sku"):
        return meta["sku"].lower()
    items = (sub_obj.get("items") or {}).get("data") or []
    for item in items:
        price = item.get("price") or {}
        prod = price.get("product")
        if isinstance(prod, dict):
            return (prod.get("name") or prod.get("id") or "").lower()
        elif isinstance(prod, str):
            return prod.lower()
    return None


async def _resolve_customer(obj: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (email, name, stripe_customer_id) from a Stripe object."""
    customer_id = obj.get("customer")
    email = (
        (obj.get("customer_details") or {}).get("email")
        or obj.get("customer_email")
        or obj.get("receipt_email")
    )
    name = (obj.get("customer_details") or {}).get("name")
    if not email and customer_id:
        try:
            cust = stripe.Customer.retrieve(customer_id)
            email = cust.get("email")
            name = cust.get("name")
        except Exception as exc:
            log.warning("customer retrieve failed for %s: %s", customer_id, exc)
    return email, name, customer_id


async def _already_onboarded(email: str) -> bool:
    """True if a Foundation onboarding record exists for this client."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id FROM klaravex_onboarding_checklists
             WHERE email = $1
               AND segment = 'b2b'
            """,
            email.lower(),
        )
    return row is not None


async def _ensure_foundation_checklist(email: str, client_id: Optional[str]) -> dict:
    """Create a Foundation-specific onboarding checklist row (idempotent)."""
    import json
    tasks = _FOUNDATION_ONBOARDING_TASKS
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id::text, status FROM klaravex_onboarding_checklists WHERE email = $1",
            email.lower(),
        )
        if existing:
            return {"checklist_id": existing["id"], "created": False}

        if client_id is None:
            client_id = await conn.fetchval(
                "SELECT id FROM klaravex_clients WHERE email = $1",
                email.lower(),
            )

        checklist_id = await conn.fetchval(
            """
            INSERT INTO klaravex_onboarding_checklists
                (client_id, email, segment, tasks, total_count)
            VALUES ($1, $2, 'b2b', $3::jsonb, $4)
            RETURNING id::text
            """,
            client_id,
            email.lower(),
            json.dumps(tasks),
            len(tasks),
        )
    log.info("Foundation onboarding checklist created: %s (%d tasks)", email, len(tasks))
    return {"checklist_id": checklist_id, "created": True, "tasks_total": len(tasks)}


def _kickoff_cta() -> str:
    return CALENDLY_QBR_URL or f"{PORTAL_BASE_URL.rstrip('/')}/portal/onboarding"


# ── Day-0 onboarding email ─────────────────────────────────────────────────────

_ONBOARDING_EMAIL_SUBJECT = "Welcome to Klaravex Foundation — next steps to get started"

def _onboarding_email_body(name: Optional[str], company: Optional[str], checklist_url: str, kickoff_url: str) -> str:
    greeting = f"Hi {name}," if name else "Hi,"
    org_line = f" for {company}" if company else ""
    return (
        f"{greeting}\n\n"
        f"Thank you for activating Klaravex Foundation{org_line}.\n\n"
        f"To get your environment fully under management, we need a few things from you. "
        f"The checklist below guides you through each step — it usually takes less than 15 minutes:\n\n"
        f"  {checklist_url}\n\n"
        f"Once we receive your checklist items, we will:\n"
        f"  • Deploy Atera RMM agents across your endpoints\n"
        f"  • Complete a baseline security scan\n"
        f"  • Enable patch management and real-time monitoring\n"
        f"  • Set up your Klaravex AI support coordinator\n\n"
        f"To schedule your kickoff call with a senior engineer:\n"
        f"  {kickoff_url}\n\n"
        f"If you have urgent questions before your kickoff call, reply to this email or "
        f"start a chat at klaravex.com — our AI coordinator responds immediately.\n\n"
        f"— The Klaravex Team\n"
        f"support@klaravex.com\n"
    )


# ── Monthly ops email ──────────────────────────────────────────────────────────

def _monthly_ops_email_subject(company: Optional[str]) -> str:
    from datetime import datetime
    month = datetime.utcnow().strftime("%B %Y")
    org = f" — {company}" if company else ""
    return f"Klaravex Foundation — Monthly Operations Report{org} ({month})"


def _monthly_ops_email_body(name: Optional[str], company: Optional[str], portal_url: str, qbr_url: str) -> str:
    greeting = f"Hi {name}," if name else "Hi,"
    org_line = f" for {company}" if company else ""
    return (
        f"{greeting}\n\n"
        f"Your monthly Klaravex Foundation operations report{org_line} is ready in your portal:\n\n"
        f"  {portal_url}\n\n"
        f"The report covers the past 30 days:\n"
        f"  • Patch compliance status across all managed endpoints\n"
        f"  • Tickets opened, resolved, and mean time to resolution\n"
        f"  • Monitoring alerts handled\n"
        f"  • Vulnerability findings (if any)\n\n"
        f"Ready to review with a senior engineer? Schedule your next QBR:\n"
        f"  {qbr_url}\n\n"
        f"Questions? Reply here or start a chat at klaravex.com.\n\n"
        f"— The Klaravex Team\n"
        f"support@klaravex.com\n"
    )


# ── Offboarding email ──────────────────────────────────────────────────────────

def _offboarding_email_body(name: Optional[str], company: Optional[str]) -> str:
    greeting = f"Hi {name}," if name else "Hi,"
    org_line = f" for {company}" if company else ""
    return (
        f"{greeting}\n\n"
        f"We have received the cancellation of your Klaravex Foundation subscription{org_line}. "
        f"Access continues through the end of your current billing period.\n\n"
        f"Offboarding steps we will complete on your behalf:\n"
        f"  1. Export your ticket history and operational reports to a secure ZIP — "
        f"link emailed within 48 hours\n"
        f"  2. Remove Atera RMM agents from all enrolled endpoints\n"
        f"  3. Revoke GDAP / M365 delegated access\n"
        f"  4. Issue your final invoice summary\n\n"
        f"If this cancellation was made in error or you would like to discuss options, "
        f"reply to this email within 48 hours and a senior engineer will contact you.\n\n"
        f"— The Klaravex Team\n"
        f"support@klaravex.com\n"
    )


# ── Anthony alert helper ───────────────────────────────────────────────────────

async def _alert_anthony(subject: str, body: str) -> None:
    """Best-effort email + Telegram. Never raises."""
    try:
        await send_email(to=ANTHONY_EMAIL, subject=subject, body=body)
    except Exception as exc:
        log.warning("Foundation alert email failed: %s", exc)

    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    telegram_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if telegram_token and telegram_chat:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"https://api.telegram.org/bot{telegram_token}/sendMessage",
                    json={"chat_id": telegram_chat, "text": f"{subject}\n\n{body}"},
                )
        except Exception as exc:
            log.warning("Foundation Telegram alert failed: %s", exc)


# ── Public lifecycle handlers ──────────────────────────────────────────────────

async def handle_subscription_created(event: dict[str, Any]) -> dict[str, Any]:
    """Day-0: kick off Foundation onboarding when a new subscription is created.

    Called from stripe_webhook._dispatch_event() for
    customer.subscription.created events.

    Returns a result dict for logging. Never raises — all errors are caught
    and included in the returned result.
    """
    obj = event["data"]["object"]
    sku = _sku_from_subscription(obj)
    if not _is_foundation_sku(sku):
        return {"action": "skipped", "reason": f"sku {sku!r} not Foundation"}

    email, name, stripe_customer_id = await _resolve_customer(obj)
    if not email:
        log.warning("Foundation subscription.created: no customer email found")
        return {"action": "error", "reason": "no_email"}

    company: Optional[str] = (obj.get("metadata") or {}).get("company")

    # 1. Upsert client record.
    client_id: Optional[str] = None
    try:
        client_id = await tickets_lib.get_or_create_client(
            email,
            segment="b2b",
            name=name,
            stripe_customer_id=stripe_customer_id,
            company=company,
            metadata={"tier": sku, "source": "stripe_foundation_created"},
        )
    except Exception as exc:
        log.warning("Foundation client upsert failed: %s", exc)

    # 2. Open an onboarding ticket.
    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=email,
            subject=f"Foundation onboarding — {company or email}",
            severity="standard",
            status="open",
            source="stripe",
            archetype="A3",
            sku=sku,
            summary=f"New Foundation subscription. Onboarding checklist sent to {email}.",
            segment_hint="b2b",
            metadata={"company": company, "stripe_sub_id": obj.get("id")},
        )
    except Exception as exc:
        log.warning("Foundation ticket creation failed: %s", exc)

    # 3. Create the Foundation onboarding checklist (idempotent).
    checklist: dict = {}
    try:
        checklist = await _ensure_foundation_checklist(email, client_id)
    except Exception as exc:
        log.warning("Foundation checklist creation failed: %s", exc)

    checklist_url = f"{PORTAL_BASE_URL.rstrip('/')}/portal/onboarding"
    kickoff_url = _kickoff_cta()

    # 4. Send onboarding email to client.
    try:
        await send_email(
            to=email,
            subject=_ONBOARDING_EMAIL_SUBJECT,
            body=_onboarding_email_body(name, company, checklist_url, kickoff_url),
        )
    except Exception as exc:
        log.warning("Foundation onboarding email failed for %s: %s", email, exc)

    # 5. Notify Anthony — new managed client on board.
    alert_subject = f"[Klaravex Foundation] New client — {company or email} ({sku})"
    alert_body = (
        f"A new Foundation subscription has been activated.\n\n"
        f"Company:     {company or '(not provided)'}\n"
        f"Contact:     {name or '(not provided)'}\n"
        f"Email:       {email}\n"
        f"SKU:         {sku}\n"
        f"Sub ID:      {obj.get('id') or '—'}\n"
        f"Client ID:   {client_id or '—'}\n"
        f"Ticket ID:   {ticket_id or '—'}\n\n"
        f"Checklist:   {checklist_url}\n"
        f"Kickoff URL: {kickoff_url}\n\n"
        f"Onboarding checklist sent to client. "
        f"Await GDAP approval + employee list before provisioning Atera.\n"
    )
    await _alert_anthony(alert_subject, alert_body)

    return {
        "action": "foundation_onboarding_initiated",
        "sku": sku,
        "email": email,
        "client_id": client_id,
        "ticket_id": ticket_id,
        "checklist_created": checklist.get("created", False),
    }


async def handle_invoice_paid(event: dict[str, Any]) -> dict[str, Any]:
    """Monthly: send monthly ops report and QBR reminder on each successful invoice.

    Called from stripe_webhook._dispatch_event() for invoice.paid events.
    """
    obj = event["data"]["object"]

    # invoice.paid gives us the subscription via obj["subscription"]; retrieve it.
    sub_id = obj.get("subscription")
    sku: Optional[str] = None
    if sub_id:
        try:
            sub = stripe.Subscription.retrieve(sub_id)
            sub_dict = sub.to_dict() if hasattr(sub, "to_dict") else dict(sub)
            sku = _sku_from_subscription(sub_dict)
        except Exception as exc:
            log.warning("Foundation invoice.paid: sub retrieve failed for %s: %s", sub_id, exc)

    if not _is_foundation_sku(sku):
        # Fallback: check invoice line-item metadata
        lines = (obj.get("lines") or {}).get("data") or []
        for line in lines:
            line_sku = ((line.get("metadata") or {}).get("sku") or "").lower()
            if _is_foundation_sku(line_sku):
                sku = line_sku
                break

    if not _is_foundation_sku(sku):
        return {"action": "skipped", "reason": f"sku {sku!r} not Foundation"}

    email, name, stripe_customer_id = await _resolve_customer(obj)
    if not email:
        return {"action": "error", "reason": "no_email"}

    company: Optional[str] = None
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT company FROM klaravex_clients WHERE email = $1",
                email.lower(),
            )
        if row:
            company = row["company"]
    except Exception as exc:
        log.warning("Foundation company lookup failed: %s", exc)

    portal_url = f"{PORTAL_BASE_URL.rstrip('/')}/portal/reports/monthly"
    qbr_url = CALENDLY_QBR_URL or f"{PORTAL_BASE_URL.rstrip('/')}/portal/qbr"

    # Send monthly report email to client.
    try:
        await send_email(
            to=email,
            subject=_monthly_ops_email_subject(company),
            body=_monthly_ops_email_body(name, company, portal_url, qbr_url),
        )
    except Exception as exc:
        log.warning("Foundation monthly report email failed for %s: %s", email, exc)
        return {"action": "error", "reason": str(exc), "sku": sku}

    # Open a low-severity ops ticket so the monthly cycle is traceable.
    ticket_id: Optional[str] = None
    try:
        from datetime import datetime
        month_label = datetime.utcnow().strftime("%Y-%m")
        ticket_id = await tickets_lib.create_ticket(
            client_email=email,
            subject=f"Foundation monthly ops cycle — {month_label}",
            severity="low",
            status="resolved",
            source="stripe",
            archetype="A3",
            sku=sku,
            summary=f"Monthly ops report sent to {email}. QBR link included.",
            segment_hint="b2b",
            metadata={"invoice_id": obj.get("id"), "month": month_label},
        )
    except Exception as exc:
        log.warning("Foundation monthly ticket creation failed: %s", exc)

    log.info("Foundation monthly ops report sent: email=%s sku=%s", email, sku)
    return {
        "action": "foundation_monthly_report_sent",
        "sku": sku,
        "email": email,
        "ticket_id": ticket_id,
    }


async def handle_subscription_deleted(event: dict[str, Any]) -> dict[str, Any]:
    """Offboarding: begin offboarding sequence when a Foundation subscription is cancelled.

    Called from stripe_webhook._dispatch_event() for
    customer.subscription.deleted events.
    """
    obj = event["data"]["object"]
    sku = _sku_from_subscription(obj)
    if not _is_foundation_sku(sku):
        return {"action": "skipped", "reason": f"sku {sku!r} not Foundation"}

    email, name, stripe_customer_id = await _resolve_customer(obj)
    if not email:
        return {"action": "error", "reason": "no_email"}

    company: Optional[str] = (obj.get("metadata") or {}).get("company")

    # 1. Open a high-severity offboarding ticket.
    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=email,
            subject=f"Foundation offboarding — {company or email}",
            severity="high",
            status="open",
            source="stripe",
            archetype="A3",
            sku=sku,
            summary=(
                f"Foundation subscription cancelled for {email}. "
                "Offboarding: data export, agent removal, GDAP revocation, final invoice."
            ),
            segment_hint="b2b",
            metadata={"company": company, "stripe_sub_id": obj.get("id")},
        )
    except Exception as exc:
        log.warning("Foundation offboarding ticket failed: %s", exc)

    # 2. Escalate to Anthony with full context (A3.5 — cancellation → Anthony retention call).
    if ticket_id:
        try:
            await escalate(
                ticket_id=ticket_id,
                client_email=email,
                severity="high",
                summary=(
                    f"Foundation subscription cancelled: {company or email} ({sku}). "
                    "Retention call within 24 hours required."
                ),
                attempted="Automated offboarding sequence initiated",
                recommended=(
                    "Call client within 24 hours. Review ticket history for churn signals. "
                    "Offer pause or discount if appropriate before full offboarding proceeds."
                ),
            )
        except Exception as exc:
            log.warning("Foundation offboarding escalation failed: %s", exc)

    # 3. Send offboarding email to client.
    try:
        await send_email(
            to=email,
            subject=f"Klaravex Foundation — cancellation confirmed, offboarding next steps",
            body=_offboarding_email_body(name, company),
        )
    except Exception as exc:
        log.warning("Foundation offboarding email failed for %s: %s", email, exc)

    # 4. Alert Anthony directly (in addition to the escalation row).
    alert_subject = f"[Klaravex Foundation] Cancellation — {company or email} ({sku})"
    alert_body = (
        f"A Foundation subscription has been cancelled.\n\n"
        f"Company:   {company or '(not provided)'}\n"
        f"Contact:   {name or '(not provided)'}\n"
        f"Email:     {email}\n"
        f"SKU:       {sku}\n"
        f"Sub ID:    {obj.get('id') or '—'}\n"
        f"Ticket ID: {ticket_id or '—'}\n\n"
        f"Action required: retention call within 24 hours.\n"
        f"Offboarding checklist (data export, agent removal, GDAP revoke, final invoice) "
        f"queued. Approve in portal to proceed.\n"
    )
    await _alert_anthony(alert_subject, alert_body)

    log.info("Foundation offboarding initiated: email=%s sku=%s ticket=%s", email, sku, ticket_id)
    return {
        "action": "foundation_offboarding_initiated",
        "sku": sku,
        "email": email,
        "ticket_id": ticket_id,
    }


# ── Incident triage entry point (called from atera_webhook / chat handlers) ───

async def handle_incident(
    *,
    client_email: str,
    summary: str,
    severity: str = "standard",
    source: str = "atera",
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Open a Foundation incident ticket and escalate to Anthony if P1/P2.

    Called by atera_webhook.py (RMM alert) or chat handlers when the client
    is on the Foundation tier.  Not triggered by Stripe.

    severity mapping (A3.5):
      emergency / high → P1/P2 → escalate to Anthony immediately
      standard / low   → P3/P4 → Klara AI resolves; Anthony not paged
    """
    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=client_email,
            subject=f"Foundation incident — {summary[:80]}",
            severity=severity,
            status="open",
            source=source,
            archetype="A3",
            sku="foundation",
            summary=summary,
            segment_hint="b2b",
            metadata=metadata or {},
        )
    except Exception as exc:
        log.error("Foundation incident ticket creation failed: %s", exc)
        return {"action": "error", "reason": str(exc)}

    result: dict[str, Any] = {
        "action": "foundation_incident_opened",
        "ticket_id": ticket_id,
        "severity": severity,
        "escalated": False,
    }

    # P1/P2 — page Anthony immediately (A3.5).
    if severity in ("emergency", "high") and ticket_id:
        try:
            await escalate(
                ticket_id=ticket_id,
                client_email=client_email,
                severity=severity,
                summary=f"{severity.upper()} Foundation incident: {summary[:200]}",
                attempted="Klara AI triage initiated",
                recommended=(
                    "P1: respond within 1 hour. P2: within 2 hours. "
                    "Do not modify production systems before review."
                ),
            )
            result["escalated"] = True
        except Exception as exc:
            log.warning("Foundation incident escalation failed: %s", exc)

    log.info(
        "Foundation incident: ticket=%s severity=%s escalated=%s",
        ticket_id, severity, result["escalated"],
    )
    return result
