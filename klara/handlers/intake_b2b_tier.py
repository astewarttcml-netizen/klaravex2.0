"""
B2B tier onboarding intake handler — T6.6.3.

FastAPI router at /api/v1/intake/b2b-tier.
Accepts structured B2B prospect data, creates client + ticket records,
notifies Anthony via escalation lib, and returns a next-steps acknowledgement.

Accepted body:
    {
        "company_name":     str,
        "contact_name":     str,
        "email":            str,
        "phone":            str | null,
        "employee_count":   int,
        "current_it_setup": str,
        "tier":             "foundation" | "assurance" | "directive",
        "urgency":          "low" | "standard" | "high" | "emergency"
    }

Returns:
    {
        "client_id":  uuid,
        "status":     "intake_received",
        "next_step":  "A senior engineer will contact you within 2 business hours"
    }

Mount with:
    from infra.klara.handlers.intake_b2b_tier import router as intake_b2b_tier_router
    app.include_router(intake_b2b_tier_router, prefix="/api/v1/intake")
"""

import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from .lib import escalation as escalation_lib
from .lib import tickets as tickets_lib
from .lib.email import send_email
from .lib.rate_limit import limiter

log = logging.getLogger("klaravex.intake_b2b_tier")
router = APIRouter()

APPROVAL_NOTIFY_EMAIL = os.environ.get(
    "APPROVAL_NOTIFY_EMAIL",
    os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com"),
)

NEXT_STEP_MSG = "A senior engineer will contact you within 2 business hours"


class B2BTierIntake(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    contact_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    employee_count: int = Field(ge=1, le=100_000)
    current_it_setup: str = Field(min_length=2, max_length=2000)
    tier: str = Field(
        default="foundation",
        pattern="^(foundation|assurance|directive)$",
    )
    urgency: str = Field(
        default="standard",
        pattern="^(low|standard|high|emergency)$",
    )


async def _send_confirmation_email(to: str, name: str, company: str, tier: str) -> None:
    subject = f"Klaravex — We've received your {tier.title()} inquiry"
    body = (
        f"Hi {name},\n\n"
        f"Thank you for reaching out about Klaravex {tier.title()} for {company}.\n\n"
        f"We've received your information and a senior engineer will be in contact within 2 business hours "
        f"to discuss your IT environment and how Klaravex can help.\n\n"
        f"In the meantime, if you have any urgent questions, reply to this email or call us directly.\n\n"
        f"— The Klaravex Team\n"
    )
    await send_email(to=to, subject=subject, body=body)


async def _send_notify_email(payload: B2BTierIntake, client_id: str, ticket_id: str | None) -> None:
    subject = (
        f"[Klaravex B2B] {payload.urgency.upper()} — {payload.company_name} "
        f"({payload.employee_count} seats) — {payload.tier.title()}"
    )
    body = (
        f"New B2B tier intake received.\n\n"
        f"Company:       {payload.company_name}\n"
        f"Contact:       {payload.contact_name}\n"
        f"Email:         {str(payload.email)}\n"
        f"Phone:         {payload.phone or '—'}\n"
        f"Employees:     {payload.employee_count}\n"
        f"Tier:          {payload.tier}\n"
        f"Urgency:       {payload.urgency}\n"
        f"Client ID:     {client_id}\n"
        f"Ticket ID:     {ticket_id or '—'}\n\n"
        f"Current IT setup:\n{payload.current_it_setup}\n"
    )
    await send_email(to=APPROVAL_NOTIFY_EMAIL, subject=subject, body=body)


@router.post("/b2b-tier", status_code=201)
@limiter.limit("20/minute")
async def intake_b2b_tier(request: Request, payload: B2BTierIntake) -> dict[str, str]:
    """Intake a new B2B tier prospect. Creates client + ticket, notifies Anthony."""
    client_id: str | None = None
    try:
        client_id = await tickets_lib.get_or_create_client(
            email=str(payload.email),
            segment="b2b",
            name=payload.contact_name,
            phone=payload.phone,
            company=payload.company_name,
            metadata={
                "employee_count": payload.employee_count,
                "tier_interest": payload.tier,
                "source": "intake_b2b_tier",
                "intake_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as e:  # noqa: BLE001
        log.warning("client upsert failed (continuing): %s", e)
        client_id = str(uuid.uuid4())

    ticket_id: str | None = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=str(payload.email),
            subject=f"B2B tier intake: {payload.company_name} — {payload.tier}",
            severity=payload.urgency,
            status="open",
            source="intake_b2b",
            archetype="A3",
            sku=payload.tier,
            summary=(
                f"{payload.company_name} ({payload.employee_count} seats) requesting {payload.tier}. "
                f"IT setup: {payload.current_it_setup[:200]}"
            ),
            segment_hint="b2b",
            metadata={
                "company_name": payload.company_name,
                "contact_name": payload.contact_name,
                "employee_count": payload.employee_count,
                "current_it_setup": payload.current_it_setup,
            },
        )
    except Exception as e:  # noqa: BLE001
        log.warning("ticket creation failed (continuing): %s", e)

    # Notify Anthony via email (always) + escalation lib for high/emergency.
    try:
        await _send_notify_email(payload, client_id, ticket_id)
    except Exception as e:  # noqa: BLE001
        log.exception("notify email failed: %s", e)

    if payload.urgency in ("high", "emergency") and ticket_id:
        try:
            await escalation_lib.escalate(
                ticket_id=ticket_id,
                client_email=str(payload.email),
                severity=payload.urgency,
                summary=(
                    f"{payload.urgency.upper()} B2B intake: {payload.company_name} "
                    f"({payload.employee_count} seats) — {payload.tier} tier"
                ),
                attempted="Captured intake and emailed Anthony",
                recommended="Call within 30 minutes; lead with Directive tier triage",
            )
        except Exception as e:  # noqa: BLE001
            log.exception("escalation failed: %s", e)

    # Confirmation email to prospect.
    try:
        await _send_confirmation_email(
            str(payload.email), payload.contact_name, payload.company_name, payload.tier
        )
    except Exception as e:  # noqa: BLE001
        log.warning("confirmation email failed (continuing): %s", e)

    if not client_id:
        raise HTTPException(status_code=500, detail="client record creation failed")

    return {
        "client_id": client_id,
        "status": "intake_received",
        "next_step": NEXT_STEP_MSG,
    }
