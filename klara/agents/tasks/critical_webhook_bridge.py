"""
app/tasks/critical_webhook_bridge.py
─────────────────────────────────────
phase11-005 — forward critical AuditLog events to a configurable webhook.

Runs every 15 minutes. Selects AuditLog rows with event_type in the
CRITICAL_EVENT_TYPES set that were created since the last successful
forward AND have not yet been forwarded. POSTs each as JSON to the
URL in CRITICAL_EVENT_WEBHOOK_URL env (Slack-incoming-webhook style).

Idempotency: tracked by writing a `webhook.forwarded` AuditLog row
referencing the original event id in its details. A row is considered
forwarded if such a marker exists.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

import httpx
import structlog
from celery import shared_task
from sqlalchemy import and_, exists, func, or_, select

from app.database import db_context
from app.models.audit import AuditLog

logger = structlog.get_logger(__name__)

# phase17-005 — retry policy. After this many failed forward attempts, give up.
MAX_ATTEMPTS = 3


# AuditLog event types we forward. Tight list — only true ops-level events.
CRITICAL_EVENT_TYPES = (
    "llm.budget_exceeded",
    "approval.expired",
    "gdpr.erase_executed",
    "autonomy.promotion_proposed",
    # phase16-005 — Stripe payment lifecycle
    "stripe.payment.succeeded",
    "stripe.payment.failed",
    # phase16-003 — smoke test failures
    "smoke_test.failure",
)


@shared_task(
    bind=True,
    name="app.tasks.critical_webhook_bridge.run_webhook_bridge",
    max_retries=2,
    default_retry_delay=300,
)
def run_webhook_bridge(self):
    try:
        result = asyncio.run(_run())
        logger.info("critical_webhook_bridge.complete", **result)
        return result
    except Exception as exc:
        logger.error("critical_webhook_bridge.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _run() -> dict:
    webhook_url = os.environ.get("CRITICAL_EVENT_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return {"skipped": "no_webhook_url_configured"}

    # Only look at the last 24h to avoid back-filling history on first run
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    forwarded = 0
    skipped = 0

    async with db_context() as db:
        rows_q = await db.execute(
            select(AuditLog).where(
                AuditLog.event_type.in_(list(CRITICAL_EVENT_TYPES)),
                AuditLog.created_at >= cutoff,
            ).order_by(AuditLog.created_at.asc())
        )
        rows = list(rows_q.scalars().all())

        for row in rows:
            # Idempotency: skip if we already forwarded this row id
            marker_q = await db.execute(
                select(AuditLog.id).where(
                    AuditLog.event_type == "webhook.forwarded",
                    AuditLog.details.like(f'%"{row.id}"%'),
                ).limit(1)
            )
            if marker_q.scalar_one_or_none() is not None:
                skipped += 1
                continue

            # phase17-005: how many prior failed attempts for this source row?
            prior_q = await db.execute(
                select(func.count(AuditLog.id)).where(
                    AuditLog.event_type == "webhook.forward_failed",
                    AuditLog.details.like(f'%"{row.id}"%'),
                )
            )
            prior_attempts = int(prior_q.scalar() or 0)
            if prior_attempts >= MAX_ATTEMPTS:
                # Already exhausted retries — write abandoned marker (once)
                abandoned_q = await db.execute(
                    select(AuditLog.id).where(
                        AuditLog.event_type == "webhook.forward_abandoned",
                        AuditLog.details.like(f'%"{row.id}"%'),
                    ).limit(1)
                )
                if abandoned_q.scalar_one_or_none() is None:
                    db.add(AuditLog(
                        id=str(uuid4()),
                        event_type="webhook.forward_abandoned",
                        action_name="critical_webhook_bridge",
                        details=json.dumps({
                            "source_id": row.id,
                            "source_event": row.event_type,
                            "attempts": prior_attempts,
                        }),
                    ))
                skipped += 1
                continue

            payload = {
                "text": f":warning: Klaravex critical event — {row.event_type}",
                "event_type": row.event_type,
                "agent_name": row.agent_name,
                "action_name": row.action_name,
                "created_at": row.created_at.isoformat(),
                "details": row.details,
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(webhook_url, json=payload)
                if resp.status_code < 400:
                    marker = AuditLog(
                        id=str(uuid4()),
                        event_type="webhook.forwarded",
                        action_name="critical_webhook_bridge",
                        details=json.dumps({
                            "source_id": row.id,
                            "source_event": row.event_type,
                            "webhook_status": resp.status_code,
                            "attempt": prior_attempts + 1,
                        }),
                    )
                    db.add(marker)
                    forwarded += 1
                else:
                    # phase17-005: write a failure marker so retry counter sees it
                    db.add(AuditLog(
                        id=str(uuid4()),
                        event_type="webhook.forward_failed",
                        action_name="critical_webhook_bridge",
                        details=json.dumps({
                            "source_id": row.id,
                            "status": resp.status_code,
                            "attempt": prior_attempts + 1,
                        }),
                    ))
                    logger.warning(
                        "critical_webhook_bridge.non_2xx",
                        source_id=row.id,
                        status=resp.status_code,
                        attempt=prior_attempts + 1,
                    )
            except Exception as exc:
                # phase17-005: write a failure marker so retry counter sees it
                db.add(AuditLog(
                    id=str(uuid4()),
                    event_type="webhook.forward_failed",
                    action_name="critical_webhook_bridge",
                    details=json.dumps({
                        "source_id": row.id,
                        "error": str(exc)[:200],
                        "attempt": prior_attempts + 1,
                    }),
                ))
                logger.warning(
                    "critical_webhook_bridge.post_failed",
                    source_id=row.id,
                    error=str(exc),
                    attempt=prior_attempts + 1,
                )

    return {
        "forwarded": forwarded,
        "skipped_already_forwarded": skipped,
        "candidates": len(rows),
    }
