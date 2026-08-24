"""SMS sender — gated on the SMS_ENABLED feature flag.

Single source of truth for outbound SMS. Every other module should
call `send_sms()` here instead of hitting Twilio directly. When
SMS_ENABLED is anything other than truthy ("1" / "true" / "yes"),
sends are skipped silently with a log line and the function returns
(False, "sms disabled").

Why this exists
---------------
2026-06-10: Anthony confirmed SMS is currently DISABLED at the Twilio
account level (A2P 10DLC registration pending). Until Twilio
re-enables outbound SMS, every Messages.json POST is wasted — it
either errors or silently drops. Worse, the Vapi assistant tells the
caller "I just texted you" and nothing arrives.

This flag-gated helper lets the code paths stay in place. Flip
SMS_ENABLED=true on Azure Container App env when Twilio is live.
"""

import logging
import os
from typing import Optional, Tuple

import httpx

log = logging.getLogger("klaravex.sms")

TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.environ.get("TWILIO_FROM_NUMBER", "")


def sms_enabled() -> bool:
    """True iff outbound SMS is currently allowed."""
    return os.environ.get("SMS_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


async def send_sms(to: str, body: str, *, source: str = "unknown") -> Tuple[bool, str]:
    """Send an SMS via Twilio if and only if SMS_ENABLED is truthy.

    Returns (ok, error_or_empty).
    - (True, "")           — message accepted by Twilio
    - (False, "sms_disabled") — feature flag is off; nothing attempted
    - (False, reason)      — Twilio rejected or network error

    `source` is a free-form tag (e.g. "splashtop_link", "dunning") that
    shows up in the log line so we can attribute usage.
    """
    if not sms_enabled():
        log.info("sms_disabled feature flag; skip send to=%s source=%s", to, source)
        return False, "sms_disabled"

    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM):
        log.warning("twilio not fully configured; skip sms to=%s source=%s", to, source)
        return False, "twilio_not_configured"

    if not to:
        return False, "missing_recipient"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json",
                auth=(TWILIO_SID, TWILIO_TOKEN),
                data={"From": TWILIO_FROM, "To": to, "Body": body},
            )
            if r.status_code >= 300:
                log.warning(
                    "twilio sms rejected source=%s to=%s status=%s body=%s",
                    source, to, r.status_code, r.text[:200],
                )
                return False, f"twilio_http_{r.status_code}"
            log.info("sms sent to=%s source=%s sid=%s", to, source, r.json().get("sid", "?"))
            return True, ""
    except Exception as exc:  # noqa: BLE001
        log.warning("twilio sms exception source=%s to=%s: %s", source, to, exc)
        return False, f"exception:{type(exc).__name__}"
