"""
app/api/proposals_admin.py
──────────────────────────
Admin endpoint for proposal lifecycle transitions (phase5-003).

  POST /api/v1/admin/proposals/{id}/mark-accepted
      Flip the proposal to accepted, advance the linked lead to won,
      and fire client_onboarding (which queues its own P3 approval).
      Idempotent.

  POST /api/v1/admin/proposals/{id}/mark-declined
      Flip the proposal to declined. Does not touch the lead status —
      operators can still revive a declined deal manually.

Requires X-API-Key.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentContext
from app.agents.registry import registry
from app.config import get_settings
from app.core.security import verify_api_key
from app.database import get_db
from app.models.lead import Lead, LeadStatus
from app.models.proposal import Proposal, ProposalStatus

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post("/{proposal_id}/mark-accepted", status_code=status.HTTP_200_OK)
async def mark_accepted(
    proposal_id: str,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> dict:
    pr = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    proposal = pr.scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")

    # Idempotency: re-accepting is a no-op if already accepted
    already_accepted = proposal.status == ProposalStatus.accepted.value

    if not already_accepted:
        proposal.status = ProposalStatus.accepted.value
        await db.flush()

    lead_q = await db.execute(select(Lead).where(Lead.id == proposal.lead_id))
    lead = lead_q.scalar_one_or_none()

    onboarding_approval_id: str | None = None
    if lead is not None and not already_accepted:
        # Advance the lead to won — same rule client_onboarding's existing
        # mark-won endpoint uses (it bails on anonymised leads).
        if lead.status != LeadStatus.anonymised.value:
            lead.status = LeadStatus.won.value
            await db.flush()

        # Fire the onboarding agent. It generates content + queues its own
        # P3 ApprovalRequest with action='send_client_onboarding_email' —
        # the existing execute_approved_action Celery task handles the send.
        # Failures here MUST NOT roll back the proposal acceptance.
        try:
            agent = registry.get("client_onboarding")
            ctx = AgentContext(db=db, settings=get_settings(), lead_id=lead.id)
            result = await agent(ctx, {"lead_id": lead.id})
            if result.approval_required and result.approval_id:
                onboarding_approval_id = result.approval_id
        except Exception as exc:
            logger.error(
                "proposals_admin.onboarding_trigger_failed",
                proposal_id=proposal_id,
                lead_id=lead.id,
                error=str(exc),
            )

    await db.commit()
    logger.info(
        "proposals_admin.marked_accepted",
        proposal_id=proposal_id,
        lead_id=proposal.lead_id,
        idempotent_skip=already_accepted,
        onboarding_approval_id=onboarding_approval_id,
    )
    return {
        "status": "accepted",
        "proposal_id": proposal_id,
        "lead_id": proposal.lead_id,
        "idempotent_skip": already_accepted,
        "onboarding_approval_id": onboarding_approval_id,
    }


@router.post("/{proposal_id}/mark-declined", status_code=status.HTTP_200_OK)
async def mark_declined(
    proposal_id: str,
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> dict:
    pr = await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    proposal = pr.scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status != ProposalStatus.declined.value:
        proposal.status = ProposalStatus.declined.value
        await db.commit()

    logger.info(
        "proposals_admin.marked_declined",
        proposal_id=proposal_id,
    )
    return {"status": "declined", "proposal_id": proposal_id}
