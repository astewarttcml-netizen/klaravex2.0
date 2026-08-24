"""
app/api/deal_admin.py
──────────────────────
Admin endpoints for deal conversion actions.

POST /api/v1/admin/deals/{lead_id}/call-notes         — submit discovery call notes
POST /api/v1/admin/deals/{lead_id}/mark-won           — mark lead as won, trigger onboarding
POST /api/v1/admin/deals/{lead_id}/call-prep          — generate discovery call prep document
POST /api/v1/admin/deals/{lead_id}/generate-contract  — draft SoW/contract, queue for P4 approval

All endpoints require X-API-Key header (admin-only, nginx IP-restricted).
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.agents.base import AgentContext
from app.agents.registry import registry
from app.config import get_settings, Settings
from app.core.security import verify_api_key
from app.database import get_db
from app.models.lead import Lead

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class CallNotesRequest(BaseModel):
    raw_notes: str = Field(
        ...,
        min_length=10,
        max_length=5000,
        description="Anthony's raw discovery call notes — freeform text.",
    )


class MarkWonRequest(BaseModel):
    notes: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional internal notes about the deal close.",
    )


class CallPrepRequest(BaseModel):
    tier: Optional[str] = Field(
        "WARM",
        description="Lead temperature tier — HOT, WARM, or COLD.",
    )
    qualification: Optional[dict] = Field(
        None,
        description=(
            "Optional qualification dict from lead_qualification agent output. "
            "Keys: services_fit, urgency, company_size_est, decision_maker, confidence."
        ),
    )


class GenerateContractRequest(BaseModel):
    pass  # All data loaded from DB via lead_id; no extra payload required


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/{lead_id}/call-notes",
    dependencies=[Depends(verify_api_key)],
    summary="Submit discovery call notes for a lead",
)
async def submit_call_notes(
    lead_id: str,
    req: CallNotesRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Submit raw discovery call notes for a lead.

    Runs PostCallProcessorAgent (P2) which:
    - Extracts pain points, budget, timeline, next action via Claude
    - Updates lead.call_notes with structured JSON
    - Stamps lead.call_completed_at
    - Sets lead.status → discovery_done

    Returns structured call notes + recommended next action.
    """
    # Verify lead exists
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    if lead.status == "anonymised":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Cannot update anonymised lead.",
        )

    context = AgentContext(db=db, settings=settings, lead_id=lead_id)
    agent = registry.get("post_call_processor")
    if not agent:
        raise HTTPException(status_code=503, detail="post_call_processor agent not available.")

    result = await agent(context, {"raw_notes": req.raw_notes})

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error or "PostCallProcessorAgent failed.",
        )

    return {
        "lead_id": lead_id,
        "status": "discovery_done",
        "call_notes": result.output.get("call_notes"),
        "lead_temperature": result.output.get("lead_temperature"),
        "next_action": result.output.get("next_action"),
        "summary": result.output.get("summary"),
    }


@router.post(
    "/{lead_id}/mark-won",
    dependencies=[Depends(verify_api_key)],
    summary="Mark a lead as won and trigger client onboarding",
)
async def mark_won(
    lead_id: str,
    req: MarkWonRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Mark a lead as won.

    Runs ClientOnboardingAgent (P3) which:
    - Updates lead.status → won
    - Generates bilingual welcome email (EN/DE based on email domain)
    - Queues email for Anthony's approval via approval_manager
    - Stamps lead.onboarding_sent_at (idempotent)

    The approval request will appear in the approvals queue for action.
    """
    # Verify lead exists
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    if lead.status == "anonymised":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Cannot update anonymised lead.",
        )

    # Append optional notes to lead.notes
    # NOTE: `lead` is already tracked by `db` — mutate directly and flush.
    # Never wrap an injected AsyncSession in `async with db as session:` —
    # that calls __aexit__ which closes the session before AgentContext can use it.
    if req.notes:
        existing = lead.notes or ""
        lead.notes = f"{existing}\n[Deal won notes]: {req.notes}".strip()
        await db.flush()

    context = AgentContext(db=db, settings=settings, lead_id=lead_id)
    agent = registry.get("client_onboarding")
    if not agent:
        raise HTTPException(status_code=503, detail="client_onboarding agent not available.")

    result = await agent(context, {"lead_id": lead_id})

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error or "ClientOnboardingAgent failed.",
        )

    return {
        "lead_id": lead_id,
        "lead_status": "won",
        "onboarding_status": result.output.get("status"),
        "subject": result.output.get("subject"),
        "language": result.output.get("language"),
        "message": (
            "Onboarding email queued for approval."
            if result.output.get("status") == "queued_for_approval"
            else result.output.get("status")
        ),
    }


@router.post(
    "/{lead_id}/call-prep",
    dependencies=[Depends(verify_api_key)],
    summary="Generate a discovery call prep document for a lead",
)
async def generate_call_prep(
    lead_id: str,
    req: CallPrepRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Generate a structured discovery call prep document for a lead.

    Runs DiscoveryCallPrepAgent (P1) which produces:
    - 2-3 sentence lead summary
    - 5 tailored talking points / questions
    - Context flags (budget signals, urgency, decision-maker status)
    - Recommended call approach
    - Services focus list

    P1 — read-only, fires immediately with no approval gate.
    Useful immediately before a scheduled discovery call.
    """
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    if lead.status == "anonymised":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Cannot generate call prep for anonymised lead.",
        )

    context = AgentContext(db=db, settings=settings, lead_id=lead_id)
    agent = registry.get("discovery_call_prep")
    if not agent:
        raise HTTPException(status_code=503, detail="discovery_call_prep agent not available.")

    agent_input = {
        "lead_id": lead_id,
        "tier": req.tier or "WARM",
        "qualification": req.qualification or {},
    }
    result = await agent(context, agent_input)

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error or "DiscoveryCallPrepAgent failed.",
        )

    return {
        "lead_id": lead_id,
        "lead_name": result.output.get("lead_name"),
        "lead_company": result.output.get("lead_company"),
        "summary": result.output.get("summary"),
        "talking_points": result.output.get("talking_points"),
        "context_flags": result.output.get("context_flags"),
        "recommended_approach": result.output.get("recommended_approach"),
        "services_focus": result.output.get("services_focus"),
    }


@router.post(
    "/{lead_id}/generate-contract",
    dependencies=[Depends(verify_api_key)],
    summary="Draft a SoW/contract for a lead and queue for P4 approval",
)
async def generate_contract(
    lead_id: str,
    req: GenerateContractRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Draft a Statement of Work / Service Contract for a won lead.

    Runs ContractGeneratorAgent (P4) which:
    - Loads lead data and latest proposal (if any)
    - Drafts a bilingual SoW in EN or DE based on email domain
    - Includes Scope, Deliverables, Timeline, Payment Terms,
      GDPR Art. 28 clause, Confidentiality, and Governing Law (Germany)
    - Queues the draft for Anthony's P4 approval before it can be sent

    P4 — always requires Anthony's manual review and approval.
    The draft will appear in the approvals queue. Lead must be won or
    discovery_done status to proceed.
    """
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    if lead.status == "anonymised":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Cannot generate contract for anonymised lead.",
        )

    context = AgentContext(db=db, settings=settings, lead_id=lead_id)
    agent = registry.get("contract_generator")
    if not agent:
        raise HTTPException(status_code=503, detail="contract_generator agent not available.")

    result = await agent(context, {"lead_id": lead_id})

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error or "ContractGeneratorAgent failed.",
        )

    return {
        "lead_id": lead_id,
        "status": result.output.get("status"),
        "language": result.output.get("language"),
        "proposal_ref": result.output.get("proposal_ref"),
        "contract_preview": result.output.get("contract_preview"),
        "tokens_used": result.output.get("tokens_used"),
        "message": "Contract draft queued for P4 approval. Review it in the approvals queue.",
    }
