"""
Klaravex consumer intake — drop-in FastAPI router.

Mount with:
    from infra.klara.handlers.intake_consumer import router as consumer_intake
    app.include_router(consumer_intake, prefix="/api/v1/intake")
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

log = logging.getLogger("klaravex.intake_consumer")
router = APIRouter()

ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")


class ConsumerIntake(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=40)
    primary_issue: str = Field(min_length=2, max_length=2000)
    urgency: str = Field(default="standard", pattern="^(low|standard|high|emergency)$")
    referrer: Optional[str] = Field(default=None, max_length=300)
    sku_interest: Optional[str] = Field(default=None, max_length=80)


@router.post("/consumer", status_code=202)
@limiter.limit("20/minute")
async def consumer_intake(request: Request, payload: ConsumerIntake) -> dict[str, str]:
    received_at = datetime.now(timezone.utc).isoformat()
    subject = f"[Klaravex Intake] {payload.urgency.upper()} — {payload.name}"
    body = (
        f"Received: {received_at}\n"
        f"Name:     {payload.name}\n"
        f"Email:    {payload.email}\n"
        f"Phone:    {payload.phone or '—'}\n"
        f"Urgency:  {payload.urgency}\n"
        f"Interest: {payload.sku_interest or '—'}\n"
        f"Referrer: {payload.referrer or '—'}\n\n"
        f"Issue:\n{payload.primary_issue}\n"
    )

    # Persist as ticket (best-effort; do not fail intake if DB unavailable).
    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=str(payload.email),
            subject=f"Consumer intake: {payload.name}",
            severity=payload.urgency,
            status="open",
            source="intake_consumer",
            archetype="A2",
            sku=payload.sku_interest,
            summary=payload.primary_issue[:500],
            segment_hint="consumer",
            metadata={
                "name": payload.name,
                "phone": payload.phone,
                "referrer": payload.referrer,
            },
        )
    except Exception as e:  # noqa: BLE001
        log.warning("ticket persistence failed (continuing): %s", e)

    try:
        await send_email(ALERT_EMAIL, subject, body + (f"\nTicket: {ticket_id}\n" if ticket_id else ""))
    except Exception as e:  # noqa: BLE001
        log.exception("intake_consumer email failed: %s", e)
        raise HTTPException(status_code=500, detail="failed to dispatch intake")

    # Emergency urgency → escalate immediately.
    if payload.urgency == "emergency" and ticket_id:
        try:
            await escalation_lib.escalate(
                ticket_id=ticket_id,
                client_email=str(payload.email),
                severity="emergency",
                summary=f"Emergency consumer intake from {payload.name}",
                attempted="Captured intake and emailed Anthony",
                recommended="Phone call within 30 minutes",
            )
        except Exception as e:  # noqa: BLE001
            log.exception("emergency escalation failed: %s", e)

    return {"status": "accepted", "received_at": received_at, "ticket_id": ticket_id or ""}
