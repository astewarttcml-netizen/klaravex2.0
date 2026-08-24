"""A9 Twilio voice: post-troubleshoot callback / queue options.

Presented when Klara AI can't resolve an issue or the payment window expires.
Offers the caller two paths:
  1 — Hold for the next available tech (conference bridge)
  2 — We'll call you back (logs request, alerts Anthony, graceful hang-up)
Timeout defaults to callback so the call never dead-ends with <Hangup/>.
"""

import logging
import os
from typing import Annotated

import httpx
from fastapi import APIRouter, Form, Response

from .lib.email import send_email

log = logging.getLogger("klaravex.voice.callback_options")
router = APIRouter()

BASE_URL = os.environ.get("API_BASE_URL", "https://api.klaravex.com")
ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")


@router.post("/callback_options")
async def voice_callback_options(
    CallSid: Annotated[str, Form()] = "",
    From: Annotated[str, Form()] = "",
    SpeechResult: Annotated[str, Form()] = "",
    Digits: Annotated[str, Form()] = "",
) -> Response:
    """Present queue-or-callback menu on first hit; route on second hit."""
    digit = (Digits or "").strip()
    speech = (SpeechResult or "").lower()

    escalate_url = f"{BASE_URL}/api/v1/voice/escalate"
    self_url = f"{BASE_URL}/api/v1/voice/callback_options"

    # No input yet — ask the question
    if not digit and not speech:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather action="{self_url}" method="POST" input="speech dtmf"
          timeout="10" speechTimeout="3" numDigits="1">
    <Say voice="Polly.Joanna">
      No problem. Press 1 or say hold to stay on the line for the next available tech.
      Press 2 or say callback and we will call you back within two hours.
    </Say>
  </Gather>
  <!-- Timeout: default to callback so the call never dead-ends -->
  <Redirect method="POST">{self_url}?_default_callback=1</Redirect>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    wants_queue = (
        digit == "1"
        or any(k in speech for k in ("hold", "wait", "stay", "queue", "now"))
    )
    wants_callback = (
        digit == "2"
        or any(k in speech for k in ("callback", "call back", "call me", "later", "busy"))
    )

    if wants_queue:
        # Put caller in conference bridge — escalate handler manages the dial-out
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    Got it. Connecting you to the next available tech now. Please hold.
  </Say>
  <Redirect method="POST">{escalate_url}</Redirect>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    # Default: callback (covers wants_callback=True AND timeout default)
    await _log_callback(CallSid, From)

    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    Perfect. We have your number and will call you back within two hours.
    You will receive a text confirmation shortly. Have a great day!
  </Say>
  <Hangup/>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


async def _log_callback(call_sid: str, caller: str) -> None:
    """Alert Anthony via Telegram + email that a callback was requested."""
    subject = f"[Klaravex] Callback requested — {caller}"
    body = (
        f"A caller requested a callback.\n"
        f"Phone: {caller}\n"
        f"Call SID: {call_sid}\n\n"
        f"Call them back within 2 hours."
    )
    log.info("callback requested from=%s sid=%s", caller, call_sid)
    try:
        await send_email(to=ALERT_EMAIL, subject=subject, body=body)
        if TELEGRAM_TOKEN and TELEGRAM_CHAT:
            async with httpx.AsyncClient(timeout=8) as client:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": TELEGRAM_CHAT, "text": f"{subject}\n\n{body}"},
                )
    except Exception as e:  # noqa: BLE001
        log.warning("callback alert failed: %s", e)
