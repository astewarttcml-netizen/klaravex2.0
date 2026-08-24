"""
app/core/security_headers.py
─────────────────────────────
phase15-003 — security headers middleware.

Adds these to every response:
  Content-Security-Policy        — strict, allows self + Stripe + inline scripts
                                   needed for the inline dashboard JS
  Strict-Transport-Security      — 1 year, includeSubDomains
  X-Frame-Options                — DENY
  X-Content-Type-Options         — nosniff
  Referrer-Policy                — same-origin
  Permissions-Policy             — minimal (no geolocation, mic, camera)

CSP is intentionally permissive on inline-style/script because:
  - admin_dashboard.py renders inline JS for the dashboard UI
  - kb_landing.py + testimonials_public.py both have inline scripts
A future hardening pass could refactor those to external files + use nonces.
"""
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'"
    ),
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        for name, value in _HEADERS.items():
            if name not in response.headers:
                response.headers[name] = value
        return response
