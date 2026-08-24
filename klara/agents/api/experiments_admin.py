"""
app/api/experiments_admin.py
─────────────────────────────
phase14-002 + phase14-005 — A/B experiment admin endpoints.

  GET /api/v1/admin/experiments                    list all experiments
  GET /api/v1/admin/experiments/{id}/results       per-arm aggregations
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.database import get_db
from app.models.experiments import Experiment, ExperimentArm, ExperimentAssignment

logger = structlog.get_logger(__name__)
router = APIRouter()


class ExperimentSummary(BaseModel):
    id: str
    name: str
    description: Optional[str]
    status: str
    created_at: datetime
    arm_count: int
    total_assignments: int


class ArmResult(BaseModel):
    id: str
    name: str
    weight: int
    assignments: int


class ExperimentResults(BaseModel):
    experiment: ExperimentSummary
    arms: List[ArmResult]


@router.get("", response_model=List[ExperimentSummary])
async def list_experiments(
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> List[ExperimentSummary]:
    exps_q = await db.execute(select(Experiment).order_by(Experiment.created_at.desc()))
    out: List[ExperimentSummary] = []
    for e in exps_q.scalars():
        arm_count_q = await db.execute(
            select(func.count(ExperimentArm.id)).where(ExperimentArm.experiment_id == e.id)
        )
        assign_count_q = await db.execute(
            select(func.count(ExperimentAssignment.id))
            .where(ExperimentAssignment.experiment_id == e.id)
        )
        out.append(ExperimentSummary(
            id=e.id, name=e.name, description=e.description, status=e.status,
            created_at=e.created_at,
            arm_count=int(arm_count_q.scalar() or 0),
            total_assignments=int(assign_count_q.scalar() or 0),
        ))
    return out


@router.get("/{experiment_id}/results", response_model=ExperimentResults)
async def experiment_results(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> ExperimentResults:
    exp_q = await db.execute(select(Experiment).where(Experiment.id == experiment_id))
    exp = exp_q.scalar_one_or_none()
    if exp is None:
        raise HTTPException(status_code=404, detail="Experiment not found")

    arms_q = await db.execute(
        select(ExperimentArm).where(ExperimentArm.experiment_id == experiment_id)
        .order_by(ExperimentArm.id)
    )
    arms = list(arms_q.scalars().all())

    arm_results: List[ArmResult] = []
    total_assignments = 0
    for a in arms:
        cnt_q = await db.execute(
            select(func.count(ExperimentAssignment.id))
            .where(ExperimentAssignment.arm_id == a.id)
        )
        cnt = int(cnt_q.scalar() or 0)
        total_assignments += cnt
        arm_results.append(ArmResult(
            id=a.id, name=a.name, weight=a.weight, assignments=cnt,
        ))

    summary = ExperimentSummary(
        id=exp.id, name=exp.name, description=exp.description, status=exp.status,
        created_at=exp.created_at,
        arm_count=len(arms),
        total_assignments=total_assignments,
    )

    return ExperimentResults(experiment=summary, arms=arm_results)
