"""A9 Vapi tool: escalate_to_anthony.

Pages Anthony via Telegram + email, optionally dials his mobile and bridges
to the active Vapi call. See WORKFLOWS.md §A9.7.
"""

import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..lib.email import send_email

log = logging.getLogger("klaravex.vapi.escalate")
router = APIRouter()

ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
ANTHONY_MOBILE = os.environ.get("ANTHONY_MOBILE_E164", "")
TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.environ.get("TWILIO_FROM_NUMBER", "")


class EscalateRequest(BaseModel):
    call_sid: str = Field(default="")
    reason: str = Field(default="caller requested human")
    summary: str = Field(default="")
    severity: str = Field(default="high")
    bridge_call: bool = Field(default=False)
    test: bool = Field(default=False, alias="_test")


@router.post("/escalate_to_anthony")
async def escalate_to_anthony(req: EscalateRequest) -> dict[str, Any]:
    if req.test:
        return {"status": "ok", "test": True}

    subject = f"[Klaravex A9] {req.severity.upper()} — {req.reason}"
    body = (
        f"Vapi call escalation\nCall SID: {req.call_sid}\nReason: {req.reason}\n"
        f"Severity: {req.severity}\n\nSummary:\n{req.summary}\n"
    )

    bridge_sid = None
    await send_email(to=ALERT_EMAIL, subject=subject, body=body)
    async with httpx.AsyncClient(timeout=10) as client:
        if TELEGRAM_TOKEN and TELEGRAM_CHAT:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT, "text": f"{subject}\n\n{body}"},
            )
        if req.bridge_call and ANTHONY_MOBILE and TWILIO_SID and req.call_sid:
            r = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Calls.json",
                auth=(TWILIO_SID, TWILIO_TOKEN),
                data={
                    "From": TWILIO_FROM,
                    "To": ANTHONY_MOBILE,
                    "Url": f"https://api.klaravex.com/api/v1/vapi/_bridge_twiml?call_sid={req.call_sid}",
                },
            )
            if r.status_code < 300:
                bridge_sid = r.json().get("sid")

    return {"status": "ok", "bridge_call_sid": bridge_sid}
