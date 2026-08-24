"""Vapi tool: open_ticket.

Phase 12 V6 — voice tool for biz_engineer and pillar voice assistants to
file a ticket from inside a live call. Writes a klaravex_tickets row and
emails a digest to the on-call team.

Ticket archetypes (callable from voice):
  * advice_note          — emails the call's advice summary to the client
  * work_request         — P2/P3 hands-on change (read by ops the next morning)
  * callback             — caller asked us to call back later
  * security_note        — caller mentioned an active security concern
  * unauthenticated_callback — auth failed; we should call back to verify
"""

import json
import logging
import os
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..lib.db import get_pool
from ..lib.email import send_email

log = logging.getLogger("klaravex.vapi.open_ticket")
router = APIRouter()

ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")

ALLOWED_ARCHETYPES = (
    "advice_note",
    "work_request",
    "callback",
    "security_note",
    "unauthenticated_callback",
)
ALLOWED_SEVERITIES = ("P1", "P2", "P3", "P4")
DEFAULT_SEVERITY_BY_ARCHETYPE = {
    "advice_note": "P4",
    "work_request": "P3",
    "callback": "P3",
    "security_note": "P1",
    "unauthenticated_callback": "P3",
}


class OpenTicketRequest(BaseModel):
    archetype: str = Field(..., description="advice_note | work_request | callback | security_note | unauthenticated_callback")
    subject: str = Field(..., max_length=200)
    summary: str = Field(default="", max_length=8000)
    client_id: str | None = Field(default=None, description="UUID — present if caller is auth'd via lookup_client")
    client_email: str | None = Field(default=None, description="Email — required if client_id is missing")
    call_sid: str = Field(default="")
    caller_phone: str | None = None
    pillar: str | None = Field(default=None, description="managed_security | microsoft_365 | regulatory_readiness | ai_adoption | strategic_advisory | infrastructure_support")
    severity: str | None = Field(default=None)
    test: bool = Field(default=False, alias="_test")


def _coerce_client_uuid(s: str | None) -> UUID | None:
    if not s:
        return None
    try:
        return UUID(s)
    except (ValueError, TypeError):
        return None


@router.post("/open_ticket")
async def open_ticket(req: OpenTicketRequest) -> dict[str, Any]:
    if req.test:
        return {"status": "ok", "test": True, "ticket_id": "test"}

    if req.archetype not in ALLOWED_ARCHETYPES:
        raise HTTPException(400, f"archetype must be one of {ALLOWED_ARCHETYPES}")

    severity = req.severity or DEFAULT_SEVERITY_BY_ARCHETYPE[req.archetype]
    if severity not in ALLOWED_SEVERITIES:
        raise HTTPException(400, f"severity must be one of {ALLOWED_SEVERITIES}")

    client_uuid = _coerce_client_uuid(req.client_id)
    client_email = req.client_email or ""

    pool = await get_pool()
    async with pool.acquire() as conn:
        if client_uuid and not client_email:
            client_email = await conn.fetchval(
                "SELECT email FROM klaravex_clients WHERE id = $1", client_uuid
            ) or ""
        if not client_email:
            raise HTTPException(400, "client_email required when client_id is not provided")

        metadata = {
            "call_sid": req.call_sid,
            "caller_phone": req.caller_phone,
            "pillar": req.pillar,
            "channel": "voice",
        }
        history = [{
            "actor": "voice_assistant",
            "event": "opened",
            "summary": (req.summary or "")[:400],
            "pillar": req.pillar,
        }]

        ticket_id = await conn.fetchval(
            """
            INSERT INTO klaravex_tickets
              (client_id, client_email, severity, status, source, archetype, subject, summary,
               history, metadata)
            VALUES ($1, $2, $3, 'open', 'voice', $4, $5, $6, $7::jsonb, $8::jsonb)
            RETURNING id
            """,
            client_uuid, client_email, severity, req.archetype, req.subject,
            req.summary or None, json.dumps(history), json.dumps(metadata),
        )

    log.info("open_ticket id=%s archetype=%s severity=%s call_sid=%s",
             ticket_id, req.archetype, severity, req.call_sid)

    # P1 → also page on-call team via email (Telegram piggy-backs through
    # escalate_to_anthony when the caller actively requests bridging).
    if severity == "P1":
        try:
            await send_email(
                to=ALERT_EMAIL,
                subject=f"[Klaravex ticket] P1 {req.archetype} — {req.subject[:80]}",
                body=(
                    f"Ticket: {ticket_id}\n"
                    f"Archetype: {req.archetype}\n"
                    f"Client email: {client_email}\n"
                    f"Caller phone: {req.caller_phone or '?'}\n"
                    f"Call SID: {req.call_sid}\n"
                    f"Pillar: {req.pillar or '—'}\n\n"
                    f"Subject:\n{req.subject}\n\n"
                    f"Summary:\n{req.summary or '(none)'}\n"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("open_ticket P1 alert email failed: %s", exc)

    return {
        "status": "ok",
        "ticket_id": str(ticket_id),
        "severity": severity,
        "archetype": req.archetype,
    }
