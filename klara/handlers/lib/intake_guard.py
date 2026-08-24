"""
Intake hardening helpers — V4 (pentest 2026-06-12).

Defensive layer applied by every public /api/v1/intake/* route:

  - Optional Cloudflare Turnstile verification (gracefully no-op when
    TURNSTILE_SECRET_KEY is unset; consumer dev/staging still works).
  - 24-hour duplicate-summary dedupe (per email + summary hash) — same form
    submitted twice with identical body returns the original ticket id
    instead of double-paging Anthony.

Per-IP rate limit is enforced at the route level via the existing
@limiter.limit(...) decorators (intake forms already share the 20/min ceiling
from klara.handlers/lib/rate_limit.py). V4 narrows that for /intake/* to
3/hour by re-decorating the routes that need it most.
"""

import hashlib
import logging
import os
from typing import Optional

import httpx
from fastapi import HTTPException, Request

log = logging.getLogger("klaravex.intake_guard")

# Cloudflare Turnstile verification endpoint.
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_turnstile(request: Request, token: Optional[str]) -> None:
    """Verify a Cloudflare Turnstile token. No-op when not configured.

    Behaviour:
      - TURNSTILE_SECRET_KEY unset → silently allow (graceful no-op so the
        consumer intake form keeps working before Anthony adds the key).
      - TURNSTILE_SECRET_KEY set + token missing → 403 (form widget didn't
        run; almost certainly a bot).
      - TURNSTILE_SECRET_KEY set + token present but rejected by Cloudflare
        → 403.
    """
    secret = os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
    if not secret:
        return  # not configured — fail-open intentionally; surface to ops separately
    if not token:
        raise HTTPException(status_code=403, detail="captcha token missing")
    ip = (
        (request.headers.get("x-forwarded-for", "") or "").split(",")[0].strip()
        or (request.client.host if request.client else "")
    )
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                TURNSTILE_VERIFY_URL,
                data={"secret": secret, "response": token, "remoteip": ip},
            )
            data = resp.json()
    except Exception as exc:
        log.warning("turnstile verify HTTP error: %s — failing closed", exc)
        raise HTTPException(status_code=503, detail="captcha verify unavailable") from exc
    if not data.get("success"):
        log.info("turnstile verify rejected: %s", data.get("error-codes"))
        raise HTTPException(status_code=403, detail="captcha verify failed")


def summary_fingerprint(email: str, summary: str) -> str:
    """24h dedupe key: SHA256 of normalized email + raw summary."""
    norm = (email or "").strip().lower() + "|" + (summary or "").strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


async def find_recent_duplicate(email: str, summary: str) -> Optional[str]:
    """Return the existing ticket id (text) for the same email+summary in
    the last 24h, or None.

    Lookup uses klaravex_tickets.metadata->>'intake_fingerprint' set by
    record_fingerprint() below. Safe to call when the table/column doesn't
    yet exist — returns None on any DB error so intake never breaks.
    """
    if not email or not summary:
        return None
    fp = summary_fingerprint(email, summary)
    try:
        from .db import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id::text AS id
                  FROM klaravex_tickets
                 WHERE metadata->>'intake_fingerprint' = $1
                   AND created_at >= now() - INTERVAL '24 hours'
                 ORDER BY created_at DESC
                 LIMIT 1
                """,
                fp,
            )
        return row["id"] if row else None
    except Exception as exc:
        log.warning("find_recent_duplicate failed (allowing intake): %s", exc)
        return None


def fingerprint_for_metadata(email: str, summary: str) -> dict[str, str]:
    """Snippet to merge into a ticket's metadata dict so the next dedupe
    lookup will find it. Caller is responsible for actually passing
    metadata to tickets_lib.create_ticket()."""
    return {"intake_fingerprint": summary_fingerprint(email, summary)}
