"""Phase 12 V4 — biz_intake: send_booking_link.

Thin wrapper that delivers a STATIC Calendly URL to the caller. Static link
because Calendly OAuth (T0.3) remains blocked and the discovery-call funnel
needs to ship without it. When T0.3 unblocks, the booking event will arrive
via the existing /api/v1/calendly/webhook and the pre-brief pipeline (V7)
flips from "lead-created" trigger to "booking-confirmed" trigger.

Delivery channels (in order, first one that succeeds wins; we always
attempt email when an address is on file):
  1. SMS to the caller's phone (if SMS_ENABLED — currently OFF until Twilio
     A2P 10DLC lands).
  2. Email to the caller's email-on-file or supplied address.

The endpoint always returns success when at least one channel succeeded;
the lead row gets booking_link_sent_at stamped so we don't re-spam on
re-call.

Behind x-vapi-secret (mounted in vapi/router.py).
"""

import logging
import os
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..lib.email import send_email
from ..lib.sms import send_sms, sms_enabled

log = logging.getLogger("klaravex.vapi.send_booking_link")
router = APIRouter()

BOOKING_URL = os.environ.get(
    "B2B_BOOKING_URL",
    "https://calendly.com/klaravex/klaravex-onboarding",
)
BOOKING_FROM_EMAIL = os.environ.get(
    "B2B_BOOKING_FROM_EMAIL",
    "hello@klaravex.com",
)

_PLACEHOLDER_SIDS = {"call_sid_placeholder", "1234567890", "", "{{call.id}}", "unknown"}


class SendBookingLinkRequest(BaseModel):
    call_sid: str = Field(default="")
    lead_id: str = Field(default="")
    caller_phone: str = Field(default="")
    caller_email: str = Field(default="")
    company: str = Field(default="")
    test: bool = Field(default=False, alias="_test")


def _email_body(company: str) -> tuple[str, str]:
    who = f" for {company}" if company else ""
    subject = f"Klaravex — book your discovery call{who}"
    body = (
        "Hi —\n\n"
        "Thanks for calling Klaravex. As promised, here's the link to pick "
        "a time with Anthony, our founder and senior engineer:\n\n"
        f"  {BOOKING_URL}\n\n"
        "Pick whatever slot works for you. Our AI engineering team will "
        "have a project pre-brief ready before the meeting so the call is "
        "about decisions, not discovery.\n\n"
        "If nothing on the calendar works, just reply to this email and "
        "we'll find a time.\n\n"
        "— Klaravex\n"
    )
    return subject, body


def _sms_body(company: str) -> str:
    who = f" for {company}" if company else ""
    return (
        f"Klaravex: book your discovery call with Anthony{who}: {BOOKING_URL} "
        "(reply for help)."
    )


async def _stamp_lead(lead_id: str, *, url: str) -> None:
    if not lead_id:
        return
    try:
        from ..lib.db import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE klaravex_b2b_leads
                   SET booking_link_sent_at = now(),
                       booking_link_url     = $2,
                       updated_at           = now()
                 WHERE id = $1
                """,
                lead_id,
                url,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("could not stamp booking link on lead %s: %s", lead_id, exc)


@router.post("/send_booking_link")
async def send_booking_link(req: SendBookingLinkRequest) -> dict[str, Any]:
    if req.test:
        return {"status": "ok", "test": True, "url": BOOKING_URL}

    channels: list[str] = []
    errors: list[str] = []

    if req.caller_phone and sms_enabled():
        ok, msg = await send_sms(
            req.caller_phone,
            _sms_body(req.company),
            source="vapi.send_booking_link",
        )
        if ok:
            channels.append("sms")
        else:
            errors.append(f"sms: {msg}")

    if req.caller_email:
        subject, body = _email_body(req.company)
        try:
            await send_email(
                to=req.caller_email,
                subject=subject,
                body=body,
                from_addr=BOOKING_FROM_EMAIL,
            )
            channels.append("email")
        except TypeError:
            # Older send_email signatures don't accept from_addr; retry
            # without it so we degrade rather than fail the call.
            try:
                await send_email(
                    to=req.caller_email,
                    subject=subject,
                    body=body,
                )
                channels.append("email")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"email: {exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"email: {exc}")

    if channels:
        await _stamp_lead(req.lead_id, url=BOOKING_URL)
        return {
            "status": "ok",
            "url": BOOKING_URL,
            "channels": channels,
            "errors": errors or None,
        }

    return {
        "status": "error",
        "url": BOOKING_URL,
        "reason": (
            "Could not deliver the booking link automatically. "
            "Klara: read the URL to the caller letter-by-letter."
        ),
        "errors": errors or None,
    }
