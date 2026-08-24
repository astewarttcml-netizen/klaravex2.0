"""
app/tasks/rarv_heartbeat_klaravex.py
──────────────────────────────────────
Klaravex-side RARV heartbeat.

Registered on celery_klaravex so klaravex_worker can execute it.
When running in klaravex_worker:
  - DB: Azure klaravex-db-r2 (via DATABASE_URL → host.docker.internal:15432 SSH tunnel)
  - Schema: klaravex (via DB_SCHEMA=klaravex)
  - Reads: klaravex.note_submissions
  - Writes: klaravex-vault on GitHub (via GITHUB_VAULT_* in .env.klaravex)

Fired by klaravex_beat every 30 min via beat_schedule entry
'rarv-heartbeat-30m' in celery_klaravex.py.
"""
from __future__ import annotations

import asyncio

import structlog

from klara.rarv.runtime import celery_klaravex
from klara.rarv.tasks.rarv_heartbeat import BATCH_SIZE_DEFAULT, _heartbeat

logger = structlog.get_logger(__name__)


@celery_klaravex.task(
    name="klaravex.tasks.rarv_heartbeat.run_heartbeat",
    bind=True,
    max_retries=0,
)
def run_heartbeat_klaravex(self, batch_size: int = BATCH_SIZE_DEFAULT) -> dict:
    """Klaravex-side heartbeat: Azure klaravex-db-r2 klaravex.note_submissions → klaravex-vault."""
    try:
        return asyncio.run(_heartbeat(batch_size=int(batch_size)))
    except Exception as exc:
        logger.error("rarv_heartbeat_klaravex.fatal", error=str(exc), exc_info=True)
        return {"ok": False, "error": str(exc), "processed": 0}
