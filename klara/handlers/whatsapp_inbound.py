# SETUP REQUIRED (Anthony):
# 1. Go to console.twilio.com → Messaging → WhatsApp → Senders
# 2. For testing: enable WhatsApp Sandbox, send "join <keyword>" from your phone
# 3. For production: submit WhatsApp Business Profile (requires Facebook Business Manager)
# 4. Set webhook URL to https://api.klaravex.com/api/v1/whatsapp/inbound
# 5. For LATAM: consider a separate WhatsApp number per country for better deliverability
"""Twilio inbound WhatsApp webhook — routes client messages to the AI resolver.

Mirrors sms_inbound.py. Key differences:
- From/To fields carry a whatsapp: prefix (e.g. "whatsapp:+14155238886")
- The prefix is stripped to clean E.164 before any lookup or resolver call
- Outbound replies use the whatsapp: prefix so Twilio routes them over WhatsApp
- channel="whatsapp" is passed to the resolver so it uses send_whatsapp, not SMS
"""

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Form, Response

from .agents.resolver import handle_reply
from .lib.db import get_pool
from .lib.twilio_verify import verify_twilio_signature

log = logging.getLogger("klaravex.whatsapp_inbound")
# WhatsApp inbound is the same Twilio webhook shape as SMS — verify HMAC
# signature at the router level so a spoofed POST cannot reach the
# resolver, mint Stripe payment links, or burn LLM tokens (H3).
router = APIRouter(dependencies=[Depends(verify_twilio_signature)])

TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "+14243486010")


def _strip_whatsapp_prefix(raw: str) -> str:
    """Return a clean E.164 phone number from a Twilio whatsapp:-prefixed field.

    Examples:
        "whatsapp:+14155238886"  → "+14155238886"
        "+14155238886"           → "+14155238886"  (already clean)
        "whatsapp:5511999990000" → "+5511999990000"  (add + if missing)
    """
    number = raw.strip()
    if number.lower().startswith("whatsapp:"):
        number = number[len("whatsapp:"):]
    number = number.strip()
    if number and not number.startswith("+"):
        number = "+" + number
    return number


async def send_whatsapp_message(to_phone: str, body: str) -> bool:
    """Send outbound WhatsApp message via Twilio.

    to_phone must be a clean E.164 number without whatsapp: prefix (e.g. "+5511999990000").
    Returns True on success, False on any error — never raises.
    """
    if not (TWILIO_SID and TWILIO_TOKEN):
        log.warning("whatsapp send skipped — Twilio credentials not configured")
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json",
                auth=(TWILIO_SID, TWILIO_TOKEN),
                data={
                    "From": f"whatsapp:{TWILIO_FROM_NUMBER}",
                    "To": f"whatsapp:{to_phone}",
                    "Body": body,
                },
            )
            if r.status_code >= 300:
                log.warning(
                    "whatsapp send failed to=%s status=%s body=%s",
                    to_phone, r.status_code, r.text[:200],
                )
                return False
            return True
    except Exception as exc:  # noqa: BLE001
        log.warning("whatsapp send exception to=%s: %s", to_phone, exc)
        return False


async def _handle_patch_delay(phone: str) -> bool:
    """Check whether a DELAY reply maps to an open patch maintenance ticket.

    Mirrors sms_inbound._handle_patch_delay exactly; uses the clean E.164 phone
    so the same klaravex_clients lookup works regardless of channel.

    Returns True if a matching ticket was found and deferred, False otherwise.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            client_row = await conn.fetchrow(
                """
                SELECT id, email FROM klaravex_clients
                 WHERE phone = $1
                 LIMIT 1
                """,
                phone,
            )
            if client_row is None:
                log.info("patch_delay(wa): no client found for phone=%s", phone)
                return False

            client_email = client_row["email"]

            ticket_row = await conn.fetchrow(
                """
                SELECT id, metadata FROM klaravex_tickets
                 WHERE client_email = lower($1)
                   AND source = 'workflow'
                   AND archetype = 'A3'
                   AND status = 'in_progress'
                   AND metadata->>'source_system' = 'atera'
                   AND (metadata->>'deferred')::boolean IS NOT TRUE
                 ORDER BY created_at DESC
                 LIMIT 1
                """,
                client_email,
            )
            if ticket_row is None:
                log.info("patch_delay(wa): no open patch ticket for client=%s", client_email)
                return False

            ticket_id = str(ticket_row["id"])
            now_iso = datetime.now(timezone.utc).isoformat()
            reschedule_after = (
                datetime.now(timezone.utc) + timedelta(days=7)
            ).isoformat()

            delay_event = {
                "at": now_iso,
                "type": "client_deferred",
                "source": "whatsapp_inbound",
                "phone": phone,
                "reschedule_after": reschedule_after,
            }

            await conn.execute(
                """
                UPDATE klaravex_tickets
                   SET metadata = metadata || $2::jsonb,
                       history  = history  || $3::jsonb,
                       updated_at = now()
                 WHERE id = $1
                """,
                uuid.UUID(ticket_id),
                json.dumps({
                    "deferred": True,
                    "reschedule_after": reschedule_after,
                    "deferred_at": now_iso,
                }),
                json.dumps([delay_event]),
            )

            log.info(
                "patch_delay(wa): ticket %s deferred 7 days for client=%s (phone=%s)",
                ticket_id, client_email, phone,
            )
            return True

    except Exception as exc:  # noqa: BLE001
        log.warning("patch_delay(wa) handler error phone=%s: %s", phone, exc)
        return False


@router.post("/whatsapp/inbound")
async def whatsapp_inbound(
    From: Annotated[str, Form()] = "",
    Body: Annotated[str, Form()] = "",
    MessageSid: Annotated[str, Form()] = "",
) -> Response:
    """Receive inbound WhatsApp message from Twilio, route to resolver or patch-delay handler.

    Twilio posts the same form fields as SMS but with whatsapp: prefixed phone numbers.
    We strip the prefix before any lookup so the resolver always works with clean E.164.
    """
    log.info("whatsapp_inbound from=%s sid=%s body=%r", From, MessageSid, Body[:50])

    if not From or not Body:
        return Response(content="<Response/>", media_type="application/xml")

    # Strip whatsapp: prefix — all downstream logic expects clean E.164
    phone = _strip_whatsapp_prefix(From)
    cleaned = Body.strip()

    # DELAY keyword — defer patch maintenance window if a matching ticket exists.
    # Avoids confusing "no active session" reply for a deliberate scheduling interaction.
    if cleaned.upper() == "DELAY":
        deferred = await _handle_patch_delay(phone)
        if deferred:
            return Response(content="<Response/>", media_type="application/xml")
        # Fall through to resolver — DELAY may be meaningful in another context

    try:
        result = await handle_reply(phone=phone, reply=cleaned, channel="whatsapp")
        log.info("resolver result: %s", result.get("action"))
    except Exception as exc:
        log.warning("whatsapp_inbound handler error from=%s: %s", phone, exc)

    # Always return empty TwiML — responses go back via send_whatsapp calls in the resolver
    return Response(content="<Response/>", media_type="application/xml")
