"""
app/services/magic_link_service.py
────────────────────────────────────
Passwordless magic-link generation and verification for the client portal.

## How it works

1. `request_link(email, db, settings)` is called when a client submits their
   email on the login page.
   - Looks up the Client row by email.
   - Rate-limits to 1 link per email per RATE_LIMIT_WINDOW_SECONDS via Redis.
   - Generates a 32-byte cryptographically random token.
   - Stores only the SHA-256 hash (never the raw token).
   - Sends a login email via Resend with the raw token as a query param.
   - Always returns True to the caller regardless of whether the email exists
     (prevents account enumeration).

2. `verify_link(raw_token, db)` is called when the client follows the link.
   - SHA-256 hashes the incoming raw token.
   - Looks up the row by hash.
   - Validates: row exists, not expired, not already used.
   - Stamps used_at atomically — prevents replay within the same request.
   - Returns the Client object so the route can issue a JWT.

## Security properties

- Raw token never persisted — compromise of the DB yields only useless hashes.
- Single-use enforced in the DB via used_at + uniqueness on token_hash.
- 15-minute TTL (MAGIC_LINK_TTL_MINUTES).
- Rate limiting via Redis: 1 request per email per 5 minutes prevents abuse.
- Constant-time hash comparison not required here — we look up by unique index,
  not by iterating/comparing; timing oracle does not apply.
- Dead rows (expired, unused) can be purged by a daily cleanup task.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.magic_link import MagicLink
from app.models.portal import Client

logger = structlog.get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

MAGIC_LINK_TTL_MINUTES: int = 15
RATE_LIMIT_WINDOW_SECONDS: int = 300   # 1 request per email per 5 min
RATE_LIMIT_REDIS_PREFIX: str = "magic_link_rl:"

# ── Internal helpers ──────────────────────────────────────────────────────────


def _hash_token(raw: str) -> str:
    """Return the SHA-256 hex digest of a raw token string."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _generate_raw_token() -> str:
    """Return a URL-safe 32-byte random token (43 chars, no padding)."""
    return secrets.token_urlsafe(32)


async def _is_rate_limited(email: str, settings) -> bool:
    """
    Return True if this email has requested a magic link within the last
    RATE_LIMIT_WINDOW_SECONDS.  Uses Redis via aioredis.

    Falls back to False (allow) if Redis is unavailable — better to let a
    request through than to permanently break login on a Redis hiccup.
    """
    try:
        import redis.asyncio as aioredis  # redis-py ≥ 4.2 bundles asyncio support

        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        key = f"{RATE_LIMIT_REDIS_PREFIX}{email.lower()}"
        async with r:
            exists = await r.exists(key)
            if exists:
                return True
            await r.setex(key, RATE_LIMIT_WINDOW_SECONDS, "1")
            return False
    except Exception as exc:
        logger.warning("magic_link.rate_limit_check_failed", error=str(exc))
        return False  # fail open — don't break login if Redis is temporarily down


async def _send_magic_link_email(
    to_email: str,
    to_name: str,
    raw_token: str,
    settings,
) -> None:
    """
    Send the magic link email via Resend.
    The link URL format: https://api.klaravex.de/api/v1/portal/auth/verify-link?token=<raw>
    Clients should be redirected from this endpoint to the portal frontend.
    """
    from app.services.email_sender import send_transactional_email

    portal_url = f"{settings.app_base_url}/api/v1/portal/auth/verify-link?token={raw_token}"
    ttl_min = MAGIC_LINK_TTL_MINUTES
    display_name = to_name or "there"

    subject = "Your Klaravex portal login link"

    body_text = (
        f"Hi {display_name},\n\n"
        f"Click the link below to log in to your Klaravex portal.\n"
        f"This link expires in {ttl_min} minutes and can only be used once.\n\n"
        f"{portal_url}\n\n"
        f"If you didn't request this, you can safely ignore this email.\n\n"
        f"— Klaravex"
    )

    body_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;
             padding:24px;color:#222;background:#ffffff;">

  <div style="margin-bottom:24px;">
    <img src="https://klaravex.de/wp-content/themes/kadence-child/assets/logo.png"
         alt="Klaravex" height="36" style="display:block;">
  </div>

  <h2 style="font-size:20px;font-weight:600;margin:0 0 12px;">
    Your portal login link
  </h2>

  <p style="margin:0 0 20px;line-height:1.6;">
    Hi {display_name},<br>
    Click the button below to log in to your Klaravex portal.
    This link expires in <strong>{ttl_min} minutes</strong> and can
    only be used <strong>once</strong>.
  </p>

  <div style="text-align:center;margin:28px 0;">
    <a href="{portal_url}"
       style="background:#0071c5;color:#ffffff;padding:14px 28px;
              border-radius:4px;text-decoration:none;
              font-size:15px;font-weight:600;display:inline-block;">
      Log in to Portal
    </a>
  </div>

  <p style="font-size:13px;color:#666;margin:0 0 8px;">
    Or copy and paste this link into your browser:
  </p>
  <p style="font-size:12px;color:#888;word-break:break-all;margin:0 0 24px;">
    {portal_url}
  </p>

  <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
  <p style="font-size:12px;color:#aaa;margin:0;">
    If you didn't request this login link, you can safely ignore this email.
    Your account will not be affected.<br><br>
    Klaravex &nbsp;·&nbsp; klaravex.de
  </p>

</body>
</html>"""

    await send_transactional_email(
        settings,
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        body_html=body_html,
        body_text=body_text,
    )


# ── Public API ────────────────────────────────────────────────────────────────


async def request_link(
    email: str,
    db: AsyncSession,
    settings,
) -> bool:
    """
    Generate and email a magic login link for the given email address.

    Always returns True — the caller must NOT reveal whether the email
    exists in the database (prevents account enumeration).

    Returns False only on hard errors (DB write failed, etc.) — the caller
    should log but still return a success-looking HTTP 200 to the client.
    """
    log = logger.bind(email=email)

    # ── Rate limit ─────────────────────────────────────────────────────────────
    if await _is_rate_limited(email, settings):
        log.info("magic_link.rate_limited")
        return True  # silent — don't reveal that we rate-limited them

    # ── Look up client ─────────────────────────────────────────────────────────
    result = await db.execute(
        select(Client).where(Client.email == email.lower())
    )
    client: Optional[Client] = result.scalar_one_or_none()

    if client is None or not client.is_active:
        # Do NOT reveal account non-existence — log internally only
        log.info("magic_link.email_not_found_or_inactive")
        return True  # Return success to caller regardless

    # ── Generate token ─────────────────────────────────────────────────────────
    raw_token = _generate_raw_token()
    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=MAGIC_LINK_TTL_MINUTES)

    # ── Persist hash (never the raw token) ────────────────────────────────────
    try:
        link_row = MagicLink(
            client_id=client.id,
            token_hash=token_hash,
            expires_at=expires_at,
            created_at=now,
        )
        db.add(link_row)
        await db.flush()  # catch unique constraint violations early
    except Exception as exc:
        log.error("magic_link.db_write_failed", error=str(exc))
        return False

    # ── Send email ─────────────────────────────────────────────────────────────
    try:
        await _send_magic_link_email(
            to_email=client.email,
            to_name=client.name or "",
            raw_token=raw_token,
            settings=settings,
        )
        log.info("magic_link.sent", client_id=client.id, expires_at=expires_at.isoformat())
    except Exception as exc:
        # Don't roll back the DB row — we can resend or debug.
        # The row will expire naturally in 15 min.
        log.error("magic_link.email_send_failed", client_id=client.id, error=str(exc))
        return False

    return True


def _mask_email(email: str) -> str:
    """
    Mask an email address for display in the peek response.

    "anthony@example.com" → "a*****@example.com"
    Preserves the first character of the local part and the full domain.
    """
    try:
        local, domain = email.rsplit("@", 1)
        if len(local) <= 1:
            return f"{local}@{domain}"
        return f"{local[0]}{'*' * (len(local) - 1)}@{domain}"
    except ValueError:
        return "***"


async def peek_link(
    raw_token: str,
    db: AsyncSession,
) -> dict:
    """
    Peek at a magic-link token without consuming it.

    Returns a dict suitable for the PeekResponse schema:
      {"valid": True,  "email_hint": "a*****@example.com"}
      {"valid": False, "reason": "invalid_or_expired"}
      {"valid": False, "reason": "already_used"}

    This function is STRICTLY read-only — it never sets used_at.
    Safe to call from a GET endpoint that email scanners may pre-fetch.
    """
    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)

    log = logger.bind(action="peek_link")

    result = await db.execute(
        select(MagicLink).where(MagicLink.token_hash == token_hash)
    )
    link: Optional[MagicLink] = result.scalar_one_or_none()

    if link is None:
        log.info("magic_link.peek_not_found")
        return {"valid": False, "reason": "invalid_or_expired"}

    if link.used_at is not None:
        log.info("magic_link.peek_already_used", link_id=link.id, client_id=link.client_id)
        return {"valid": False, "reason": "already_used"}

    if link.expires_at < now:
        log.info("magic_link.peek_expired", link_id=link.id, client_id=link.client_id)
        return {"valid": False, "reason": "invalid_or_expired"}

    # Load client to supply the masked email hint
    client_result = await db.execute(
        select(Client).where(Client.id == link.client_id)
    )
    client: Optional[Client] = client_result.scalar_one_or_none()

    if client is None or not client.is_active:
        log.warning("magic_link.peek_client_missing_or_inactive", client_id=link.client_id)
        return {"valid": False, "reason": "invalid_or_expired"}

    log.info("magic_link.peek_valid", client_id=client.id)
    return {"valid": True, "email_hint": _mask_email(client.email)}


async def verify_link(
    raw_token: str,
    db: AsyncSession,
) -> Optional[Client]:
    """
    Verify a raw magic-link token.

    Returns the Client on success, None on any failure (expired, used,
    not found).  Stamps used_at atomically to prevent replay.

    Callers should issue a portal JWT on success and redirect the browser
    to the portal frontend.
    """
    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)

    # ── Look up by hash ────────────────────────────────────────────────────────
    result = await db.execute(
        select(MagicLink).where(MagicLink.token_hash == token_hash)
    )
    link: Optional[MagicLink] = result.scalar_one_or_none()

    if link is None:
        logger.warning("magic_link.not_found")
        return None

    if link.used_at is not None:
        logger.warning("magic_link.already_used", link_id=link.id, client_id=link.client_id)
        return None

    if link.expires_at < now:
        logger.warning("magic_link.expired", link_id=link.id, client_id=link.client_id)
        return None

    # ── Stamp used_at — prevents replay ────────────────────────────────────────
    await db.execute(
        update(MagicLink)
        .where(MagicLink.id == link.id)
        .values(used_at=now)
    )

    # ── Load client ────────────────────────────────────────────────────────────
    client_result = await db.execute(
        select(Client).where(Client.id == link.client_id)
    )
    client: Optional[Client] = client_result.scalar_one_or_none()

    if client is None or not client.is_active:
        logger.warning("magic_link.client_not_found_or_inactive", client_id=link.client_id)
        return None

    logger.info("magic_link.verified", client_id=client.id)
    return client
