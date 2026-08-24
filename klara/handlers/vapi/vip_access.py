"""Phase 12 V12 — VIP access lookup.

triage_en calls this on every inbound call. If the from-number is in
klaravex_vip_directory AND active, returns is_vip=True with the assistant
key to silently transfer to. Otherwise returns is_vip=False and triage_en
proceeds with the standard consumer greeting (PH12.V13).

Latency budget: <100ms p99. Vapi function timeout is 5s; anything slower
fails open (treated as is_vip=False by triage_en — see PH12.V14 scenario 9).

Behind x-vapi-secret (mounted in vapi/router.py).
"""

import logging
import re
import time
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..lib.db import get_pool

log = logging.getLogger("klaravex.vapi.vip_access")
router = APIRouter()

_E164_RE = re.compile(r"^\+[1-9][0-9]{6,14}$")
_PLACEHOLDER_PHONES = {"", "+15555555555", "+10000000000", "anonymous", "unknown"}


class VipAccessRequest(BaseModel):
    call_sid: str = Field(default="")
    from_number_e164: str = Field(default="")
    assistant_id: str = Field(default="")
    test: bool = Field(default=False, alias="_test")
    # Vapi doesn't substitute {{call.customer.number}} into LLM-generated
    # function arguments — only into static prompt text. The LLM sends
    # "unknown" for both fields, so we fall back to the envelope below.
    message: Optional[dict[str, Any]] = None


def _normalize_phone(raw: str) -> str:
    """E.164-ish normalization: drop spaces, dashes, parens; ensure leading +."""
    if not raw:
        return ""
    cleaned = re.sub(r"[\s\-\(\)\.]+", "", raw.strip())
    if cleaned and not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned


def _miss_response(call_sid: str, from_phone: str, started_ns: int, outcome: str = "miss") -> dict[str, Any]:
    """Standard miss/error response. Backend NEVER hands a non-VIP caller VIP context."""
    return {
        "is_vip": False,
        "vip_id": None,
        "vip_name": None,
        "route_to_assistant": None,
        "context": None,
        "diagnostic": {
            "call_sid": call_sid,
            "from_phone": from_phone,
            "outcome": outcome,
            "latency_ms": int((time.monotonic_ns() - started_ns) / 1_000_000),
        },
    }


@router.post("/vip_access")
async def vip_access(req: VipAccessRequest) -> dict[str, Any]:
    started_ns = time.monotonic_ns()

    if req.test:
        return {
            "is_vip": True,
            "vip_id": 1,
            "vip_name": "Test User",
            "route_to_assistant": "vip_handler",
            "context": {"test": True},
            "diagnostic": {"outcome": "test", "latency_ms": 0},
        }

    envelope_call = ((req.message or {}).get("call") or {}) if req.message else {}
    envelope_number = ((envelope_call.get("customer") or {}).get("number") or "").strip()
    envelope_call_id = (envelope_call.get("id") or "").strip()

    raw_phone = req.from_number_e164 or ""
    if (not raw_phone) or raw_phone.lower() in _PLACEHOLDER_PHONES:
        raw_phone = envelope_number

    raw_call_sid = (req.call_sid or "").strip()
    if (not raw_call_sid) or raw_call_sid.lower() in _PLACEHOLDER_PHONES:
        raw_call_sid = envelope_call_id

    phone = _normalize_phone(raw_phone)
    call_sid = raw_call_sid

    if not phone or phone in _PLACEHOLDER_PHONES or not _E164_RE.match(phone):
        log.info("vip_access miss (bad phone): call_sid=%s raw=%r", call_sid, req.from_number_e164)
        await _log_access(call_sid, phone, req.assistant_id, is_vip=False, vip_id=None, latency_ms=0, outcome="miss")
        return _miss_response(call_sid, phone, started_ns, outcome="miss")

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, vip_name, route_to_assistant, context
                  FROM klaravex_vip_directory
                 WHERE phone_e164 = $1
                   AND is_active = TRUE
                 LIMIT 1
                """,
                phone,
            )
    except Exception as exc:
        log.exception("vip_access DB error: %s", exc)
        latency_ms = int((time.monotonic_ns() - started_ns) / 1_000_000)
        await _log_access(call_sid, phone, req.assistant_id, is_vip=False, vip_id=None, latency_ms=latency_ms, outcome="error")
        return _miss_response(call_sid, phone, started_ns, outcome="error")

    latency_ms = int((time.monotonic_ns() - started_ns) / 1_000_000)

    if row is None:
        log.info("vip_access miss: phone=%s latency_ms=%d", phone, latency_ms)
        await _log_access(call_sid, phone, req.assistant_id, is_vip=False, vip_id=None, latency_ms=latency_ms, outcome="miss")
        return _miss_response(call_sid, phone, started_ns, outcome="miss")

    log.info("vip_access HIT: phone=%s vip=%s route=%s latency_ms=%d",
             phone, row["vip_name"], row["route_to_assistant"], latency_ms)
    await _log_access(call_sid, phone, req.assistant_id, is_vip=True, vip_id=row["id"], latency_ms=latency_ms, outcome="hit")

    return {
        "is_vip": True,
        "vip_id": row["id"],
        "vip_name": row["vip_name"],
        "route_to_assistant": row["route_to_assistant"],
        "context": row["context"] or {},
        "diagnostic": {
            "call_sid": call_sid,
            "from_phone": phone,
            "outcome": "hit",
            "latency_ms": latency_ms,
        },
    }


async def _log_access(
    call_sid: str,
    from_phone: str,
    assistant_id: str,
    *,
    is_vip: bool,
    vip_id: int | None,
    latency_ms: int,
    outcome: str,
) -> None:
    """Best-effort access log. Failure to log NEVER blocks the response."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO klaravex_vip_access_log
                    (call_sid, from_phone_e164, assistant_id, is_vip, vip_id, latency_ms, outcome)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                call_sid or "",
                from_phone or "",
                assistant_id or "",
                is_vip,
                vip_id,
                latency_ms,
                outcome,
            )
    except Exception as exc:
        log.warning("vip_access log insert failed (non-fatal): %s", exc)
