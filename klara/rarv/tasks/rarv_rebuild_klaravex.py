"""
app/tasks/rarv_rebuild_klaravex.py
────────────────────────────────────
Klaravex-side RARV rebuild tasks.

Registered on celery_klaravex so klaravex_worker can execute them.
Reads daily/*.md from klaravex-vault and rewrites MEMORY.md.
All GitHub credentials come from settings (GITHUB_VAULT_* in .env.klaravex).

Fired by klaravex_beat:
  - Nightly at 02:00 Berlin
  - Monthly on the 1st at 04:00 Berlin
"""
from __future__ import annotations

import asyncio

import structlog

from app.tasks.celery_klaravex import celery_klaravex
from app.tasks.rarv_rebuild import _monthly, _nightly

logger = structlog.get_logger(__name__)


@celery_klaravex.task(
    name="klaravex.tasks.rarv_rebuild.run_nightly_rebuild",
    bind=True,
    max_retries=1,
    default_retry_delay=600,
)
def run_nightly_rebuild_klaravex(self) -> dict:
    """02:00 Berlin — rebuild klaravex-vault MEMORY.md from trailing 30 days."""
    try:
        return asyncio.run(_nightly())
    except Exception as exc:
        logger.error("rarv_rebuild_klaravex.nightly.failed", error=str(exc), exc_info=True)
        try:
            raise self.retry(exc=exc)
        except Exception:
            return {"ok": False, "error": str(exc)}


@celery_klaravex.task(
    name="klaravex.tasks.rarv_rebuild.run_monthly_rebuild",
    bind=True,
    max_retries=1,
    default_retry_delay=900,
)
def run_monthly_rebuild_klaravex(self) -> dict:
    """04:00 Berlin day 1 — full re-derivation of klaravex-vault knowledge/ tree."""
    try:
        return asyncio.run(_monthly())
    except Exception as exc:
        logger.error("rarv_rebuild_klaravex.monthly.failed", error=str(exc), exc_info=True)
        try:
            raise self.retry(exc=exc)
        except Exception:
            return {"ok": False, "error": str(exc)}
