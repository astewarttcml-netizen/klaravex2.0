"""Klaravex consumer scam escalation — escalate_to_sam.

Chat-time escalation for active scams / identity theft / fraud on the
personal surface. Emails Sam (Klaravex Identity Recovery) and opens a
Critical Atera ticket under Personal Clients. NEVER pages Anthony —
consumer scam alerts route exclusively to Sam's team.

The [chat-scam] case tag in the ticket title lets the agentmail inbound
webhook dedupe against this ticket instead of creating a duplicate when
Sam's reply thread comes back in.
"""

import logging
import os
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..lib.email import send_email

log = logging.getLogger("klaravex.vapi.escalate_sam")
router = APIRouter()

SAM_ALERT_EMAIL = os.environ.get("SAM_ALERT_EMAIL", "sam@ai.klaravex.com")
CASE_TAG = "[chat-scam]"


class EscalateToSamRequest(BaseModel):
    call_sid: str = Field(default="")
    reason: str = Field(default="scam escalation")
    summary: str = Field(default="")
    severity: str = Field(default="high")
    caller_email: str = Field(default="")
    caller_phone: str = Field(default="")
    caller_name: str = Field(default="")
    test: bool = Field(default=False, alias="_test")


@router.post("/escalate_to_sam")
async def escalate_to_sam(req: EscalateToSamRequest) -> dict[str, Any]:
    if req.test:
        return {"status": "ok", "test": True}

    subject = f"[Klaravex Consumer Scam] {req.severity.upper()} — {req.reason}"
    contact_line = (
        f"Contact: {req.caller_name or 'n/a'}"
        + (f" <{req.caller_email}>" if req.caller_email else "")
        + (f" | phone {req.caller_phone}" if req.caller_phone else "")
    )
    body = (
        f"Consumer scam / identity recovery escalation\n"
        f"Chat session: {req.call_sid}\n"
        f"Reason: {req.reason}\n"
        f"Severity: {req.severity}\n"
        f"{contact_line}\n\n"
        f"Summary:\n{req.summary}\n"
    )

    # Atera ticket — only when we have a real customer email to attach it to.
    # Any failure here must NOT block the email to Sam, so wrap and continue.
    ticket: dict[str, Any] = {}
    atera_error: str | None = None
    api_key = os.environ.get("ATERA_API_KEY", "")
    if api_key and req.caller_email:
        try:
            from services.atera_client import AteraClient

            client = AteraClient(api_key)
            customer_id = await client.get_or_create_personal_customer()
            parts = ((req.caller_name or "Scam").strip().split(" ", 1) + [""])[:2]
            contact_id = await client.get_or_create_contact(
                customer_id=customer_id,
                email=req.caller_email,
                firstname=parts[0] or "Unknown",
                lastname=parts[1] or "Client",
                phone=req.caller_phone,
            )
            ticket = await client.create_ticket(
                end_user_id=contact_id,
                title=f"{CASE_TAG} Identity recovery — {req.reason[:60]}",
                first_comment=body,
                priority="Critical",
            )
        except Exception:  # noqa: BLE001 — email to Sam must still fire
            atera_error = "Atera ticket creation failed (see logs)"
            log.exception("escalate_sam.atera_failed")

    await send_email(to=SAM_ALERT_EMAIL, subject=subject, body=body)

    return {
        "status": "ok",
        "ticket_id": ticket.get("ticket_id"),
        "ticket_number": ticket.get("ticket_number"),
        "atera_error": atera_error,
        "notified": SAM_ALERT_EMAIL,
    }
