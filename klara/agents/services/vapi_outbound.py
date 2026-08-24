"""
app/services/vapi_outbound.py
──────────────────────────────
Thin async wrapper for Vapi outbound call creation.

Used by the Stripe webhook to trigger consumer troubleshooting callbacks
after payment succeeds.
"""
from __future__ import annotations

import structlog
import aiohttp

logger = structlog.get_logger(__name__)

_VAPI_BASE = "https://api.vapi.ai"
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)


async def place_consumer_callback(
    *,
    api_key: str,
    phone_number_id: str,
    troubleshoot_assistant_id: str,
    customer_phone: str,
    customer_name: str,
    device: str,
    problem: str,
    ticket_number: str,
) -> dict:
    """
    Fire a Vapi outbound call to a consumer after their payment succeeds.

    Injects ticket context as Vapi variable values so the assistant can
    reference {{customer_name}}, {{device}}, {{problem}}, {{ticket_number}}
    in its first message and system prompt.

    Returns the Vapi call object dict on success.
    Raises RuntimeError on API failure.
    """
    payload = {
        "assistantId": troubleshoot_assistant_id,
        "assistantOverrides": {
            "variableValues": {
                "customer_name": customer_name or "there",
                "device": device or "device",
                "problem": problem or "the issue you reported",
                "ticket_number": ticket_number,
            }
        },
        "phoneNumberId": phone_number_id,
        "customer": {
            "number": customer_phone,
            "name": customer_name or "",
        },
        "metadata": {
            "ticket_number": ticket_number,
            "source": "consumer_payment_callback",
        },
    }

    async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
        async with session.post(
            f"{_VAPI_BASE}/call/phone",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        ) as resp:
            data = await resp.json()
            if resp.status not in (200, 201):
                error_msg = data.get("message") or data.get("error") or f"HTTP {resp.status}"
                raise RuntimeError(f"Vapi API error: {error_msg}")
            logger.info(
                "vapi_outbound.call_placed",
                call_id=data.get("id"),
                ticket_number=ticket_number,
                phone_prefix=customer_phone[:5] + "****",
            )
            return data
