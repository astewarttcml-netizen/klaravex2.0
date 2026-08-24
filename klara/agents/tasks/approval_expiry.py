"""
app/tasks/approval_expiry.py
─────────────────────────────
phase10-002 — daily sweep that expires stale pending approvals.

Any ApprovalRequest with status='pending' AND created_at < now - APPROVAL_TTL_DAYS
gets flipped to status='expired'. An AuditLog row is written for each expiry.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import structlog
from celery import shared_task
from sqlalchemy import select

from app.database import db_context
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.audit import AuditLog

logger = structlog.get_logger(__name__)

APPROVAL_TTL_DAYS = 7


@shared_task(
    bind=True,
    name="app.tasks.approval_expiry.run_approval_expiry_sweep",
    max_retries=2,
    default_retry_delay=600,
)
def run_approval_expiry_sweep(self):
    try:
        result = asyncio.run(_sweep())
        logger.info("approval_expiry.complete", **result)
        return result
    except Exception as exc:
        logger.error("approval_expiry.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _sweep() -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=APPROVAL_TTL_DAYS)
    expired = 0

    async with db_context() as db:
        q = await db.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.status == ApprovalStatus.pending.value,
                ApprovalRequest.created_at < cutoff,
            )
        )
        for approval in q.scalars():
            approval.status = ApprovalStatus.expired.value
            audit = AuditLog(
                id=str(uuid4()),
                event_type="approval.expired",
                action_name=approval.action_name,
                approval_id=approval.id,
                lead_id=approval.lead_id,
                details=json.dumps({
                    "ttl_days": APPROVAL_TTL_DAYS,
                    "created_at": approval.created_at.isoformat(),
                }),
            )
            db.add(audit)
            expired += 1

    return {"expired": expired, "ttl_days": APPROVAL_TTL_DAYS}
