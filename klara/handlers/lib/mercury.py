"""
Mercury bank + virtual card API client for the marketing AI competition.

Two responsibilities:

  1. Issue + manage virtual cards (one per team) with $1000 hard cap.
  2. Receive Mercury transaction webhooks → record into klaravex_marketing_spend
     → if spend approaches cap, freeze the card via Mercury API.

Mercury API docs: https://docs.mercury.com/reference/
Auth: Bearer token via Authorization header. Account ID is account-scoped.

Required env:
    MERCURY_API_TOKEN
    MERCURY_ACCOUNT_ID
    MERCURY_WEBHOOK_SECRET   (HMAC signing for inbound webhooks)
"""

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from .db import get_pool

log = logging.getLogger("klaravex.mercury")

MERCURY_API = "https://api.mercury.com/api/v1"
MERCURY_API_TOKEN = os.environ.get("MERCURY_API_TOKEN", "")
MERCURY_ACCOUNT_ID = os.environ.get("MERCURY_ACCOUNT_ID", "")
MERCURY_WEBHOOK_SECRET = os.environ.get("MERCURY_WEBHOOK_SECRET", "")

# Merchant Category Codes considered "approved" for marketing spend.
APPROVED_MERCHANT_CATEGORIES = {
    "ads", "advertising", "marketing", "saas",
    "software", "professional_services", "design",
}


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {MERCURY_API_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


# ── Allowlist ─────────────────────────────────────────────────────────────────
#
# Defense in depth. Mercury Personal Access Tokens are scoped to the whole
# account — so technically the API token can see other cards on Anthony's
# Mercury account.
#
# This module REFUSES to touch any card_id that is not registered in
# klaravex_marketing_teams.mercury_card_id. Even if the token leaks, even
# if Anthony adds an instruction that asks the agent to "use card X to buy Y",
# this gate ensures the only cards our code will ever issue API calls against
# are the two assigned to Alpha and Beta.
#
# To extend the allowlist: insert a row in klaravex_marketing_teams. The
# allowlist is read fresh on every call (no caching) so it's always current.

async def _is_allowed_card(card_id: str) -> bool:
    """Return True only if card_id is registered to a Klaravex marketing team."""
    if not card_id:
        return False
    pool = await get_pool()
    async with pool.acquire() as conn:
        match = await conn.fetchval(
            "SELECT 1 FROM klaravex_marketing_teams WHERE mercury_card_id = $1",
            card_id,
        )
    return bool(match)


async def list_allowed_cards() -> list[dict]:
    """Operator-introspectable allowlist. What cards CAN this code touch?"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT team_code, display_name, mercury_card_id, mercury_card_last4, status
              FROM klaravex_marketing_teams
             WHERE mercury_card_id IS NOT NULL
             ORDER BY team_code
            """,
        )
    return [dict(r) for r in rows]


async def issue_virtual_card(
    *,
    team_code: str,
    nickname: str,
    limit_usd: float,
    period: str = "month",
) -> dict:
    """Create a Mercury virtual card with a spending limit.

    Returns the raw Mercury response with card.id, card.last_four_digits, etc.

    Safety: bails out if the named team already has a card assigned —
    prevents accidental "issue more cards" loop. To issue a new card,
    first manually NULL out mercury_card_id on the team row.
    """
    if not (MERCURY_API_TOKEN and MERCURY_ACCOUNT_ID):
        return {"error": "MERCURY_API_TOKEN or MERCURY_ACCOUNT_ID not set"}
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT mercury_card_id FROM klaravex_marketing_teams WHERE team_code=$1",
            team_code,
        )
    if existing:
        log.warning("issue_virtual_card refused: team %s already has card %s", team_code, existing)
        return {
            "error": "team_already_has_card",
            "team_code": team_code,
            "existing_card_id": existing,
        }
    payload = {
        "nickname": nickname,
        "type": "virtual",
        "limit": {
            "amount": int(limit_usd * 100),
            "period": period,
        },
        "metadata": {"team_code": team_code, "purpose": "ai_marketing_team"},
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{MERCURY_API}/accounts/{MERCURY_ACCOUNT_ID}/cards",
                json=payload,
                headers=_headers(),
            )
        if r.status_code in (200, 201):
            return r.json()
        return {"error": f"http_{r.status_code}: {r.text[:300]}"}
    except Exception as exc:
        log.exception("mercury card issue exception: %s", exc)
        return {"error": str(exc)}


async def freeze_card(card_id: str) -> dict:
    """Freeze a card immediately. Used when daily cap or budget hit."""
    if not MERCURY_API_TOKEN:
        return {"error": "MERCURY_API_TOKEN not set"}
    if not await _is_allowed_card(card_id):
        log.error("REFUSED freeze on card_id=%s — not in marketing-team allowlist", card_id)
        return {"error": "card_not_in_allowlist", "card_id": card_id}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{MERCURY_API}/cards/{card_id}/freeze",
                headers=_headers(),
            )
        if r.status_code in (200, 204):
            return {"ok": True}
        return {"error": f"http_{r.status_code}: {r.text[:200]}"}
    except Exception as exc:
        log.exception("mercury card freeze exception: %s", exc)
        return {"error": str(exc)}


async def unfreeze_card(card_id: str) -> dict:
    if not MERCURY_API_TOKEN:
        return {"error": "MERCURY_API_TOKEN not set"}
    if not await _is_allowed_card(card_id):
        log.error("REFUSED unfreeze on card_id=%s — not in marketing-team allowlist", card_id)
        return {"error": "card_not_in_allowlist", "card_id": card_id}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{MERCURY_API}/cards/{card_id}/unfreeze",
                headers=_headers(),
            )
        if r.status_code in (200, 204):
            return {"ok": True}
        return {"error": f"http_{r.status_code}: {r.text[:200]}"}
    except Exception as exc:
        log.exception("mercury card unfreeze exception: %s", exc)
        return {"error": str(exc)}


def verify_webhook_signature(payload: bytes, signature_header: str) -> bool:
    """Mercury sends HMAC-SHA256 of body using webhook secret."""
    if not MERCURY_WEBHOOK_SECRET:
        return True  # not configured = accept all (dev / test)
    expected = hmac.new(
        MERCURY_WEBHOOK_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


async def record_transaction(team_id: str, mercury_txn: dict) -> Optional[str]:
    """Record a Mercury card transaction into klaravex_marketing_spend.

    Returns the inserted spend row id, or None if duplicate (idempotent).
    """
    pool = await get_pool()
    txn_id = mercury_txn.get("id")
    amount_cents = mercury_txn.get("amount", {}).get("amount") or 0
    amount_usd = abs(amount_cents / 100.0)
    merchant_name = (mercury_txn.get("counterparty") or {}).get("name")
    merchant_category = (mercury_txn.get("counterparty") or {}).get("category") or "other"
    status = mercury_txn.get("status", "authorized").lower()
    txn_at_iso = mercury_txn.get("created_at") or mercury_txn.get("transacted_at")
    try:
        txn_at = datetime.fromisoformat(txn_at_iso.replace("Z", "+00:00")) if txn_at_iso else datetime.now(tz=timezone.utc)
    except Exception:
        txn_at = datetime.now(tz=timezone.utc)

    async with pool.acquire() as conn:
        spend_id = await conn.fetchval(
            """
            INSERT INTO klaravex_marketing_spend
              (team_id, mercury_txn_id, merchant_name, merchant_category,
               amount_usd, status, raw_webhook, txn_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
            ON CONFLICT (mercury_txn_id) DO NOTHING
            RETURNING id::text
            """,
            team_id, txn_id, merchant_name, merchant_category,
            amount_usd, status, json.dumps(mercury_txn), txn_at,
        )
        if not spend_id:
            return None
        # Roll spend up to the team row (settled charges only)
        if status == "settled":
            await conn.execute(
                "UPDATE klaravex_marketing_teams SET spend_usd = spend_usd + $1, updated_at=now() WHERE id=$2",
                amount_usd, team_id,
            )
    return spend_id


async def enforce_budget_after_transaction(team_id: str) -> dict:
    """After a charge, check if we're past the budget. If so, freeze the card."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT spend_usd, budget_usd, mercury_card_id, status FROM klaravex_marketing_teams WHERE id=$1",
            team_id,
        )
    if not row:
        return {"checked": False, "reason": "team_not_found"}
    spent = float(row["spend_usd"] or 0)
    budget = float(row["budget_usd"] or 0)
    if spent >= budget and row["mercury_card_id"] and row["status"] in ("live", "soft_launch"):
        result = await freeze_card(row["mercury_card_id"])
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE klaravex_marketing_teams SET status='paused', updated_at=now() WHERE id=$1",
                team_id,
            )
        log.warning("team %s hit budget cap ($%s of $%s) — card frozen", team_id, spent, budget)
        return {"checked": True, "frozen": True, "spent": spent, "budget": budget, "freeze_result": result}
    return {"checked": True, "frozen": False, "spent": spent, "budget": budget}
