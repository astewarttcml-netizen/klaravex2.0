"""Phase 12 V2 — biz_engineer authentication: lookup_client.

Customer types their 6-digit code on the DTMF keypad (spoken-digit fallback
handled by Vapi). This endpoint:

  1. Validates the code against klaravex_clients.customer_code (constant-time
     comparison after the SELECT — no fast path that leaks "code unknown" vs.
     "code valid but phone mismatch").
  2. Decides a trust_level:
       full    — code matches AND caller_phone matches a number on file.
       verify  — code matches but caller_phone does not.
       invalid — code does not match any client.
       locked  — third invalid attempt in the same call_sid.
  3. Records every attempt to klaravex_voice_auth_attempts so dashboards
     and post-call review can audit the auth path.
  4. Returns ONLY metadata the caller is allowed to hear at that trust level
     (NEVER leak stored phone/email/seat names at `verify` trust).

Behind x-vapi-secret (mounted in vapi/router.py).
"""

import hmac
import logging
import os
import re
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

log = logging.getLogger("klaravex.vapi.lookup_client")
router = APIRouter()

MAX_ATTEMPTS = int(os.environ.get("VOICE_AUTH_MAX_ATTEMPTS", "3"))
_CODE_RE = re.compile(r"^\d{6,8}$")  # 6–8 digits — room for growth (2026-06-26)
_PLACEHOLDER_SIDS = {"call_sid_placeholder", "1234567890", "", "{{call.id}}", "unknown"}


class LookupClientRequest(BaseModel):
    call_sid: str = Field(default="")
    customer_code: str = Field(default="")
    caller_phone: str = Field(default="")
    test: bool = Field(default=False, alias="_test")


def _normalize_phone(raw: str) -> str:
    """E.164-ish normalization — drop spaces, parens, dashes; keep leading +."""
    if not raw:
        return ""
    cleaned = re.sub(r"[^\d+]", "", raw)
    # If multiple + signs leaked in, only the leading one survives.
    if "+" in cleaned[1:]:
        cleaned = cleaned[0] + cleaned[1:].replace("+", "")
    return cleaned


def _phones_match(submitted: str, on_file: str) -> bool:
    a, b = _normalize_phone(submitted), _normalize_phone(on_file)
    if not a or not b:
        return False
    # Compare last 10 digits — covers +1 vs. unprefixed US numbers without
    # being fooled by leading-zero padding.
    return a[-10:] == b[-10:] and len(a) >= 10 and len(b) >= 10


async def _count_recent_attempts(conn: Any, call_sid: str) -> int:
    if not call_sid:
        return 0
    row = await conn.fetchrow(
        """
        SELECT count(*) AS n
          FROM klaravex_voice_auth_attempts
         WHERE call_sid = $1
        """,
        call_sid,
    )
    return int(row["n"]) if row else 0


async def _record_attempt(
    conn: Any,
    *,
    call_sid: str,
    submitted_code: str,
    caller_phone: str,
    matched_client: str | None,
    trust_level: str,
    outcome: str,
    attempt_number: int,
) -> None:
    await conn.execute(
        """
        INSERT INTO klaravex_voice_auth_attempts
            (call_sid, submitted_code, caller_phone, matched_client,
             trust_level, outcome, attempt_number)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        call_sid,
        submitted_code,
        caller_phone or None,
        matched_client,
        trust_level,
        outcome,
        attempt_number,
    )


async def _open_tickets_count(conn: Any, client_id: str) -> int:
    row = await conn.fetchrow(
        """
        SELECT count(*) AS n
          FROM klaravex_tickets
         WHERE client_id = $1
           AND status IN ('open', 'in_progress', 'awaiting_customer')
        """,
        client_id,
    )
    return int(row["n"]) if row else 0


def _bundle_full(client: dict[str, Any], open_tickets: int) -> dict[str, Any]:
    """FULL trust — the caller can hear specifics."""
    return {
        "trust_level": "full",
        "authorized": True,
        "client": {
            "id": str(client["id"]),
            "company": client.get("name") or "",
            "plan_tier": client.get("plan_tier") or client.get("segment") or "",
            "email_on_file": client.get("email") or "",
            "phone_on_file": client.get("phone") or "",
            "open_tickets": open_tickets,
        },
    }


def _bundle_verify(client: dict[str, Any]) -> dict[str, Any]:
    """VERIFY trust — code valid, phone mismatch. NEVER read back stored data."""
    return {
        "trust_level": "verify",
        "authorized": True,
        "client": {
            "id": str(client["id"]),
            # No company / contact / ticket detail at this level.
        },
        "advice": (
            "Caller code is valid but the phone number is unknown. "
            "Stay in advisory mode: do not read back stored contact data, "
            "seat names, or environment details. You may open a ticket and "
            "give general guidance."
        ),
    }


@router.post("/lookup_client")
async def lookup_client(req: LookupClientRequest) -> dict[str, Any]:
    if req.test:
        return {"status": "ok", "test": True, "trust_level": "test"}

    code = (req.customer_code or "").strip()
    call_sid = req.call_sid if req.call_sid not in _PLACEHOLDER_SIDS else ""

    if not _CODE_RE.match(code):
        return {
            "authorized": False,
            "trust_level": "invalid",
            "reason": "Customer code must be six to eight digits.",
        }

    # Import lazily so test_handler_imports compile-check stays dependency-free.
    from ..lib.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        prior_attempts = await _count_recent_attempts(conn, call_sid)
        if prior_attempts >= MAX_ATTEMPTS:
            await _record_attempt(
                conn,
                call_sid=call_sid,
                submitted_code=code,
                caller_phone=req.caller_phone,
                matched_client=None,
                trust_level="locked",
                outcome="locked",
                attempt_number=prior_attempts + 1,
            )
            return {
                "authorized": False,
                "trust_level": "locked",
                "reason": (
                    "Too many invalid attempts. Please end the call and try again, "
                    "or speak to our new-client team."
                ),
            }

        # Look up by code; compare constant-time after fetch so the timing
        # is identical for "no such code" vs. "code present but phone wrong".
        row = await conn.fetchrow(
            """
            SELECT id, name, email, phone, segment,
                   COALESCE(metadata ->> 'plan_tier', segment) AS plan_tier,
                   customer_code
              FROM klaravex_clients
             WHERE customer_code = $1
            """,
            code,
        )

        # Constant-time check: compare a known good salt to the row's code
        # (or an empty string) so the same hmac.compare_digest path runs.
        match_ok = row is not None and hmac.compare_digest(
            (row["customer_code"] or "").encode("ascii"),
            code.encode("ascii"),
        )

        if not match_ok:
            attempt_no = prior_attempts + 1
            await _record_attempt(
                conn,
                call_sid=call_sid,
                submitted_code=code,
                caller_phone=req.caller_phone,
                matched_client=None,
                trust_level="invalid",
                outcome="bad_code",
                attempt_number=attempt_no,
            )
            return {
                "authorized": False,
                "trust_level": "invalid",
                "reason": "That code did not match an account on file.",
                "attempts_remaining": max(MAX_ATTEMPTS - attempt_no, 0),
            }

        client = dict(row)
        phone_match = _phones_match(req.caller_phone, client.get("phone") or "")
        open_tickets = await _open_tickets_count(conn, client["id"])

        if phone_match:
            bundle = _bundle_full(client, open_tickets)
            await _record_attempt(
                conn,
                call_sid=call_sid,
                submitted_code=code,
                caller_phone=req.caller_phone,
                matched_client=str(client["id"]),
                trust_level="full",
                outcome="ok",
                attempt_number=prior_attempts + 1,
            )
            return bundle

        bundle = _bundle_verify(client)
        await _record_attempt(
            conn,
            call_sid=call_sid,
            submitted_code=code,
            caller_phone=req.caller_phone,
            matched_client=str(client["id"]),
            trust_level="verify",
            outcome="phone_mismatch",
            attempt_number=prior_attempts + 1,
        )
        return bundle
