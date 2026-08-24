"""
app/api/status_page.py
───────────────────────
phase10-005 — public lightweight system status endpoint.

  GET /status   (no auth required)

Returns aggregate, non-sensitive system health:
  status         "ok" | "degraded" | "down"
  uptime_seconds since the api process started
  agents         number of registered agents
  llm_calls_today   integer
  db_reachable   bool

Used by external monitoring + customer-facing trust signal.
"""
from __future__ import annotations

import time
from datetime import datetime, time as dtime, timezone

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import get_db
from klara.rarv.llm_call import LlmCall

logger = structlog.get_logger(__name__)
router = APIRouter()

# Process-start timestamp captured at import time
_PROCESS_START = time.monotonic()


class StatusResponse(BaseModel):
    status: str
    uptime_seconds: int
    agents: int
    llm_calls_today: int
    db_reachable: bool


@router.get("", response_model=StatusResponse)
async def status(db: AsyncSession = Depends(get_db)) -> StatusResponse:
    uptime = int(time.monotonic() - _PROCESS_START)

    # Agents count
    try:
        from app.agents.registry import registry
        agents = len(registry)
    except Exception:
        agents = 0

    # LLM calls today
    llm_today = 0
    db_reachable = True
    try:
        now = datetime.now(timezone.utc)
        start_of_day = datetime.combine(now.date(), dtime.min, tzinfo=timezone.utc)
        q = await db.execute(
            select(func.count(LlmCall.id)).where(LlmCall.called_at >= start_of_day)
        )
        llm_today = int(q.scalar() or 0)
    except Exception as exc:
        logger.warning("status.db_query_failed", error=str(exc))
        db_reachable = False

    overall = "ok" if db_reachable else "degraded"

    return StatusResponse(
        status=overall,
        uptime_seconds=uptime,
        agents=agents,
        llm_calls_today=llm_today,
        db_reachable=db_reachable,
    )
