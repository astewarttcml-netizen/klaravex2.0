"""
app/api/webhooks_didww.py
──────────────────────────
DIDWW SMS callback receiver.

  POST /api/v1/webhooks/didww/callback

Receives delivery receipts (DLR) and inbound SMS (MO) from DIDWW
HTTP OUT SMS trunks.

Callback types:
  - DLR:  {id, status, delivered_at, status_code, error_message}
  - MO:   {id, from, to, body, received_at}

All callbacks are logged and stored in sms_events for audit.
Always returns 200 OK — DIDWW retries non-2xx.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import get_db

logger = structlog.get_logger(__name__)
router = APIRouter()


class DidwwCallback(BaseModel):
    """Flexible model that accepts the DIDWW callback payload shapes.

    DLR fields:  id, status, delivered_at, status_code, error_message
    MO  fields:  id, from, to, body, received_at
    """
    id: Optional[str] = None
    status: Optional[str] = None
    delivered_at: Optional[str] = None
    status_code: Optional[str] = None
    error_message: Optional[str] = None
    # MO (inbound) fields
    from_: Optional[str] = None
    to: Optional[str] = None
    body: Optional[str] = None
    received_at: Optional[str] = None


@router.post("/didww/callback", status_code=200)
async def didww_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    DIDWW SMS callback — delivery receipts + inbound messages.

    Always returns 200 OK. DIDWW retries non-2xx responses.
    Payload is logged and persisted to sms_events table.
    """
    raw: dict = {}
    try:
        raw = await request.json()
    except Exception:
        raw = {"_raw_body": (await request.body()).decode("utf-8", errors="replace")}

    event_type = "dlr" if "status" in raw else "mo" if "body" in raw else "unknown"

    logger.info(
        "didww_callback.received",
        event_type=event_type,
        payload=raw,
    )

    try:
        await db.execute(
            text("""
                INSERT INTO sms_events (id, event_type, payload, created_at)
                VALUES (gen_random_uuid(), :event_type, :payload, :now)
            """),
            {
                "event_type": event_type,
                "payload": str(raw),
                "now": datetime.now(timezone.utc),
            },
        )
        await db.commit()
    except Exception as exc:
        logger.error("didww_callback.db_error", error=str(exc))

    return {"ok": True, "type": event_type}
