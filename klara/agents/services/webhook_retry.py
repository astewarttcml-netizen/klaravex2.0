"""
app/services/webhook_retry.py
─────────────────────────────
phase17-005 -- enqueue an inbound webhook for later retry instead of
returning 500 to the sender.

Backoff schedule (5 attempts max):
    attempt 1: +1 min
    attempt 2: +5 min
    attempt 3: +25 min
    attempt 4: +2 h
    attempt 5: +12 h
After attempt 5 fails, status flips to 'permanent_failure' and the row
sticks around for audit.

Called from FastAPI webhook handlers. The handler returns 200 OK; the
retry task picks the row up on its next sweep.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# Backoff for attempt N (1-indexed). Index 0 unused -- placeholder so
# attempts line up with array index.
_BACKOFF_DELAYS = [
    timedelta(0),
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=25),
    timedelta(hours=2),
    timedelta(hours=12),
]
MAX_ATTEMPTS = 5


def next_retry_at(attempt: int) -> datetime:
    """Compute when attempt N should fire. Clamped to MAX_ATTEMPTS."""
    idx = min(max(attempt, 1), MAX_ATTEMPTS)
    return datetime.now(timezone.utc) + _BACKOFF_DELAYS[idx]


async def enqueue_for_retry(
    db: AsyncSession,
    *,
    source: str,
    endpoint_path: str,
    payload: Any,
    error: str,
) -> int:
    """
    INSERT a webhook_retries row and return its id.

    Args:
        source: short tag identifying the sender ('stripe', 'wordpress', ...)
        endpoint_path: the URL path the webhook hit
        payload: the raw payload (will be json.dumps'd)
        error: the exception message that triggered the enqueue

    Returns the new row id so the handler can log it.
    """
    payload_str = json.dumps(payload) if not isinstance(payload, str) else payload
    eta = next_retry_at(1)
    result = await db.execute(
        text(
            """
            INSERT INTO webhook_retries
            (source, endpoint_path, payload_json, error,
             attempt_count, status, next_retry_at)
            VALUES (:src, :path, :payload, :err, 0, 'pending', :eta)
            RETURNING id
            """
        ),
        {
            "src": source[:64],
            "path": endpoint_path[:255],
            "payload": payload_str,
            "err": (error or "")[:5000],
            "eta": eta,
        },
    )
    new_id = result.scalar_one()
    await db.commit()
    logger.warning(
        "webhook_retry.enqueued",
        retry_id=new_id,
        source=source,
        endpoint=endpoint_path,
        error_head=error[:120] if error else None,
    )
    return new_id
