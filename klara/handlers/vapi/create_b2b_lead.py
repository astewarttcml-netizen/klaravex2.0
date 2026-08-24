"""Phase 12 V3 — biz_intake: create_b2b_lead.

Klara invokes this as soon as she has captured the qualifying fields from a
new-business caller. Behavior:

  1. Idempotent per call_sid — if a lead with that call_sid already exists,
     we UPDATE it (appending notes) rather than insert a duplicate.
  2. Inserts into klaravex_b2b_leads, returns the lead_id so subsequent
     send_booking_link / open_ticket calls can attach to the same row.
  3. Fires a Telegram + email page to Anthony so he knows a real human is
     waiting on a booking link.

Behind x-vapi-secret (mounted in vapi/router.py).
"""

import asyncio
import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..lib.email import send_email
from .pre_brief import dispatch_lead_pre_brief

log = logging.getLogger("klaravex.vapi.create_b2b_lead")
router = APIRouter()

ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

_PLACEHOLDER_SIDS = {"call_sid_placeholder", "1234567890", "", "{{call.id}}", "unknown"}


class CreateB2BLeadRequest(BaseModel):
    call_sid: str = Field(default="")
    company: str = Field(default="")
    caller_name: str = Field(default="")
    caller_role: str = Field(default="")
    seat_count: int | None = Field(default=None)
    current_it_setup: str = Field(default="")
    pain_points: str = Field(default="")
    urgency: str = Field(default="")
    phone: str = Field(default="")
    email: str = Field(default="")
    notes: str = Field(default="")
    test: bool = Field(default=False, alias="_test")


def _digest(req: CreateB2BLeadRequest, lead_id: str) -> tuple[str, str]:
    subject = f"[Klaravex B2B] New lead — {req.company or 'unknown company'}"
    seat = f"{req.seat_count} seats" if req.seat_count else "seats: not given"
    body = (
        f"Klara has a new business prospect on the line.\n\n"
        f"Lead ID: {lead_id}\n"
        f"Company: {req.company}\n"
        f"Caller: {req.caller_name} ({req.caller_role or 'role not stated'})\n"
        f"{seat}\n"
        f"Current IT setup: {req.current_it_setup or 'not stated'}\n"
        f"Urgency: {req.urgency or 'not stated'}\n"
        f"Pain points:\n  {req.pain_points or '(none captured yet)'}\n\n"
        f"Phone: {req.phone or '(not captured)'}\n"
        f"Email: {req.email or '(not captured)'}\n\n"
        f"Notes:\n  {req.notes or '(none)'}\n"
    )
    return subject, body


async def _page_anthony(subject: str, body: str) -> None:
    """Best-effort email + Telegram. Never raises — paging failure must not
    take down the voice call."""
    try:
        await send_email(to=ALERT_EMAIL, subject=subject, body=body)
    except Exception as exc:  # noqa: BLE001
        log.warning("send_email failed for B2B lead digest: %s", exc)

    if TELEGRAM_TOKEN and TELEGRAM_CHAT:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={
                        "chat_id": TELEGRAM_CHAT,
                        "text": f"{subject}\n\n{body}",
                    },
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("telegram page failed for B2B lead digest: %s", exc)


@router.post("/create_b2b_lead")
async def create_b2b_lead(req: CreateB2BLeadRequest) -> dict[str, Any]:
    if req.test:
        return {"status": "ok", "test": True, "lead_id": "test-lead-id"}

    if not req.company.strip():
        return {
            "status": "error",
            "reason": "Company name is required before creating a lead.",
        }

    from ..lib.db import get_pool

    pool = await get_pool()
    call_sid = req.call_sid if req.call_sid not in _PLACEHOLDER_SIDS else None

    async with pool.acquire() as conn:
        existing = None
        if call_sid:
            existing = await conn.fetchrow(
                "SELECT id FROM klaravex_b2b_leads WHERE call_sid = $1",
                call_sid,
            )

        if existing is not None:
            await conn.execute(
                """
                UPDATE klaravex_b2b_leads
                   SET company          = COALESCE(NULLIF($2, ''), company),
                       caller_name      = COALESCE(NULLIF($3, ''), caller_name),
                       caller_role      = COALESCE(NULLIF($4, ''), caller_role),
                       seat_count       = COALESCE($5,           seat_count),
                       current_it_setup = COALESCE(NULLIF($6, ''), current_it_setup),
                       pain_points      = COALESCE(NULLIF($7, ''), pain_points),
                       urgency          = COALESCE(NULLIF($8, ''), urgency),
                       phone            = COALESCE(NULLIF($9, ''), phone),
                       email            = COALESCE(NULLIF($10, ''), email),
                       notes            = trim(both E'\n' FROM COALESCE(notes, '') || E'\n' || $11),
                       updated_at       = now()
                 WHERE id = $1
                """,
                existing["id"],
                req.company,
                req.caller_name,
                req.caller_role,
                req.seat_count,
                req.current_it_setup,
                req.pain_points,
                req.urgency,
                req.phone,
                req.email,
                req.notes or "",
            )
            lead_id = str(existing["id"])
            updated = True
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO klaravex_b2b_leads
                    (call_sid, company, caller_name, caller_role, seat_count,
                     current_it_setup, pain_points, urgency, phone, email,
                     notes, pre_brief_status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'pending')
                RETURNING id
                """,
                call_sid,
                req.company,
                req.caller_name or None,
                req.caller_role or None,
                req.seat_count,
                req.current_it_setup or None,
                req.pain_points or None,
                req.urgency or None,
                req.phone or None,
                req.email or None,
                req.notes or None,
            )
            lead_id = str(row["id"])
            updated = False

    subject, body = _digest(req, lead_id)
    await _page_anthony(subject, body)

    # Fire pre-brief pipeline as a background task (V7). The voice call must
    # not wait for LLM round-trips — dispatch_lead_pre_brief is fire-and-forget.
    if not updated:
        asyncio.create_task(dispatch_lead_pre_brief(lead_id, req.model_dump(by_alias=False)))

    return {
        "status": "ok",
        "lead_id": lead_id,
        "updated": updated,
        "next_step": "send_booking_link",
    }
