"""A9 Twilio voice: gather caller's issue description before payment.

Inserted between /voice/menu (press 1) and /voice/gather_email so that
Klara AI already knows the problem when troubleshooting starts after payment.
Stores description in voice_session_store keyed by CallSid.
"""

import logging
import os
from typing import Annotated

from fastapi import APIRouter, Form, Response

from . import voice_session_store as store

log = logging.getLogger("klaravex.voice.gather_issue")
router = APIRouter()

BASE_URL = os.environ.get("API_BASE_URL", "https://api.klaravex.com")


@router.post("/gather_issue")
async def voice_gather_issue(
    CallSid: Annotated[str, Form()] = "",
    From: Annotated[str, Form()] = "",
    SpeechResult: Annotated[str, Form()] = "",
) -> Response:
    """Ask the caller what's wrong; store it, then proceed to email/payment."""
    gather_email_url = f"{BASE_URL}/api/v1/voice/gather_email"
    self_url = f"{BASE_URL}/api/v1/voice/gather_issue"

    if SpeechResult:
        store.set_value(CallSid, "issue", SpeechResult)
        log.info("stored issue sid=%s: %r", CallSid, SpeechResult[:120])
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">Got it — I have that noted.</Say>
  <Redirect method="POST">{gather_email_url}</Redirect>
</Response>"""
    else:
        # First hit — gather the issue
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather action="{self_url}" method="POST" input="speech"
          speechTimeout="5" timeout="12">
    <Say voice="Polly.Joanna">
      Before we get started — briefly describe what's happening.
      What device, what error, and when did it start?
    </Say>
  </Gather>
  <!-- Timeout: proceed without description rather than dead-end -->
  <Redirect method="POST">{gather_email_url}</Redirect>
</Response>"""

    return Response(content=twiml, media_type="application/xml")
