"""
app/tasks/fm_cookie_renewer.py
───────────────────────────────
Freelancermap.de session-cookie auto-renewal.

Freelancermap issues REMEMBERME cookies with a 7-day lifespan.  When the
cookie expires every bid POST to /api/projects/apply silently fails with
aiohttp status=0 (the server drops the connection).

This module handles renewal without a browser by exploiting the fact that
the login form is a plain GET request:

  GET /mein_account.html?login=<email>&password=<pass>&_remember_me=on

The server responds with Set-Cookie: PHPSESSID + REMEMBERME.  We serialise
all freelancermap.de cookies into a single header string and store it in
Redis under FM_COOKIE_KEY with a 6-day TTL (renewed every 5 days by the
beat schedule, giving a 2-day safety buffer before the 7-day expiry).

Public API
──────────
  login_freelancermap(settings)   → (ok: bool, cookie: str, error: str)
  store_fm_cookie_in_redis(cookie, redis_url) → None
  get_fm_cookie_from_redis(redis_url) → str | None
"""
from __future__ import annotations

import asyncio
from http.cookies import SimpleCookie
from typing import Optional
import aiohttp
import structlog

logger = structlog.get_logger(__name__)

FM_COOKIE_KEY = "fm:session_cookie"
FM_COOKIE_TTL = 6 * 24 * 3600  # 6 days — renewed every 5 days by beat

_LOGIN_URL = "https://www.freelancermap.de/login"
_FM_DOMAIN = "freelancermap.de"

# Cookies we actually need for auth; everything else is analytics noise
_AUTH_COOKIE_NAMES = {"PHPSESSID", "REMEMBERME"}
# Additional cookies the server sets that help requests look legitimate
_KEEP_COOKIE_NAMES = {"OptanonConsent", "OptanonAlertBoxClosed", "_fbp", "zft-sdc"}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def login_freelancermap(settings) -> tuple[bool, str, str]:
    """
    Log in to freelancermap.de using stored credentials.

    Returns (success, cookie_string, error_message).
    cookie_string is a semicolon-separated header value ready for use in
    the Cookie: header; empty string on failure.
    """
    email = getattr(settings, "freelancermap_email", None)
    password = getattr(settings, "freelancermap_password", None)

    if not email or not password:
        return False, "", "FREELANCERMAP_EMAIL or FREELANCERMAP_PASSWORD not set"

    form_data = {"login": email, "password": password, "_remember_me": "on"}

    timeout = aiohttp.ClientTimeout(total=30)
    jar = aiohttp.CookieJar(unsafe=True)

    try:
        async with aiohttp.ClientSession(
            cookie_jar=jar,
            headers=_HEADERS,
            timeout=timeout,
        ) as session:
            # Fetch the login page first so any session-init cookies are set
            async with session.get(_LOGIN_URL, allow_redirects=True):
                pass

            post_headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": _LOGIN_URL,
                "Origin": "https://www.freelancermap.de",
            }
            async with session.post(
                _LOGIN_URL,
                data=form_data,
                headers=post_headers,
                allow_redirects=True,
            ) as resp:
                final_url = str(resp.url)
                status = resp.status

                # Successful login lands on /mein_account.html or a profile sub-page.
                # Failed login redirects back to /login.
                if "/login" in final_url.lower() or status not in (200, 301, 302):
                    body = await resp.text(errors="replace")
                    return (
                        False,
                        "",
                        f"Login failed — redirected to {final_url} (HTTP {status}). "
                        f"Body snippet: {body[:200]}",
                    )

                # Build cookie string from all cookies the jar captured for
                # the freelancermap.de domain.
                cookie_pairs: list[str] = []
                for morsel in jar:
                    if _FM_DOMAIN in morsel.get("domain", ""):
                        name = morsel.key
                        if name in _AUTH_COOKIE_NAMES or name in _KEEP_COOKIE_NAMES:
                            cookie_pairs.append(f"{name}={morsel.coded_value}")

                if not any(k.split("=")[0] == "PHPSESSID" for k in cookie_pairs):
                    return False, "", "Login appeared to succeed but PHPSESSID not set in response"

                cookie_string = "; ".join(cookie_pairs)
                logger.info(
                    "fm_cookie_renewer.login_ok",
                    final_url=final_url,
                    cookie_count=len(cookie_pairs),
                    has_remember_me=any("REMEMBERME" in k for k in cookie_pairs),
                )
                return True, cookie_string, ""

    except Exception as exc:
        return False, "", f"Login request failed: {exc}"


async def store_fm_cookie_in_redis(cookie: str, redis_url: str) -> None:
    """Store cookie string in Redis (FM_COOKIE_TTL) AND mirror it into the shared DB.

    The Azure klaravex-api freelancermap submitter reads the cookie from
    klaravex_runtime_secrets (it cannot reach rig Redis). Without mirroring, that
    DB copy rots and the Azure path fails "credentials not configured". The DB
    write is best-effort and never blocks Redis storage.
    """
    import redis.asyncio as aioredis

    r = aioredis.from_url(redis_url, decode_responses=True)
    try:
        await r.set(FM_COOKIE_KEY, cookie, ex=FM_COOKIE_TTL)
        logger.info("fm_cookie_renewer.stored_in_redis", ttl_days=FM_COOKIE_TTL // 86400)
    finally:
        await r.aclose()

    # Mirror into klaravex_runtime_secrets (shared Azure DB) for the klaravex-api path.
    try:
        from datetime import datetime, timedelta, timezone
        from app.database import db_context
        from sqlalchemy import text

        expires = datetime.now(timezone.utc) + timedelta(seconds=FM_COOKIE_TTL)
        async with db_context() as _db:
            await _db.execute(
                text(
                    "INSERT INTO klaravex_runtime_secrets (name, value, expires_at, updated_at) "
                    "VALUES ('fm_session_cookie', :v, :exp, now()) "
                    "ON CONFLICT (name) DO UPDATE SET "
                    "value = EXCLUDED.value, expires_at = EXCLUDED.expires_at, updated_at = now()"
                ),
                {"v": cookie, "exp": expires},
            )
            await _db.commit()
        logger.info("fm_cookie_renewer.stored_in_db", ttl_days=FM_COOKIE_TTL // 86400)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fm_cookie_renewer.db_store_failed", error=str(exc))


async def get_fm_cookie_from_redis(redis_url: str) -> Optional[str]:
    """Return the cached cookie string from Redis, or None if not present."""
    import redis.asyncio as aioredis

    try:
        r = aioredis.from_url(redis_url, decode_responses=True)
        try:
            value = await r.get(FM_COOKIE_KEY)
            if value:
                ttl = await r.ttl(FM_COOKIE_KEY)
                logger.debug(
                    "fm_cookie_renewer.cache_hit",
                    ttl_hours=round(ttl / 3600, 1) if ttl > 0 else "no-expiry",
                )
            return value
        finally:
            await r.aclose()
    except Exception as exc:
        logger.warning("fm_cookie_renewer.redis_miss", error=str(exc))
        return None
