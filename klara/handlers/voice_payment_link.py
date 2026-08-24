"""A9 Twilio voice: in-call payment link generator.

Called from /api/v1/voice/gather_email after the caller optionally provides
their email address (as SpeechResult). Creates a Stripe Checkout Session,
sends the URL via SMS (always) and via email (when email provided),
then returns TwiML holding the caller on the line.

See WORKFLOWS.md §A9.4.
"""

import logging
import os
import re
from typing import Annotated

import httpx
import stripe
from fastapi import APIRouter, Form, Request, Response

from .lib.email import send_email
from .lib.rate_limit import limiter

log = logging.getLogger("klaravex.voice.payment_link")
router = APIRouter()

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "TWILIO_ACCOUNT_SID_REDACTED")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.environ.get("TWILIO_FROM_NUMBER", "+14243486010")
BASE_URL = os.environ.get("API_BASE_URL", "https://api.klaravex.com")

# Default per-session SKU for voice-initiated sessions
# 2026-07-21: $29 flat rate, no time limit (was $39, was $79 before that).
PER_INCIDENT_PRICE = "price_1TvQqI14iRJDip4yBEGW2tUb"


def _parse_spoken_email(speech: str) -> str:
    """Convert spoken email to address: 'john at example dot com' → 'john@example.com'."""
    if not speech:
        return ""
    text = speech.lower().strip()
    text = re.sub(r"\s+at\s+", "@", text)
    text = re.sub(r"\s+dot\s+", ".", text)
    text = re.sub(r"\s+", "", text)
    if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", text):
        return text
    return ""


@router.post("/payment_link")
@limiter.limit("5/minute")
async def voice_payment_link(
    request: Request,
    CallSid: Annotated[str, Form()] = "",
    From: Annotated[str, Form()] = "",
    To: Annotated[str, Form()] = "",
    SpeechResult: Annotated[str, Form()] = "",
) -> Response:
    """Create Stripe Checkout, SMS + optionally email the link, return hold TwiML."""
    caller_email = _parse_spoken_email(SpeechResult)
    log.info("payment_link sid=%s from=%s email=%r", CallSid, From, caller_email or "none")

    confirmation_url = f"{BASE_URL}/api/v1/voice/payment_confirmation"
    checkout_url = ""

    if stripe.api_key:
        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                payment_intent_data={"capture_method": "manual"},
                invoice_creation={"enabled": True},
                line_items=[{"price": PER_INCIDENT_PRICE, "quantity": 1}],
                customer_email=caller_email or None,
                success_url="https://klaravex.com/personal/thanks/?session_id={CHECKOUT_SESSION_ID}",
                cancel_url="https://klaravex.com/personal/pricing/",
                metadata={
                    "call_sid": CallSid,
                    "caller_phone": From,
                    "intent": "per-incident",
                    "source": "twilio_voice",
                },
            )
            checkout_url = session.url or ""
        except Exception as e:  # noqa: BLE001
            log.warning("stripe checkout create failed: %s", e)
    else:
        log.warning("STRIPE_SECRET_KEY not set; skipping checkout session creation")

    sent_channels: list[str] = []

    # Always send SMS to caller's phone
    if checkout_url and From and TWILIO_SID and TWILIO_TOKEN:
        await _send_sms(
            to=From,
            body=f"Klaravex payment link ($29 IT support session): {checkout_url}",
        )
        sent_channels.append("phone")

    # Also send to email when we have an address
    if checkout_url and caller_email:
        await send_email(
            to=caller_email,
            subject="Your Klaravex payment link",
            body=(
                "Here's your $29 IT support payment link:\n\n"
                f"{checkout_url}\n\n"
                "This link is valid for 24 hours. "
                "Stay on the call — a tech will join as soon as payment is complete.\n\n"
                "Questions? Call +1 (424) 348-6010."
            ),
        )
        sent_channels.append("email")

    if checkout_url:
        if len(sent_channels) == 2:
            delivery_msg = "I've sent it to both your phone and email."
        elif "email" in sent_channels:
            delivery_msg = "I've sent it to your email."
        else:
            delivery_msg = "I've sent it to your phone."
        message = (
            f"{delivery_msg} "
            "Tap Pay when you're ready — I'll stay on the line and connect you "
            "with a tech as soon as payment goes through."
        )
    else:
        message = (
            "I'm having a small technical issue sending the link right now. "
            "Let me connect you with our engineer directly."
        )
        confirmation_url = f"{BASE_URL}/api/v1/voice/escalate"

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">{message}</Say>
  <Pause length="20"/>
  <Say voice="Polly.Joanna">Still here — take your time, you have a few minutes to complete the payment.</Say>
  <Pause length="40"/>
  <Redirect method="POST">{confirmation_url}?CallSid={CallSid}</Redirect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


async def _send_sms(to: str, body: str) -> None:
    """Delegates to the gated lib.sms helper so SMS_ENABLED is honored centrally."""
    from .lib.sms import send_sms as _gated
    await _gated(to, body, source="voice_payment_link")


