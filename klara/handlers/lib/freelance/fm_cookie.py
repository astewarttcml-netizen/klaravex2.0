"""Freelancermap.de session-cookie auto-renewal — Azure port.

Original lived in itexperts-berlin/loki-agents/app/tasks/fm_cookie_renewer.py
and used Redis as the cookie cache. Klaravex Azure has no Redis, so the
cookie lives in klaravex_runtime_secrets (Postgres) keyed by 'fm_session_cookie'.

Freelancermap issues REMEMBERME cookies with a 7-day lifespan. We renew
every 5 days (gives a 2-day safety buffer). Cookie is stored with a 6-day
expires_at so reads transparently treat an unrenewed-for-too-long cookie
as absent.

Login flow (pure HTTP — no browser):
  POST https://www.freelancermap.de/login   (form-encoded)
    login=<email>&password=<pass>&_remember_me=on
  Server responds with Set-Cookie: PHPSESSID + REMEMBERME.

Public API:
  - login_freelancermap()      -> (ok, cookie_string, error_msg)
  - store_fm_cookie(cookie)    -> None  (writes klaravex_runtime_secrets)
  - get_fm_cookie()            -> str | None
  - renew_fm_cookie()          -> dict  (login + store, used by endpoint)
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

from ..db import get_pool

log = logging.getLogger("klaravex.freelance.fm_cookie")

FM_COOKIE_NAME = "fm_session_cookie"
FM_COOKIE_TTL_DAYS = 6

_LOGIN_URL = "https://www.freelancermap.de/login"
_FM_DOMAIN = "freelancermap.de"

_AUTH_COOKIE_NAMES = {"PHPSESSID", "REMEMBERME"}
_KEEP_COOKIE_NAMES = {"OptanonConsent", "OptanonAlertBoxClosed", "_fbp", "zft-sdc"}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def login_freelancermap() -> tuple[bool, str, str]:
    """Log in to freelancermap.de using FREELANCERMAP_EMAIL/_PASSWORD env vars.

    Returns (success, cookie_string, error_message). cookie_string is a
    semicolon-separated `name=value` header ready for the Cookie: header.
    """
    email = os.environ.get("FREELANCERMAP_EMAIL", "")
    password = os.environ.get("FREELANCERMAP_PASSWORD", "")

    if not email or not password:
        return False, "", "FREELANCERMAP_EMAIL or FREELANCERMAP_PASSWORD not set"

    form_data = {"login": email, "password": password, "_remember_me": "on"}

    timeout = aiohttp.ClientTimeout(total=30)
    jar = aiohttp.CookieJar(unsafe=True)

    try:
        async with aiohttp.ClientSession(
            cookie_jar=jar, headers=_HEADERS, timeout=timeout,
        ) as session:
            async with session.get(_LOGIN_URL, allow_redirects=True):
                pass

            post_headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": _LOGIN_URL,
                "Origin": "https://www.freelancermap.de",
            }
            async with session.post(
                _LOGIN_URL, data=form_data, headers=post_headers, allow_redirects=True,
            ) as resp:
                final_url = str(resp.url)
                status = resp.status

                if "/login" in final_url.lower() or status not in (200, 301, 302):
                    body = await resp.text(errors="replace")
                    return (
                        False, "",
                        f"Login failed — redirected to {final_url} "
                        f"(HTTP {status}). Body: {body[:200]}",
                    )

                cookie_pairs: list[str] = []
                for morsel in jar:
                    if _FM_DOMAIN in morsel.get("domain", ""):
                        name = morsel.key
                        if name in _AUTH_COOKIE_NAMES or name in _KEEP_COOKIE_NAMES:
                            cookie_pairs.append(f"{name}={morsel.coded_value}")

                if not any(k.startswith("PHPSESSID=") for k in cookie_pairs):
                    return False, "", "Login appeared to succeed but PHPSESSID not set"

                cookie_string = "; ".join(cookie_pairs)
                log.info(
                    "fm_cookie.login_ok final_url=%s pairs=%d has_remember=%s",
                    final_url, len(cookie_pairs),
                    any("REMEMBERME" in k for k in cookie_pairs),
                )
                return True, cookie_string, ""

    except Exception as exc:
        return False, "", f"Login request failed: {exc}"


async def store_fm_cookie(cookie: str) -> None:
    """Upsert cookie into klaravex_runtime_secrets with FM_COOKIE_TTL expiry."""
    pool = await get_pool()
    expires_at = datetime.now(timezone.utc) + timedelta(days=FM_COOKIE_TTL_DAYS)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO klaravex_runtime_secrets (name, value, expires_at, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (name)
                DO UPDATE SET value = EXCLUDED.value,
                              expires_at = EXCLUDED.expires_at,
                              updated_at = now()
            """,
            FM_COOKIE_NAME, cookie, expires_at,
        )
    log.info("fm_cookie.stored ttl_days=%d", FM_COOKIE_TTL_DAYS)


async def get_fm_cookie() -> Optional[str]:
    """Return the active Freelancermap session cookie string.

    Preference order:
      1. klaravex_runtime_secrets (auto-renewed every 5 days)
      2. FREELANCERMAP_SESSION_COOKIE env var (bootstrap / manual fallback)

    Cookies past their expires_at are treated as absent so a renewer failure
    can't keep the submit path using a known-stale value.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT value, expires_at
              FROM klaravex_runtime_secrets
             WHERE name = $1
            """,
            FM_COOKIE_NAME,
        )
    if row and row["value"]:
        if row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc):
            log.warning("fm_cookie.expired in_db — falling back to env")
        else:
            return row["value"]
    env_fallback = os.environ.get("FREELANCERMAP_SESSION_COOKIE", "").strip()
    return env_fallback or None


async def renew_fm_cookie() -> dict:
    """Run login + store. Used by POST /api/v1/internal/freelance/fm-cookie-renew.

    Returns a JSON-able dict for the endpoint to echo back.
    """
    ok, cookie, err = await login_freelancermap()
    if not ok:
        log.warning("fm_cookie.renew_failed err=%s", err)
        return {"ok": False, "error": err}
    await store_fm_cookie(cookie)
    return {
        "ok": True,
        "ttl_days": FM_COOKIE_TTL_DAYS,
        "cookie_pairs": cookie.count(";") + 1 if cookie else 0,
    }
