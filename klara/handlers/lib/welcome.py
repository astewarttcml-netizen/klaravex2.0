"""
Klaravex post-signup welcome flow.

Sends a single welcome email per client (tracked via klaravex_clients.welcome_sent_at)
containing a one-click portal magic link. Called by Stripe webhook handlers after
a `customer.subscription.created` event, and by manual intake forms.

Idempotent: re-running for the same email is a no-op.
"""

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import get_pool
from .email import send_email

log = logging.getLogger("klaravex.welcome")

PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")
WELCOME_TOKEN_TTL_DAYS = int(os.environ.get("WELCOME_TOKEN_TTL_DAYS", "7"))


# SKU prefix → human-friendly plan name (best-effort; falls back to raw SKU)
_PLAN_LABELS = {
    "foundation":      "Foundation",
    "assurance":       "Assurance",
    "directive":       "Directive",
    "essentials":      "Klaravex Essentials",
    "home-":           "Home Membership",
    "family-":         "Family Senior",
    "per-incident":    "Per-Incident Support",
    "resume-":         "Resume Service",
    "tech-":           "Tech Concierge",
    "ai-":             "AI Concierge",
    "identity-":       "Identity Protection",
    "solo-":           "Solo Plan",
}


def _plan_label(sku: Optional[str]) -> str:
    if not sku:
        return "your plan"
    s = sku.lower()
    for prefix, label in _PLAN_LABELS.items():
        if s.startswith(prefix):
            return label
    return sku


async def _issue_welcome_token(email: str) -> str:
    """Issue a single-use login token valid for WELCOME_TOKEN_TTL_DAYS."""
    plaintext = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(plaintext.encode("utf-8")).digest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=WELCOME_TOKEN_TTL_DAYS)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO klaravex_portal_tokens
                (token_hash, email, purpose, expires_at)
            VALUES ($1, $2, 'login', $3)
            """,
            token_hash, email.lower(), expires_at,
        )
    return plaintext


async def _mark_welcome_sent(email: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex_clients SET welcome_sent_at = now() WHERE email = $1",
            email.lower(),
        )


async def _welcome_already_sent(email: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT welcome_sent_at FROM klaravex_clients WHERE email = $1",
            email.lower(),
        )
    return bool(row and row["welcome_sent_at"])


async def send_post_signup_welcome(
    *,
    email: str,
    name: Optional[str] = None,
    sku: Optional[str] = None,
    segment: str = "consumer",
    force: bool = False,
) -> dict[str, object]:
    """Send a welcome email with portal magic link. Idempotent unless force=True.

    Returns: {"sent": bool, "reason": str, "portal_url": Optional[str]}
    """
    email_norm = email.lower().strip()
    if not email_norm or "@" not in email_norm:
        return {"sent": False, "reason": "invalid_email"}

    if not force and await _welcome_already_sent(email_norm):
        return {"sent": False, "reason": "already_sent"}

    try:
        token = await _issue_welcome_token(email_norm)
    except Exception as exc:
        log.exception("welcome token issuance failed for %s: %s", email_norm, exc)
        return {"sent": False, "reason": f"token_error: {exc}"}

    portal_url = f"{PORTAL_BASE_URL}/portal/login/verify?token={token}"
    plan = _plan_label(sku)
    greeting = f"Hi {name}," if name and name != "Anthony Stewart (Test)" else "Hi there,"

    if segment == "b2b":
        body = (
            f"{greeting}\n\n"
            f"Welcome to Klaravex — your {plan} subscription is active.\n\n"
            f"One-click access to your client portal:\n\n"
            f"  {portal_url}\n\n"
            f"In your portal you can:\n"
            f"  • Review your active services and SLAs\n"
            f"  • Open and track support tickets\n"
            f"  • Access compliance documents (HIPAA/SOC 2 readiness reports)\n"
            f"  • View AI-handled vs human-escalated incidents\n\n"
            f"Your link works for {WELCOME_TOKEN_TTL_DAYS} days. After that, request a new one\n"
            f"at {PORTAL_BASE_URL}/portal/login by entering this email address.\n\n"
            f"Questions? Reply to this email or reach support@klaravex.com.\n\n"
            f"— The Klaravex Team\n"
        )
    else:
        body = (
            f"{greeting}\n\n"
            f"Welcome to Klaravex — your {plan} membership is active.\n\n"
            f"One-click access to your portal:\n\n"
            f"  {portal_url}\n\n"
            f"In your portal you can:\n"
            f"  • Open a support request (AI answers in seconds, 24/7)\n"
            f"  • Track open and resolved issues\n"
            f"  • Manage your subscription\n\n"
            f"Your link works for {WELCOME_TOKEN_TTL_DAYS} days. After that, request a new one\n"
            f"at {PORTAL_BASE_URL}/portal/login by entering this email address.\n\n"
            f"Need help right now? Reply to this email or reach support@klaravex.com.\n\n"
            f"— The Klaravex Team\n"
        )

    subject = f"Welcome to Klaravex — your {plan} access is ready"

    try:
        await send_email(to=email_norm, subject=subject, body=body)
    except Exception as exc:
        log.exception("welcome email send failed for %s: %s", email_norm, exc)
        return {"sent": False, "reason": f"email_error: {exc}", "portal_url": portal_url}

    try:
        await _mark_welcome_sent(email_norm)
    except Exception as exc:
        log.warning("welcome flag update failed for %s (email already sent): %s", email_norm, exc)

    log.info("welcome email sent to %s (plan=%s segment=%s)", email_norm, plan, segment)
    return {"sent": True, "reason": "delivered", "portal_url": portal_url}
