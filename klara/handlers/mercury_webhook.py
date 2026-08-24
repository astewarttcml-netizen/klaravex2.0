"""
Mercury bank webhook handler.

Mercury sends transaction events for our virtual cards (one per AI marketing team).
Each event is recorded into klaravex_marketing_spend and then we enforce the
budget cap (freeze the card if exceeded).
"""

import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from .lib.db import get_pool
from .lib import mercury as mercury_lib

log = logging.getLogger("klaravex.mercury_webhook")
router = APIRouter()


@router.get("/webhook")
async def mercury_webhook_verify_get():
    """Mercury / curl reachability ping. Always 200."""
    return {"status": "ok", "service": "mercury-webhook"}


@router.post("/webhook")
async def mercury_webhook(
    request: Request,
    x_mercury_signature: str = Header(default=""),
):
    payload = await request.body()

    # Mercury sends an empty-body verification ping when you add the endpoint.
    # Always return 200 on those — no signature, no JSON to parse.
    if not payload or payload.strip() in (b"", b"{}", b'""'):
        return {"status": "ok", "ping": True}

    if not mercury_lib.verify_webhook_signature(payload, x_mercury_signature):
        log.warning("Mercury webhook signature invalid")
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        event = json.loads(payload)
    except Exception:
        # Don't fail the webhook on malformed body — log + 200 so Mercury
        # doesn't keep retrying garbage.
        log.warning("Mercury webhook body not JSON: %s", payload[:200])
        return {"status": "ignored", "reason": "non_json_body"}

    event_type = event.get("type", "")
    txn = event.get("data", {}) or {}
    card_id = txn.get("card_id") or txn.get("cardId")

    if not card_id:
        return {"status": "ignored", "reason": "no_card_id"}

    # Look up which team owns this card
    pool = await get_pool()
    async with pool.acquire() as conn:
        team_id = await conn.fetchval(
            "SELECT id FROM klaravex_marketing_teams WHERE mercury_card_id=$1",
            card_id,
        )
    if not team_id:
        log.warning("Mercury txn for unknown card %s", card_id)
        return {"status": "ignored", "reason": "card_not_owned_by_team"}

    spend_id = await mercury_lib.record_transaction(str(team_id), txn)
    enforcement = await mercury_lib.enforce_budget_after_transaction(str(team_id))

    log.info(
        "Mercury %s | team=%s | spend_row=%s | enforce=%s",
        event_type, team_id, spend_id, enforcement,
    )
    return {"status": "ok", "spend_id": spend_id, "enforcement": enforcement}
