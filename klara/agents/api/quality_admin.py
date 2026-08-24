"""
app/api/quality_admin.py
─────────────────────────
phase12-004 — quality dashboard endpoint.

  GET /api/v1/admin/quality?window_days=N
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.prompt_quality import QualitySample

logger = structlog.get_logger(__name__)
router = APIRouter()


class AgentQuality(BaseModel):
    agent_name: str
    sample_count: int
    avg_score: float
    score_5: int
    score_4: int
    score_3: int
    score_2: int
    score_1: int


class LowScoreSample(BaseModel):
    id: str
    llm_call_id: str
    agent_name: str
    score: int
    reason: Optional[str]
    judged_at: datetime


class QualityResponse(BaseModel):
    window_days: int
    generated_at: datetime
    by_agent: List[AgentQuality]
    recent_low_scores: List[LowScoreSample]


@router.get("", response_model=QualityResponse)
async def quality(
    window_days: int = Query(default=14, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> QualityResponse:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    # Per-agent aggregation
    by_agent_q = await db.execute(
        select(
            QualitySample.agent_name,
            func.count(QualitySample.id),
            func.coalesce(func.avg(QualitySample.score), 0),
            func.sum(func.case((QualitySample.score == 5, 1), else_=0)),
            func.sum(func.case((QualitySample.score == 4, 1), else_=0)),
            func.sum(func.case((QualitySample.score == 3, 1), else_=0)),
            func.sum(func.case((QualitySample.score == 2, 1), else_=0)),
            func.sum(func.case((QualitySample.score == 1, 1), else_=0)),
        )
        .where(QualitySample.judged_at >= cutoff)
        .group_by(QualitySample.agent_name)
        .order_by(func.avg(QualitySample.score))   # worst first
    )
    by_agent = [
        AgentQuality(
            agent_name=row[0],
            sample_count=int(row[1] or 0),
            avg_score=round(float(row[2] or 0.0), 2),
            score_5=int(row[3] or 0),
            score_4=int(row[4] or 0),
            score_3=int(row[5] or 0),
            score_2=int(row[6] or 0),
            score_1=int(row[7] or 0),
        )
        for row in by_agent_q.all()
    ]

    # Recent low scores (1 or 2)
    low_q = await db.execute(
        select(QualitySample)
        .where(
            QualitySample.judged_at >= cutoff,
            QualitySample.score <= 2,
        )
        .order_by(QualitySample.judged_at.desc())
        .limit(50)
    )
    recent = [
        LowScoreSample(
            id=r.id, llm_call_id=r.llm_call_id, agent_name=r.agent_name,
            score=r.score, reason=r.reason, judged_at=r.judged_at,
        )
        for r in low_q.scalars().all()
    ]

    return QualityResponse(
        window_days=window_days, generated_at=now,
        by_agent=by_agent, recent_low_scores=recent,
    )
