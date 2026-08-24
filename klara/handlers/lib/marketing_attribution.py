"""
Attribution helpers for the marketing AI team competition.

Two paths into Klaravex carry team attribution:

  1. Web traffic with ?t=alpha or ?t=beta → captured by middleware,
     stored in a cookie, and stamped on any signup/intake event during that session.

  2. Stripe Checkout sessions created with metadata.marketing_team=alpha|beta
     → captured in stripe_webhook → written to klaravex_clients.attribution_team.

Both routes converge on the same column so the leaderboard query is dead simple.
"""

import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .db import get_pool

log = logging.getLogger("klaravex.marketing_attribution")

ATTRIBUTION_COOKIE = "klaravex_team"
COOKIE_MAX_AGE_DAYS = 90
VALID_TEAMS = {"alpha", "beta"}


class MarketingAttributionMiddleware(BaseHTTPMiddleware):
    """If the request URL contains ?t=alpha|beta, drop a 90-day cookie.

    Cookie is consumed by intake / portal handlers to stamp attribution_team
    on klaravex_clients rows for the user's first conversion event.
    """

    async def dispatch(self, request: Request, call_next):
        team = request.query_params.get("t", "").lower()
        response: Response = await call_next(request)
        if team in VALID_TEAMS and request.cookies.get(ATTRIBUTION_COOKIE) != team:
            response.set_cookie(
                ATTRIBUTION_COOKIE,
                team,
                max_age=COOKIE_MAX_AGE_DAYS * 86400,
                path="/",
                httponly=False,  # readable from JS for client-side analytics
                secure=True,
                samesite="lax",
            )
        return response


def attribution_from_request(request: Request) -> Optional[str]:
    """Return the team code attached to this request, if any.

    Precedence: explicit ?t= query > cookie > X-Klaravex-Team header (for testing).
    """
    t = request.query_params.get("t", "").lower()
    if t in VALID_TEAMS:
        return t
    cookie = request.cookies.get(ATTRIBUTION_COOKIE, "").lower()
    if cookie in VALID_TEAMS:
        return cookie
    hdr = request.headers.get("x-klaravex-team", "").lower()
    if hdr in VALID_TEAMS:
        return hdr
    return None


async def stamp_attribution_on_client(email: str, team: Optional[str]) -> bool:
    """Upsert attribution_team on klaravex_clients. Idempotent — never overwrites
    an existing non-null attribution_team (first-touch wins).
    """
    if not team or team not in VALID_TEAMS:
        return False
    pool = await get_pool()
    async with pool.acquire() as conn:
        updated = await conn.fetchval(
            """
            UPDATE klaravex_clients
               SET attribution_team = $1, updated_at = now()
             WHERE email = $2 AND attribution_team IS NULL
             RETURNING id
            """,
            team, email.lower(),
        )
    if updated:
        log.info("attribution stamped: %s → %s", email, team)
        return True
    return False
