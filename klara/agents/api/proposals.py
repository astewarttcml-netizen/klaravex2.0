"""
app/api/proposals.py
──────────────────────
Proposal management endpoints.

GET  /api/v1/proposals/              — list proposals (auth required)
GET  /api/v1/proposals/{id}          — get proposal with full markdown (auth required)
POST /api/v1/proposals/trigger       — manually request a proposal for a lead (creates P4 approval)

Typical flow (automated, via routing agent):
  1. HOT lead scored → routing.py creates ApprovalRequest(action_name="proposal_drafting.draft")
  2. Admin approves via /api/v1/approvals/{id}/approve
  3. approvals.py runs ProposalDraftingAgent, saves Proposal, emails consultant

Typical flow (manual, via this endpoint):
  1. POST /api/v1/proposals/trigger  {"lead_id": "...", "triggered_by": "admin@..."}
  2. Returns approval_id
  3. Admin approves via /api/v1/approvals/{id}/approve → same dispatch as above
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import AgentContext
from app.agents.registry import registry
from klara.rarv.runtime import get_settings, Settings
from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.proposal import Proposal

logger = structlog.get_logger(__name__)

router = APIRouter()


class TriggerProposalRequest(BaseModel):
    lead_id: str
    triggered_by: str         # email of the person requesting (for audit)
    note: Optional[str] = None


@router.get("/", dependencies=[Depends(verify_api_key)])
async def list_proposals(
    status_filter: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List generated proposals, newest first. Optionally filter by status."""
    query = select(Proposal).order_by(Proposal.created_at.desc()).limit(limit)
    if status_filter:
        query = query.where(Proposal.status == status_filter)
    result = await db.execute(query)
    proposals = result.scalars().all()
    return [
        {
            "id": p.id,
            "lead_id": p.lead_id,
            "company": p.company,
            "status": p.status,
            "tokens_used": p.tokens_used,
            "emailed_to": p.emailed_to,
            "emailed_at": p.emailed_at.isoformat() if p.emailed_at else None,
            "created_at": p.created_at.isoformat(),
        }
        for p in proposals
    ]


@router.get("/{proposal_id}", dependencies=[Depends(verify_api_key)])
async def get_proposal(proposal_id: str, db: AsyncSession = Depends(get_db)):
    """Get a proposal including full markdown content."""
    result = await db.execute(
        select(Proposal).where(Proposal.id == proposal_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    return {
        "id": p.id,
        "lead_id": p.lead_id,
        "company": p.company,
        "approval_id": p.approval_id,
        "proposal_markdown": p.proposal_markdown,
        "tokens_used": p.tokens_used,
        "status": p.status,
        "emailed_to": p.emailed_to,
        "emailed_at": p.emailed_at.isoformat() if p.emailed_at else None,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


@router.post("/trigger", dependencies=[Depends(verify_api_key)])
async def trigger_proposal(
    req: TriggerProposalRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Manually request a proposal draft for a lead.

    Creates a P4 ApprovalRequest. Approve it via
    POST /api/v1/approvals/{approval_id}/approve to generate and email the proposal.
    """
    context = AgentContext(
        db=db,
        settings=settings,
        lead_id=req.lead_id,
    )
    approval_mgr = registry.get("approval_manager")
    result = await approval_mgr(
        context,
        {
            "action": "create",
            "action_name": "proposal_drafting.draft",
            "risk_level": "P4",
            "payload": {
                "lead_id": req.lead_id,
                "triggered_by": req.triggered_by,
                "note": req.note,
            },
            "justification": (
                f"Manual proposal request by {req.triggered_by}"
                + (f": {req.note}" if req.note else "")
            ),
            "requested_by": "api.manual",
        },
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    logger.info(
        "proposals.trigger",
        lead_id=req.lead_id,
        approval_id=result.output["approval_id"],
        triggered_by=req.triggered_by,
    )

    return {
        "status": "pending_approval",
        "approval_id": result.output["approval_id"],
        "message": (
            "Proposal approval request created. "
            "Approve via POST /api/v1/approvals/{id}/approve to generate the proposal."
        ),
    }
