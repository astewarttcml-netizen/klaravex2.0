"""A9 Twilio voice: escalate to Anthony.

Creates a Twilio conference bridge and dials Anthony's mobile to join the
active call. If ANTHONY_MOBILE_E164 is not set, reads a graceful message
instead of attempting the dial.

See WORKFLOWS.md §A9.5 step 6, §A9.7.
"""

import logging
import os
from typing import Annotated

import httpx
from fastapi import APIRouter, Form, Request, Response

from .lib.email import send_email
from .lib.rate_limit import limiter

log = logging.getLogger("klaravex.voice.escalate")
router = APIRouter()

TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "TWILIO_ACCOUNT_SID_REDACTED")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.environ.get("TWILIO_FROM_NUMBER", "+14243486010")
ANTHONY_MOBILE = os.environ.get("ANTHONY_MOBILE_E164", "")  # no default per spec
BASE_URL = os.environ.get("API_BASE_URL", "https://api.klaravex.com")

ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")


@router.post("/escalate")
@limiter.limit("5/minute")
async def voice_escalate(
    request: Request,
    CallSid: Annotated[str, Form()] = "",
    From: Annotated[str, Form()] = "",
    SpeechResult: Annotated[str, Form()] = "",
    Digits: Annotated[str, Form()] = "",
) -> Response:
    """Bridge caller to Anthony via conference, or leave graceful message if mobile not set."""
    log.info("escalate sid=%s from=%s speech=%r digits=%r", CallSid, From, SpeechResult, Digits)

    # Check if caller said "yes" / pressed 1 (resolved — no escalation needed)
    digit = (Digits or "").strip()
    speech = SpeechResult.lower()
    if digit == "1" or "yes" in speech or "thank" in speech or "good" in speech:
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    Wonderful. I'm glad we got that sorted. Don't hesitate to call back anytime.
    Have a great day!
  </Say>
  <Hangup/>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    # Fire Telegram + email alert regardless of bridge availability
    await _alert_anthony(CallSid, From, SpeechResult)

    conference_name = f"klaravex-{CallSid}"

    if not ANTHONY_MOBILE:
        # Per spec: skip dial if ANTHONY_MOBILE_E164 not set
        log.warning("ANTHONY_MOBILE_E164 not set; cannot bridge call %s", CallSid)
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    I'm transferring you to our on-call engineer now. Please hold for just a moment.
  </Say>
  <Dial>
    <Conference waitUrl="https://twimlets.com/holdmusic?Bucket=com.twilio.music.classical"
                startConferenceOnEnter="true"
                endConferenceOnExit="true">
      {conference_name}
    </Conference>
  </Dial>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    # Dial Anthony into the same conference
    await _dial_anthony(conference_name, CallSid)

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    I'm bringing in Anthony now. Please hold for just a moment.
  </Say>
  <Dial>
    <Conference waitUrl="https://twimlets.com/holdmusic?Bucket=com.twilio.music.classical"
                startConferenceOnEnter="true"
                endConferenceOnExit="true">
      {conference_name}
    </Conference>
  </Dial>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


async def _dial_anthony(conference_name: str, call_sid: str) -> None:
    """Outbound Twilio call to Anthony's mobile that joins the conference."""
    if not (TWILIO_SID and TWILIO_TOKEN and ANTHONY_MOBILE):
        return

    # TwiML URL that puts Anthony straight into the conference
    conference_twiml_url = (
        f"{BASE_URL}/api/v1/voice/conference_join?name={conference_name}"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Calls.json",
                auth=(TWILIO_SID, TWILIO_TOKEN),
                data={
                    "From": TWILIO_FROM,
                    "To": ANTHONY_MOBILE,
                    "Url": conference_twiml_url,
                },
            )
            if r.status_code >= 300:
                log.warning("anthony dial failed: %s %s", r.status_code, r.text[:200])
    except Exception as e:  # noqa: BLE001
        log.warning("anthony dial exception: %s", e)


@router.post("/conference_join")
async def conference_join(name: str = "") -> Response:
    """TwiML served to Anthony's outbound call leg to drop him into the conference."""
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    Klaravex call. A client is waiting for your assistance.
  </Say>
  <Dial>
    <Conference startConferenceOnEnter="true" endConferenceOnExit="true">
      {name}
    </Conference>
  </Dial>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


async def _alert_anthony(call_sid: str, caller: str, summary: str) -> None:
    """Send Telegram + email alert to Anthony when a call is escalated."""
    subject = f"[Klaravex A9] ESCALATION — inbound call {call_sid}"
    body = (
        f"Inbound call escalated to Anthony.\n"
        f"Call SID: {call_sid}\n"
        f"Caller: {caller}\n"
        f"Context: {summary or 'caller requested human'}\n"
    )
    try:
        await send_email(to=ALERT_EMAIL, subject=subject, body=body)
        if TELEGRAM_TOKEN and TELEGRAM_CHAT:
            async with httpx.AsyncClient(timeout=8) as client:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": TELEGRAM_CHAT, "text": f"{subject}\n\n{body}"},
                )
    except Exception as e:  # noqa: BLE001
        log.warning("alert_anthony failed: %s", e)
