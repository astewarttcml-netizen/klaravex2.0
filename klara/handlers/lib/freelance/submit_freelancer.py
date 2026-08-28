"""Freelancer.com bid submission — Azure port.

Original: itexperts-berlin/loki-agents/app/agents/platform_bid_submitter.py
         (_submit_freelancer function).

Flow:
  1. Resolve the numeric project ID from the platform ID.
  2. POST /api/projects/apply as multipart/form-data with the session cookie.
  3. Map response → (success, platform_bid_id, error_message).

Freelancer.com has specific requirements for bid submission:
- Uses access token instead of session cookie
- Different API endpoints and structure
- Specific headers required
- Application limit enforced server-side

Monthly application limit is enforced by Freelancer server-side (HTTP 403
with descriptive message). We pass it through unchanged so the daily cap
on our side acts as a soft brake; their cap is the hard ceiling.
"""

import json
import logging
import os
import re
from typing import Optional

import aiohttp

from .freelancer_cookie import get_freelancer_cookie

log = logging.getLogger("klaravex.freelance.submit_freelancer")

_FREELANCER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
}
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)


async def _resolve_numeric_id(
    session: aiohttp.ClientSession,
    platform_id: str,
) -> Optional[str]:
    """Resolve the numeric Freelancer.com project ID required for bid submission.

    Strategy A: platform_id is already purely numeric -> use directly.
    Strategy B: slug contains numeric ID in a specific pattern.
    """
    if re.fullmatch(r"\d+", platform_id):
        return platform_id

    # Extract numeric ID from patterns like "project-123456789"
    m = re.search(r"-(\d{5,10})$", platform_id)
    if m:
        return m.group(1)

    # For Freelancer.com, the platform_id is often already a numeric project ID
    # but we'll try to be safe and extract it properly
    return platform_id


async def submit_freelancer_bid(
    platform_id: str,
    cover_letter: str,
) -> tuple[bool, Optional[str], Optional[str]]:
    """Submit a single bid to Freelancer.com.

    Returns (success, freelancer_numeric_id, error_message). When Freelancer
    accepts the application it returns 200/201 with no application ID body
    that's reliably parseable, so we use the project's numeric ID as the
    platform_bid_id (good enough to dedupe + audit).
    """
    access_token = await get_freelancer_cookie()

    if not access_token:
        return False, None, (
            "Freelancer.com credentials not configured — need FREELANCER_ACCESS_TOKEN "
            "(or auto-renew token in klaravex_runtime_secrets)"
        )

    async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
        numeric_id = await _resolve_numeric_id(session, platform_id)
        if not numeric_id:
            return False, None, (
                f"Could not resolve numeric Freelancer.com project ID "
                f"for platform_id={platform_id!r}"
            )

        # Prepare the bid data for Freelancer.com API
        bid_data = {
            "project_id": int(numeric_id),
            "cover_letter": cover_letter or "",
            "bid_amount": 0,  # We'll use 0 as default or fetch from bid strategy
            "duration": 7,   # Default duration in days
        }

        headers = {
            **_FREELANCER_HEADERS,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Origin": "https://www.freelancer.com",
            "Referer": f"https://www.freelancer.com/projects/{numeric_id}",
        }

        try:
            # Submit the bid to Freelancer.com
            async with session.post(
                f"https://www.freelancer.com/api/projects/{numeric_id}/bids",
                json=bid_data,
                headers=headers,
            ) as resp:
                body = await resp.text()
                if resp.status in (200, 201):
                    log.info("freelancer.submit_ok numeric_id=%s", numeric_id)
                    return True, numeric_id, None
                elif resp.status == 401:
                    log.warning("freelancer.submit_session_expired numeric_id=%s", numeric_id)
                    return False, None, "Freelancer.com session expired — renew token"
                elif resp.status == 403:
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