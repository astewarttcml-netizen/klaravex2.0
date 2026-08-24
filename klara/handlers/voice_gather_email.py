"""A9 Twilio voice: gather caller email before sending payment link.

Inserted between /voice/menu and /voice/payment_link. Asks the caller
for their email address so the payment link can be delivered by email
AND SMS. If the caller doesn't respond, falls back to SMS-only.

See WORKFLOWS.md §A9.4.
"""

import logging
import os
from typing import Annotated

from fastapi import APIRouter, Form, Response

log = logging.getLogger("klaravex.voice.gather_email")
router = APIRouter()

BASE_URL = os.environ.get("API_BASE_URL", "https://api.klaravex.com")


@router.post("/gather_email")
async def voice_gather_email(
    CallSid: Annotated[str, Form()] = "",
    From: Annotated[str, Form()] = "",
) -> Response:
    """Ask for email, then POST SpeechResult to /voice/payment_link."""
    log.info("gather_email sid=%s from=%s", CallSid, From)

    payment_link_url = f"{BASE_URL}/api/v1/voice/payment_link"

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather action="{payment_link_url}" method="POST" input="speech"
          speechTimeout="4" timeout="10">
    <Say voice="Polly.Joanna">
      What email should I send the payment link to?
      Say it clearly — for example, john at example dot com.
    </Say>
  </Gather>
  <Say voice="Polly.Joanna">No problem — I'll send it to your phone instead.</Say>
  <Redirect method="POST">{payment_link_url}</Redirect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")
