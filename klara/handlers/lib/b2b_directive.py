"""A3 archetype — Directive tier lifecycle (premium B2B managed service).

Directive is the top-tier plan. It extends Assurance with:
  • Full vCISO advisory (Anthony-delivered, Klara AI preps board reports)
  • Compliance program management (Klara AI tracks controls for SOC 2 / HIPAA / ISO 27001)
  • Risk register updates (Klara AI maintains, Anthony reviews)
  • Tabletop exercise facilitation prep (Klara AI drafts, Anthony runs)
  • Board-level security reporting
  • Annual compliance roadmap with milestone tracking

Handles the four phases of a Directive subscription:

  1. Onboarding    (customer.subscription.created, sku=directive*)
  2. Monthly ops   (invoice.paid, sku=directive*)
  3. Incident      (called from atera_webhook / chat handlers, not Stripe)
  4. Offboarding   (customer.subscription.deleted, sku=directive*)

Entry points called from stripe_webhook._dispatch_event():
    handle_subscription_created(event)   → Day-0 onboarding
    handle_invoice_paid(event)           → monthly cycle
    handle_subscription_deleted(event)   → offboarding sequence

All functions are idempotent. Re-running on a duplicate Stripe event is safe.

SKUs matched (Directive + co-managed variant + annual):
    directive, directive-annual, directive-comanaged
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

log = logging.getLogger("klaravex.b2b_directive")

# ── constants ──────────────────────────────────────────────────────────────────

DIRECTIVE_SKUS: frozenset[str] = frozenset({
    "directive",
    "directive-annual",
    "directive-comanaged",
})

PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "support@klaravex.com")
ANTHONY_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
CALENDLY_QBR_URL = os.environ.get("CALENDLY_QBR_URL", "")
CALENDLY_VCISO_URL = os.environ.get("CALENDLY_VCISO_URL", "")    # monthly vCISO advisory
CALENDLY_BOARD_URL = os.environ.get("CALENDLY_BOARD_URL", "")    # quarterly board briefing

# Day-0 onboarding checklist for Directive tier.
# Extends Assurance with full vCISO, compliance program, risk register, and tabletop items.
_DIRECTIVE_ONBOARDING_TASKS: list[dict[str, Any]] = [
    # ── Foundation-baseline client items ──────────────────────────────────────
    {"key": "msa_sow_signed",            "title": "MSA + SOW signed and countersigned",                                   "owner": "client",   "done": False},
    {"key": "primary_contact",           "title": "Designate a single point of contact (SPOC)",                          "owner": "client",   "done": False},
    {"key": "employee_list",             "title": "Submit employee list (name, email, role, device)",                    "owner": "client",   "done": False},
    {"key": "escalation_contacts",       "title": "Provide primary + after-hours escalation contacts",                   "owner": "client",   "done": False},
    {"key": "m365_gdap",                 "title": "Approve GDAP request for M365 tenant",                                "owner": "client",   "done": False},
    {"key": "tools_inventory",           "title": "Share existing tools inventory (RMM, EDR, backup, ITSM)",             "owner": "client",   "done": False},
    {"key": "baa_signed",                "title": "BAA signed (required if healthcare / HIPAA scope)",                   "owner": "client",   "done": False},
    # ── Assurance-inherited client items ──────────────────────────────────────
    {"key": "huntress_consent",          "title": "Approve Huntress MDR agent deployment on all endpoints",              "owner": "client",   "done": False},
    {"key": "sat_employee_scope",        "title": "Confirm SAT training scope — all staff or named subset",              "owner": "client",   "done": False},
    {"key": "email_security_access",     "title": "Grant access for M365 Defender / GWS DLP configuration",             "owner": "client",   "done": False},
    {"key": "security_contact",          "title": "Designate security point of contact for advisory calls",              "owner": "client",   "done": False},
    # ── Directive-specific client items ───────────────────────────────────────
    {"key": "compliance_framework",      "title": "Confirm target compliance framework(s): SOC 2 / HIPAA / ISO 27001",  "owner": "client",   "done": False},
    {"key": "board_contact",             "title": "Identify board or executive sponsor for quarterly security briefings","owner": "client",   "done": False},
    {"key": "existing_risk_register",    "title": "Share any existing risk register or prior gap assessment",            "owner": "client",   "done": False},
    {"key": "current_controls_inventory","title": "Provide current security controls inventory (policies, tools, certs)","owner": "client",   "done": False},
    {"key": "tabletop_schedule",         "title": "Agree on annual tabletop exercise dates (at least 1 per year)",       "owner": "client",   "done": False},
    {"key": "vciso_nda",                 "title": "Executive NDA / confidentiality addendum signed (for board briefings)","owner": "client",  "done": False},
    # ── Klaravex provisioning items ───────────────────────────────────────────
    {"key": "atera_tenant",              "title": "Provision Atera tenant + RMM agents on all endpoints",                "owner": "klaravex", "done": False},
    {"key": "huntress_org",              "title": "Provision Huntress organization + MDR agents on all endpoints",       "owner": "klaravex", "done": False},
    {"key": "monitoring_active",         "title": "Monitoring + alerting confirmed end-to-end",                          "owner": "klaravex", "done": False},
    {"key": "baseline_scan",             "title": "Baseline security scan completed",                                    "owner": "klaravex", "done": False},
    {"key": "patch_policy",              "title": "Patch management policy applied (Atera)",                              "owner": "klaravex", "done": False},
    {"key": "email_security_config",     "title": "M365 Defender / GWS DLP baseline configuration applied",              "owner": "klaravex", "done": False},
    {"key": "sat_campaign_setup",        "title": "Initial SAT campaign created and first training assigned",             "owner": "klaravex", "done": False},
    {"key": "loki_concierge",            "title": "Klara AI Concierge instance provisioned for client",                       "owner": "klaravex", "done": False},
    {"key": "risk_register_init",        "title": "Initial risk register created from baseline scan + controls inventory","owner": "klaravex", "done": False},
    {"key": "compliance_roadmap_draft",  "title": "Draft compliance roadmap delivered for client review",                 "owner": "klaravex", "done": False},
    {"key": "vciso_kickoff_scheduled",   "title": "vCISO kickoff call scheduled with Anthony",                            "owner": "klaravex", "done": False},
    {"key": "board_briefing_template",   "title": "Board reporting template prepared and shared with executive sponsor",  "owner": "klaravex", "done": False},
]


# ── helpers ────────────────────────────────────────────────────────────────────

def _is_directive_sku(sku: Optional[str]) -> bool:
    if not sku:
        return False
    return sku.lower() in DIRECTIVE_SKUS


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


async def _ensure_directive_checklist(email: str, client_id: Optional[str]) -> dict:
    """Create a Directive-specific onboarding checklist row (idempotent)."""
    import json
    tasks = _DIRECTIVE_ONBOARDING_TASKS
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
    log.info("Directive onboarding checklist created: %s (%d tasks)", email, len(tasks))
    return {"checklist_id": checklist_id, "created": True, "tasks_total": len(tasks)}


def _kickoff_cta() -> str:
    return CALENDLY_QBR_URL or f"{PORTAL_BASE_URL.rstrip('/')}/portal/onboarding"


def _vciso_cta() -> str:
    return CALENDLY_VCISO_URL or f"{PORTAL_BASE_URL.rstrip('/')}/portal/advisory"


def _board_cta() -> str:
    return CALENDLY_BOARD_URL or f"{PORTAL_BASE_URL.rstrip('/')}/portal/board-briefing"


# ── Day-0 onboarding email ─────────────────────────────────────────────────────

_ONBOARDING_EMAIL_SUBJECT = "Welcome to Klaravex Directive — next steps to get started"


def _onboarding_email_body(
    name: Optional[str], company: Optional[str], checklist_url: str, kickoff_url: str
) -> str:
    greeting = f"Hi {name}," if name else "Hi,"
    org_line = f" for {company}" if company else ""
    return (
        f"{greeting}\n\n"
        f"Thank you for activating Klaravex Directive{org_line} — our most comprehensive "
        f"managed security and compliance tier.\n\n"
        f"Your team will have managed detection and response, a dedicated vCISO, an active "
        f"compliance program, and board-level security reporting. To get started we need a "
        f"few items from you — the checklist below typically takes 30–45 minutes:\n\n"
        f"  {checklist_url}\n\n"
        f"Once we receive your items, we will:\n"
        f"  • Deploy Atera RMM and Huntress MDR agents across all endpoints\n"
        f"  • Configure M365 Defender / GWS DLP baseline protection\n"
        f"  • Launch your security awareness training program\n"
        f"  • Build your initial risk register from the baseline scan\n"
        f"  • Draft your compliance roadmap against your target framework(s)\n"
        f"  • Prepare your board reporting template\n"
        f"  • Schedule your vCISO kickoff call with Anthony\n\n"
        f"To schedule your kickoff call:\n"
        f"  {kickoff_url}\n\n"
        f"If you have urgent questions before the kickoff, reply to this email or "
        f"start a chat at klaravex.com — our AI coordinator responds immediately.\n\n"
        f"— The Klaravex Team\n"
        f"support@klaravex.com\n"
    )


# ── Monthly ops email ──────────────────────────────────────────────────────────

def _monthly_ops_email_subject(company: Optional[str]) -> str:
    from datetime import datetime
    month = datetime.utcnow().strftime("%B %Y")
    org = f" — {company}" if company else ""
    return f"Klaravex Directive — Monthly Operations Report{org} ({month})"


def _monthly_ops_email_body(
    name: Optional[str],
    company: Optional[str],
    portal_url: str,
    qbr_url: str,
    vciso_url: str,
    board_url: str,
) -> str:
    greeting = f"Hi {name}," if name else "Hi,"
    org_line = f" for {company}" if company else ""
    return (
        f"{greeting}\n\n"
        f"Your monthly Klaravex Directive operations report{org_line} is ready:\n\n"
        f"  {portal_url}\n\n"
        f"This month's report covers:\n"
        f"  • Patch compliance status across all managed endpoints\n"
        f"  • Huntress MDR alert summary (detections, investigations, resolutions)\n"
        f"  • Security awareness training completion rates and phishing simulation results\n"
        f"  • Email security filter activity and threat detections\n"
        f"  • Compliance program status — open controls, closed controls, outstanding items\n"
        f"  • Risk register updates (new risks added, mitigated, accepted)\n"
        f"  • Tickets opened, resolved, and mean time to resolution\n\n"
        f"Book your monthly vCISO advisory call:\n"
        f"  {vciso_url}\n\n"
        f"Schedule your quarterly board briefing (if this is a quarter-end month):\n"
        f"  {board_url}\n\n"
        f"Ready to review with a senior engineer? Schedule your QBR:\n"
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
        f"We have received the cancellation of your Klaravex Directive subscription{org_line}. "
        f"Access continues through the end of your current billing period.\n\n"
        f"Offboarding steps we will complete on your behalf:\n"
        f"  1. Export your ticket history, MDR incident reports, SAT completion records, "
        f"compliance program artifacts, risk register, and board reports to a secure ZIP — "
        f"link emailed within 48 hours\n"
        f"  2. Remove Atera RMM and Huntress MDR agents from all enrolled endpoints\n"
        f"  3. Revert M365 Defender / GWS DLP to pre-engagement baseline\n"
        f"  4. Revoke GDAP / M365 delegated access\n"
        f"  5. Transfer compliance program ownership documents to your designated contact\n"
        f"  6. Issue your final invoice summary\n\n"
        f"If this cancellation was made in error or you would like to discuss options "
        f"(including downgrade to Assurance), reply to this email within 48 hours and "
        f"Anthony will contact you directly.\n\n"
        f"— The Klaravex Team\n"
        f"support@klaravex.com\n"
    )


# ── Anthony alert helper ───────────────────────────────────────────────────────

async def _alert_anthony(subject: str, body: str) -> None:
    """Best-effort email + Telegram. Never raises."""
    try:
        await send_email(to=ANTHONY_EMAIL, subject=subject, body=body)
    except Exception as exc:
        log.warning("Directive alert email failed: %s", exc)

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
            log.warning("Directive Telegram alert failed: %s", exc)


# ── Public lifecycle handlers ──────────────────────────────────────────────────

async def handle_subscription_created(event: dict[str, Any]) -> dict[str, Any]:
    """Day-0: kick off Directive onboarding when a new subscription is created.

    Called from stripe_webhook._dispatch_event() for
    customer.subscription.created events.

    Returns a result dict for logging. Never raises — all errors are caught
    and included in the returned result.
    """
    obj = event["data"]["object"]
    sku = _sku_from_subscription(obj)
    if not _is_directive_sku(sku):
        return {"action": "skipped", "reason": f"sku {sku!r} not Directive"}

    email, name, stripe_customer_id = await _resolve_customer(obj)
    if not email:
        log.warning("Directive subscription.created: no customer email found")
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
            metadata={"tier": sku, "source": "stripe_directive_created"},
        )
    except Exception as exc:
        log.warning("Directive client upsert failed: %s", exc)

    # 2. Open an onboarding ticket.
    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=email,
            subject=f"Directive onboarding — {company or email}",
            severity="standard",
            status="open",
            source="stripe",
            archetype="A3",
            sku=sku,
            summary=f"New Directive subscription. Onboarding checklist sent to {email}.",
            segment_hint="b2b",
            metadata={"company": company, "stripe_sub_id": obj.get("id")},
        )
    except Exception as exc:
        log.warning("Directive ticket creation failed: %s", exc)

    # 3. Create the Directive onboarding checklist (idempotent).
    checklist: dict = {}
    try:
        checklist = await _ensure_directive_checklist(email, client_id)
    except Exception as exc:
        log.warning("Directive checklist creation failed: %s", exc)

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
        log.warning("Directive onboarding email failed for %s: %s", email, exc)

    # 5. Notify Anthony — highest-tier client, treat this as a P1 priority onboarding.
    alert_subject = f"[Klaravex Directive] NEW CLIENT — {company or email} ({sku})"
    alert_body = (
        f"A new Directive subscription has been activated — top-tier client.\n\n"
        f"Company:       {company or '(not provided)'}\n"
        f"Contact:       {name or '(not provided)'}\n"
        f"Email:         {email}\n"
        f"SKU:           {sku}\n"
        f"Sub ID:        {obj.get('id') or '—'}\n"
        f"Client ID:     {client_id or '—'}\n"
        f"Ticket ID:     {ticket_id or '—'}\n\n"
        f"Checklist:     {checklist_url}\n"
        f"Kickoff URL:   {kickoff_url}\n"
        f"vCISO:         {_vciso_cta()}\n"
        f"Board URL:     {_board_cta()}\n\n"
        f"ACTION: Schedule vCISO kickoff call within 48 hours. "
        f"Await compliance framework confirmation and board contact before drafting "
        f"risk register and compliance roadmap.\n"
    )
    await _alert_anthony(alert_subject, alert_body)

    return {
        "action": "directive_onboarding_initiated",
        "sku": sku,
        "email": email,
        "client_id": client_id,
        "ticket_id": ticket_id,
        "checklist_created": checklist.get("created", False),
    }


async def handle_invoice_paid(event: dict[str, Any]) -> dict[str, Any]:
    """Monthly: send monthly ops report on each successful invoice.

    Called from stripe_webhook._dispatch_event() for invoice.paid events.
    """
    obj = event["data"]["object"]

    sub_id = obj.get("subscription")
    sku: Optional[str] = None
    if sub_id:
        try:
            sub = stripe.Subscription.retrieve(sub_id)
            sub_dict = sub.to_dict() if hasattr(sub, "to_dict") else dict(sub)
            sku = _sku_from_subscription(sub_dict)
        except Exception as exc:
            log.warning("Directive invoice.paid: sub retrieve failed for %s: %s", sub_id, exc)

    if not _is_directive_sku(sku):
        lines = (obj.get("lines") or {}).get("data") or []
        for line in lines:
            line_sku = ((line.get("metadata") or {}).get("sku") or "").lower()
            if _is_directive_sku(line_sku):
                sku = line_sku
                break

    if not _is_directive_sku(sku):
        return {"action": "skipped", "reason": f"sku {sku!r} not Directive"}

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
        log.warning("Directive company lookup failed: %s", exc)

    portal_url = f"{PORTAL_BASE_URL.rstrip('/')}/portal/reports/monthly"
    qbr_url = CALENDLY_QBR_URL or f"{PORTAL_BASE_URL.rstrip('/')}/portal/qbr"
    vciso_url = _vciso_cta()
    board_url = _board_cta()

    try:
        await send_email(
            to=email,
            subject=_monthly_ops_email_subject(company),
            body=_monthly_ops_email_body(name, company, portal_url, qbr_url, vciso_url, board_url),
        )
    except Exception as exc:
        log.warning("Directive monthly report email failed for %s: %s", email, exc)
        return {"action": "error", "reason": str(exc), "sku": sku}

    ticket_id: Optional[str] = None
    try:
        from datetime import datetime
        month_label = datetime.utcnow().strftime("%Y-%m")
        ticket_id = await tickets_lib.create_ticket(
            client_email=email,
            subject=f"Directive monthly ops cycle — {month_label}",
            severity="low",
            status="resolved",
            source="stripe",
            archetype="A3",
            sku=sku,
            summary=(
                f"Monthly ops report + MDR summary + SAT stats + compliance status + "
                f"risk register update sent to {email}. vCISO and board briefing links included."
            ),
            segment_hint="b2b",
            metadata={"invoice_id": obj.get("id"), "month": month_label},
        )
    except Exception as exc:
        log.warning("Directive monthly ticket creation failed: %s", exc)

    log.info("Directive monthly ops report sent: email=%s sku=%s", email, sku)
    return {
        "action": "directive_monthly_report_sent",
        "sku": sku,
        "email": email,
        "ticket_id": ticket_id,
    }


async def handle_subscription_deleted(event: dict[str, Any]) -> dict[str, Any]:
    """Offboarding: begin offboarding sequence when a Directive subscription is cancelled.

    Called from stripe_webhook._dispatch_event() for
    customer.subscription.deleted events.
    """
    obj = event["data"]["object"]
    sku = _sku_from_subscription(obj)
    if not _is_directive_sku(sku):
        return {"action": "skipped", "reason": f"sku {sku!r} not Directive"}

    email, name, stripe_customer_id = await _resolve_customer(obj)
    if not email:
        return {"action": "error", "reason": "no_email"}

    company: Optional[str] = (obj.get("metadata") or {}).get("company")

    # 1. Open a high-severity offboarding ticket.
    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=email,
            subject=f"Directive offboarding — {company or email}",
            severity="high",
            status="open",
            source="stripe",
            archetype="A3",
            sku=sku,
            summary=(
                f"Directive subscription cancelled for {email}. "
                "Offboarding: data export, compliance artifacts transfer, MDR/RMM agent removal, "
                "email security revert, GDAP revocation, final invoice."
            ),
            segment_hint="b2b",
            metadata={"company": company, "stripe_sub_id": obj.get("id")},
        )
    except Exception as exc:
        log.warning("Directive offboarding ticket failed: %s", exc)

    # 2. Escalate to Anthony — highest-tier churn, retention call required immediately (A3.5).
    if ticket_id:
        try:
            await escalate(
                ticket_id=ticket_id,
                client_email=email,
                severity="high",
                summary=(
                    f"DIRECTIVE subscription cancelled: {company or email} ({sku}). "
                    "Top-tier churn — Anthony retention call within 24 hours required."
                ),
                attempted="Automated offboarding sequence initiated",
                recommended=(
                    "Call client within 24 hours. This is top-tier churn. "
                    "Review compliance program progress, MDR incident history, and board "
                    "reporting cadence for churn signals. "
                    "Offer Directive → Assurance downgrade, 60-day pause, or adjusted scope "
                    "before initiating full offboarding."
                ),
            )
        except Exception as exc:
            log.warning("Directive offboarding escalation failed: %s", exc)

    # 3. Send offboarding email to client.
    try:
        await send_email(
            to=email,
            subject="Klaravex Directive — cancellation confirmed, offboarding next steps",
            body=_offboarding_email_body(name, company),
        )
    except Exception as exc:
        log.warning("Directive offboarding email failed for %s: %s", email, exc)

    # 4. Alert Anthony directly — flag as high priority.
    alert_subject = f"[Klaravex Directive] CANCELLATION — {company or email} ({sku})"
    alert_body = (
        f"A DIRECTIVE subscription has been cancelled — top-tier churn.\n\n"
        f"Company:   {company or '(not provided)'}\n"
        f"Contact:   {name or '(not provided)'}\n"
        f"Email:     {email}\n"
        f"SKU:       {sku}\n"
        f"Sub ID:    {obj.get('id') or '—'}\n"
        f"Ticket ID: {ticket_id or '—'}\n\n"
        f"ACTION REQUIRED: Retention call within 24 hours. "
        f"Consider offering downgrade to Assurance or a 60-day pause.\n\n"
        f"Offboarding checklist (data export, compliance artifacts, MDR/RMM removal, "
        f"email security revert, GDAP revoke, final invoice) queued. "
        f"Approve in portal to proceed.\n"
    )
    await _alert_anthony(alert_subject, alert_body)

    log.info("Directive offboarding initiated: email=%s sku=%s ticket=%s", email, sku, ticket_id)
    return {
        "action": "directive_offboarding_initiated",
        "sku": sku,
        "email": email,
        "ticket_id": ticket_id,
    }


# ── Incident triage entry point (called from atera_webhook / Huntress / chat) ─

async def handle_incident(
    *,
    client_email: str,
    summary: str,
    severity: str = "standard",
    source: str = "huntress",
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Open a Directive incident ticket and escalate to Anthony if P1/P2.

    Called by atera_webhook.py (RMM alert), Huntress webhook, or chat handlers
    when the client is on the Directive tier. Not triggered by Stripe.

    Directive clients receive the most aggressive incident response:
    - Any Huntress active-threat alert is treated as at least P2 (high severity).
    - Any compliance-relevant incident (data exposure, unauthorized access,
      regulatory trigger) should be flagged at emergency severity.

    severity mapping (A3.5):
      emergency / high → P1/P2 → escalate to Anthony immediately
      standard / low   → P3/P4 → Klara AI resolves; Anthony not paged
    """
    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=client_email,
            subject=f"Directive incident — {summary[:80]}",
            severity=severity,
            status="open",
            source=source,
            archetype="A3",
            sku="directive",
            summary=summary,
            segment_hint="b2b",
            metadata=metadata or {},
        )
    except Exception as exc:
        log.error("Directive incident ticket creation failed: %s", exc)
        return {"action": "error", "reason": str(exc)}

    result: dict[str, Any] = {
        "action": "directive_incident_opened",
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
                summary=f"{severity.upper()} Directive incident: {summary[:200]}",
                attempted="Klara AI triage + Huntress MDR alert review initiated",
                recommended=(
                    "P1: respond within 1 hour. P2: within 2 hours. "
                    "Assess compliance breach notification obligations before any public statement. "
                    "Contain before any remediation. Do not modify production systems "
                    "without Anthony's sign-off. If data exposure is possible, assume "
                    "breach notification may be required and loop in legal."
                ),
            )
            result["escalated"] = True
        except Exception as exc:
            log.warning("Directive incident escalation failed: %s", exc)

    log.info(
        "Directive incident: ticket=%s severity=%s escalated=%s",
        ticket_id, severity, result["escalated"],
    )
    return result
