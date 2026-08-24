"""Shared FastAPI dependency for /admin/* routes — session OAuth + allowlist.

Replaces the legacy `?secret=<LOKI_INTERNAL_SECRET>` query-string auth.
The session cookie is set by the Google/Microsoft OAuth callbacks in
admin_index.py; verify_session() there returns the email iff the cookie's
HMAC is valid, the TTL hasn't expired, and the email is in ADMIN_EMAILS.
"""

from fastapi import Cookie, HTTPException

from ..admin_index import SESSION_COOKIE, verify_session


async def require_admin_session(
    klaravex_admin_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> str:
    email = verify_session(klaravex_admin_session)
    if not email:
        raise HTTPException(
            status_code=401,
            detail="admin session required — sign in at /admin/",
        )
    return email
