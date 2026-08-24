"""Freelancermap.de bid submission — Azure port.

Original: itexperts-berlin/loki-agents/app/agents/platform_bid_submitter.py
         (_submit_freelancermap function).

Flow:
  1. Resolve the numeric project ID (search results give us a slug-derived id
     that's sometimes already numeric, sometimes needs a fetch of the project
     page to extract it from the React JSON blob).
  2. POST /api/projects/apply as multipart/form-data with the session cookie.
  3. Map response → (success, platform_bid_id, error_message).

Monthly application limit is enforced by Freelancermap server-side (HTTP 403
with descriptive message). We pass it through unchanged so the daily cap
on our side acts as a soft brake; their cap is the hard ceiling.
"""

import json
import logging
import os
import re
from typing import Optional

import aiohttp

from .fm_cookie import get_fm_cookie

log = logging.getLogger("klaravex.freelance.submit_fm")

_FM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)


async def _resolve_numeric_id(
    session: aiohttp.ClientSession,
    platform_id: str,
    project_url: Optional[str],
) -> Optional[str]:
    """Resolve the numeric Freelancermap project ID required for /api/projects/apply.

    Strategy A: platform_id is already purely numeric -> use directly.
    Strategy B: slug ends in -{numericId}, e.g. 'some-title-3002479'.
    Strategy C: fetch project page; parse "id":N,"title": from the React blob.
    Strategy D: parse /projekt/{slug}-{numericId}/ pattern from HTML (fallback).
    """
    if re.fullmatch(r"\d+", platform_id):
        return platform_id
    m = re.search(r"-(\d{5,8})$", platform_id)
    if m:
        return m.group(1)

    url = project_url or f"https://www.freelancermap.de/projekt/{platform_id}"
    try:
        async with session.get(url, headers=_FM_HEADERS) as resp:
            if resp.status != 200:
                log.warning("fm.id_resolve_fetch_failed pid=%s status=%d", platform_id, resp.status)
                return None
            html = await resp.text(encoding="utf-8", errors="replace")
        m = re.search(r'"id"\s*:\s*(\d{4,8})\s*,\s*"title"\s*:', html)
        if m:
            return m.group(1)
        m = re.search(r"/projekt/[^/?#\s\"']+-(\d{5,8})(?=[/\"'\s])", html)
        if m:
            return m.group(1)
    except Exception as exc:
        log.warning("fm.id_resolve_error pid=%s err=%s", platform_id, exc)
    return None


async def submit_freelancermap_bid(
    platform_id: str,
    project_url: Optional[str],
    cover_letter: str,
) -> tuple[bool, Optional[str], Optional[str]]:
    """Submit a single bid to Freelancermap.de.

    Returns (success, freelancermap_numeric_id, error_message). When FM
    accepts the application it returns 200/201 with no application ID body
    that's reliably parseable, so we use the project's numeric ID as the
    platform_bid_id (good enough to dedupe + audit).
    """
    session_cookie = await get_fm_cookie()
    user_id = os.environ.get("FREELANCERMAP_USER_ID", "")
    profile_id = os.environ.get("FREELANCERMAP_PROFILE_ID", "")

    if not session_cookie or not user_id or not profile_id:
        return False, None, (
            "Freelancermap credentials not configured — need FREELANCERMAP_SESSION_COOKIE "
            "(or auto-renew cookie in klaravex_runtime_secrets), FREELANCERMAP_USER_ID, "
            "FREELANCERMAP_PROFILE_ID"
        )

    async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
        numeric_id = await _resolve_numeric_id(session, platform_id, project_url)
        if not numeric_id:
            return False, None, (
                f"Could not resolve numeric Freelancermap project ID "
                f"for platform_id={platform_id!r}"
            )

        form = aiohttp.FormData()
        form.add_field("user", f"/api/users/{user_id}")
        form.add_field("project", f"/api/projects/{numeric_id}")
        form.add_field("body", cover_letter or "")
        form.add_field("sendEmail", "true")
        form.add_field("sendPhone", "false")
        form.add_field("profile", str(profile_id))
        form.add_field("profileAttachmentIds[]", "")
        form.add_field("dataPrivacyAccepted", "true")

        headers = {
            **_FM_HEADERS,
            "Cookie": session_cookie,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.freelancermap.de",
            "Referer": project_url or "https://www.freelancermap.de/",
        }

        try:
            async with session.post(
                "https://www.freelancermap.de/api/projects/apply",
                data=form, headers=headers,
            ) as resp:
                body = await resp.text()
                if resp.status in (200, 201):
                    log.info("fm.submit_ok numeric_id=%s", numeric_id)
                    return True, numeric_id, None
                if resp.status == 401:
                    log.warning("fm.submit_session_expired numeric_id=%s", numeric_id)
                    return False, None, "Freelancermap session expired — renew cookie"
                if resp.status == 403:
                    try:
                        data = json.loads(body)
                        msg = (data.get("message") or data.get("detail")
                               or "HTTP 403 — possibly monthly application limit")
                    except Exception:
                        msg = f"HTTP 403: {body[:200]}"
                    return False, None, msg
                try:
                    data = json.loads(body)
                    msg = (data.get("message") or data.get("detail")
                           or f"HTTP {resp.status}: {body[:300]}")
                except Exception:
                    msg = f"HTTP {resp.status}: {body[:300]}"
                return False, None, msg
        except Exception as exc:
            return False, None, f"submit exception: {exc}"
