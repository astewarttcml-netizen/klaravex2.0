"""
Klaravex per-incident intake handler — T6.1.3.

FastAPI router at /api/v1/intake/per-incident.

Accepts a free-form service request from a consumer who has purchased
or intends to purchase the per-incident SKU. Validates, creates a
ticket, sends a confirmation email via Resend, and returns a ticket ID.

Mount with:
    from klara.handlers.intake_per_incident import router as per_incident_router
    app.include_router(per_incident_router, prefix="/api/v1/intake", tags=["Intake per-incident"])

Required env vars (optional — email skipped if absent):
    SMTP_PASS                (M365 SMTP password)
    SMTP_USER                default: support@klaravex.com
    ANTHONY_ALERT_EMAIL      default: astewart@klaravex.com
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from .lib import tickets as tickets_lib
from .lib import escalation as escalation_lib
from .lib.email import send_email
from .lib.rate_limit import limiter

log = logging.getLogger("klaravex.intake_per_incident")
router = APIRouter()

ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")

NEXT_STEP_STD = "A support engineer will contact you within 2 hours."
NEXT_STEP_HIGH = "A support engineer will contact you within 30 minutes."


class PerIncidentIntake(BaseModel):
    issue_description: str = Field(min_length=2, max_length=3000)
    device_type: Optional[str] = Field(default=None, max_length=120)
    urgency: str = Field(default="standard", pattern="^(low|standard|high|emergency)$")
    screen_share_ok: bool = Field(default=False)
    best_time: Optional[str] = Field(default=None, max_length=200)
    contact_email: Optional[EmailStr] = Field(default=None)
    contact_name: Optional[str] = Field(default=None, max_length=120)
    contact_phone: Optional[str] = Field(default=None, max_length=40)


async def _send_confirmation(
    to_email: str,
    contact_name: Optional[str],
    ticket_id: str,
    urgency: str,
) -> None:
    """Send a confirmation email to the client."""
    name = contact_name or "there"
    next_step = NEXT_STEP_HIGH if urgency in ("high", "emergency") else NEXT_STEP_STD
    body = (
        f"Hi {name},\n\n"
        f"We've received your support request. Your ticket reference is:\n\n"
        f"  {ticket_id}\n\n"
        f"{next_step}\n\n"
        f"You can view your ticket status in the Klaravex client portal:\n"
        f"  https://klaravex.com/portal/\n\n"
        f"If your situation is urgent, reply to this email or call us directly.\n\n"
        f"— Klaravex Support\n"
        f"support@klaravex.com · klaravex.com"
    )
    await send_email(
        to=to_email,
        subject=f"[Klaravex] Your support request — ticket {ticket_id}",
        body=body,
    )


async def _alert_anthony(payload: PerIncidentIntake, ticket_id: str) -> None:
    """Alert Anthony about a new per-incident intake."""
    subject = f"[Klaravex Per-Incident] {payload.urgency.upper()} — {payload.contact_name or payload.contact_email or 'anonymous'}"
    body = (
        f"New per-incident support request:\n\n"
        f"Ticket:    {ticket_id}\n"
        f"Name:      {payload.contact_name or '—'}\n"
        f"Email:     {payload.contact_email or '—'}\n"
        f"Phone:     {payload.contact_phone or '—'}\n"
        f"Device:    {payload.device_type or '—'}\n"
        f"Urgency:   {payload.urgency}\n"
        f"Screen OK: {'Yes' if payload.screen_share_ok else 'No'}\n"
        f"Best time: {payload.best_time or '—'}\n\n"
        f"Issue:\n{payload.issue_description}\n"
    )
    await send_email(to=ALERT_EMAIL, subject=subject, body=body)


@router.post("/per-incident", status_code=202)
@limiter.limit("20/minute")
async def per_incident_intake(request: Request, payload: PerIncidentIntake) -> dict:
    """
    Accept a per-incident support request.

    - Validates the request.
    - INSERTs a ticket row to klaravex_tickets.
    - Sends a confirmation email to contact_email (if provided).
    - Alerts Anthony via Resend.
    - Escalates immediately if urgency is high or emergency.
    - Returns ticket_id, status, and next_step instructions.
    """
    received_at = datetime.now(timezone.utc).isoformat()

    # Determine effective email for ticket (may be anonymous).
    client_email = str(payload.contact_email) if payload.contact_email else "anonymous@klaravex.com"

    # Persist ticket (best-effort; never fail the intake).
    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=client_email,
            subject=f"Per-incident: {(payload.issue_description[:80] + '…') if len(payload.issue_description) > 80 else payload.issue_description}",
            severity=payload.urgency,
            status="open",
            source="intake_consumer",
            archetype="A2",
            sku="per-incident",
            summary=payload.issue_description[:500],
            segment_hint="consumer",
            metadata={
                "device_type": payload.device_type,
                "screen_share_ok": payload.screen_share_ok,
                "best_time": payload.best_time,
                "contact_name": payload.contact_name,
                "contact_phone": payload.contact_phone,
                "received_at": received_at,
            },
        )
    except Exception as exc:
        log.warning("ticket persistence failed (continuing): %s", exc)

    # Send confirmation to client if email provided.
    if payload.contact_email and ticket_id:
        try:
            await _send_confirmation(
                str(payload.contact_email),
                payload.contact_name,
                ticket_id,
                payload.urgency,
            )
        except Exception as exc:
            log.warning("confirmation email failed (non-fatal): %s", exc)

    # Alert Anthony.
    try:
        await _alert_anthony(payload, ticket_id or "pending")
    except Exception as exc:
        log.warning("Anthony alert failed (non-fatal): %s", exc)

    # Immediate escalation for high/emergency severity.
    if payload.urgency in ("high", "emergency") and ticket_id:
        try:
            await escalation_lib.escalate(
                ticket_id=ticket_id,
                client_email=client_email,
                severity=payload.urgency,
                summary=f"{payload.urgency.upper()} per-incident from {payload.contact_name or client_email}: {payload.issue_description[:200]}",
                attempted="Intake captured; confirmation sent; Anthony alerted",
                recommended="Contact client within 30 minutes — screen share if authorized",
            )
        except Exception as exc:
            log.exception("escalation failed (non-fatal): %s", exc)

    next_step = NEXT_STEP_HIGH if payload.urgency in ("high", "emergency") else NEXT_STEP_STD

    return {
        "ticket_id": ticket_id or "",
        "status": "received",
        "next_step": next_step,
    }


# ---------------------------------------------------------------------------
# Session lifecycle endpoints — called by Anthony's admin tooling or Vapi.
# ---------------------------------------------------------------------------

class ResolvePayload(BaseModel):
    ticket_id: str
    resolution_notes: str = ""
    resolved_by: str = "loki"


class RefundPayload(BaseModel):
    ticket_id: str
    reason: str = "out_of_scope"


@router.post("/per-incident/resolve", status_code=200)
async def per_incident_resolve(payload: ResolvePayload) -> dict:
    """Mark a per-incident ticket as resolved and trigger follow-up schedule."""
    from .lib.per_incident_session import resolve as session_resolve
    try:
        await session_resolve(
            payload.ticket_id,
            resolution_notes=payload.resolution_notes,
            resolved_by=payload.resolved_by,
        )
    except Exception as exc:
        log.exception("resolve endpoint failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ticket_id": payload.ticket_id, "status": "resolved"}


@router.post("/per-incident/refund", status_code=200)
async def per_incident_refund(payload: RefundPayload) -> dict:
    """Initiate an out-of-scope refund for a per-incident ticket."""
    from .lib.per_incident_session import escalate_out_of_scope
    try:
        await escalate_out_of_scope(payload.ticket_id, reason=payload.reason)
    except Exception as exc:
        log.exception("refund endpoint failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ticket_id": payload.ticket_id, "status": "refunded"}
