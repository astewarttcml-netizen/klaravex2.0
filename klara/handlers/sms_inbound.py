"""Twilio inbound SMS webhook — routes client replies to the AI resolver."""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Response

from .agents.resolver import handle_reply
from .lib.db import get_pool
from .lib.twilio_verify import verify_twilio_signature

log = logging.getLogger("klaravex.sms_inbound")
# Twilio signs every inbound SMS POST. We verify at the router level so the
# DELAY-handling and patch-deferral paths are both protected (H3).
router = APIRouter(dependencies=[Depends(verify_twilio_signature)])


async def _handle_patch_delay(phone: str) -> bool:
    """
    Check whether the inbound DELAY reply maps to an open patch maintenance ticket.

    If a matching ticket is found (in_progress, source_system=atera, not already deferred),
    update it: set deferred=true, reschedule_after = now + 7 days, append a history event.

    Returns True if a patch ticket was found and deferred, False otherwise.
    The caller uses this to skip the AI resolver for pure patch-delay replies.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Resolve client by phone number
            client_row = await conn.fetchrow(
                """
                SELECT id, email FROM klaravex_clients
                 WHERE phone = $1
                 LIMIT 1
                """,
                phone,
            )
            if client_row is None:
                log.info("patch_delay: no client found for phone=%s", phone)
                return False

            client_email = client_row["email"]

            # Find an open patch maintenance ticket for this client
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
                log.info("patch_delay: no open patch ticket for client=%s", client_email)
                return False

            ticket_id = str(ticket_row["id"])
            now_iso = datetime.now(timezone.utc).isoformat()
            reschedule_after = (
                datetime.now(timezone.utc) + timedelta(days=7)
            ).isoformat()

            delay_event = {
                "at": now_iso,
                "type": "client_deferred",
                "source": "sms_inbound",
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
                "patch_delay: ticket %s deferred 7 days for client=%s (phone=%s)",
                ticket_id, client_email, phone,
            )
            return True

    except Exception as exc:  # noqa: BLE001
        log.warning("patch_delay handler error phone=%s: %s", phone, exc)
        return False


@router.post("/sms/inbound")
async def sms_inbound(
    From: Annotated[str, Form()] = "",
    Body: Annotated[str, Form()] = "",
    MessageSid: Annotated[str, Form()] = "",
) -> Response:
    """Receive inbound SMS from Twilio, route to resolver or patch-delay handler."""
    log.info("sms_inbound from=%s sid=%s body=%r", From, MessageSid, Body[:50])

    if not From or not Body:
        return Response(content="<Response/>", media_type="application/xml")

    cleaned = Body.strip()

    # DELAY keyword — check for a pending patch maintenance ticket first.
    # If matched, we defer the maintenance window and skip the AI resolver
    # so the client does not receive a confusing "no active support session" reply.
    if cleaned.upper() == "DELAY":
        deferred = await _handle_patch_delay(From)
        if deferred:
            # No TwiML reply needed — the patch cron handles follow-up scheduling
            return Response(content="<Response/>", media_type="application/xml")
        # Fall through to the resolver so it can handle DELAY in any other context

    try:
        result = await handle_reply(phone=From, reply=cleaned)
        log.info("resolver result: %s", result.get("action"))
    except Exception as e:
        log.warning("sms_inbound handler error from=%s: %s", From, e)

    # Always return empty TwiML — responses go back via the resolver's _send_sms calls
    return Response(content="<Response/>", media_type="application/xml")
