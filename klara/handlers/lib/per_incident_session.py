"""
A2 consumer one-time session kickoff — T6.1 (per-incident) + T6.4 (remaining SKUs).

Called by the Stripe webhook handler when checkout.session.completed fires
for any A2 one-time-session SKU.  Implements WORKFLOWS.md §A2.2–A2.3 (immediate
intake + triage) and schedules the A2.6 follow-up emails.

Config-driven dispatch — add a new SKU by adding one entry to SKU_CONFIG.
No separate file per SKU.

Public surface:
    a2_kickoff(sku: str, checkout_session: dict) -> dict
        Generic dispatcher.  Idempotent — safe to call multiple times for
        the same Stripe session.
        Returns {"ticket_id": str, "triage": str, "followups_scheduled": int,
                 "sku": str}

    kickoff(checkout_session: dict) -> dict
        Backward-compatible alias: calls a2_kickoff("per-incident", ...).

    resolve(ticket_id: str, resolution_notes: str) -> None
        Called when Anthony posts a recap or Klara AI confirms walkthrough resolved.
        Transitions ticket → resolved and triggers follow-up schedule.

    escalate_out_of_scope(ticket_id: str, reason: str) -> None
        Physical repair or OOS — initiates Stripe refund + notifies client.
        Only meaningful for per-incident; safe (no-op refund) for other SKUs
        where Stripe refund logic is not applicable.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import stripe

from .db import get_pool
from .email import send_email
from . import tickets as tickets_lib

log = logging.getLogger("klaravex.per_incident_session")

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")

# ---------------------------------------------------------------------------
# Per-SKU configuration — the only place SKU-specific behaviour lives.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _SkuConfig:
    """Everything Klara AI needs to drive a specific A2 SKU end-to-end.

    Fields
    ------
    display_name        Human-readable product name (used in emails + alerts).
    price_usd           List price in whole dollars (display only).
    intake_fields       Ordered list of field names collected on the intake form.
    session_count       Number of sessions / calls included.
    deliverable         One-line deliverable description for the confirmation email.
    deliverable_days    SLA in calendar days.
    anthony_always      True = Anthony is always required (never Klara AI-only).
    anthony_role        What Anthony does in the workflow (for the alert email).
    followup_schedule   List of {offset_hours, template} for A2.6 follow-ups.
    intake_path         Portal intake form path (relative, appended to PORTAL_BASE_URL).
    escalation_note     Extra sentence in the intake email for urgent escalation context.
    """
    display_name: str
    price_usd: int
    intake_fields: tuple[str, ...]
    session_count: int
    deliverable: str
    deliverable_days: int
    anthony_always: bool
    anthony_role: str
    followup_schedule: tuple[dict[str, Any], ...]
    intake_path: str
    escalation_note: str = ""


# Shared A2.6 follow-up schedule (all SKUs use the same three touch-points).
_STANDARD_FOLLOWUPS: tuple[dict[str, Any], ...] = (
    {"offset_hours": 24,    "template": "a2_feedback"},
    {"offset_hours": 24*7,  "template": "nps_one_question"},
    {"offset_hours": 24*30, "template": "upsell_essentials"},
)

# Per-incident has its own legacy template name for backward compat.
_PER_INCIDENT_FOLLOWUPS: tuple[dict[str, Any], ...] = (
    {"offset_hours": 24,    "template": "per_incident_feedback"},
    {"offset_hours": 24*7,  "template": "nps_one_question"},
    {"offset_hours": 24*30, "template": "upsell_essentials"},
)

SKU_CONFIG: dict[str, _SkuConfig] = {
    # --- per-incident (existing) ------------------------------------------
    "per-incident": _SkuConfig(
        display_name="Per-Incident Remote Support",
        price_usd=79,
        intake_fields=(
            "device_type",
            "issue_description",
            "urgency",
            "screen_share_ok",
            "best_contact_time",
        ),
        session_count=1,
        deliverable="30-min remote session, Klara AI walkthrough, or full refund",
        deliverable_days=1,
        anthony_always=False,
        anthony_role="Join Splashtop SOS session for complex issues",
        followup_schedule=_PER_INCIDENT_FOLLOWUPS,
        intake_path="/intake/per-incident",
        escalation_note=(
            "For urgent issues (account locked out, suspected breach), "
            "reply to this email directly and we will escalate immediately."
        ),
    ),

    # --- ai-coaching ($49) -----------------------------------------------
    "ai-coaching": _SkuConfig(
        display_name="AI Skills Coaching Session",
        price_usd=49,
        intake_fields=(
            "coaching_goal",          # job search / writing / admin / other
            "current_ai_tools",       # what they already use
            "target_outcome",         # what they want to be able to do
            "availability",           # preferred times for the 1-hour Zoom
        ),
        session_count=1,
        deliverable="1-hour coaching session + recording + personalized AI tool guide",
        deliverable_days=7,
        anthony_always=True,
        anthony_role="Deliver 1-hour coaching Zoom; Klara AI preps brief and sends recap",
        followup_schedule=_STANDARD_FOLLOWUPS,
        intake_path="/intake/ai-coaching",
        escalation_note=(
            "After submitting the form, Klara AI will send you a Calendly link "
            "to book your 1-hour session with our team."
        ),
    ),

    # --- identity-privacy -------------------------------------------------
    "identity-privacy": _SkuConfig(
        display_name="Identity & Privacy Hardening",
        price_usd=149,
        intake_fields=(
            "breach_context",         # what happened or what they are worried about
            "accounts_to_lock_down",  # email, financial, social — comma list
            "data_broker_preference", # opt-out all / opt-out specific list / skip
            "credit_bureau_action",   # freeze all 3 / freeze specific / skip
        ),
        session_count=1,
        deliverable="5-day lockdown report + credit-freeze checklist + removal request log",
        deliverable_days=5,
        anthony_always=True,
        anthony_role="Review automated lockdown report; add personal recommendations before delivery",
        followup_schedule=_STANDARD_FOLLOWUPS,
        intake_path="/intake/identity-privacy",
        escalation_note=(
            "If you believe you are actively being targeted (identity theft in progress, "
            "fraudulent accounts opened), reply to this email immediately."
        ),
    ),

    # --- tech-kit ($149) --------------------------------------------------
    "tech-kit": _SkuConfig(
        display_name="Job-Hunt Tech Kit",
        price_usd=149,
        intake_fields=(
            "existing_domain",        # do they already own a domain? which?
            "email_provider",         # current email: Gmail / Outlook / other
            "portfolio_purpose",      # what the portfolio will showcase
            "target_platforms",       # LinkedIn / GitHub / personal site / all
            "linkedin_url",           # existing profile URL or blank if none
        ),
        session_count=1,
        deliverable="5-day provisioning (domain, email, portfolio scaffold, LinkedIn audit) + 1-hour handoff call",
        deliverable_days=5,
        anthony_always=True,
        anthony_role="Deliver 1-hour handoff call after Klara AI provisions the kit",
        followup_schedule=_STANDARD_FOLLOWUPS,
        intake_path="/intake/tech-kit",
        escalation_note=(
            "Once you submit this form, Klara AI will begin provisioning your kit "
            "and schedule your handoff call within 24 hours."
        ),
    ),

    # --- solo-launch ($399, 3-session package) ----------------------------
    "solo-launch": _SkuConfig(
        display_name="Solo-Business Launch Kit",
        price_usd=399,
        intake_fields=(
            "business_idea",          # what they want to launch
            "current_state",          # idea only / already have customers / revenue
            "target_revenue_model",   # service / product / SaaS / marketplace
            "licenses_needed",        # any known licenses or registrations
            "timeline",               # target launch date or "ASAP"
        ),
        session_count=3,  # 2 coaching calls + 1 handoff; multi-session tracking
        deliverable=(
            "2-week scaffolding (Stripe, website, accounting, legal templates) "
            "+ 2 coaching calls with Anthony"
        ),
        deliverable_days=14,
        anthony_always=True,
        anthony_role="Deliver 2 coaching calls spaced ~1 week apart; Klara AI scaffolds and sends 30-day check-in",
        followup_schedule=(
            {"offset_hours": 24,     "template": "a2_feedback"},
            {"offset_hours": 24*7,   "template": "nps_one_question"},
            {"offset_hours": 24*30,  "template": "solo_launch_30d_checkin"},
            {"offset_hours": 24*90,  "template": "upsell_essentials"},
        ),
        intake_path="/intake/solo-launch",
        escalation_note=(
            "After submitting the form, Klara AI will schedule your first coaching "
            "call within 48 hours and begin setting up your business toolkit."
        ),
    ),
}

# ---------------------------------------------------------------------------
# Legacy per-incident follow-up schedule (kept for backward compat)
# ---------------------------------------------------------------------------
_FOLLOWUP_SCHEDULE = list(_PER_INCIDENT_FOLLOWUPS)

# Keywords that force immediate escalation (from WORKFLOWS.md U5)
_ESCALATION_KEYWORDS = frozenset([
    "hacked", "ransomware", "locked out of email", "money missing",
    "data breach", "legal demand",
])

# Out-of-scope keywords that trigger a refund instead of support
_OUT_OF_SCOPE_KEYWORDS = frozenset([
    "physical repair", "hardware damage", "cracked screen", "broken",
    "water damage", "motherboard",
])


def _needs_immediate_escalation(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in _ESCALATION_KEYWORDS)


def _is_out_of_scope(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in _OUT_OF_SCOPE_KEYWORDS)


# ---------------------------------------------------------------------------
# Generic A2 kickoff — config-driven, all SKUs go through here.
# ---------------------------------------------------------------------------

async def a2_kickoff(sku: str, checkout_session: dict[str, Any]) -> dict[str, Any]:
    """Generic A2 one-time-session kickoff.

    Dispatches via SKU_CONFIG — every supported SKU shares this path.
    Returns {"ticket_id": str|None, "triage": str, "followups_scheduled": int, "sku": str}.

    Raise on unknown SKU so the caller can log and continue gracefully.
    """
    cfg = SKU_CONFIG.get(sku)
    if cfg is None:
        raise ValueError(f"a2_kickoff: unknown SKU '{sku}' — add it to SKU_CONFIG first")

    stripe_session_id = checkout_session.get("id", "")
    obj = checkout_session
    meta = obj.get("metadata") or {}

    # Resolve customer email + name
    customer_email: Optional[str] = (
        (obj.get("customer_details") or {}).get("email")
        or obj.get("customer_email")
        or meta.get("caller_email")
    )
    customer_name: Optional[str] = None
    if not customer_email and obj.get("customer"):
        try:
            cust = stripe.Customer.retrieve(obj["customer"])
            customer_email = cust.get("email")
            customer_name = cust.get("name")
        except Exception as exc:
            log.warning("a2_kickoff[%s]: stripe customer retrieve failed: %s", sku, exc)
    else:
        customer_name = (obj.get("customer_details") or {}).get("name")

    if not customer_email:
        log.warning("a2_kickoff[%s]: no customer email on session %s — skipping", sku, stripe_session_id)
        return {"ticket_id": None, "triage": "skipped_no_email", "followups_scheduled": 0, "sku": sku}

    # Idempotency: skip if ticket already exists for this session+SKU
    existing_ticket_id = await _find_existing_ticket(stripe_session_id, sku=sku)
    if existing_ticket_id:
        log.info(
            "a2_kickoff[%s]: session %s already has ticket %s — skipping",
            sku, stripe_session_id, existing_ticket_id,
        )
        return {"ticket_id": existing_ticket_id, "triage": "duplicate_skipped", "followups_scheduled": 0, "sku": sku}

    # Upsert client profile
    try:
        await tickets_lib.get_or_create_client(
            customer_email,
            segment="consumer",
            name=customer_name,
            stripe_customer_id=obj.get("customer"),
        )
    except Exception as exc:
        log.warning("a2_kickoff[%s]: client upsert failed (continuing): %s", sku, exc)

    # Pull any partial description from Stripe metadata (voice/per-incident flow)
    issue_description = meta.get("issue_description") or meta.get("intent") or ""
    urgency = meta.get("urgency") or "standard"
    severity = "high" if urgency in ("high", "emergency") else "standard"

    # Subject line differs by SKU
    subject = f"{cfg.display_name} — {customer_name or customer_email}"

    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=customer_email,
            subject=subject,
            severity=severity,
            status="open",
            source="stripe",
            archetype="A2",
            sku=sku,
            workflow_state="INTAKE",
            summary=issue_description[:500] if issue_description else "Intake pending",
            segment_hint="consumer",
            metadata={
                "stripe_session_id": stripe_session_id,
                "stripe_customer_id": obj.get("customer"),
                "contact_name": customer_name,
                "source": meta.get("source"),
                "call_sid": meta.get("call_sid"),
                "session_count": cfg.session_count,
            },
            initial_event={
                "type": "checkout.session.completed",
                "source": "stripe",
                "stripe_session_id": stripe_session_id,
            },
        )
    except Exception as exc:
        log.exception("a2_kickoff[%s]: ticket creation failed: %s", sku, exc)
        return {"ticket_id": None, "triage": "ticket_error", "followups_scheduled": 0, "sku": sku}

    # Send intake form email
    try:
        await _send_a2_intake_email(customer_email, customer_name, ticket_id, cfg)
    except Exception as exc:
        log.warning("a2_kickoff[%s]: intake email failed (non-fatal): %s", sku, exc)

    # Alert Anthony (always — every A2 SKU requires Anthony at some point)
    try:
        await _alert_anthony_a2(customer_email, customer_name, ticket_id, cfg, issue_description, urgency)
    except Exception as exc:
        log.warning("a2_kickoff[%s]: Anthony alert failed (non-fatal): %s", sku, exc)

    # Keyword triage (most relevant for per-incident; runs for all SKUs harmlessly)
    triage = "intake_pending"
    if issue_description:
        if _needs_immediate_escalation(issue_description):
            triage = "escalated_keyword"
            try:
                from . import escalation as escalation_lib
                await escalation_lib.escalate(
                    ticket_id=ticket_id,
                    client_email=customer_email,
                    severity="high",
                    summary=(
                        f"KEYWORD ESCALATION — {sku} intake from "
                        f"{customer_name or customer_email}: {issue_description[:200]}"
                    ),
                    attempted="A2 intake captured; keyword match triggered immediate escalation",
                    recommended="Contact client immediately",
                )
            except Exception as exc:
                log.exception("a2_kickoff[%s]: keyword escalation failed: %s", sku, exc)
        elif sku == "per-incident" and _is_out_of_scope(issue_description):
            triage = "out_of_scope_flagged"
            try:
                await _notify_out_of_scope(customer_email, customer_name, ticket_id, issue_description)
            except Exception as exc:
                log.warning("a2_kickoff[%s]: out-of-scope notify failed (non-fatal): %s", sku, exc)

    # Schedule follow-up rows (SKU-specific schedule from config)
    followups_scheduled = 0
    try:
        followups_scheduled = await _schedule_a2_followups(
            ticket_id, customer_email, customer_name, cfg
        )
    except Exception as exc:
        log.warning("a2_kickoff[%s]: followup scheduling failed (non-fatal): %s", sku, exc)

    log.info(
        "a2_kickoff[%s] complete: ticket=%s email=%s triage=%s followups=%d",
        sku, ticket_id, customer_email, triage, followups_scheduled,
    )
    return {"ticket_id": ticket_id, "triage": triage, "followups_scheduled": followups_scheduled, "sku": sku}


async def kickoff(checkout_session: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible alias — routes per-incident checkouts through a2_kickoff.

    Callers in stripe_webhook.py that imported this function directly continue
    to work unchanged.  New SKUs should call a2_kickoff(sku, session) instead.
    """
    return await a2_kickoff("per-incident", checkout_session)


async def resolve(ticket_id: str, *, resolution_notes: str = "", resolved_by: str = "loki") -> None:
    """Transition ticket to resolved and mark follow-ups as ready to send.

    Called when:
    - Klara AI confirms the walkthrough worked (SIMPLE_FIX → FOLLOWUP → RESOLVED)
    - Anthony posts a recap (SPLASHTOP_SESSION → FOLLOWUP → RESOLVED)
    """
    try:
        await tickets_lib.update_status(
            ticket_id,
            status="resolved",
            resolution=resolution_notes[:2000] if resolution_notes else "Session complete",
            assignee=resolved_by,
            workflow_state="RESOLVED",
        )
        await tickets_lib.append_event(
            ticket_id,
            "session_resolved",
            {"resolved_by": resolved_by, "notes": resolution_notes[:500]},
        )
    except Exception as exc:
        log.exception("resolve transition failed for ticket %s: %s", ticket_id, exc)
        return

    # Mark the 24h follow-up as due immediately (it will send on next cron run)
    # The 7d and 30d rows stay on their natural schedule.
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE klaravex_per_incident_followups
                   SET resolved_at = now()
                 WHERE ticket_id = $1
                   AND resolved_at IS NULL
                """,
                ticket_id,
            )
    except Exception as exc:
        log.warning("followup resolved_at update failed (non-fatal): %s", exc)


async def escalate_out_of_scope(ticket_id: str, *, reason: str = "out_of_scope") -> None:
    """Flag ticket as refunded and notify client.

    Per WORKFLOWS.md §A2.4: physical repair or out-of-scope → Klara AI auto-refunds
    via Stripe API and notifies client. Anthony is alerted.
    """
    try:
        row = await _get_ticket_row(ticket_id)
        if not row:
            log.warning("escalate_out_of_scope: ticket %s not found", ticket_id)
            return

        customer_email = row.get("client_email")
        stripe_session_id = (row.get("metadata") or {}).get("stripe_session_id")

        # Attempt Stripe refund
        refund_id: Optional[str] = None
        if stripe_session_id and stripe.api_key:
            try:
                session = stripe.checkout.Session.retrieve(stripe_session_id)
                payment_intent_id = session.get("payment_intent")
                if payment_intent_id:
                    refund = stripe.Refund.create(
                        payment_intent=payment_intent_id,
                        reason="requested_by_customer",
                        metadata={"ticket_id": ticket_id, "reason": reason},
                    )
                    refund_id = refund.get("id")
                    log.info("stripe refund created: %s for ticket %s", refund_id, ticket_id)
            except Exception as exc:
                log.warning("stripe refund failed (non-fatal): %s", exc)

        await tickets_lib.update_status(
            ticket_id,
            status="resolved",
            resolution=f"Refunded: {reason}",
            workflow_state="REFUNDED",
        )
        await tickets_lib.append_event(
            ticket_id, "refunded",
            {"reason": reason, "stripe_refund_id": refund_id},
        )

        if customer_email:
            await _send_refund_notification(customer_email, ticket_id, reason)

        await _alert_anthony_refund(customer_email or "unknown", ticket_id, reason, refund_id)

    except Exception as exc:
        log.exception("escalate_out_of_scope failed for ticket %s: %s", ticket_id, exc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _find_existing_ticket(stripe_session_id: str, sku: str = "per-incident") -> Optional[str]:
    """Return ticket_id if a ticket already has this stripe_session_id+SKU, else None."""
    if not stripe_session_id:
        return None
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id::text FROM klaravex_tickets
                 WHERE archetype = 'A2'
                   AND sku = $2
                   AND metadata->>'stripe_session_id' = $1
                 LIMIT 1
                """,
                stripe_session_id,
                sku,
            )
        return row["id"] if row else None
    except Exception as exc:
        log.warning("existing-ticket lookup failed: %s", exc)
        return None


async def _get_ticket_row(ticket_id: str) -> Optional[dict[str, Any]]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT client_email, metadata FROM klaravex_tickets WHERE id = $1",
                ticket_id,
            )
        if not row:
            return None
        return {
            "client_email": row["client_email"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
        }
    except Exception as exc:
        log.warning("ticket row fetch failed: %s", exc)
        return None


async def _send_a2_intake_email(
    email: str, name: Optional[str], ticket_id: str, cfg: _SkuConfig
) -> None:
    """Generic A2 intake confirmation email — content driven by SKU config."""
    greeting = f"Hi {name}," if name else "Hi there,"
    intake_url = f"{PORTAL_BASE_URL}{cfg.intake_path}?ticket={ticket_id}"
    fields_hint = ", ".join(cfg.intake_fields[:4])  # show first 4 fields as preview
    escalation_block = f"\n{cfg.escalation_note}\n" if cfg.escalation_note else ""
    body = (
        f"{greeting}\n\n"
        f"Payment received — thank you for choosing {cfg.display_name}.\n\n"
        f"Your ticket reference: {ticket_id}\n\n"
        f"To get started, please take 2 minutes to complete the intake form:\n\n"
        f"  {intake_url}\n\n"
        f"We'll need: {fields_hint}.\n"
        f"{escalation_block}\n"
        f"Deliverable: {cfg.deliverable} (within {cfg.deliverable_days} day(s)).\n\n"
        f"— The Klaravex Team\n"
        f"support@klaravex.com · klaravex.com"
    )
    await send_email(
        to=email,
        subject=f"[Klaravex] {cfg.display_name} confirmed — ticket {ticket_id}",
        body=body,
    )


async def _send_intake_email(email: str, name: Optional[str], ticket_id: str) -> None:
    """Legacy per-incident intake email — kept for direct callers; delegates to generic."""
    cfg = SKU_CONFIG["per-incident"]
    await _send_a2_intake_email(email, name, ticket_id, cfg)


async def _alert_anthony_a2(
    email: str,
    name: Optional[str],
    ticket_id: str,
    cfg: _SkuConfig,
    issue_description: str,
    urgency: str,
) -> None:
    """Generic Anthony alert for any A2 SKU purchase."""
    subject = f"[Klaravex A2] {cfg.display_name} — {urgency.upper()} — {name or email}"
    body = (
        f"New A2 purchase: {cfg.display_name}\n\n"
        f"Ticket:        {ticket_id}\n"
        f"Email:         {email}\n"
        f"Name:          {name or '—'}\n"
        f"Urgency:       {urgency}\n"
        f"Sessions:      {cfg.session_count}\n"
        f"Anthony role:  {cfg.anthony_role}\n"
        f"Deliverable:   {cfg.deliverable}\n"
        f"SLA:           {cfg.deliverable_days} day(s)\n"
        f"Context:       {issue_description[:400] if issue_description else '(intake form not yet submitted)'}\n\n"
        f"Intake form link has been sent to the client.\n"
    )
    await send_email(to=ALERT_EMAIL, subject=subject, body=body)


async def _alert_anthony_new_session(
    email: str,
    name: Optional[str],
    ticket_id: str,
    issue_description: str,
    urgency: str,
) -> None:
    """Legacy per-incident Anthony alert — kept for direct callers; delegates to generic."""
    cfg = SKU_CONFIG["per-incident"]
    await _alert_anthony_a2(email, name, ticket_id, cfg, issue_description, urgency)


async def _notify_out_of_scope(email: str, name: Optional[str], ticket_id: str, issue: str) -> None:
    greeting = f"Hi {name}," if name else "Hi there,"
    body = (
        f"{greeting}\n\n"
        f"Thank you for reaching out. Based on your description, your issue\n"
        f"may involve physical hardware repair (e.g. cracked screen, hardware\n"
        f"damage), which is outside the scope of our remote support service.\n\n"
        f"We will review your ticket ({ticket_id}) and get back to you within\n"
        f"2 hours to either confirm we can help remotely, or process a full\n"
        f"refund if we cannot.\n\n"
        f"— The Klaravex Team\n"
    )
    await send_email(
        to=email,
        subject=f"[Klaravex] Your support request — quick question about scope",
        body=body,
    )
    await send_email(
        to=ALERT_EMAIL,
        subject=f"[Klaravex A2] Possible OOS — ticket {ticket_id}",
        body=f"Ticket {ticket_id} ({email}) may be out of scope.\nIssue: {issue[:300]}\nPlease review and refund if confirmed OOS.",
    )


async def _send_refund_notification(email: str, ticket_id: str, reason: str) -> None:
    body = (
        f"Hi there,\n\n"
        f"We reviewed your support request (ticket {ticket_id}) and determined\n"
        f"it falls outside the scope of our remote support service.\n\n"
        f"A full refund has been issued to your original payment method. It\n"
        f"typically appears within 5–10 business days.\n\n"
        f"If you believe this was in error, please reply to this email and\n"
        f"we will make it right.\n\n"
        f"— The Klaravex Team\n"
    )
    await send_email(
        to=email,
        subject=f"[Klaravex] Refund issued — ticket {ticket_id}",
        body=body,
    )


async def _alert_anthony_refund(
    email: str, ticket_id: str, reason: str, refund_id: Optional[str]
) -> None:
    body = (
        f"Refund issued for per-incident ticket:\n\n"
        f"Ticket:      {ticket_id}\n"
        f"Email:       {email}\n"
        f"Reason:      {reason}\n"
        f"Stripe ref:  {refund_id or 'n/a — refund may have failed'}\n"
    )
    await send_email(
        to=ALERT_EMAIL,
        subject=f"[Klaravex A2] Refund issued — {ticket_id}",
        body=body,
    )


async def _schedule_a2_followups(
    ticket_id: str, email: str, name: Optional[str], cfg: _SkuConfig
) -> int:
    """Insert scheduled follow-up rows from the SKU config. Returns count inserted.

    Writes to klaravex_a2_followups (generic) rather than the per-incident-only
    table.  The per-incident cron job should also query this table once migrated.
    Falls back gracefully if the table doesn't exist yet.
    """
    pool = await get_pool()
    count = 0
    async with pool.acquire() as conn:
        for item in cfg.followup_schedule:
            try:
                await conn.execute(
                    """
                    INSERT INTO klaravex_a2_followups
                        (ticket_id, sku, client_email, client_name, template, send_after_hours)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (ticket_id, template) DO NOTHING
                    """,
                    ticket_id,
                    cfg.display_name,  # human-readable sku label
                    email.lower(),
                    name,
                    item["template"],
                    item["offset_hours"],
                )
                count += 1
            except Exception as exc:
                log.warning("a2_followups insert failed (%s): %s", item["template"], exc)
    return count


async def _schedule_followups(ticket_id: str, email: str, name: Optional[str]) -> int:
    """Legacy per-incident follow-up scheduler.

    Preserved for any direct callers; new code uses _schedule_a2_followups.
    """
    pool = await get_pool()
    count = 0
    async with pool.acquire() as conn:
        for item in _FOLLOWUP_SCHEDULE:
            try:
                await conn.execute(
                    """
                    INSERT INTO klaravex_per_incident_followups
                        (ticket_id, client_email, client_name, template, send_after_hours)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (ticket_id, template) DO NOTHING
                    """,
                    ticket_id,
                    email.lower(),
                    name,
                    item["template"],
                    item["offset_hours"],
                )
                count += 1
            except Exception as exc:
                log.warning("followup row insert failed (%s): %s", item["template"], exc)
    return count
