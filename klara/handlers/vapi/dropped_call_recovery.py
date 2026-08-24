"""Dropped-call recovery email composer.

Triggered from vapi.webhook_call_event at end-of-call-report. If the
caller paid the $79 per-incident fee but the call ended without an
explicit `outcome=resolved` recorded by a specialist, we email the
caller a recovery message with three signed CTA buttons:

  1. ✅ Issue resolved
  2. 📞 Still having the issue — please call me back
  3. 💰 Request a refund

Refunds are NEVER processed automatically. The refund CTA only flags the
session and emails Anthony, who decides each refund manually (per the
2026-06-11 directive: "i dont want the refund issued unless theres an
issue").

Idempotency
-----------
We mark the Stripe session's `metadata.recovery_email_sent` with a unix
timestamp the first time we send. Subsequent end-of-call-report events
for the same call are no-ops.

Why driven by Stripe metadata (not a DB column)
----------------------------------------------
Stripe already holds the source of truth for which call paid + the
canonical call_sid linkage. Reusing its metadata avoids a second
distributed-state problem and keeps recovery state observable from the
Stripe dashboard.
"""

import logging
import os
import time
from typing import Any

import stripe

from ..lib.email import send_email
from ..recovery.tokens import make_token

log = logging.getLogger("klaravex.vapi.dropped_call_recovery")

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

_API_BASE = os.environ.get("APP_BASE_URL", "https://api.klaravex.com").rstrip("/")
_ANTHONY_EMAIL = os.environ.get("ANTHONY_EMAIL", "astewart.tcml@gmail.com")

# Klara records outcomes on the session via metadata.outcome (set by
# log_session_outcome). If the outcome is in this set, the call is
# considered successfully concluded and NO recovery email is sent.
_RESOLVED_OUTCOMES = {
    "resolved",
    "payment_completed",
    "payment_completed_resolved",
    "resolved_post_call",
}


async def maybe_send_recovery_email(msg: dict[str, Any]) -> str:
    """Inspect a Vapi end-of-call event; send the recovery email if warranted.

    Returns a short reason string for logging/observability. Never raises.
    """
    if not stripe.api_key:
        return "stripe-not-configured"

    call = msg.get("call") or {}
    call_sid = call.get("id") or msg.get("callId") or ""
    if not call_sid:
        return "no-call-sid"

    session = _find_session_by_call_sid(call_sid)
    if session is None:
        return "no-stripe-session"

    if getattr(session, "payment_status", None) != "paid":
        return "not-paid"

    meta = getattr(session, "metadata", None) or {}
    outcome = (getattr(meta, "outcome", None) or "") if meta else ""
    if outcome in _RESOLVED_OUTCOMES:
        return f"already-resolved:{outcome}"

    recovery_sent = (getattr(meta, "recovery_email_sent", None) or "") if meta else ""
    if recovery_sent:
        return f"already-sent:{recovery_sent}"

    caller_email = (
        getattr(session, "customer_email", None)
        or (getattr(session, "customer_details", None) and getattr(session.customer_details, "email", None))
        or ""
    )
    if not caller_email:
        return "no-caller-email"

    try:
        token_resolved = make_token(call_sid, "resolved")
        token_callback = make_token(call_sid, "callback")
        token_refund = make_token(call_sid, "refund")
    except Exception as e:  # noqa: BLE001
        log.warning("token mint failed for %s: %s", call_sid, e)
        return "token-mint-failed"

    url_resolved = f"{_API_BASE}/api/v1/recovery/resolved?token={token_resolved}"
    url_callback = f"{_API_BASE}/api/v1/recovery/callback?token={token_callback}"
    url_refund = f"{_API_BASE}/api/v1/recovery/refund?token={token_refund}"

    subject = "Klaravex — was your tech issue resolved?"
    text = (
        "Hi,\n\n"
        "Thanks for calling Klaravex. We noticed your call ended without\n"
        "a clear resolution on our side. To make this right, please tap\n"
        "one of the three options below — it takes one click:\n\n"
        f"  ✅ Issue resolved:  {url_resolved}\n\n"
        f"  📞 Still having the issue — please call me back:  {url_callback}\n\n"
        f"  💰 Request a refund (Anthony will review personally):  {url_refund}\n\n"
        "Refunds aren't issued automatically — Anthony reviews each one\n"
        "to make sure we actually missed the mark. We usually respond\n"
        "within a few hours.\n\n"
        "— The Klaravex team"
    )
    html = (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
        'max-width:560px;margin:0 auto;padding:24px;color:#111">'
        '<h2 style="margin:0 0 12px;color:#0b3d62">Was your tech issue resolved?</h2>'
        '<p>Thanks for calling Klaravex. We noticed your call ended without a '
        'clear resolution on our side. To make this right, tap one of the three '
        'options below — it takes one click.</p>'
        f'<p style="margin:28px 0"><a href="{url_resolved}" '
        'style="display:block;background:#0a7f3f;color:#fff;text-decoration:none;'
        'padding:14px 20px;border-radius:8px;text-align:center;font-weight:600">'
        '✅ Issue resolved</a></p>'
        f'<p style="margin:14px 0"><a href="{url_callback}" '
        'style="display:block;background:#0b3d62;color:#fff;text-decoration:none;'
        'padding:14px 20px;border-radius:8px;text-align:center;font-weight:600">'
        '📞 Still having the issue — please call me back</a></p>'
        f'<p style="margin:14px 0"><a href="{url_refund}" '
        'style="display:block;background:#8a4a00;color:#fff;text-decoration:none;'
        'padding:14px 20px;border-radius:8px;text-align:center;font-weight:600">'
        '💰 Request a refund</a></p>'
        '<p style="font-size:13px;color:#555;margin-top:24px">Refunds aren\'t '
        'issued automatically — Anthony reviews each one to make sure we actually '
        'missed the mark. We usually respond within a few hours.</p>'
        '<p style="font-size:13px;color:#888;margin-top:24px">— The Klaravex team</p>'
        '</div>'
    )

    await send_email(to=caller_email, subject=subject, body=text, html=html)

    try:
        stripe.checkout.Session.modify(
            session.id,
            metadata={
                **{k: getattr(meta, k) for k in (meta.keys() if hasattr(meta, "keys") else [])},
                "recovery_email_sent": str(int(time.time())),
            },
        )
    except Exception as e:  # noqa: BLE001
        log.warning("stripe metadata update failed for %s: %s", session.id, e)

    log.info(
        "recovery email sent for call_sid=%s to=%s session=%s",
        call_sid, caller_email, session.id,
    )
    return "sent"


def _find_session_by_call_sid(call_sid: str):
    """Mirror of check_payment_status._find_session_by_call_sid. Sync over SDK."""
    sessions = stripe.checkout.Session.list(limit=20)
    for s in sessions.auto_paging_iter():
        meta = getattr(s, "metadata", None)
        if not meta:
            continue
        if getattr(meta, "call_sid", None) == call_sid:
            return s
    return None
