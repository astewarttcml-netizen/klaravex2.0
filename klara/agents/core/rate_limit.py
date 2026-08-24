"""
app/core/rate_limit.py
───────────────────────
phase15-002 + phase16-001 — Redis-backed rate limiter with in-memory fallback.

Per (client_ip, route_prefix). Default: 60 requests / 60 seconds.
On exhaustion, returns HTTP 429 with Retry-After header.

Strategy:
  1. Try Redis (INCR + EXPIRE) — shared across api workers
  2. If Redis unreachable, fall back to in-memory token bucket (per-worker)

The fallback path means the limiter NEVER fails open — it just degrades
gracefully when Redis is down.
"""
from __future__ import annotations

import os
import time
from typing import Awaitable, Callable, Dict, Optional, Tuple

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger(__name__)

# In-memory fallback bucket — per (ip, route_prefix) → (tokens_remaining, window_start_monotonic)
_BUCKETS: Dict[Tuple[str, str], Tuple[float, float]] = {}

# Module-scoped Redis client — lazily initialised. None when not configured
# or unreachable; callers fall back to the in-memory path.
_REDIS_CLIENT = None
_REDIS_CHECKED = False


DEFAULT_LIMIT = 60          # requests
WINDOW_SECONDS = 60.0


def _get_redis():
    """Return a sync Redis client, or None on failure. Memoised."""
    global _REDIS_CLIENT, _REDIS_CHECKED
    if _REDIS_CHECKED:
        return _REDIS_CLIENT
    _REDIS_CHECKED = True
    try:
        import redis
        url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        client = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
        # Ping to verify reachability — never propagate errors
        client.ping()
        _REDIS_CLIENT = client
        logger.info("rate_limit.redis_connected", url=url.split('@')[-1])
    except Exception as exc:
        logger.warning("rate_limit.redis_unavailable", error=str(exc))
        _REDIS_CLIENT = None
    return _REDIS_CLIENT

# Route prefixes that get rate-limited (everything public).
RATE_LIMITED_PREFIXES = (
    "/status",
    "/kb",
    "/testimonials",
    "/api/v1/kb-public",
    "/api/v1/testimonials-public",
)


def _bucket_key(ip: str, path: str) -> Tuple[str, str]:
    for prefix in RATE_LIMITED_PREFIXES:
        if path.startswith(prefix):
            return (ip, prefix)
    return (ip, "")


def _client_ip(request: Request) -> str:
    # Behind a reverse proxy (nginx), prefer X-Forwarded-For first hop
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _consume(key: Tuple[str, str], limit: int = DEFAULT_LIMIT) -> Tuple[bool, int]:
    """Return (allowed, retry_after_seconds).

    Tries Redis first (shared across workers). Falls back to in-memory
    token bucket per process when Redis is unreachable.
    """
    # ── Redis path (phase16-001) ──────────────────────────────────────────
    client = _get_redis()
    if client is not None:
        redis_key = f"ratelim:{key[0]}:{key[1]}"
        try:
            count = client.incr(redis_key)
            if count == 1:
                # First request in window — set expiry
                client.expire(redis_key, int(WINDOW_SECONDS))
            if count > limit:
                ttl = client.ttl(redis_key)
                return False, max(int(ttl) if ttl > 0 else int(WINDOW_SECONDS), 1)
            return True, 0
        except Exception as exc:
            # Redis hiccup — fall through to in-memory bucket
            logger.warning("rate_limit.redis_error", error=str(exc))

    # ── In-memory fallback ───────────────────────────────────────────────
    now = time.monotonic()
    tokens, window_start = _BUCKETS.get(key, (float(limit), now))

    if now - window_start >= WINDOW_SECONDS:
        # New window — refill
        tokens = float(limit)
        window_start = now

    if tokens >= 1.0:
        _BUCKETS[key] = (tokens - 1.0, window_start)
        return True, 0

    retry = int(WINDOW_SECONDS - (now - window_start)) + 1
    return False, max(retry, 1)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        prefix_match = any(path.startswith(p) for p in RATE_LIMITED_PREFIXES)
        if not prefix_match:
            return await call_next(request)

        ip = _client_ip(request)
        key = _bucket_key(ip, path)
        allowed, retry_after = _consume(key)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limited", "retry_after": retry_after},
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)


def _reset_buckets_for_tests() -> None:
    _BUCKETS.clear()
    global _REDIS_CHECKED, _REDIS_CLIENT
    _REDIS_CHECKED = False
    _REDIS_CLIENT = None
