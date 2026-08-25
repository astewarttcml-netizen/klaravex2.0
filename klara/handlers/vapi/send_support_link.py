"""Vapi tool: send_support_link.

Delivers the Klaravex remote-support page (RustDesk, hosted at
support.klaravex.com) to a CONSUMER caller, by the channel the caller chose
when the specialist asked "text it, email it, or go to the site yourself?".

This REPLACES generate_splashtop_link on the consumer specialists. Klaravex
no longer uses Splashtop; the remote client is RustDesk and it lives at
support.klaravex.com. The specialist asks the caller how they want the link;
this tool honors that choice via the `delivery` field:

  - delivery="sms"   → text the link to caller_phone
  - delivery="email" → email the link to caller_email
  - delivery="both"  → attempt both
  - (the caller can also just be told to go to support.klaravex.com, in which
     case the specialist does NOT call this tool at all)

Modeled on send_booking_link.py (same email/sms libs, same degrade-not-fail
behavior). Behind x-vapi-secret (mounted in vapi/router.py).
"""

import logging
import os
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..lib.email import send_email
from ..lib.sms import send_sms, sms_enabled

log = logging.getLogger("klaravex.vapi.send_support_link")
router = APIRouter()

SUPPORT_URL = os.environ.get("SUPPORT_URL", "https://support.klaravex.com")
SUPPORT_FROM_EMAIL = os.environ.get("SUPPORT_FROM_EMAIL", "support@klaravex.com")


class SendSupportLinkRequest(BaseModel):
    call_sid: str = Field(default="")
    caller_phone: str = Field(default="")
    caller_email: str = Field(default="")
    caller_first_name: str = Field(default="")
    # "sms" | "email" | "both" — the channel the caller picked.
    delivery: str = Field(default="sms")


def _greeting(first_name: str) -> str:
    return f"Hi {first_name}," if first_name else "Hi —"


def _email_body(first_name: str) -> tuple[str, str]:
    subject = "Klaravex — your remote support link (RustDesk)"
    body = (
        f"{_greeting(first_name)}\n\n"
        "Here's your Klaravex remote support link (RustDesk):\n\n"
        f"  {SUPPORT_URL}\n\n"
        "On that page, download Klaravex Support for Mac or Windows, open it, "
        "and click Allow / Yes if your computer asks. Nothing to install — it "
        "connects to our private relay automatically.\n\n"
        "Stay in the chat (or on the call) after it opens so we can see the screen.\n\n"
        "— Klaravex\n"
    )
    return subject, body


def _sms_body(first_name: str) -> str:
    lead = f"{first_name}, " if first_name else ""
    return (
        f"Klaravex: {lead}your remote support link: {SUPPORT_URL} — open it and "
        "tap to run RustDesk (nothing to install)."
    )


@router.post("/send_support_link")
async def send_support_link(req: SendSupportLinkRequest) -> dict[str, Any]:
    delivery = (req.delivery or "sms").strip().lower()
    want_sms = delivery in ("sms", "both")
    want_email = delivery in ("email", "both")

    channels: list[str] = []
    errors: list[str] = []

    if want_sms and req.caller_phone and sms_enabled():
        ok, msg = await send_sms(
            req.caller_phone,
            _sms_body(req.caller_first_name),
            source="vapi.send_support_link",
        )
        if ok:
            channels.append("sms")
        else:
            errors.append(f"sms: {msg}")

    if want_email and req.caller_email:
        subject, body = _email_body(req.caller_first_name)
        try:
            await send_email(
                to=req.caller_email,
                subject=subject,
                body=body,
                from_addr=SUPPORT_FROM_EMAIL,
            )
            channels.append("email")
        except TypeError:
            # Older send_email signatures don't accept from_addr; degrade.
            try:
                await send_email(to=req.caller_email, subject=subject, body=body)
                channels.append("email")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"email: {exc}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"email: {exc}")

    if channels:
        return {
            "status": "ok",
            "url": SUPPORT_URL,
            "channels": channels,
            "errors": errors or None,
        }

    return {
        "status": "error",
        "url": SUPPORT_URL,
        "reason": (
            "Could not deliver the support link automatically. "
            "Specialist: tell the caller to go to support.klaravex.com directly."
        ),
        "errors": errors or None,
    }
