"""Public CTA endpoints for dropped-call recovery emails.

Mounted at /api/v1/recovery — INTENTIONALLY not behind x-vapi-secret,
because the customer clicks these links from their own email client.
Authorization is per-link via the signed token (recovery.tokens).

Endpoints
---------
GET /resolved?token=...
    Customer self-certifies the issue is fixed. Marks Stripe session
    metadata.outcome=resolved_post_call. No Anthony notification.

GET /callback?token=...
    Customer still has the issue and wants a return call. Marks Stripe
    metadata.outcome=callback_requested and emails Anthony with the
    call_sid + the customer's email so he can call them back.

GET /refund?token=...
    Customer asks for a refund. Marks Stripe metadata.outcome=
    refund_requested and emails Anthony for manual review. NEVER issues
    the refund automatically — refund authority is Anthony alone (per
    the 2026-06-11 directive).

Response
--------
Each endpoint returns a small HTML page with a friendly confirmation
and a link to klaravex.com. Customers should see something pretty, not
JSON.
"""

import logging
import os
from typing import Any

import stripe
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from ..lib.email import send_email
from .tokens import TokenError, verify_token

log = logging.getLogger("klaravex.recovery")
router = APIRouter()

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
_ANTHONY_EMAIL = os.environ.get("ANTHONY_EMAIL", "astewart.tcml@gmail.com")


def _page(title: str, body_html: str, status: int = 200) -> HTMLResponse:
    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<title>{title} — Klaravex</title>'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>'
        'body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
        'background:#f6f8fa;margin:0;padding:48px 16px;color:#111}'
        '.card{max-width:520px;margin:0 auto;background:#fff;'
        'border-radius:12px;padding:32px;box-shadow:0 1px 3px rgba(0,0,0,.08)}'
        'h1{margin:0 0 12px;color:#0b3d62;font-size:24px}'
        'p{line-height:1.55}'
        'a{color:#0b3d62}'
        '</style></head><body>'
        f'<div class="card"><h1>{title}</h1>{body_html}'
        '<p style="margin-top:24px"><a href="https://klaravex.com">'
        'Return to klaravex.com</a></p></div></body></html>'
    )
    return HTMLResponse(content=html, status_code=status)


def _find_session_by_call_sid(call_sid: str):
    sessions = stripe.checkout.Session.list(limit=20)
    for s in sessions.auto_paging_iter():
        meta = getattr(s, "metadata", None)
        if meta and getattr(meta, "call_sid", None) == call_sid:
            return s
    return None


def _merge_metadata(session, **patch) -> None:
    meta = getattr(session, "metadata", None)
    existing = {}
    if meta:
        for k in (meta.keys() if hasattr(meta, "keys") else []):
            existing[k] = getattr(meta, k)
    existing.update(patch)
    try:
        stripe.checkout.Session.modify(session.id, metadata=existing)
    except Exception as e:  # noqa: BLE001
        log.warning("stripe metadata update failed for %s: %s", session.id, e)


@router.get("/resolved")
async def cta_resolved(token: str = Query(...)) -> HTMLResponse:
    try:
        payload = verify_token(token)
    except TokenError as e:
        return _page("Link expired", f"<p>This link is no longer valid: {e}.</p>", status=400)
    call_sid = payload["sid"]
    session = _find_session_by_call_sid(call_sid)
    if session is None:
        return _page("Thanks", "<p>Thanks for the update. Glad it's working.</p>")
    _merge_metadata(session, outcome="resolved_post_call")
    log.info("recovery: resolved acknowledged call_sid=%s", call_sid)
    return _page("Thanks — glad we got it sorted",
                 "<p>We've marked your case as resolved. "
                 "If anything else comes up, just call us back at "
                 "<a href=\"tel:+14243486010\">(424) 348-6010</a>.</p>")


@router.get("/callback")
async def cta_callback(token: str = Query(...)) -> HTMLResponse:
    try:
        payload = verify_token(token)
    except TokenError as e:
        return _page("Link expired", f"<p>This link is no longer valid: {e}.</p>", status=400)
    call_sid = payload["sid"]
    session = _find_session_by_call_sid(call_sid)
    caller_email = ""
    if session is not None:
        _merge_metadata(session, outcome="callback_requested")
        caller_email = getattr(session, "customer_email", "") or (
            getattr(session, "customer_details", None) and getattr(session.customer_details, "email", "") or ""
        )
    # Notify Anthony so he can call back.
    await send_email(
        to=_ANTHONY_EMAIL,
        subject="[Klaravex] Callback requested — paid customer",
        body=(
            f"Customer requested a callback after a dropped call.\n\n"
            f"  call_sid:     {call_sid}\n"
            f"  customer:     {caller_email or 'unknown'}\n"
            f"  stripe sess:  {getattr(session, 'id', '-') if session else '-'}\n\n"
            "Please call them back."
        ),
    )
    log.info("recovery: callback requested call_sid=%s customer=%s", call_sid, caller_email)
    return _page("We'll call you back",
                 "<p>Got it. Our team has been notified and will call you back shortly. "
                 "If you'd rather call us first, we're at "
                 "<a href=\"tel:+14243486010\">(424) 348-6010</a>.</p>")


@router.get("/refund")
async def cta_refund(token: str = Query(...)) -> HTMLResponse:
    try:
        payload = verify_token(token)
    except TokenError as e:
        return _page("Link expired", f"<p>This link is no longer valid: {e}.</p>", status=400)
    call_sid = payload["sid"]
    session = _find_session_by_call_sid(call_sid)
    caller_email = ""
    if session is not None:
        _merge_metadata(session, outcome="refund_requested")
        caller_email = getattr(session, "customer_email", "") or (
            getattr(session, "customer_details", None) and getattr(session.customer_details, "email", "") or ""
        )
    # Notify Anthony — he decides whether to refund.
    amount = getattr(session, "amount_total", None) if session is not None else None
    amount_str = f"${(amount or 0)/100:.2f}" if amount else "unknown"
    await send_email(
        to=_ANTHONY_EMAIL,
        subject="[Klaravex] Refund REQUESTED — manual review needed",
        body=(
            f"Customer requested a refund after a dropped call. NOT YET ISSUED.\n\n"
            f"  call_sid:     {call_sid}\n"
            f"  customer:     {caller_email or 'unknown'}\n"
            f"  stripe sess:  {getattr(session, 'id', '-') if session else '-'}\n"
            f"  amount paid:  {amount_str}\n\n"
            "Decide refund manually in the Stripe dashboard. Refunds are NEVER\n"
            "auto-issued."
        ),
    )
    log.info("recovery: refund requested call_sid=%s customer=%s", call_sid, caller_email)
    return _page("Refund request received",
                 "<p>Got it. Our team reviews each refund personally to make sure "
                 "we actually missed the mark — you'll hear back within a few hours. "
                 "Thanks for the patience.</p>")
