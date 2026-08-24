"""
A2 resume session kickoff — T6.3.

Called by the Stripe webhook handler when checkout.session.completed fires for a
resume-basic, resume-premium, or resume-executive SKU.

Implements WORKFLOWS.md §A2.2–A2.3 (resume-* variant) and schedules the A2.6
follow-up emails plus the 30/60/90-day job-search check-ins.

SKU lifecycle constants (sessions = Anthony review rounds):
    resume-basic:     1 session  — single review
    resume-premium:   3 sessions — review + 2 revision rounds
    resume-executive: 5 sessions — review + 4 revision rounds

Public surface
--------------
    kickoff(checkout_session: dict) -> dict
        Idempotent. Returns {"ticket_id", "sku", "sessions_total",
                              "triage", "followups_scheduled"}.

    advance_session(ticket_id: str, session_notes: str) -> dict
        Called when Anthony completes a review/revision pass.
        Decrements sessions remaining; if 0 → transitions to DELIVERED.
        Returns {"ticket_id", "sessions_remaining", "state"}.

    mark_delivered(ticket_id: str) -> None
        Transitions ticket → DELIVERED; activates post-delivery follow-up schedule.
"""

import logging
import os
from typing import Any, Optional

import stripe

from .db import get_pool
from .email import send_email
from . import tickets as tickets_lib

log = logging.getLogger("klaravex.resume_session")

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")

# ---------------------------------------------------------------------------
# SKU configuration
# ---------------------------------------------------------------------------

# sessions_total = number of Anthony review/revision passes included
_SKU_CONFIG: dict[str, dict[str, Any]] = {
    "resume-basic": {
        "sessions_total": 1,
        "label": "Basic",
        "turnaround_days": 3,
        "revision_rounds": 0,  # 1 review, no revisions
    },
    "resume-premium": {
        "sessions_total": 3,
        "label": "Premium",
        "turnaround_days": 3,
        "revision_rounds": 2,  # 1 review + 2 revisions
    },
    "resume-executive": {
        "sessions_total": 5,
        "label": "Executive",
        "turnaround_days": 5,
        "revision_rounds": 4,  # 1 review + 4 revisions
    },
}
_DEFAULT_SKU = "resume-premium"

RESUME_SKUS = frozenset(_SKU_CONFIG.keys())

# ---------------------------------------------------------------------------
# Follow-up schedule (hours offset from checkout completion)
# ---------------------------------------------------------------------------

_POST_INTAKE_FOLLOWUPS = [
    {"offset_hours": 24,       "template": "resume_feedback",        "phase": "post_delivery"},
    {"offset_hours": 24 * 7,   "template": "resume_still_working",   "phase": "post_delivery"},
    {"offset_hours": 24 * 30,  "template": "job_search_checkin_30d", "phase": "job_search"},
    {"offset_hours": 24 * 60,  "template": "job_search_checkin_60d", "phase": "job_search"},
    {"offset_hours": 24 * 90,  "template": "job_search_checkin_90d", "phase": "job_search"},
    {"offset_hours": 24 * 30,  "template": "upsell_essentials",      "phase": "upsell"},
]

# ---------------------------------------------------------------------------
# Kickoff
# ---------------------------------------------------------------------------

async def kickoff(checkout_session: dict[str, Any]) -> dict[str, Any]:
    """Kick off the A2 resume workflow on a completed Stripe checkout.

    Actions (all best-effort — never raises externally; errors are logged):
    1. Validate SKU is a resume SKU.
    2. Upsert client profile.
    3. Create ticket in workflow_state='INTAKE' with SKU-specific session metadata.
    4. Send intake email with upload link and intake fields.
    5. Alert Anthony.
    6. Schedule follow-up rows in klaravex_resume_followups.

    Idempotent: if a ticket already exists for this stripe_session_id it returns
    the existing ticket_id without re-running side effects.
    """
    stripe_session_id = checkout_session.get("id", "")
    meta = checkout_session.get("metadata") or {}
    sku = meta.get("sku", "").lower()

    # Fall back to line-item inspection if SKU not in metadata
    if sku not in RESUME_SKUS:
        sku = await _detect_resume_sku(checkout_session)

    if sku not in RESUME_SKUS:
        return {"ticket_id": None, "sku": sku, "sessions_total": 0,
                "triage": "not_a_resume_sku", "followups_scheduled": 0}

    sku_cfg = _SKU_CONFIG[sku]

    # Resolve customer email + name
    customer_email: Optional[str] = (
        (checkout_session.get("customer_details") or {}).get("email")
        or checkout_session.get("customer_email")
        or meta.get("caller_email")
    )
    customer_name: Optional[str] = (checkout_session.get("customer_details") or {}).get("name")

    if not customer_email and checkout_session.get("customer"):
        try:
            cust = stripe.Customer.retrieve(checkout_session["customer"])
            customer_email = cust.get("email")
            customer_name = customer_name or cust.get("name")
        except Exception as exc:
            log.warning("stripe customer retrieve failed: %s", exc)

    if not customer_email:
        log.warning("resume kickoff: no customer email on session %s — skipping", stripe_session_id)
        return {"ticket_id": None, "sku": sku, "sessions_total": sku_cfg["sessions_total"],
                "triage": "skipped_no_email", "followups_scheduled": 0}

    # Idempotency: existing ticket for this session?
    existing_ticket_id = await _find_existing_ticket(stripe_session_id, sku)
    if existing_ticket_id:
        log.info("resume kickoff: session %s already has ticket %s — skipping", stripe_session_id, existing_ticket_id)
        return {"ticket_id": existing_ticket_id, "sku": sku,
                "sessions_total": sku_cfg["sessions_total"],
                "triage": "duplicate_skipped", "followups_scheduled": 0}

    # Upsert client
    try:
        await tickets_lib.get_or_create_client(
            customer_email,
            segment="consumer",
            name=customer_name,
            stripe_customer_id=checkout_session.get("customer"),
        )
    except Exception as exc:
        log.warning("client upsert failed (continuing): %s", exc)

    # Create ticket
    target_role = meta.get("target_role") or ""
    industry = meta.get("industry") or meta.get("target_industry") or ""
    linkedin_url = meta.get("linkedin_url") or ""

    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=customer_email,
            subject=f"Resume {sku_cfg['label']} — {customer_name or customer_email}",
            severity="standard",
            status="open",
            source="stripe",
            archetype="A2",
            sku=sku,
            workflow_state="INTAKE",
            summary=(
                f"{sku_cfg['label']} resume rewrite. "
                f"Target: {target_role or 'not yet provided'}."
            ),
            segment_hint="consumer",
            metadata={
                "stripe_session_id": stripe_session_id,
                "stripe_customer_id": checkout_session.get("customer"),
                "contact_name": customer_name,
                "target_role": target_role,
                "industry": industry,
                "linkedin_url": linkedin_url,
                "sessions_total": sku_cfg["sessions_total"],
                "sessions_remaining": sku_cfg["sessions_total"],
                "revision_rounds": sku_cfg["revision_rounds"],
                "turnaround_days": sku_cfg["turnaround_days"],
                "workflow_phase": "intake",
            },
            initial_event={
                "type": "checkout.session.completed",
                "source": "stripe",
                "stripe_session_id": stripe_session_id,
            },
        )
    except Exception as exc:
        log.exception("ticket creation failed: %s", exc)
        return {"ticket_id": None, "sku": sku,
                "sessions_total": sku_cfg["sessions_total"],
                "triage": "ticket_error", "followups_scheduled": 0}

    # Send intake email
    try:
        await _send_intake_email(customer_email, customer_name, ticket_id, sku, sku_cfg)
    except Exception as exc:
        log.warning("intake email failed (non-fatal): %s", exc)

    # Alert Anthony
    try:
        await _alert_anthony_new_resume(customer_email, customer_name, ticket_id, sku, sku_cfg, target_role)
    except Exception as exc:
        log.warning("Anthony alert failed (non-fatal): %s", exc)

    # Schedule follow-ups
    followups_scheduled = 0
    try:
        followups_scheduled = await _schedule_followups(ticket_id, customer_email, customer_name, sku)
    except Exception as exc:
        log.warning("followup scheduling failed (non-fatal): %s", exc)

    log.info(
        "resume kickoff complete: ticket=%s sku=%s sessions=%d email=%s followups=%d",
        ticket_id, sku, sku_cfg["sessions_total"], customer_email, followups_scheduled,
    )
    return {
        "ticket_id": ticket_id,
        "sku": sku,
        "sessions_total": sku_cfg["sessions_total"],
        "triage": "intake_sent",
        "followups_scheduled": followups_scheduled,
    }


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

async def advance_session(ticket_id: str, *, session_notes: str = "", reviewer: str = "anthony") -> dict[str, Any]:
    """Record that Anthony completed one review/revision pass.

    Decrements sessions_remaining in ticket metadata.
    If sessions_remaining reaches 0, calls mark_delivered().

    Returns {"ticket_id", "sessions_remaining", "state"}
    """
    row = await _get_ticket_metadata(ticket_id)
    if not row:
        log.warning("advance_session: ticket %s not found", ticket_id)
        return {"ticket_id": ticket_id, "sessions_remaining": -1, "state": "not_found"}

    meta = row.get("metadata") or {}
    sessions_remaining: int = int(meta.get("sessions_remaining", 1))
    sessions_remaining = max(0, sessions_remaining - 1)

    # Persist updated sessions_remaining
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE klaravex_tickets
                   SET metadata = jsonb_set(
                       jsonb_set(metadata, '{sessions_remaining}', $2::jsonb),
                       '{workflow_phase}', $3::jsonb
                   ),
                       updated_at = now()
                 WHERE id::text = $1
                """,
                ticket_id,
                str(sessions_remaining),
                '"revision"' if sessions_remaining > 0 else '"delivering"',
            )
    except Exception as exc:
        log.exception("advance_session metadata update failed: %s", exc)
        return {"ticket_id": ticket_id, "sessions_remaining": sessions_remaining, "state": "update_error"}

    await tickets_lib.append_event(
        ticket_id,
        "session_advanced",
        {"reviewer": reviewer, "sessions_remaining": sessions_remaining,
         "notes_preview": session_notes[:200]},
    )

    if sessions_remaining == 0:
        await mark_delivered(ticket_id)
        return {"ticket_id": ticket_id, "sessions_remaining": 0, "state": "delivered"}

    # Notify Anthony there are more rounds remaining
    try:
        client_email = row.get("client_email", "")
        await send_email(
            to=ALERT_EMAIL,
            subject=f"[Klaravex A2] Resume revision ready — {sessions_remaining} round(s) left — {client_email}",
            body=(
                f"Ticket: {ticket_id}\n"
                f"Client: {client_email}\n"
                f"Sessions remaining: {sessions_remaining}\n"
                f"Notes: {session_notes[:400] or '(none)'}\n\n"
                f"Review queue: GET /api/v1/resume/queue\n"
            ),
        )
    except Exception as exc:
        log.warning("revision-ready alert failed (non-fatal): %s", exc)

    return {"ticket_id": ticket_id, "sessions_remaining": sessions_remaining, "state": "in_revision"}


async def mark_delivered(ticket_id: str) -> None:
    """Transition ticket to DELIVERED state and activate delivery follow-up schedule.

    Called automatically by advance_session when sessions_remaining hits 0.
    Can also be called directly (e.g. from the review queue PATCH endpoint).
    """
    try:
        await tickets_lib.update_status(
            ticket_id,
            status="resolved",
            resolution="Resume delivered to client.",
            workflow_state="DELIVERED",
        )
        await tickets_lib.append_event(ticket_id, "resume_delivered", {})
    except Exception as exc:
        log.exception("mark_delivered status update failed for ticket %s: %s", ticket_id, exc)
        return

    # Activate all scheduled follow-up rows immediately (they're now eligible
    # to be sent based on their send_after_hours offsets from created_at).
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE klaravex_resume_followups
                   SET delivered_at = now()
                 WHERE ticket_id = $1
                   AND delivered_at IS NULL
                """,
                ticket_id,
            )
    except Exception as exc:
        log.warning("follow-up delivered_at stamp failed (non-fatal): %s", exc)

    log.info("resume delivered: ticket=%s", ticket_id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _detect_resume_sku(checkout_session: dict[str, Any]) -> str:
    """Best-effort SKU detection from line items when metadata.sku is absent."""
    session_id = checkout_session.get("id", "")
    if not session_id or not stripe.api_key:
        return ""
    try:
        line_items = stripe.checkout.Session.list_line_items(session_id, limit=5)
        for li in (line_items.get("data") or []):
            price = li.get("price") or {}
            # Check price metadata or product name for SKU hints
            price_meta = price.get("metadata") or {}
            sku_hint = price_meta.get("sku", "").lower()
            if sku_hint in RESUME_SKUS:
                return sku_hint
            # Check product name fallback
            prod = price.get("product")
            if isinstance(prod, dict):
                name = (prod.get("name") or "").lower()
            else:
                name = ""
            for sku in RESUME_SKUS:
                if sku in name:
                    return sku
    except Exception as exc:
        log.warning("line-item SKU detection failed: %s", exc)
    return ""


async def _find_existing_ticket(stripe_session_id: str, sku: str) -> Optional[str]:
    """Return ticket_id if a resume ticket already exists for this Stripe session."""
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


async def _get_ticket_metadata(ticket_id: str) -> Optional[dict[str, Any]]:
    """Fetch client_email + metadata dict for a ticket."""
    try:
        import json
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT client_email, metadata FROM klaravex_tickets WHERE id::text = $1",
                ticket_id,
            )
        if not row:
            return None
        raw_meta = row["metadata"]
        meta = raw_meta if isinstance(raw_meta, dict) else (
            json.loads(raw_meta) if raw_meta else {}
        )
        return {"client_email": row["client_email"], "metadata": meta}
    except Exception as exc:
        log.warning("ticket metadata fetch failed: %s", exc)
        return None


async def _send_intake_email(
    email: str,
    name: Optional[str],
    ticket_id: str,
    sku: str,
    sku_cfg: dict[str, Any],
) -> None:
    greeting = f"Hi {name}," if name else "Hi there,"
    intake_url = f"{PORTAL_BASE_URL}/intake/resume?ticket={ticket_id}"
    revision_line = (
        f"Your package includes {sku_cfg['revision_rounds']} revision round(s) after the initial draft."
        if sku_cfg["revision_rounds"] > 0
        else "Your package includes a single professional review."
    )
    body = (
        f"{greeting}\n\n"
        f"Payment received — thank you for choosing Klaravex Resume ({sku_cfg['label']}).\n\n"
        f"Your ticket reference: {ticket_id}\n\n"
        f"To get started, please take 3–5 minutes to upload your current resume and tell us your goals:\n\n"
        f"  {intake_url}\n\n"
        f"Fields we'll ask for:\n"
        f"  - Current resume (PDF or DOCX upload)\n"
        f"  - Target role\n"
        f"  - LinkedIn URL (optional but recommended)\n"
        f"  - Target industry\n"
        f"  - Salary range (optional)\n"
        f"  - Application deadline (if any)\n\n"
        f"{revision_line}\n\n"
        f"We'll deliver your first draft within {sku_cfg['turnaround_days']} business days of upload.\n\n"
        f"— The Klaravex Team\n"
        f"support@klaravex.com · klaravex.com"
    )
    await send_email(
        to=email,
        subject=f"[Klaravex] Your resume service is ready — ticket {ticket_id}",
        body=body,
    )


async def _alert_anthony_new_resume(
    email: str,
    name: Optional[str],
    ticket_id: str,
    sku: str,
    sku_cfg: dict[str, Any],
    target_role: str,
) -> None:
    subject = f"[Klaravex A2] New resume order — {sku_cfg['label']} — {name or email}"
    body = (
        f"New resume purchase:\n\n"
        f"Ticket:         {ticket_id}\n"
        f"Email:          {email}\n"
        f"Name:           {name or '—'}\n"
        f"SKU:            {sku} ({sku_cfg['label']})\n"
        f"Sessions total: {sku_cfg['sessions_total']}\n"
        f"Revision rounds:{sku_cfg['revision_rounds']}\n"
        f"Target role:    {target_role or '(intake form not yet submitted)'}\n"
        f"Turnaround:     {sku_cfg['turnaround_days']} business days after upload\n\n"
        f"Review queue:   GET /api/v1/resume/queue\n"
        f"Analyze:        POST /api/v1/resume/analyze\n"
    )
    await send_email(to=ALERT_EMAIL, subject=subject, body=body)


async def _schedule_followups(
    ticket_id: str,
    email: str,
    name: Optional[str],
    sku: str,
) -> int:
    """Insert scheduled follow-up rows into klaravex_resume_followups.

    Rows with phase='post_delivery' and phase='job_search' are gated on
    delivered_at being set (the cron job respects this).
    The 'upsell' row sends 30 days after checkout regardless of delivery.

    Returns count of rows inserted.
    """
    pool = await get_pool()
    count = 0
    async with pool.acquire() as conn:
        for item in _POST_INTAKE_FOLLOWUPS:
            try:
                await conn.execute(
                    """
                    INSERT INTO klaravex_resume_followups
                        (ticket_id, client_email, client_name, sku, template,
                         send_after_hours, phase)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (ticket_id, template) DO NOTHING
                    """,
                    ticket_id,
                    email.lower(),
                    name,
                    sku,
                    item["template"],
                    item["offset_hours"],
                    item["phase"],
                )
                count += 1
            except Exception as exc:
                log.warning("followup row insert failed (%s): %s", item["template"], exc)
    return count
