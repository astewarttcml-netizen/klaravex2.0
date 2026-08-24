"""
Shared SlowAPI Limiter for the Klaravex backend.

main.py owns the canonical Limiter (so app.state.limiter is wired correctly),
but per-route handlers in klara.handlers/ also need to decorate themselves
with @limiter.limit("…"). To avoid a circular import (main.py → klara.handlers
→ main.py), this module exposes a single global Limiter that main.py reuses
via ``from klara.handlers.lib.rate_limit import limiter``.

The limiter's key_func consults X-Forwarded-For first because Azure Container
App ingress terminates TLS and request.client.host would otherwise resolve
to the internal load-balancer IP — making the limiter effectively global.

Per-route helpers:
  - @limiter.limit("10/minute; 200/hour")  → chat
  - @limiter.limit("5/minute")              → voice payment_link / escalate
  - @limiter.limit("20/minute")             → intake forms
Anything else inherits the default in Limiter() below (60/min, 1000/hr).

SlowAPI requires the decorated route handler to take a `request: Request`
parameter — without it the decorator raises at call time.
"""

from slowapi import Limiter
from starlette.requests import Request


def client_key(request: Request) -> str:
    """Limiter key — prefer X-Forwarded-For, fall back to socket peer.

    Azure Container App ingress sets X-Forwarded-For = "<public-ip>, <internal>".
    We use the FIRST entry (the actual public client). Local dev or direct
    calls without the header fall back to request.client.host.
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


limiter = Limiter(
    key_func=client_key,
    default_limits=["60/minute", "1000/hour"],
)
