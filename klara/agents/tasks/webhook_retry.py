"""
app/tasks/webhook_retry.py
──────────────────────────
phase17-005 -- replay webhook_retries rows whose next_retry_at is due.

Scheduled via n8n + cron (entry: webhook-retry-5m). Picks rows where
status='pending' AND next_retry_at <= now(), marks them 'retrying',
re-dispatches the original webhook payload to the same endpoint
internally, and updates status based on outcome.

Each attempt that fails bumps attempt_count and pushes next_retry_at out
per the backoff in services/webhook_retry.py. Attempt 5 failure flips to
'permanent_failure'.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import httpx
import structlog
from celery import shared_task
from sqlalchemy import text

from klara.rarv.runtime import db_context
from klara.rarv.runtime.webhook_retry import next_retry_at, MAX_ATTEMPTS

logger = structlog.get_logger(__name__)

# Replays target the API container's internal port -- not via nginx.
_INTERNAL_BASE = "http://api:8000"


@shared_task(
    bind=True,
    name="app.tasks.webhook_retry.run_webhook_retries",
    max_retries=2,
    default_retry_delay=180,
)
def run_webhook_retries(self, triggered_by: str = "n8n"):
    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("webhook_retry.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _run() -> dict:
    now = datetime.now(timezone.utc)
    processed, succeeded, failed, retired = 0, 0, 0, 0

    async with db_context() as db:
        # Claim a batch atomically
        result = await db.execute(
            text(
                """
                UPDATE webhook_retries
                SET status = 'retrying', last_attempted_at = now()
                WHERE id IN (
                    SELECT id FROM webhook_retries
                    WHERE status = 'pending' AND next_retry_at <= :now
                    ORDER BY next_retry_at
                    LIMIT 25
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, source, endpoint_path, payload_json, attempt_count
                """
            ),
            {"now": now},
        )
        claimed = list(result.fetchall())
        await db.commit()

    if not claimed:
        return {"processed": 0, "succeeded": 0, "failed": 0, "retired": 0}

    async with httpx.AsyncClient(
        timeout=20.0,
        headers={"Host": "api.klaravex.de"},
    ) as http:
        for row_id, source, path, payload_str, attempts in claimed:
            processed += 1
            attempts = (attempts or 0) + 1
            try:
                # Replay the POST. We send Host header that matches the
                # TrustedHostMiddleware allow list, and tag with a header
                # so the receiver can short-circuit signature checks if it
                # wants to trust replays.
                resp = await http.post(
                    f"{_INTERNAL_BASE}{path}",
                    content=payload_str,
                    headers={
                        "X-Webhook-Replay": "1",
                        "X-Webhook-Replay-Id": str(row_id),
                        "Content-Type": "application/json",
                    },
                )
                ok = resp.status_code < 400
                err_text = None if ok else f"replay HTTP {resp.status_code}: {resp.text[:200]}"
            except Exception as exc:
                ok = False
                err_text = f"replay exception: {str(exc)[:200]}"

            async with db_context() as db:
                if ok:
                    await db.execute(
                        text(
                            """
                            UPDATE webhook_retries SET
                                status = 'succeeded',
                                resolved_at = now(),
                                attempt_count = :a
                            WHERE id = :id
                            """
                        ),
                        {"id": row_id, "a": attempts},
                    )
                    succeeded += 1
                else:
                    if attempts >= MAX_ATTEMPTS:
                        await db.execute(
                            text(
                                """
                                UPDATE webhook_retries SET
                                    status = 'permanent_failure',
                                    attempt_count = :a,
                                    error = :err,
                                    resolved_at = now()
                                WHERE id = :id
                                """
                            ),
                            {"id": row_id, "a": attempts, "err": (err_text or "")[:5000]},
                        )
                        retired += 1
                        logger.error(
                            "webhook_retry.permanent_failure",
                            retry_id=row_id,
                            source=source,
                            error=err_text,
                        )
                    else:
                        next_at = next_retry_at(attempts + 1)
                        await db.execute(
                            text(
                                """
                                UPDATE webhook_retries SET
                                    status = 'pending',
                                    attempt_count = :a,
                                    error = :err,
                                    next_retry_at = :next
                                WHERE id = :id
                                """
                            ),
                            {
                                "id": row_id,
                                "a": attempts,
                                "err": (err_text or "")[:5000],
                                "next": next_at,
                            },
                        )
                        failed += 1
                await db.commit()

    summary = {
        "processed": processed,
        "succeeded": succeeded,
        "failed": failed,
        "retired": retired,
        "triggered_by": "n8n",
    }
    logger.info("webhook_retry.run_complete", **summary)
    return summary
