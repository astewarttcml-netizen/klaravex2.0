"""
app/api/freelance_admin.py
───────────────────────────
Admin endpoints for the freelance platform pipeline.

All routes require X-API-Key admin authentication.

Routes:
  GET  /api/v1/admin/freelance/projects         — list discovered projects
  GET  /api/v1/admin/freelance/projects/{id}    — get single project
  POST /api/v1/admin/freelance/scan             — manually trigger platform scan
  POST /api/v1/admin/freelance/analyse          — manually trigger bid strategy run

  GET  /api/v1/admin/freelance/bids             — list all bids
  GET  /api/v1/admin/freelance/bids/{id}        — get single bid
  POST /api/v1/admin/freelance/bids/{id}/mark-sent  — mark manual bid as submitted
  POST /api/v1/admin/freelance/bids/{id}/mark-won   — mark bid as won → trigger client converter
  POST /api/v1/admin/freelance/bids/{id}/call       — initiate Vapi.ai call to client

  GET  /api/v1/admin/freelance/stats            — today's pipeline stats
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.portal_auth import require_admin
from app.agents.base import AgentContext
from app.config import get_settings
from app.models.freelance_project import FreelanceProject, FreelanceProjectStatus
from app.models.platform_bid import PlatformBid, PlatformBidStatus

logger = structlog.get_logger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Projects
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/freelance/projects", tags=["admin-freelance"])
async def list_projects(
    platform: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    min_score: Optional[int] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    q = select(FreelanceProject).order_by(
        FreelanceProject.posted_at.desc().nullslast(),
        FreelanceProject.created_at.desc(),
    )
    if platform:
        q = q.where(FreelanceProject.platform == platform)
    if status:
        q = q.where(FreelanceProject.status == status)
    if min_score is not None:
        q = q.where(FreelanceProject.fit_score >= min_score)

    total_q = await db.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = total_q.scalar_one()

    result = await db.execute(q.limit(limit).offset(offset))
    projects = result.scalars().all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "projects": [_project_dict(p) for p in projects],
    }


@router.get("/admin/freelance/projects/{project_id}", tags=["admin-freelance"])
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    q = await db.execute(
        select(FreelanceProject).where(FreelanceProject.id == project_id)
    )
    project = q.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return _project_dict(project)


# ─────────────────────────────────────────────────────────────────────────────
# Manual triggers
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/admin/freelance/scan", tags=["admin-freelance"])
async def trigger_scan(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Manually trigger a platform scan (same as the scheduled Celery task)."""
    from app.tasks.freelance_tasks import run_platform_scan
    task = run_platform_scan.delay()
    logger.info("freelance_admin.scan_triggered", task_id=task.id)
    return {"task_id": task.id, "status": "queued", "message": "Platform scan queued"}


@router.post("/admin/freelance/analyse", tags=["admin-freelance"])
async def trigger_analyse(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Manually run BidStrategyAgent against all new projects."""
    from app.tasks.freelance_tasks import run_bid_strategy
    task = run_bid_strategy.delay()
    return {"task_id": task.id, "status": "queued", "message": "Bid strategy run queued"}


# ─────────────────────────────────────────────────────────────────────────────
# Bids
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/freelance/bids", tags=["admin-freelance"])
async def list_bids(
    platform: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    q = select(PlatformBid).order_by(PlatformBid.created_at.desc())
    if platform:
        q = q.where(PlatformBid.platform == platform)
    if status:
        q = q.where(PlatformBid.status == status)

    total_q = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_q.scalar_one()

    result = await db.execute(q.limit(limit).offset(offset))
    bids = result.scalars().all()

    # Enrich with project titles
    bid_dicts = []
    for bid in bids:
        d = _bid_dict(bid)
        proj_q = await db.execute(
            select(FreelanceProject.title, FreelanceProject.url, FreelanceProject.fit_score)
            .where(FreelanceProject.id == bid.project_id)
        )
        row = proj_q.first()
        if row:
            d["project_title"] = row[0]
            d["project_url"] = row[1]
            d["project_fit_score"] = row[2]
        bid_dicts.append(d)

    return {"total": total, "limit": limit, "offset": offset, "bids": bid_dicts}


@router.get("/admin/freelance/bids/{bid_id}", tags=["admin-freelance"])
async def get_bid(
    bid_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    q = await db.execute(select(PlatformBid).where(PlatformBid.id == bid_id))
    bid = q.scalar_one_or_none()
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")

    d = _bid_dict(bid)
    proj_q = await db.execute(
        select(FreelanceProject).where(FreelanceProject.id == bid.project_id)
    )
    project = proj_q.scalar_one_or_none()
    if project:
        d["project"] = _project_dict(project)
    return d


@router.post("/admin/freelance/bids/{bid_id}/mark-sent", tags=["admin-freelance"])
async def mark_bid_sent(
    bid_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Mark a manual-required bid as submitted after Anthony pastes it on the platform."""
    q = await db.execute(select(PlatformBid).where(PlatformBid.id == bid_id))
    bid = q.scalar_one_or_none()
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")

    bid.status = PlatformBidStatus.submitted
    bid.submitted_at = datetime.now(tz=timezone.utc)
    await db.commit()

    logger.info("freelance_admin.bid_marked_sent", bid_id=bid_id, platform=bid.platform)
    return {"bid_id": bid_id, "status": "submitted", "submitted_at": bid.submitted_at.isoformat()}


class MarkWonRequest(BaseModel):
    client_name: Optional[str] = None
    client_email: Optional[str] = None
    client_phone: Optional[str] = None


@router.post("/admin/freelance/bids/{bid_id}/mark-won", tags=["admin-freelance"])
async def mark_bid_won(
    bid_id: str,
    body: MarkWonRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Mark bid as won and fire PlatformClientConverterAgent to create Lead + onboard client."""
    settings = get_settings()
    ctx = AgentContext(db=db, settings=settings)

    from app.agents.platform_client_converter import PlatformClientConverterAgent
    agent = PlatformClientConverterAgent()
    result = await agent.run(
        ctx,
        {
            "bid_id": bid_id,
            "client_name": body.client_name,
            "client_email": body.client_email,
            "client_phone": body.client_phone,
        },
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return result.output


class InitiateCallRequest(BaseModel):
    phone_number: str
    client_name: Optional[str] = None
    language: str = "en"


@router.post("/admin/freelance/bids/{bid_id}/call", tags=["admin-freelance"])
async def initiate_call(
    bid_id: str,
    body: InitiateCallRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    """Initiate a Vapi.ai outbound call to the client associated with this bid."""
    # Load bid + project for context
    bid_q = await db.execute(select(PlatformBid).where(PlatformBid.id == bid_id))
    bid = bid_q.scalar_one_or_none()
    if not bid:
        raise HTTPException(status_code=404, detail="Bid not found")

    proj_q = await db.execute(
        select(FreelanceProject).where(FreelanceProject.id == bid.project_id)
    )
    project = proj_q.scalar_one_or_none()

    settings = get_settings()
    ctx = AgentContext(db=db, settings=settings, lead_id=bid.lead_id)

    from app.agents.voice_call_agent import VoiceCallAgent
    agent = VoiceCallAgent()
    result = await agent.run(
        ctx,
        {
            "phone_number": body.phone_number,
            "lead_id": bid.lead_id,
            "bid_id": bid_id,
            "client_name": body.client_name or project.client_name or "there",
            "project_title": project.title if project else "your project",
            "language": body.language,
        },
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return result.output


# ─────────────────────────────────────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/freelance/stats", tags=["admin-freelance"])
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    today_start = datetime.combine(date.today(), datetime.min.time()).replace(
        tzinfo=timezone.utc
    )

    # Project counts by status
    proj_counts_q = await db.execute(
        select(FreelanceProject.status, func.count(FreelanceProject.id))
        .group_by(FreelanceProject.status)
    )
    project_counts = {row[0]: row[1] for row in proj_counts_q.all()}

    # Bid counts by status
    bid_counts_q = await db.execute(
        select(PlatformBid.status, func.count(PlatformBid.id))
        .group_by(PlatformBid.status)
    )
    bid_counts = {row[0]: row[1] for row in bid_counts_q.all()}

    # Today's activity
    bids_today_q = await db.execute(
        select(func.count(PlatformBid.id)).where(
            PlatformBid.created_at >= today_start
        )
    )
    bids_today = bids_today_q.scalar_one()

    submitted_today_q = await db.execute(
        select(func.count(PlatformBid.id)).where(
            PlatformBid.status.in_(["submitted", "manual_required"]),
            PlatformBid.updated_at >= today_start,
        )
    )
    submitted_today = submitted_today_q.scalar_one()

    return {
        "projects": project_counts,
        "bids": bid_counts,
        "today": {
            "bids_generated": bids_today,
            "bids_submitted": submitted_today,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Serialisation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _project_dict(p: FreelanceProject) -> dict:
    return {
        "id": p.id,
        "platform": p.platform,
        "platform_id": p.platform_id,
        "title": p.title,
        "description": p.description,
        "skills_required": p.skills_required,
        "budget_min": float(p.budget_min) if p.budget_min is not None else None,
        "budget_max": float(p.budget_max) if p.budget_max is not None else None,
        "budget_type": p.budget_type,
        "budget_currency": p.budget_currency,
        "client_name": p.client_name,
        "client_location": p.client_location,
        "url": p.url,
        "posted_at": p.posted_at.isoformat() if p.posted_at else None,
        "proposals_count": p.proposals_count,
        "is_verified_client": p.is_verified_client,
        "fit_score": p.fit_score,
        "fit_rationale": p.fit_rationale,
        "status": p.status,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _bid_dict(b: PlatformBid) -> dict:
    return {
        "id": b.id,
        "project_id": b.project_id,
        "lead_id": b.lead_id,
        "platform": b.platform,
        "platform_bid_id": b.platform_bid_id,
        "cover_letter": b.cover_letter,
        "bid_amount": float(b.bid_amount) if b.bid_amount is not None else None,
        "bid_currency": b.bid_currency,
        "delivery_days": b.delivery_days,
        "status": b.status,
        "submit_error": b.submit_error,
        "vapi_call_id": b.vapi_call_id,
        "call_outcome": b.call_outcome,
        "call_completed_at": b.call_completed_at.isoformat() if b.call_completed_at else None,
        "submitted_at": b.submitted_at.isoformat() if b.submitted_at else None,
        "won_at": b.won_at.isoformat() if b.won_at else None,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }
