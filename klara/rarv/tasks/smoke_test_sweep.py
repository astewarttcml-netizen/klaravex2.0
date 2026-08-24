"""
app/tasks/smoke_test_sweep.py
──────────────────────────────
phase16-003 — daily smoke test against the live api surface.

Hits each public + health endpoint via internal localhost so we catch
regressions before users do. Any non-2xx writes an AuditLog row with
event_type='smoke_test.failure', which the phase11-005 critical webhook
bridge will forward.

Internal hits to localhost:8000 keep the smoke test independent of
nginx, OAuth, and DNS — we're checking the api itself.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import structlog
from celery import shared_task

from app.database import db_context
from app.models.audit import AuditLog

logger = structlog.get_logger(__name__)


# Internal probe endpoints. Public surfaces only — no auth required.
# host.docker.internal works when api hits itself; fallback is the
# in-cluster api service name (docker compose network).
_SMOKE_TARGETS = (
    "/status",
    "/kb",
    "/testimonials",
    "/api/v1/kb-public/search?q=test",
    "/api/v1/testimonials-public",
)


def _base_url() -> str:
    return os.environ.get("SMOKE_TEST_BASE", "http://api:8000")


@shared_task(
    bind=True,
    name="app.tasks.smoke_test_sweep.run_smoke_tests",
    max_retries=2,
    default_retry_delay=300,
)
def run_smoke_tests(self):
    try:
        result = asyncio.run(_run())
        logger.info("smoke_test_sweep.complete", **result)
        return result
    except Exception as exc:
        logger.error("smoke_test_sweep.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _run() -> dict:
    base = _base_url()
    passed = 0
    failed: list[dict] = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        for path in _SMOKE_TARGETS:
            url = f"{base}{path}"
            try:
                resp = await client.get(url)
                if resp.status_code < 400:
                    passed += 1
                else:
                    failed.append({"url": url, "status": resp.status_code})
            except Exception as exc:
                failed.append({"url": url, "error": str(exc)[:120]})

    if failed:
        async with db_context() as db:
            for f in failed:
                audit = AuditLog(
                    id=str(uuid4()),
                    event_type="smoke_test.failure",
                    action_name="daily_smoke_test",
                    details=json.dumps(f),
                )
                db.add(audit)

    return {
        "tested": len(_SMOKE_TARGETS),
        "passed": passed,
        "failed_count": len(failed),
        "failures": failed,
    }
