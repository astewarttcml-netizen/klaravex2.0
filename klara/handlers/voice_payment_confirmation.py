"""A9 Twilio voice: payment confirmation poller.

Called from the live-call TwiML redirect after the payment link was sent.
Polls Stripe for a completed Checkout Session whose metadata.call_sid matches
the active call. If paid, returns TwiML confirming payment and redirecting to
troubleshooting. If not yet paid, loops with a short pause.

See WORKFLOWS.md §A9.4 step 7–8, §A9.5.
"""

import logging
import os
from typing import Annotated

import stripe
from fastapi import APIRouter, Form, Query, Response

log = logging.getLogger("klaravex.voice.payment_confirmation")
router = APIRouter()

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
BASE_URL = os.environ.get("API_BASE_URL", "https://api.klaravex.com")

# Maximum number of poll loops before giving up and escalating
MAX_POLLS = int(os.environ.get("VOICE_PAYMENT_MAX_POLLS", "18"))  # 18 × 10s = 3 min window


@router.post("/payment_confirmation")
async def voice_payment_confirmation(
    CallSid: Annotated[str, Form()] = "",
    From: Annotated[str, Form()] = "",
    poll: Annotated[int, Query()] = 0,
) -> Response:
    """Poll Stripe for payment completion; confirm or loop."""
    log.info("payment_confirmation sid=%s poll=%d", CallSid, poll)

    troubleshoot_url = f"{BASE_URL}/api/v1/voice/troubleshoot"
    escalate_url = f"{BASE_URL}/api/v1/voice/escalate"
    callback_url = f"{BASE_URL}/api/v1/voice/callback_options"

    paid = False
    if stripe.api_key and CallSid:
        try:
            paid = await _check_paid(CallSid)
        except Exception as e:  # noqa: BLE001
            log.warning("stripe poll failed: %s", e)

    if paid:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    Payment confirmed — thank you. Let me start working on your issue right now.
  </Say>
  <Redirect method="POST">{troubleshoot_url}</Redirect>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    # Not paid yet — loop up to MAX_POLLS times, then offer escalation
    if poll < MAX_POLLS:
        next_poll = poll + 1
        loop_url = f"{BASE_URL}/api/v1/voice/payment_confirmation?poll={next_poll}"
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Pause length="10"/>
  <Redirect method="POST">{loop_url}</Redirect>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    # Exceeded max polls — offer queue or callback, never dead-end
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    No problem — the payment link is good for 24 hours whenever you're ready.
  </Say>
  <Redirect method="POST">{callback_url}</Redirect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


async def _check_paid(call_sid: str) -> bool:
    """Search Stripe for a completed session whose metadata.call_sid matches."""
    sessions = stripe.checkout.Session.list(limit=20)
    for session in sessions.auto_paging_iter():
        meta = session.get("metadata") or {}
        if meta.get("call_sid") == call_sid:
            return session.get("payment_status") == "paid"
    return False
