"""Vapi tool: vip_extension_check.

Silent VIP-extension code validator. Klara calls this when a caller — unprompted —
enters DTMF digits on the keypad or says they have a "priority code."

Per design (infra/vapi-prompts/VIP-EXTENSION-DESIGN.md, 2026-06-11):
- Existence of the VIP extension is NEVER advertised. The code lives in env
  (VIP_EXTENSION_CODE), the destination number lives in env (VIP_TRANSFER_NUMBER),
  neither is ever returned to the caller or surfaced in a prompt.
- On match → returns {authorized: true}. Klara then calls escalate_to_anthony
  with bridge_call=true, which consumes VIP_TRANSFER_NUMBER server-side and
  dials Anthony's cell. The destination number never round-trips through the
  LLM transcript.
- On miss → returns {authorized: false}. No "wrong code" feedback (no brute-force
  oracle).
- Rate limit: 2 strikes per call_sid, then locked for the rest of the call.
"""

import hmac
import logging
import os
import re
from typing import Any

import asyncpg
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..lib.db import get_pool

log = logging.getLogger("klaravex.vapi.vip_extension_check")
router = APIRouter()

VIP_EXTENSION_CODE = os.environ.get("VIP_EXTENSION_CODE", "")
MAX_ATTEMPTS_PER_CALL = 2

_PLACEHOLDER_SIDS = {"", "{{call.id}}", "{{call_sid}}", "{{CALL_SID}}", "None", "null"}


class VipExtensionCheckRequest(BaseModel):
    code: str = Field(default="")
    call_sid: str = Field(default="")
    test: bool = Field(default=False, alias="_test")


def _is_valid_code(code: str) -> bool:
    # 6–8 digits — room for growth (2026-06-26). Was fixed 6.
    return bool(re.fullmatch(r"\d{6,8}", code))


async def _attempt_count(conn: asyncpg.Connection, call_sid: str) -> int:
    if not call_sid or call_sid in _PLACEHOLDER_SIDS:
        return 0
    return await conn.fetchval(
        """
        SELECT count(*) FROM klaravex_voice_auth_attempts
         WHERE call_sid = $1 AND trust_level IN ('vip_extension_match','vip_extension_miss','vip_extension_locked')
        """,
        call_sid,
    ) or 0


async def _record(
    conn: asyncpg.Connection,
    *,
    call_sid: str,
    submitted_code: str,
    trust_level: str,
    outcome: str,
    attempt_number: int,
) -> None:
    if not call_sid or call_sid in _PLACEHOLDER_SIDS:
        return
    try:
        await conn.execute(
            """
            INSERT INTO klaravex_voice_auth_attempts
              (call_sid, submitted_code, trust_level, outcome, attempt_number)
            VALUES ($1, $2, $3, $4, $5)
            """,
            call_sid, submitted_code, trust_level, outcome, attempt_number,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("vip_extension_check log insert failed (non-fatal): %s", exc)


@router.post("/vip_extension_check")
async def vip_extension_check(req: VipExtensionCheckRequest) -> dict[str, Any]:
    if req.test:
        return {"authorized": False, "test": True}

    if not VIP_EXTENSION_CODE:
        # Fail-closed: no code env means the feature is intentionally off.
        log.warning("vip_extension_check called but VIP_EXTENSION_CODE not set")
        return {"authorized": False}

    submitted = (req.code or "").strip()
    call_sid = req.call_sid if req.call_sid not in _PLACEHOLDER_SIDS else ""

    pool = await get_pool()
    async with pool.acquire() as conn:
        prior = await _attempt_count(conn, call_sid)
        if prior >= MAX_ATTEMPTS_PER_CALL:
            await _record(conn, call_sid=call_sid, submitted_code="<locked>",
                          trust_level="vip_extension_locked", outcome="locked",
                          attempt_number=prior + 1)
            log.info("vip_extension_check locked: call_sid=%s prior_attempts=%d", call_sid, prior)
            return {"authorized": False}

        attempt_number = prior + 1
        if not _is_valid_code(submitted):
            await _record(conn, call_sid=call_sid, submitted_code="<invalid_format>",
                          trust_level="vip_extension_miss", outcome="invalid_format",
                          attempt_number=attempt_number)
            return {"authorized": False}

        # Constant-time compare to prevent any timing oracle.
        is_match = hmac.compare_digest(submitted.encode(), VIP_EXTENSION_CODE.encode())

        await _record(
            conn,
            call_sid=call_sid,
            submitted_code="<match>" if is_match else "<miss>",
            trust_level="vip_extension_match" if is_match else "vip_extension_miss",
            outcome="match" if is_match else "miss",
            attempt_number=attempt_number,
        )

    if is_match:
        log.info("vip_extension_check MATCH: call_sid=%s attempt=%d", call_sid, attempt_number)
        return {"authorized": True}
    log.info("vip_extension_check miss: call_sid=%s attempt=%d", call_sid, attempt_number)
    return {"authorized": False}
