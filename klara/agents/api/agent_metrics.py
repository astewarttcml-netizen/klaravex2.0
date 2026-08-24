"""
app/api/agent_metrics.py
─────────────────────────
Per-agent operational metrics endpoint (phase8-001).

  GET /api/v1/admin/agent-metrics?window_days=N    (X-API-Key)

Aggregates AuditLog rows by agent_name. Failure detection uses an
event_type substring match: any event_type containing "fail" or "error"
counts toward failure_count. Success = total - failure.

Read-only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.audit import AuditLog

logger = structlog.get_logger(__name__)
router = APIRouter()


class AgentMetric(BaseModel):
    agent_name: str
    total_invocations: int
    success_count: int
    failure_count: int
    success_rate: float                # 0.0–1.0
    last_run_at: Optional[datetime]


class AgentMetricsResponse(BaseModel):
    window_days: int
    generated_at: datetime
    total_audit_rows: int
    agents: list[AgentMetric]


# Substring fragments in event_type that indicate a failure. Conservative
# list — anything ambiguous (like "rejected") is treated as a SUCCESS-with-
# negative-outcome (the agent did its job, the human said no). True
# failures are operational ones: parse errors, timeouts, send failures.
_FAILURE_FRAGMENTS = ("fail", "error", "exception", "timeout")


@router.get("", response_model=AgentMetricsResponse)
async def agent_metrics(
    window_days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> AgentMetricsResponse:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    # Build the failure-classification CASE expression once
    failure_expr = case(
        (
            or_(*[
                AuditLog.event_type.ilike(f"%{frag}%")
                for frag in _FAILURE_FRAGMENTS
            ]),
            1,
        ),
        else_=0,
    )

    q = (
        select(
            AuditLog.agent_name,
            func.count(AuditLog.id).label("total"),
            func.sum(failure_expr).label("failures"),
            func.max(AuditLog.created_at).label("last_run"),
        )
        .where(
            AuditLog.created_at >= cutoff,
            AuditLog.agent_name.is_not(None),
        )
        .group_by(AuditLog.agent_name)
        .order_by(func.count(AuditLog.id).desc())
    )

    rows = (await db.execute(q)).all()

    total_rows = sum(int(r.total) for r in rows)

    agents = []
    for r in rows:
        total = int(r.total or 0)
        failures = int(r.failures or 0)
        successes = total - failures
        rate = round(successes / total, 4) if total else 0.0
        agents.append(AgentMetric(
            agent_name=r.agent_name,
            total_invocations=total,
            success_count=successes,
            failure_count=failures,
            success_rate=rate,
            last_run_at=r.last_run,
        ))

    return AgentMetricsResponse(
        window_days=window_days,
        generated_at=now,
        total_audit_rows=total_rows,
        agents=agents,
    )
