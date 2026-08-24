"""
app/services/proposal_trigger.py
─────────────────────────────────
phase5-001 — auto-queue a proposal_drafting.draft approval after
post_call_processor extracts structured notes from a discovery call.

Why a service (not a chained agent invocation):
  proposal_drafting is a P4 action — it MUST go through the approval
  gate before any draft hits the DB. So we create an ApprovalRequest
  with action='proposal_drafting.draft' and let the existing approval
  dispatch handle the actual draft generation + persistence.

Triggered only when lead_temperature is HOT or WARM. COLD calls don't
auto-trigger a proposal — the operator can still create one manually.

Idempotency:
  - skip if a Proposal row already exists for this lead
  - skip if a pending or approved proposal_drafting.draft ApprovalRequest
    already exists for this lead
"""
from __future__ import annotations

import json
from typing import Optional
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalRequest, ApprovalStatus, RiskLevel
from app.models.lead import Lead
from app.models.proposal import Proposal

logger = structlog.get_logger(__name__)


# Lead temperatures that trigger an auto-proposal. COLD = manual only.
_AUTO_TRIGGER_TEMPERATURES = frozenset({"HOT", "WARM"})


async def queue_proposal_draft(
    db: AsyncSession,
    lead: Lead,
    call_notes: dict,
) -> Optional[str]:
    """
    Create a proposal_drafting.draft ApprovalRequest if and only if:
      - lead_temperature is HOT or WARM
      - no Proposal row exists yet for this lead
      - no pending/approved proposal_drafting.draft ApprovalRequest exists

    Returns the new approval_id on success, None when skipped.
    """
    temperature = (call_notes or {}).get("lead_temperature") or ""
    if temperature.upper() not in _AUTO_TRIGGER_TEMPERATURES:
        logger.info(
            "proposal_trigger.skipped_temperature",
            lead_id=lead.id,
            temperature=temperature,
        )
        return None

    # Idempotency check 1: existing Proposal row
    proposal_q = await db.execute(
        select(Proposal.id).where(Proposal.lead_id == lead.id).limit(1)
    )
    if proposal_q.scalar_one_or_none() is not None:
        logger.info(
            "proposal_trigger.skipped_proposal_exists",
            lead_id=lead.id,
        )
        return None

    # Idempotency check 2: existing pending/approved approval request
    active_states = {
        ApprovalStatus.pending.value,
        ApprovalStatus.approved.value,
        ApprovalStatus.auto_approved.value,
    }
    approval_q = await db.execute(
        select(ApprovalRequest.id).where(
            ApprovalRequest.lead_id == lead.id,
            ApprovalRequest.action_name == "proposal_drafting.draft",
            ApprovalRequest.status.in_(list(active_states)),
        ).limit(1)
    )
    if approval_q.scalar_one_or_none() is not None:
        logger.info(
            "proposal_trigger.skipped_approval_exists",
            lead_id=lead.id,
        )
        return None

    # Build qualification dict from call_notes so the proposal draft has context.
    qualification = {
        "qualified": True,
        "lead_temperature": temperature.upper(),
        "pain_points": call_notes.get("pain_points", []),
        "services_confirmed": call_notes.get("services_confirmed", []),
        "budget_range": call_notes.get("budget_range"),
        "timeline": call_notes.get("timeline"),
        "summary": call_notes.get("summary"),
        "next_action": call_notes.get("next_action"),
    }

    approval_id = str(uuid4())
    approval = ApprovalRequest(
        id=approval_id,
        action_name="proposal_drafting.draft",
        risk_level=RiskLevel.p4.value,
        payload=json.dumps({
            "lead_id": lead.id,
            "qualification": qualification,
        }),
        justification=(
            f"Auto-queued after discovery call (temperature={temperature.upper()}). "
            f"Next action: {call_notes.get('next_action') or 'not specified'}."
        ),
        requested_by_agent="post_call_processor",
        lead_id=lead.id,
        status=ApprovalStatus.pending.value,
    )
    db.add(approval)
    await db.flush()

    logger.info(
        "proposal_trigger.queued",
        lead_id=lead.id,
        approval_id=approval_id,
        temperature=temperature.upper(),
    )
    return approval_id
