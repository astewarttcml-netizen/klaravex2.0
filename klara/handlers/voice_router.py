"""A9 Twilio voice router aggregator.

Mounts every per-step voice handler under a single APIRouter so main.py
can include it with one line:

    from klara.handlers.voice_router import router as voice_router
    app.include_router(voice_router, prefix="/api/v1/voice", tags=["A9 voice"])

Security — H3
-------------
Every inbound route here is a *Twilio* webhook (call lifecycle, gathers,
TwiML redirects). Twilio signs each POST with HMAC-SHA1; we verify with
``verify_twilio_signature`` so an attacker cannot spoof TwiML hops to
mint Stripe payment links to attacker-controlled phones, escalate to
Anthony's phone from the open internet, or burn Vapi minutes.

The dependency is registered at the ROUTER level so every existing AND
future voice handler inherits it — no per-handler decorator needed.
"""

from fastapi import APIRouter, Depends

from .lib.twilio_verify import verify_twilio_signature
from .voice_inbound import router as inbound_router
from .voice_gather_issue import router as gather_issue_router
from .voice_gather_email import router as gather_email_router
from .voice_payment_link import router as payment_link_router
from .voice_payment_confirmation import router as payment_confirmation_router
from .voice_troubleshoot import router as troubleshoot_router
from .voice_escalate import router as escalate_router
from .voice_callback_options import router as callback_options_router

router = APIRouter(dependencies=[Depends(verify_twilio_signature)])
router.include_router(inbound_router)
router.include_router(gather_issue_router)
router.include_router(gather_email_router)
router.include_router(payment_link_router)
router.include_router(payment_confirmation_router)
router.include_router(troubleshoot_router)
router.include_router(escalate_router)
router.include_router(callback_options_router)
