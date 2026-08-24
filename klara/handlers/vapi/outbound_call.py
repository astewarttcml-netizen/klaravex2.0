"""Trigger an outbound Vapi call to a client after payment confirmation."""

import logging
import os
from typing import Any

import httpx

log = logging.getLogger("klaravex.vapi.outbound_call")

VAPI_API_KEY = os.environ.get("VAPI_API_KEY", "")
LIVE_TROUBLESHOOT_ASSISTANT_ID = "023e75a7-c4dc-4a66-b397-9949c62027a1"
KLARAVEX_PHONE_NUMBER_ID = os.environ.get(
    "VAPI_PHONE_NUMBER_ID", "6334ed60-a275-4bfc-b078-29048297d918"
)


async def trigger_troubleshoot_call(
    caller_phone: str,
    call_sid: str,
    intent: str = "per-incident",
) -> dict[str, Any]:
    """Initiate outbound Vapi call to caller after payment confirmation.

    Returns Vapi call object or error dict.
    """
    if not VAPI_API_KEY:
        log.warning("VAPI_API_KEY not set; outbound call skipped")
        return {"error": "vapi not configured"}

    if not caller_phone or not caller_phone.startswith("+"):
        log.warning("invalid caller_phone=%s; outbound call skipped", caller_phone)
        return {"error": "invalid caller_phone"}

    payload: dict[str, Any] = {
        "assistantId": LIVE_TROUBLESHOOT_ASSISTANT_ID,
        "customer": {
            "number": caller_phone,
        },
        "assistantOverrides": {
            "variableValues": {
                "original_call_sid": call_sid,
                "intent": intent,
            }
        },
    }

    # Use phone number ID if configured, otherwise fall back to phoneNumber directly
    if KLARAVEX_PHONE_NUMBER_ID:
        payload["phoneNumberId"] = KLARAVEX_PHONE_NUMBER_ID
    else:
        payload["phoneNumber"] = {"number": "+14243486010"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.vapi.ai/call",
                headers={
                    "Authorization": f"Bearer {VAPI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if r.status_code in (200, 201):
                data = r.json()
                log.info(
                    "outbound call triggered call_id=%s to=%s",
                    data.get("id"),
                    caller_phone,
                )
                return data
            else:
                log.warning("vapi outbound call failed: %s %s", r.status_code, r.text)
                return {"error": f"vapi {r.status_code}", "detail": r.text}
    except Exception as e:
        log.warning("vapi outbound call exception: %s", e)
        return {"error": str(e)}
