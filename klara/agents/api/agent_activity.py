"""
app/api/agent_activity.py
──────────────────────────
phase13-005 — agent activity audit.

  GET /api/v1/admin/agent-activity?window_days=30   (X-API-Key)

Buckets every registered agent into:
  active_recently  — fired in the last `window_days`
  active_ever      — fired ever, but not in the window
  never            — registered but never logged an AuditLog row

Used to identify dead-code agents that should be removed from registry,
and to confirm the active surface area of the system.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.database import get_db
from app.models.audit import AuditLog

logger = structlog.get_logger(__name__)
router = APIRouter()


class AgentActivityEntry(BaseModel):
    agent_name: str
    permission_level: str
    last_audit_at: datetime | None
    invocation_count: int   # count in the window


class AgentActivityResponse(BaseModel):
    window_days: int
    generated_at: datetime
    total_registered: int
    active_recently: List[AgentActivityEntry]
    active_ever: List[AgentActivityEntry]
    never: List[AgentActivityEntry]


@router.get("", response_model=AgentActivityResponse)
async def agent_activity(
    window_days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> AgentActivityResponse:
    from app.agents.registry import registry

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    # All registered agents
    registered = [(a.name, a.permission_level.value) for a in registry]

    # Last-seen + recent count from AuditLog
    last_seen_q = await db.execute(
        select(
            AuditLog.agent_name,
            func.max(AuditLog.created_at).label("last_at"),
            func.sum(
                func.case((AuditLog.created_at >= cutoff, 1), else_=0)
            ).label("recent_count"),
        )
        .where(AuditLog.agent_name.is_not(None))
        .group_by(AuditLog.agent_name)
    )
    stats = {
        row[0]: (row[1], int(row[2] or 0))
        for row in last_seen_q.all()
    }

    active_recently: List[AgentActivityEntry] = []
    active_ever: List[AgentActivityEntry] = []
    never: List[AgentActivityEntry] = []

    for name, level in registered:
        last_at, recent_count = stats.get(name, (None, 0))
        entry = AgentActivityEntry(
            agent_name=name,
            permission_level=level,
            last_audit_at=last_at,
            invocation_count=recent_count,
        )
        if recent_count > 0:
            active_recently.append(entry)
        elif last_at is not None:
            active_ever.append(entry)
        else:
            never.append(entry)

    # Sort: most-active first within recently; most-recent within ever
    active_recently.sort(key=lambda e: -e.invocation_count)
    active_ever.sort(key=lambda e: e.last_audit_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    never.sort(key=lambda e: e.agent_name)

    return AgentActivityResponse(
        window_days=window_days,
        generated_at=now,
        total_registered=len(registered),
        active_recently=active_recently,
        active_ever=active_ever,
        never=never,
    )
