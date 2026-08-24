"""
app/api/llm_cost_admin.py
──────────────────────────
phase9-002 — LLM cost analytics endpoint.

  GET /api/v1/admin/llm-cost?window_days=N    (X-API-Key)

Aggregates llm_calls rows by agent + by day. Used by the Cost dashboard
tab and by the daily budget alarm.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.database import get_db
from app.models.llm_call import LlmCall

logger = structlog.get_logger(__name__)
router = APIRouter()


class AgentCost(BaseModel):
    agent_name: str
    call_count: int
    input_tokens: int
    output_tokens: int
    cost_eur: float


class DailyCost(BaseModel):
    day: str            # YYYY-MM-DD
    call_count: int
    cost_eur: float


class LlmCostResponse(BaseModel):
    window_days: int
    generated_at: datetime
    total_calls: int
    total_cost_eur: float
    by_agent: list[AgentCost]
    by_day: list[DailyCost]


@router.get("", response_model=LlmCostResponse)
async def llm_cost(
    window_days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> LlmCostResponse:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    by_agent_q = await db.execute(
        select(
            LlmCall.agent_name,
            func.count(LlmCall.id),
            func.coalesce(func.sum(LlmCall.input_tokens), 0),
            func.coalesce(func.sum(LlmCall.output_tokens), 0),
            func.coalesce(func.sum(LlmCall.cost_eur), 0),
        )
        .where(LlmCall.called_at >= cutoff)
        .group_by(LlmCall.agent_name)
        .order_by(func.sum(LlmCall.cost_eur).desc())
    )
    by_agent = [
        AgentCost(
            agent_name=row[0],
            call_count=int(row[1] or 0),
            input_tokens=int(row[2] or 0),
            output_tokens=int(row[3] or 0),
            cost_eur=float(row[4] or 0.0),
        )
        for row in by_agent_q.all()
    ]

    by_day_q = await db.execute(
        select(
            func.date_trunc("day", LlmCall.called_at).label("day"),
            func.count(LlmCall.id),
            func.coalesce(func.sum(LlmCall.cost_eur), 0),
        )
        .where(LlmCall.called_at >= cutoff)
        .group_by("day")
        .order_by("day")
    )
    by_day = [
        DailyCost(
            day=row[0].date().isoformat() if isinstance(row[0], datetime) else str(row[0])[:10],
            call_count=int(row[1] or 0),
            cost_eur=float(row[2] or 0.0),
        )
        for row in by_day_q.all()
    ]

    total_calls_q = await db.execute(
        select(func.count(LlmCall.id)).where(LlmCall.called_at >= cutoff)
    )
    total_calls = int(total_calls_q.scalar() or 0)

    total_cost_q = await db.execute(
        select(func.coalesce(func.sum(LlmCall.cost_eur), 0))
        .where(LlmCall.called_at >= cutoff)
    )
    total_cost = float(total_cost_q.scalar() or 0.0)

    return LlmCostResponse(
        window_days=window_days,
        generated_at=now,
        total_calls=total_calls,
        total_cost_eur=round(total_cost, 4),
        by_agent=by_agent,
        by_day=by_day,
    )
