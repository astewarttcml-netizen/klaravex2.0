"""
Klaravex B2B intake handler — drop-in FastAPI router.

Mount with:
    from infra.klara.handlers.intake_b2b import router as b2b_intake
    app.include_router(b2b_intake, prefix="/api/v1/intake")
"""
import os
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from .lib import tickets as tickets_lib
from .lib import escalation as escalation_lib
from .lib.email import send_email
from .lib.rate_limit import limiter

log = logging.getLogger("klaravex.intake_b2b")
router = APIRouter()

ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")


class B2BIntake(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    company: str = Field(min_length=1, max_length=200)
    employee_count: int = Field(ge=1, le=100000)
    primary_cloud: str = Field(default="other", pattern="^(m365|gws|aws|multi|other)$")
    primary_concern: str = Field(min_length=2, max_length=2000)
    urgency: str = Field(default="standard", pattern="^(low|standard|high|emergency)$")
    tier_interest: Optional[str] = Field(default=None, max_length=80)


@router.post("/b2b", status_code=202)
@limiter.limit("20/minute")
async def b2b_intake(request: Request, payload: B2BIntake) -> dict[str, str]:
    received_at = datetime.now(timezone.utc).isoformat()
    subject = f"[Klaravex B2B] {payload.urgency.upper()} — {payload.company} ({payload.employee_count})"
    body = (
        f"Received:      {received_at}\n"
        f"Name:          {payload.name}\n"
        f"Email:         {payload.email}\n"
        f"Company:       {payload.company}\n"
        f"Employees:     {payload.employee_count}\n"
        f"Primary cloud: {payload.primary_cloud}\n"
        f"Tier interest: {payload.tier_interest or '—'}\n"
        f"Urgency:       {payload.urgency}\n\n"
        f"Primary concern:\n{payload.primary_concern}\n"
    )
    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=str(payload.email),
            subject=f"B2B intake: {payload.company} ({payload.employee_count} seats)",
            severity=payload.urgency,
            status="open",
            source="intake_b2b",
            archetype="A3",
            sku=payload.tier_interest,
            summary=payload.primary_concern[:500],
            segment_hint="b2b",
            metadata={
                "name": payload.name,
                "company": payload.company,
                "employee_count": payload.employee_count,
                "primary_cloud": payload.primary_cloud,
            },
        )
    except Exception as e:  # noqa: BLE001
        log.warning("ticket persistence failed (continuing): %s", e)

    try:
        await send_email(ALERT_EMAIL, subject, body + (f"\nTicket: {ticket_id}\n" if ticket_id else ""))
    except Exception as e:  # noqa: BLE001
        log.exception("intake_b2b email failed: %s", e)
        raise HTTPException(status_code=500, detail="failed to dispatch intake")

    if payload.urgency == "emergency" and ticket_id:
        try:
            await escalation_lib.escalate(
                ticket_id=ticket_id,
                client_email=str(payload.email),
                severity="emergency",
                summary=f"Emergency B2B intake from {payload.company}",
                attempted="Captured intake and emailed Anthony",
                recommended="Phone call within 30 minutes; recommend Directive tier triage",
            )
        except Exception as e:  # noqa: BLE001
            log.exception("emergency escalation failed: %s", e)

    return {"status": "accepted", "received_at": received_at, "ticket_id": ticket_id or ""}
