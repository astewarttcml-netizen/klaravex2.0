"""
app/api/audit_timeline.py
──────────────────────────
Admin endpoint for the chronological audit timeline (phase7-005).

  GET /api/v1/admin/audit-timeline?event_type=&agent=&days=&limit=&offset=

Reads from AuditLog with optional filters. Read-only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.audit import AuditLog

logger = structlog.get_logger(__name__)
router = APIRouter()


class AuditEntry(BaseModel):
    id: str
    event_type: str
    agent_name: Optional[str]
    action_name: Optional[str]
    lead_id: Optional[str]
    conversation_id: Optional[str]
    approval_id: Optional[str]
    details: Optional[str]
    created_at: datetime


class AuditTimelineResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AuditEntry]


@router.get("", response_model=AuditTimelineResponse)
async def audit_timeline(
    event_type: Optional[str] = Query(default=None),
    agent: Optional[str] = Query(default=None),
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> AuditTimelineResponse:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    base = select(AuditLog).where(AuditLog.created_at >= cutoff)
    count_base = select(func.count(AuditLog.id)).where(AuditLog.created_at >= cutoff)

    if event_type:
        base = base.where(AuditLog.event_type == event_type)
        count_base = count_base.where(AuditLog.event_type == event_type)
    if agent:
        base = base.where(AuditLog.agent_name == agent)
        count_base = count_base.where(AuditLog.agent_name == agent)

    total_q = await db.execute(count_base)
    total = int(total_q.scalar() or 0)

    rows_q = await db.execute(
        base.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    )
    rows = list(rows_q.scalars().all())

    return AuditTimelineResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[
            AuditEntry(
                id=r.id,
                event_type=r.event_type,
                agent_name=r.agent_name,
                action_name=r.action_name,
                lead_id=r.lead_id,
                conversation_id=r.conversation_id,
                approval_id=r.approval_id,
                details=r.details,
                created_at=r.created_at,
            )
            for r in rows
        ],
    )
