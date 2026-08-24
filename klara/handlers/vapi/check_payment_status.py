"""A9 Vapi tool: check_payment_status.

Vapi polls this every ~5 seconds while caller is on the line waiting for
payment. Returns paid=true once the Stripe checkout.session has paid.
"""

import os
from typing import Any

import stripe
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")


class CheckRequest(BaseModel):
    """Accepts either:
      - call_sid (preferred — Klara has the Vapi call SID via Vapi's tool
        envelope; we search Stripe metadata.call_sid for the matching
        session, same pattern as voice_payment_confirmation.py)
      - session_id (legacy — if Klara was given the Stripe session_id
        directly from a prior send_payment_link result).

    At least ONE must be provided.
    """
    call_sid: str = Field(default="")
    session_id: str = Field(default="")
    test: bool = Field(default=False, alias="_test")


async def _find_session_by_call_sid(call_sid: str):
    """Search the most-recent Stripe checkout sessions for metadata.call_sid == call_sid.

    Bounded to a single 100-row page so that a MISS (e.g. caller hung up
    before send_payment_link fired) returns in <1s instead of paginating
    through the account's entire session history. Calls in flight always
    have their Stripe session within the last few minutes, so the first
    page is enough.

    Note: Stripe SDK objects are StripeObject (not dict). Use attribute access
    or dict-cast; dict-style .get() raises AttributeError on the StripeObject.
    """
    sessions = stripe.checkout.Session.list(limit=100)
    for session in sessions.data:
        meta = getattr(session, "metadata", None)
        if not meta:
            continue
        # metadata is a StripeObject too — getattr is safest
        if getattr(meta, "call_sid", None) == call_sid:
            return session
    return None


@router.post("/check_payment_status")
async def check_payment_status(req: CheckRequest) -> dict[str, Any]:
    if req.test:
        return {"status": "ok", "test": True, "paid": False}
    if not stripe.api_key:
        raise HTTPException(status_code=503, detail="stripe not configured")
    if not req.session_id and not req.call_sid:
        raise HTTPException(status_code=400, detail="call_sid or session_id required")

    session = None
    # Defense-in-depth: Klara has historically passed her Vapi call_id as
    # `session_id` even though that field expects a Stripe checkout session
    # ID. Real Stripe session IDs always begin with `cs_`. If the value
    # doesn't, ignore it and fall through to the call_sid metadata search
    # — the prompt-layer fix is the primary defense; this is the safety net.
    looks_like_stripe_session = req.session_id.startswith("cs_")
    if looks_like_stripe_session:
        try:
            session = stripe.checkout.Session.retrieve(req.session_id)
        except stripe.error.InvalidRequestError as exc:
            raise HTTPException(status_code=404, detail=f"session not found: {exc.user_message}") from exc
        except stripe.error.StripeError as exc:
            raise HTTPException(status_code=502, detail=f"stripe error: {exc.user_message}") from exc
    if session is None and req.call_sid:
        # Klara passed call_sid — find the matching Stripe session via metadata.
        try:
            session = await _find_session_by_call_sid(req.call_sid)
        except stripe.error.StripeError as exc:
            raise HTTPException(status_code=502, detail=f"stripe error: {exc.user_message}") from exc
        if session is None:
            # No checkout session for this call yet — most common reason:
            # send_payment_link wasn't called yet OR the caller hasn't tapped
            # the link. Tell Klara not_paid so she keeps waiting.
            return {
                "status": "ok",
                "paid": False,
                "payment_status": "not_yet_started",
                "call_sid": req.call_sid,
            }

    payment_status = getattr(session, "payment_status", None)
    paid = payment_status == "paid"
    meta = getattr(session, "metadata", None)
    return {
        "status": "ok",
        "paid": paid,
        "session_id": getattr(session, "id", None),
        "call_sid": req.call_sid or (getattr(meta, "call_sid", None) if meta else None),
        "payment_status": payment_status,
        "amount_total": getattr(session, "amount_total", None),
    }
