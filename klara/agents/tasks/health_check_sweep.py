"""
app/tasks/health_check_sweep.py
────────────────────────────────
phase8-003 — daily external service health checks.

Pings:
  resend     — POST /emails (HEAD on api.resend.com instead of actual send)
  anthropic  — model list endpoint (cheap, no inference cost)
  cloud86_db — SELECT 1 against the configured DATABASE_URL
  calendly   — GET /users/me (lightweight)
  stripe     — GET /v1/charges?limit=1 (lightweight)

Each check writes a row to external_service_health. Failures are logged
but do NOT raise — the sweep must complete for every service even if
one is unreachable.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx
import structlog
from celery import shared_task
from sqlalchemy import text

from klara.rarv.runtime import get_settings
from klara.rarv.runtime import db_context
from klara.rarv.external_service_health import ExternalServiceHealth, ServiceStatus

logger = structlog.get_logger(__name__)


# Latency threshold (ms) above which a healthy 2xx is downgraded to "degraded"
_DEGRADED_LATENCY_MS = 3000


@shared_task(
    bind=True,
    name="app.tasks.health_check_sweep.run_health_check_sweep",
    max_retries=2,
    default_retry_delay=300,
)
def run_health_check_sweep(self):
    """Celery entry point — runs all checks once per call."""
    try:
        result = asyncio.run(_sweep())
        logger.info("health_check_sweep.complete", **result)
        return result
    except Exception as exc:
        logger.error("health_check_sweep.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _sweep() -> dict:
    settings = get_settings()
    checks = [
        ("anthropic",  _check_anthropic(settings)),
        ("resend",     _check_resend(settings)),
        ("cloud86_db", _check_db()),
        ("calendly",   _check_calendly(settings)),
        ("stripe",     _check_stripe(settings)),
    ]

    summary: dict[str, str] = {}
    async with db_context() as db:
        for name, coro in checks:
            try:
                status, latency_ms, err = await coro
            except Exception as exc:
                status, latency_ms, err = ServiceStatus.down, None, str(exc)[:200]
            row = ExternalServiceHealth(
                service_name=name,
                status=status,
                latency_ms=latency_ms,
                error=err,
            )
            db.add(row)
            summary[name] = status
    return summary


async def _timed_request(method: str, url: str, **kwargs) -> tuple[str, int, Optional[str]]:
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.request(method, url, **kwargs)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        if r.status_code >= 500:
            return ServiceStatus.down, elapsed_ms, f"HTTP {r.status_code}"
        if r.status_code >= 400:
            return ServiceStatus.degraded, elapsed_ms, f"HTTP {r.status_code}"
        if elapsed_ms > _DEGRADED_LATENCY_MS:
            return ServiceStatus.degraded, elapsed_ms, "slow response"
        return ServiceStatus.up, elapsed_ms, None
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ServiceStatus.down, elapsed_ms, str(exc)[:200]


async def _check_anthropic(settings) -> tuple[str, int, Optional[str]]:
    key = getattr(settings, "anthropic_api_key", None)
    if not key:
        return ServiceStatus.degraded, 0, "no API key configured"
    return await _timed_request(
        "GET",
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
    )


async def _check_resend(settings) -> tuple[str, int, Optional[str]]:
    key = getattr(settings, "resend_api_key", None) or getattr(settings, "RESEND_API_KEY", None)
    if not key:
        return ServiceStatus.degraded, 0, "no API key configured"
    return await _timed_request(
        "GET",
        "https://api.resend.com/domains",
        headers={"Authorization": f"Bearer {key}"},
    )


async def _check_db() -> tuple[str, int, Optional[str]]:
    start = time.monotonic()
    try:
        async with db_context() as db:
            await db.execute(text("SELECT 1"))
        elapsed_ms = int((time.monotonic() - start) * 1000)
        if elapsed_ms > _DEGRADED_LATENCY_MS:
            return ServiceStatus.degraded, elapsed_ms, "slow query"
        return ServiceStatus.up, elapsed_ms, None
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ServiceStatus.down, elapsed_ms, str(exc)[:200]


async def _check_calendly(settings) -> tuple[str, int, Optional[str]]:
    token = getattr(settings, "calendly_token", None) or getattr(settings, "CALENDLY_TOKEN", None)
    if not token:
        return ServiceStatus.degraded, 0, "no token configured"
    return await _timed_request(
        "GET",
        "https://api.calendly.com/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )


async def _check_stripe(settings) -> tuple[str, int, Optional[str]]:
    key = getattr(settings, "stripe_secret_key", None) or getattr(settings, "STRIPE_SECRET_KEY", None)
    if not key:
        return ServiceStatus.degraded, 0, "no API key configured"
    return await _timed_request(
        "GET",
        "https://api.stripe.com/v1/charges?limit=1",
        headers={"Authorization": f"Bearer {key}"},
    )
