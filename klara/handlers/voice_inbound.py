"""A9 Twilio inbound voice handler.

Twilio POSTs form-encoded data here on every inbound call to the Klaravex
main line (+14243486010). Returns TwiML that:
  1. Greets the caller with the required US recording disclosure.
  2. Offers a DTMF + speech menu.
  3. /menu endpoint routes the gather result.

See WORKFLOWS.md §A9.1–A9.3.
"""

import logging
import os
from typing import Annotated

from fastapi import APIRouter, Form, Response

log = logging.getLogger("klaravex.voice.inbound")
router = APIRouter()

BASE_URL = os.environ.get("API_BASE_URL", "https://api.klaravex.com")


# ---------------------------------------------------------------------------
# /api/v1/voice/inbound — Twilio Voice webhook entry
# ---------------------------------------------------------------------------

@router.post("/inbound")
async def voice_inbound(
    CallSid: Annotated[str, Form()] = "",
    From: Annotated[str, Form()] = "",
    To: Annotated[str, Form()] = "",
    CallStatus: Annotated[str, Form()] = "",
) -> Response:
    """Return TwiML greeting + <Gather> menu for all inbound calls."""
    log.info("inbound call sid=%s from=%s status=%s", CallSid, From, CallStatus)

    menu_url = f"{BASE_URL}/api/v1/voice/menu"
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    Hi, you've reached Klaravex. I'm Klara AI, the AI assistant.
    This call may be recorded for quality and training purposes.
  </Say>
  <Gather action="{menu_url}" method="POST" numDigits="1"
          input="dtmf speech" speechTimeout="3" timeout="8">
    <Say voice="Polly.Joanna">
      Press 1, or say IT support, for help with a tech issue right now.
      Press 2, or say specialist, to speak with a human expert.
    </Say>
  </Gather>
  <Redirect method="POST">{menu_url}?Digits=timeout</Redirect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


# ---------------------------------------------------------------------------
# /api/v1/voice/menu — handles <Gather> result
# ---------------------------------------------------------------------------

@router.post("/menu")
async def voice_menu(
    CallSid: Annotated[str, Form()] = "",
    From: Annotated[str, Form()] = "",
    Digits: Annotated[str, Form()] = "",
    SpeechResult: Annotated[str, Form()] = "",
) -> Response:
    """Route the caller based on DTMF digit or speech result."""
    log.info("menu sid=%s digits=%r speech=%r", CallSid, Digits, SpeechResult)

    speech = SpeechResult.lower()
    digit = (Digits or "").strip()

    # Determine intent from digit or speech
    wants_support = (
        digit == "1"
        or any(k in speech for k in ("support", "help", "issue", "problem", "fix", "tech"))
    )
    wants_specialist = (
        digit == "2"
        or any(k in speech for k in ("specialist", "human", "person", "anthony", "expert", "talk"))
    )

    escalate_url = f"{BASE_URL}/api/v1/voice/escalate"
    gather_issue_url = f"{BASE_URL}/api/v1/voice/gather_issue"

    if wants_support:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    Great. There is a $79 per-incident fee — I will send you a payment link
    while we talk so you can pay on your own time. Stay on the line.
  </Say>
  <Redirect method="POST">{gather_issue_url}</Redirect>
</Response>"""

    elif wants_specialist:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    Sure thing. Let me bring in our on-call engineer. Please hold for just a moment.
  </Say>
  <Redirect method="POST">{escalate_url}</Redirect>
</Response>"""

    else:
        # Unclear / timeout — collect more context
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    Sorry, I didn't catch that. Let me connect you with our on-call engineer.
  </Say>
  <Redirect method="POST">{escalate_url}</Redirect>
</Response>"""

    return Response(content=twiml, media_type="application/xml")
