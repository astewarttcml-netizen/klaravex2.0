"""A9 Vapi webhook receiver.

Vapi POSTs lifecycle events here (call-started, call-ended, transcript,
function-call, end-of-call-report). We persist the transcript and final
ticket update. See WORKFLOWS.md §A9.8/§A9.9.

Also fires the T-AC-06 `phone_call_qualified` GA4 conversion (secondary,
$150) on qualifying end-of-call events (duration >= 60s, customer email
present, endedReason not in the spam/rejected set).
"""

import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..lib import tickets as tickets_lib  # noqa: F401
from services.ga4_measurement_protocol import (
    _hashed_user_data,
    new_client_id,
    send_event,
)

log = logging.getLogger("klaravex.vapi.webhook")
router = APIRouter()

PHONE_CALL_QUALIFIED_VALUE_USD = 150
_UNQUALIFIED_ENDED_REASONS = {
    "customer-did-not-give-microphone-permission",
    "assistant-said-message-with-end-call-enabled",
    "twilio-failed-to-connect-call",
    "silence-timed-out",
    "voicemail",
    "call-rejected",
    "spam",
}


class VapiEventEnvelope(BaseModel):
    message: dict[str, Any] | None = None
    type: str | None = None


@router.post("/webhook")
async def vapi_webhook(request: Request) -> dict[str, Any]:
    raw = await request.json()
    if raw.get("_test"):
        return {"status": "ok", "test": True}

    msg = raw.get("message") or raw
    event_type = msg.get("type") or raw.get("type") or "unknown"

    if event_type in ("end-of-call-report", "call-ended"):
        try:
            await _persist_call(msg)
        except Exception as e:  # noqa: BLE001
            log.warning("call persistence failed: %s", e)
        try:
            from .dropped_call_recovery import maybe_send_recovery_email
            reason = await maybe_send_recovery_email(msg)
            log.info("recovery check: %s", reason)
        except Exception as e:  # noqa: BLE001
            log.warning("recovery check failed: %s", e)
        try:
            await _maybe_fire_phone_call_qualified(msg)
        except Exception as e:  # noqa: BLE001
            log.warning("ga4 phone_call_qualified fire failed: %s", e)

    return {"status": "ok", "event": event_type}


async def _maybe_fire_phone_call_qualified(msg: dict[str, Any]) -> None:
    """T-AC-06 secondary conversion: phone_call_qualified ($150).

    Fires when:
      - end-of-call event AND
      - duration_seconds >= 60 AND
      - customer email or E.164 phone number present (proxy for real lead) AND
      - endedReason not in _UNQUALIFIED_ENDED_REASONS.

    Attribution channel is `unknown` until Google Ads call-tracking numbers
    are wired (each ad group gets its own dynamic number). Metadata that
    Vapi passes through (utm_source, gclid, ga_client_id set at call
    initiation) is used when present.
    """
    call = msg.get("call") or {}
    duration = int(msg.get("durationSeconds") or call.get("durationSeconds") or 0)
    ended_reason = (msg.get("endedReason") or "").lower()
    customer = msg.get("customer") or {}
    email = customer.get("email")
    phone = customer.get("number") or call.get("customer", {}).get("number")

    if duration < 60:
        log.info("phone_call_qualified skipped: duration=%s < 60s", duration)
        return
    if ended_reason in _UNQUALIFIED_ENDED_REASONS:
        log.info("phone_call_qualified skipped: endedReason=%s (unqualified)", ended_reason)
        return
    if not email and not phone:
        log.info("phone_call_qualified skipped: no email or phone on customer")
        return

    metadata = msg.get("metadata") or call.get("metadata") or {}
    utm_source = metadata.get("utm_source")
    utm_medium = metadata.get("utm_medium")
    utm_campaign = metadata.get("utm_campaign")
    utm_content = metadata.get("utm_content")
    gclid = metadata.get("gclid")
    ga_client_id = metadata.get("ga_client_id") or new_client_id()
    vertical = metadata.get("vertical", "general")

    if utm_source == "google_ads" or utm_medium == "cpc":
        channel = "google_ads"
    elif utm_source:
        channel = utm_source
    else:
        channel = "unknown"

    params: dict[str, Any] = {
        "value": PHONE_CALL_QUALIFIED_VALUE_USD,
        "currency": "USD",
        "vertical": vertical,
        "channel": channel,
        "duration_seconds": duration,
        "ended_reason": ended_reason or "unknown",
        "call_sid": call.get("id") or msg.get("callId") or "",
    }
    if utm_content:
        params["source_ad_group"] = utm_content
    if utm_campaign:
        params["campaign"] = utm_campaign
    if gclid:
        params["gclid"] = gclid

    user_data = _hashed_user_data(
        email=email,
        phone_e164=phone,
        first_name=customer.get("firstName") or customer.get("first_name"),
        last_name=customer.get("lastName") or customer.get("last_name"),
    )

    result = await send_event(
        client_id=ga_client_id,
        event_name="phone_call_qualified",
        params=params,
        user_id=email or phone,
        user_data=user_data,
    )
    log.info(
        "phone_call_qualified fired duration=%s channel=%s mp_ok=%s",
        duration,
        channel,
        result.get("ok"),
    )


async def _persist_call(msg: dict[str, Any]) -> None:
    call = msg.get("call") or {}
    call_sid = call.get("id") or msg.get("callId") or ""
    transcript = msg.get("transcript") or msg.get("artifact", {}).get("transcript") or ""
    customer = msg.get("customer") or {}
    email = customer.get("email")
    if not email:
        return

    ticket_id = (msg.get("metadata") or {}).get("ticket_id") or call.get("metadata", {}).get("ticket_id")
    if not ticket_id:
        log.info("vapi call event for %s with no ticket_id; skipping append", email)
        return

    await tickets_lib.append_event(
        ticket_id,
        msg.get("type") or "vapi.event",
        {
            "call_sid": call_sid,
            "transcript_excerpt": (transcript or "")[:2000],
            "ended_reason": msg.get("endedReason"),
            "cost": msg.get("cost"),
        },
    )
