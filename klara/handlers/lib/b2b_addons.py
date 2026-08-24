"""A4 archetype — B2B add-on recurring services (bolt-on to Foundation/Assurance/Directive).

Add-ons are activated when a new line item is added to an existing B2B
subscription via ``customer.subscription.updated`` (or created at the same time
as the base tier via ``customer.subscription.created``).

Each add-on has exactly one ``_AddonConfig`` entry.  Adding a new add-on means
adding one entry to ``ADDON_CONFIG`` — no other file changes needed.

Public surface
--------------
handle_subscription_created(event)
    Called from stripe_webhook for customer.subscription.created.
    Checks all line items for add-on SKUs and activates each found.

handle_subscription_updated(event)
    Called from stripe_webhook for customer.subscription.updated.
    Diffs old vs new items and activates newly-added add-on SKUs.

handle_subscription_deleted(event)
    Called from stripe_webhook for customer.subscription.deleted.
    Deactivates all add-on SKUs on the subscription (best-effort).

Each handler returns a list of per-addon result dicts (action + sku + email).
All functions are idempotent.  Re-running on a duplicate Stripe event is safe.

Add-on SKUs (WORKFLOWS.md §A4)
-------------------------------
    sat               Security Awareness Training
    email-security    Email security filter configuration + monitoring
    managed-edr       Managed EDR via Huntress/Defender
    loki-concierge    Dedicated AI first-line support instance tuned to client
    vcio-standalone   Virtual CIO — quarterly strategy + meeting prep
    vciso-standalone  Virtual CISO — security leadership + compliance check-ins
    ir-retainer       Incident Response retainer — standby, activated on incident
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import stripe

from .db import get_pool
from .email import send_email
from .escalation import escalate
from . import tickets as tickets_lib

log = logging.getLogger("klaravex.b2b_addons")

# ── Environment ────────────────────────────────────────────────────────────────

PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "support@klaravex.com")
ANTHONY_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
CALENDLY_VCIO_URL = os.environ.get("CALENDLY_VCIO_URL", "")
CALENDLY_VCISO_URL = os.environ.get("CALENDLY_VCISO_URL", "")

# ── Config dataclass ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _AddonConfig:
    """All behaviour Klara AI needs to activate, run, and report on a single add-on.

    Fields
    ------
    display_name        Human-readable product name used in emails and alerts.
    intake_fields       Ordered list of fields collected on the Day-0 intake form.
    anthony_always      True  → Anthony is always involved (never Klara AI-only).
    anthony_role        What Anthony does (for the activation alert email).
    activation_steps    Ordered list of provisioning steps Klara AI executes on Day 0.
    autonomous_cadence  One-line description of the ongoing Klara AI automation cadence.
    deliverable         One-line deliverable description for the activation email.
    intake_path         Portal intake form path (relative, appended to PORTAL_BASE_URL).
    calendly_url_env    Optional env-var name holding the Calendly URL for this add-on.
    escalation_note     Extra sentence added to the activation email for urgency context.
    """
    display_name: str
    intake_fields: tuple[str, ...]
    anthony_always: bool
    anthony_role: str
    activation_steps: tuple[str, ...]
    autonomous_cadence: str
    deliverable: str
    intake_path: str
    calendly_url_env: str = ""
    escalation_note: str = ""


# ── Per-add-on configuration (WORKFLOWS.md §A4) ────────────────────────────────

ADDON_CONFIG: dict[str, _AddonConfig] = {

    "sat": _AddonConfig(
        display_name="Security Awareness Training",
        intake_fields=(
            "employee_list",
            "training_vendor_preference",   # KnowBe4 / Hook / usecure
            "phishing_sim_cadence",         # monthly / bi-monthly
            "baseline_phishing_score",
        ),
        anthony_always=False,
        anthony_role="Review quarterly SAT metrics; sign off on insurer-ready report",
        activation_steps=(
            "Verify employee list from onboarding checklist (or request update)",
            "Provision training vendor account and enroll all employees",
            "Schedule first phishing simulation campaign (within 7 days)",
            "Configure monthly training assignment cadence",
            "Configure completion-tracking webhook → Klara AI portal",
        ),
        autonomous_cadence=(
            "Monthly: assign new training module; run 1-2 phishing simulations; "
            "track completion rates; alert Anthony on stragglers; "
            "generate insurer-ready report quarterly"
        ),
        deliverable="Ongoing SAT campaigns, phishing simulations, and compliance-ready completion reports",
        intake_path="/intake/sat",
        escalation_note=(
            "If an employee clicks a phishing simulation and enters credentials, "
            "Klara AI will notify you immediately and open a security ticket."
        ),
    ),

    "email-security": _AddonConfig(
        display_name="Email Security",
        intake_fields=(
            "email_platform",               # M365 / Google Workspace
            "tenant_access_confirmed",
            "current_spam_rate_baseline",
            "dmarc_dkim_spf_status",
            "exclusion_domains",
        ),
        anthony_always=False,
        anthony_role=(
            "Review novel threat detections; approve policy changes "
            "that could impact business email flow"
        ),
        activation_steps=(
            "Verify M365 Defender or GWS Advanced Protection access",
            "Audit existing DMARC / DKIM / SPF records; flag gaps",
            "Enable and tune spam / phishing filter policies",
            "Configure DLP policies matching client data classification",
            "Set up Klara AI alert webhook for high-confidence phishing detections",
        ),
        autonomous_cadence=(
            "Continuous: monitor filter trigger counts; "
            "weekly digest to client on blocked threats; "
            "alert Anthony on novel threat patterns or policy-gap events"
        ),
        deliverable="Configured email security filters, DLP policies, and weekly threat digest",
        intake_path="/intake/email-security",
        escalation_note=(
            "Business email compromise (BEC) or credential-phishing detections "
            "are escalated to Anthony immediately, 24/7."
        ),
    ),

    "managed-edr": _AddonConfig(
        display_name="Managed EDR",
        intake_fields=(
            "device_list",
            "os_breakdown",                 # Windows / macOS / Linux counts
            "exclusion_list",
            "existing_edr_to_replace",
            "huntress_org_exists",
        ),
        anthony_always=False,
        anthony_role="Lead active threat response; approve any endpoint isolation or remediation action",
        activation_steps=(
            "Create or link Huntress organization for client",
            "Deploy Huntress agent on all devices (via Atera scripted deployment)",
            "Configure Microsoft Defender policy baseline (if M365 tenant)",
            "Confirm all endpoints reporting to Huntress dashboard",
            "Set Klara AI alert webhook on Huntress incident events",
        ),
        autonomous_cadence=(
            "Real-time: monitor Huntress incident feed; "
            "triage P3-P4 alerts autonomously; "
            "escalate active threats (P1-P2) to Anthony immediately; "
            "weekly EDR health summary to client"
        ),
        deliverable="24/7 EDR monitoring across all endpoints, with Anthony-led active threat response",
        intake_path="/intake/managed-edr",
        escalation_note=(
            "Active threat detections (ransomware, credential theft, C2 callbacks) "
            "trigger an immediate Anthony escalation regardless of time of day."
        ),
    ),

    "loki-concierge": _AddonConfig(
        display_name="Klara AI Concierge (Dedicated AI Support)",
        intake_fields=(
            "environment_stack",            # M365 / GWS / AWS / on-prem
            "user_count",
            "kb_topics_to_emphasize",
            "escalation_contacts",
            "internal_it_contact",          # co-managed: who to coordinate with
        ),
        anthony_always=False,
        anthony_role="Approve KB content additions; review monthly Concierge performance metrics",
        activation_steps=(
            "Provision dedicated Klara AI Concierge instance for client tenant",
            "Load client-specific KB articles and stack documentation",
            "Configure escalation routing (Klara AI → Anthony / client IT contact)",
            "Set up portal widget on client intranet or Teams tab (if applicable)",
            "Send 'your AI support coordinator is live' email to all end users",
        ),
        autonomous_cadence=(
            "24/7: answer internal user questions; "
            "route to client IT or Anthony per escalation matrix; "
            "monthly performance report (resolution rate, top topics, CSAT)"
        ),
        deliverable="Dedicated 24/7 AI support instance trained on client's environment",
        intake_path="/intake/loki-concierge",
    ),

    "vcio-standalone": _AddonConfig(
        display_name="Virtual CIO (vCIO)",
        intake_fields=(
            "meeting_cadence",              # monthly default
            "agenda_priorities",
            "board_reporting_required",
            "current_it_budget",
            "strategic_initiatives",
        ),
        anthony_always=True,
        anthony_role="Deliver every vCIO meeting; own technology roadmap recommendations",
        activation_steps=(
            "Schedule first vCIO strategy session via Calendly (within 14 days)",
            "Klara AI pulls 30-day ticket trends and infrastructure posture for meeting prep",
            "Klara AI drafts initial technology roadmap template from intake data",
        ),
        autonomous_cadence=(
            "Monthly: Klara AI drafts meeting agenda from ticket trends + recommendations; "
            "Anthony delivers session; Klara AI documents outcomes and action items; "
            "quarterly: Klara AI preps board-level summary deck for Anthony to deliver"
        ),
        deliverable="Monthly vCIO strategy session (Anthony-led) with Klara AI-drafted agenda and action tracking",
        intake_path="/intake/vcio",
        calendly_url_env="CALENDLY_VCIO_URL",
        escalation_note=(
            "Strategic decisions (budget approvals, vendor changes, architecture shifts) "
            "require Anthony's direct involvement — never Klara AI-only."
        ),
    ),

    "vciso-standalone": _AddonConfig(
        display_name="Virtual CISO (vCISO)",
        intake_fields=(
            "meeting_cadence",
            "security_focus_areas",         # e.g. HIPAA, SOC 2, ISO 27001
            "compliance_framework",
            "board_reporting_required",
            "existing_risk_register",
            "security_incidents_last_12mo",
        ),
        anthony_always=True,
        anthony_role=(
            "Deliver every vCISO engagement; own security posture recommendations; "
            "sign off on risk register updates and compliance interpretations"
        ),
        activation_steps=(
            "Schedule initial vCISO kickoff session via Calendly (within 14 days)",
            "Klara AI runs automated security posture baseline (M365 Secure Score, AWS Security Hub)",
            "Klara AI drafts initial risk register template from intake data",
            "Klara AI configures compliance framework tracking (controls checklist in portal)",
        ),
        autonomous_cadence=(
            "Monthly: Klara AI preps security posture delta and compliance check-in agenda; "
            "Anthony delivers session; Klara AI updates risk register and control status; "
            "quarterly: Klara AI generates compliance progress report for Anthony to deliver"
        ),
        deliverable="Monthly vCISO security leadership session (Anthony-led) with risk register and compliance tracking",
        intake_path="/intake/vciso",
        calendly_url_env="CALENDLY_VCISO_URL",
        escalation_note=(
            "Compliance interpretations and risk acceptance decisions "
            "are Anthony-only — Klara AI never makes these calls."
        ),
    ),

    "ir-retainer": _AddonConfig(
        display_name="Incident Response Retainer",
        intake_fields=(
            "ir_playbook_exists",
            "primary_ir_contact",
            "after_hours_phone",
            "environment_summary",          # key systems, cloud accounts, data classification
            "insurance_carrier",
            "legal_counsel_on_retainer",
        ),
        anthony_always=True,
        anthony_role="Lead every IR activation; coordinate with legal, insurer, and affected parties",
        activation_steps=(
            "Document client environment in IR runbook (Klara AI-drafted, Anthony-reviewed)",
            "Confirm after-hours contact and escalation phone tree",
            "Store IR runbook in encrypted portal vault",
            "Test Klara AI → Anthony activation pager (dry-run notification)",
        ),
        autonomous_cadence=(
            "Standby: no routine automation; "
            "on incident trigger → Klara AI activates playbook, creates P1 ticket, "
            "pages Anthony immediately, notifies client primary contact; "
            "annual tabletop exercise prep (Klara AI drafts scenario, Anthony facilitates)"
        ),
        deliverable=(
            "IR runbook on file; standby retainer with guaranteed Anthony-led response "
            "on incident activation; annual tabletop exercise"
        ),
        intake_path="/intake/ir-retainer",
        escalation_note=(
            "IR retainer activations are treated as P1 regardless of time of day. "
            "Anthony is paged immediately via Telegram + phone."
        ),
    ),
}

# Canonical set of all add-on SKU strings.
ADDON_SKUS: frozenset[str] = frozenset(ADDON_CONFIG.keys())


# ── Stripe helpers ─────────────────────────────────────────────────────────────

def _extract_skus_from_subscription(sub_obj: dict) -> frozenset[str]:
    """Return the set of SKU strings present in a Stripe subscription object."""
    found: set[str] = set()

    # Prefer top-level metadata.sku (single add-on subscriptions).
    top_sku = ((sub_obj.get("metadata") or {}).get("sku") or "").lower()
    if top_sku:
        found.add(top_sku)

    # Line items (multi-item subscriptions carry one item per add-on).
    for item in (sub_obj.get("items") or {}).get("data") or []:
        # item-level metadata
        item_sku = ((item.get("metadata") or {}).get("sku") or "").lower()
        if item_sku:
            found.add(item_sku)
        # price-level metadata
        price = item.get("price") or {}
        price_sku = ((price.get("metadata") or {}).get("sku") or "").lower()
        if price_sku:
            found.add(price_sku)
        # product name / id as last resort
        prod = price.get("product")
        if isinstance(prod, dict):
            prod_sku = (prod.get("name") or prod.get("id") or "").lower()
            if prod_sku:
                found.add(prod_sku)
        elif isinstance(prod, str):
            found.add(prod.lower())

    return frozenset(found)


def _addon_skus_in(skus: frozenset[str]) -> frozenset[str]:
    """Filter a set of SKU strings to only those that are known add-on SKUs."""
    return skus & ADDON_SKUS


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


async def _client_company(email: str) -> Optional[str]:
    """Look up the company name for an existing B2B client (best-effort)."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT company FROM klaravex_clients WHERE email = $1",
                email.lower(),
            )
        return row["company"] if row else None
    except Exception as exc:
        log.warning("company lookup failed for %s: %s", email, exc)
        return None


# ── Alert helper ───────────────────────────────────────────────────────────────

async def _alert_anthony(subject: str, body: str) -> None:
    """Best-effort email + Telegram.  Never raises."""
    try:
        await send_email(to=ANTHONY_EMAIL, subject=subject, body=body)
    except Exception as exc:
        log.warning("addon alert email failed: %s", exc)

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
            log.warning("addon Telegram alert failed: %s", exc)


# ── Activation email builders ──────────────────────────────────────────────────

def _activation_email(
    *,
    sku: str,
    cfg: _AddonConfig,
    name: Optional[str],
    company: Optional[str],
    intake_url: str,
    calendly_url: str,
) -> tuple[str, str]:
    """Return (subject, body) for the Day-0 activation email sent to the client."""
    greeting = f"Hi {name}," if name else "Hi,"
    org_line = f" for {company}" if company else ""
    steps_text = "\n".join(f"  • {s}" for s in cfg.activation_steps)
    subject = f"Klaravex {cfg.display_name} — activated{org_line}"
    body_parts = [
        f"{greeting}\n\n"
        f"Your Klaravex **{cfg.display_name}** add-on is now active{org_line}.\n\n"
        f"**What we're setting up for you:**\n{steps_text}\n\n"
        f"**To complete Day-0 setup, please fill in your intake form** (takes ~5 minutes):\n"
        f"  {intake_url}\n\n"
        f"**What Klara AI does automatically once live:**\n  {cfg.autonomous_cadence}\n\n"
        f"**Deliverable:** {cfg.deliverable}\n",
    ]
    if cfg.escalation_note:
        body_parts.append(f"\n{cfg.escalation_note}\n")
    if calendly_url:
        body_parts.append(f"\nSchedule your kickoff session here:\n  {calendly_url}\n")
    body_parts.append(
        f"\nQuestions? Reply to this email or start a chat at klaravex.com.\n\n"
        f"— The Klaravex Team\nsupport@klaravex.com\n"
    )
    return subject, "".join(body_parts)


def _deactivation_email(
    *,
    sku: str,
    cfg: _AddonConfig,
    name: Optional[str],
    company: Optional[str],
) -> tuple[str, str]:
    """Return (subject, body) for the offboarding email when an add-on is removed."""
    greeting = f"Hi {name}," if name else "Hi,"
    org_line = f" for {company}" if company else ""
    subject = f"Klaravex {cfg.display_name} — deactivated{org_line}"
    body = (
        f"{greeting}\n\n"
        f"Your Klaravex **{cfg.display_name}** add-on has been deactivated{org_line}. "
        f"Access and automation will wind down by the end of your current billing period.\n\n"
        f"If this was made in error or you would like to re-activate, "
        f"reply to this email within 48 hours.\n\n"
        f"— The Klaravex Team\nsupport@klaravex.com\n"
    )
    return subject, body


# ── Core per-addon activation / deactivation ──────────────────────────────────

async def _activate_addon(
    *,
    sku: str,
    email: str,
    name: Optional[str],
    company: Optional[str],
    stripe_customer_id: Optional[str],
    stripe_sub_id: Optional[str],
) -> dict[str, Any]:
    """Run the full Day-0 activation workflow for a single add-on SKU.

    1. Upsert client record.
    2. Open an activation ticket.
    3. Store add-on status row (idempotent).
    4. Send activation email to client.
    5. Alert Anthony (add-on activated + intake URL + any anthony_always note).

    Returns a result dict.
    """
    cfg = ADDON_CONFIG[sku]
    intake_url = f"{PORTAL_BASE_URL.rstrip('/')}{cfg.intake_path}"
    calendly_url = os.environ.get(cfg.calendly_url_env, "") if cfg.calendly_url_env else ""

    # 1. Upsert client.
    client_id: Optional[str] = None
    try:
        client_id = await tickets_lib.get_or_create_client(
            email,
            segment="b2b",
            name=name,
            stripe_customer_id=stripe_customer_id,
            company=company,
            metadata={"addon": sku, "source": f"stripe_addon_{sku}_created"},
        )
    except Exception as exc:
        log.warning("addon client upsert failed (%s, %s): %s", sku, email, exc)

    # 2. Open activation ticket.
    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=email,
            subject=f"{cfg.display_name} activated — {company or email}",
            severity="standard",
            status="open",
            source="stripe",
            archetype="A4",
            sku=sku,
            summary=(
                f"{cfg.display_name} add-on activated. "
                f"Intake form sent to {email}. "
                f"Activation steps: {'; '.join(cfg.activation_steps)}"
            ),
            segment_hint="b2b",
            metadata={
                "company": company,
                "stripe_sub_id": stripe_sub_id,
                "anthony_always": cfg.anthony_always,
            },
        )
    except Exception as exc:
        log.warning("addon ticket creation failed (%s, %s): %s", sku, email, exc)

    # 3. Persist add-on status (idempotent INSERT).
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO klaravex_addon_status
                    (client_email, sku, status, stripe_sub_id, activated_at)
                VALUES ($1, $2, 'active', $3, NOW())
                ON CONFLICT (client_email, sku) DO UPDATE
                    SET status = 'active',
                        stripe_sub_id = EXCLUDED.stripe_sub_id,
                        activated_at = NOW()
                """,
                email.lower(),
                sku,
                stripe_sub_id,
            )
    except Exception as exc:
        log.warning("addon status upsert failed (%s, %s): %s", sku, email, exc)

    # 4. Send activation email.
    try:
        subject, body = _activation_email(
            sku=sku,
            cfg=cfg,
            name=name,
            company=company,
            intake_url=intake_url,
            calendly_url=calendly_url,
        )
        await send_email(to=email, subject=subject, body=body)
    except Exception as exc:
        log.warning("addon activation email failed (%s, %s): %s", sku, email, exc)

    # 5. Alert Anthony.
    alert_subject = f"[Klaravex Add-On] {cfg.display_name} activated — {company or email}"
    anthony_note = (
        f"\nAnthony role: {cfg.anthony_role}\n"
        f"Action required: review intake form once submitted.\n"
        if cfg.anthony_always else
        f"\nLoki handles routine automation. Anthony role: {cfg.anthony_role}\n"
    )
    alert_body = (
        f"Add-on activated: {cfg.display_name} ({sku})\n\n"
        f"Company:     {company or '(not provided)'}\n"
        f"Contact:     {name or '(not provided)'}\n"
        f"Email:       {email}\n"
        f"Sub ID:      {stripe_sub_id or '—'}\n"
        f"Client ID:   {client_id or '—'}\n"
        f"Ticket ID:   {ticket_id or '—'}\n"
        f"Intake URL:  {intake_url}\n"
        f"{anthony_note}"
    )
    if calendly_url:
        alert_body += f"Calendly:    {calendly_url}\n"

    await _alert_anthony(alert_subject, alert_body)

    log.info("addon activated: sku=%s email=%s ticket=%s", sku, email, ticket_id)
    return {
        "action": "addon_activated",
        "sku": sku,
        "email": email,
        "client_id": client_id,
        "ticket_id": ticket_id,
        "anthony_always": cfg.anthony_always,
    }


async def _deactivate_addon(
    *,
    sku: str,
    email: str,
    name: Optional[str],
    company: Optional[str],
    stripe_sub_id: Optional[str],
) -> dict[str, Any]:
    """Deactivate a single add-on: update status row + notify client + alert Anthony."""
    cfg = ADDON_CONFIG.get(sku)
    if not cfg:
        return {"action": "skipped", "reason": f"unknown sku {sku!r}"}

    # Update status row.
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE klaravex_addon_status
                   SET status = 'inactive', deactivated_at = NOW()
                 WHERE client_email = $1 AND sku = $2
                """,
                email.lower(),
                sku,
            )
    except Exception as exc:
        log.warning("addon status deactivation failed (%s, %s): %s", sku, email, exc)

    # Open a deactivation ticket.
    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=email,
            subject=f"{cfg.display_name} deactivated — {company or email}",
            severity="standard",
            status="open",
            source="stripe",
            archetype="A4",
            sku=sku,
            summary=f"{cfg.display_name} add-on deactivated for {email}. Offboarding steps queued.",
            segment_hint="b2b",
            metadata={"company": company, "stripe_sub_id": stripe_sub_id},
        )
    except Exception as exc:
        log.warning("addon deactivation ticket failed (%s, %s): %s", sku, email, exc)

    # Send deactivation email.
    try:
        subject, body = _deactivation_email(sku=sku, cfg=cfg, name=name, company=company)
        await send_email(to=email, subject=subject, body=body)
    except Exception as exc:
        log.warning("addon deactivation email failed (%s, %s): %s", sku, email, exc)

    # Alert Anthony.
    alert_subject = f"[Klaravex Add-On] {cfg.display_name} removed — {company or email}"
    alert_body = (
        f"Add-on deactivated: {cfg.display_name} ({sku})\n\n"
        f"Company:   {company or '(not provided)'}\n"
        f"Email:     {email}\n"
        f"Sub ID:    {stripe_sub_id or '—'}\n"
        f"Ticket ID: {ticket_id or '—'}\n\n"
        f"Action: deactivate vendor account / agent / instance tied to this add-on.\n"
    )
    await _alert_anthony(alert_subject, alert_body)

    log.info("addon deactivated: sku=%s email=%s ticket=%s", sku, email, ticket_id)
    return {
        "action": "addon_deactivated",
        "sku": sku,
        "email": email,
        "ticket_id": ticket_id,
    }


# ── Public lifecycle handlers ──────────────────────────────────────────────────

async def handle_subscription_created(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Activate all add-on SKUs present in a new subscription.

    Called from stripe_webhook._dispatch_event() for
    customer.subscription.created events.
    """
    obj = event["data"]["object"]
    all_skus = _extract_skus_from_subscription(obj)
    addon_skus = _addon_skus_in(all_skus)

    if not addon_skus:
        return [{"action": "skipped", "reason": "no addon skus in subscription"}]

    email, name, stripe_customer_id = await _resolve_customer(obj)
    if not email:
        log.warning("addon subscription.created: no customer email found")
        return [{"action": "error", "reason": "no_email"}]

    company = (obj.get("metadata") or {}).get("company") or await _client_company(email)
    stripe_sub_id = obj.get("id")

    results = []
    for sku in sorted(addon_skus):
        try:
            result = await _activate_addon(
                sku=sku,
                email=email,
                name=name,
                company=company,
                stripe_customer_id=stripe_customer_id,
                stripe_sub_id=stripe_sub_id,
            )
        except Exception as exc:
            log.exception("addon activation failed (%s, %s): %s", sku, email, exc)
            result = {"action": "error", "sku": sku, "reason": str(exc)}
        results.append(result)

    return results


async def handle_subscription_updated(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Diff old vs new subscription line items and activate newly-added add-ons.

    Called from stripe_webhook._dispatch_event() for
    customer.subscription.updated events.

    Stripe includes ``event["data"]["previous_attributes"]`` with the fields
    that changed.  We compare the current items set against the previous items
    set to find net-new add-on SKUs.  If previous_attributes doesn't include
    items (i.e. something else changed), we skip quietly.
    """
    obj = event["data"]["object"]
    prev = (event["data"].get("previous_attributes") or {})

    current_skus = _extract_skus_from_subscription(obj)
    current_addon_skus = _addon_skus_in(current_skus)

    # Only diff when items actually changed.
    prev_items_raw = prev.get("items")
    if prev_items_raw is None:
        # Items didn't change; check if nothing add-on related changed at all.
        if not current_addon_skus:
            return [{"action": "skipped", "reason": "items unchanged and no addon skus"}]
        # Items unchanged but there are add-on SKUs already — nothing to activate.
        return [{"action": "skipped", "reason": "items unchanged, no new addons to activate"}]

    # Build the set of SKUs that were on the subscription BEFORE this update.
    prev_sub_snapshot = {"items": prev_items_raw, "metadata": obj.get("metadata") or {}}
    previous_skus = _extract_skus_from_subscription(prev_sub_snapshot)
    previous_addon_skus = _addon_skus_in(previous_skus)

    # Net-new add-ons = present now but not before.
    new_addon_skus = current_addon_skus - previous_addon_skus
    # Removed add-ons = present before but not now.
    removed_addon_skus = previous_addon_skus - current_addon_skus

    if not new_addon_skus and not removed_addon_skus:
        return [{"action": "skipped", "reason": "no addon sku changes in update"}]

    email, name, stripe_customer_id = await _resolve_customer(obj)
    if not email:
        log.warning("addon subscription.updated: no customer email found")
        return [{"action": "error", "reason": "no_email"}]

    company = (obj.get("metadata") or {}).get("company") or await _client_company(email)
    stripe_sub_id = obj.get("id")

    results: list[dict[str, Any]] = []

    for sku in sorted(new_addon_skus):
        try:
            result = await _activate_addon(
                sku=sku,
                email=email,
                name=name,
                company=company,
                stripe_customer_id=stripe_customer_id,
                stripe_sub_id=stripe_sub_id,
            )
        except Exception as exc:
            log.exception("addon activation failed on update (%s, %s): %s", sku, email, exc)
            result = {"action": "error", "sku": sku, "reason": str(exc)}
        results.append(result)

    for sku in sorted(removed_addon_skus):
        try:
            result = await _deactivate_addon(
                sku=sku,
                email=email,
                name=name,
                company=company,
                stripe_sub_id=stripe_sub_id,
            )
        except Exception as exc:
            log.exception("addon deactivation failed on update (%s, %s): %s", sku, email, exc)
            result = {"action": "error", "sku": sku, "reason": str(exc)}
        results.append(result)

    return results


async def handle_subscription_deleted(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Deactivate all add-on SKUs when a subscription is fully cancelled.

    Called from stripe_webhook._dispatch_event() for
    customer.subscription.deleted events.
    """
    obj = event["data"]["object"]
    all_skus = _extract_skus_from_subscription(obj)
    addon_skus = _addon_skus_in(all_skus)

    if not addon_skus:
        return [{"action": "skipped", "reason": "no addon skus in deleted subscription"}]

    email, name, stripe_customer_id = await _resolve_customer(obj)
    if not email:
        log.warning("addon subscription.deleted: no customer email found")
        return [{"action": "error", "reason": "no_email"}]

    company = (obj.get("metadata") or {}).get("company") or await _client_company(email)
    stripe_sub_id = obj.get("id")

    results = []
    for sku in sorted(addon_skus):
        try:
            result = await _deactivate_addon(
                sku=sku,
                email=email,
                name=name,
                company=company,
                stripe_sub_id=stripe_sub_id,
            )
        except Exception as exc:
            log.exception("addon deactivation failed on delete (%s, %s): %s", sku, email, exc)
            result = {"action": "error", "sku": sku, "reason": str(exc)}
        results.append(result)

    return results
