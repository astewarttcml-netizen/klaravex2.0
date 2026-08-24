"""
app/services/contract_trigger.py
─────────────────────────────────
phase6-001 — auto-queue a contract_generator approval after onboarding.

Triggered by the send_client_onboarding_email handler once the welcome
email is sent. Mirrors the proposal_trigger pattern from phase5-001:
this service creates a P4 ApprovalRequest with action='contract.send'
and lets the existing approval dispatch (or a future contract.send
handler) take it from there.

Idempotency: leads.contract_sent_at being set short-circuits the trigger.
A pending or approved 'contract.send' ApprovalRequest also blocks
re-firing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.approval import ApprovalRequest, ApprovalStatus, RiskLevel
from klara.rarv.lead import Lead

logger = structlog.get_logger(__name__)


async def queue_contract_draft(
    db: AsyncSession,
    lead: Lead,
) -> Optional[str]:
    """
    Create a contract.send ApprovalRequest if not already queued/sent.
    Returns the new approval_id on success, None when skipped.
    """
    if not lead.email:
        logger.info("contract_trigger.skipped_no_email", lead_id=lead.id)
        return None

    if lead.contract_sent_at is not None:
        logger.info("contract_trigger.skipped_already_sent", lead_id=lead.id)
        return None

    # Idempotency: an existing pending/approved contract approval for this lead
    active_states = {
        ApprovalStatus.pending.value,
        ApprovalStatus.approved.value,
        ApprovalStatus.auto_approved.value,
    }
    existing = await db.execute(
        select(ApprovalRequest.id).where(
            ApprovalRequest.lead_id == lead.id,
            ApprovalRequest.action_name == "contract.send",
            ApprovalRequest.status.in_(list(active_states)),
        ).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        logger.info("contract_trigger.skipped_approval_exists", lead_id=lead.id)
        return None

    approval_id = str(uuid4())
    approval = ApprovalRequest(
        id=approval_id,
        action_name="contract.send",
        risk_level=RiskLevel.p4.value,
        payload=json.dumps({
            "lead_id": lead.id,
            "to_email": lead.email,
            "to_name": lead.name or "",
            "company": lead.company or "",
        }),
        justification=(
            f"Auto-queued contract draft for {lead.email} after onboarding "
            f"email sent. P4 — legal document, always requires manual review."
        ),
        requested_by_agent="post_onboarding_trigger",
        lead_id=lead.id,
        status=ApprovalStatus.pending.value,
    )
    db.add(approval)

    # Stamp idempotency BEFORE the approval is approved — phase6-001 contract
    # of work is "we attempted to queue a contract". Subsequent runs see the
    # timestamp and short-circuit. If the approval is rejected later, an
    # operator can clear contract_sent_at to re-trigger.
    lead.contract_sent_at = datetime.now(timezone.utc)
    await db.flush()

    logger.info(
        "contract_trigger.queued",
        lead_id=lead.id,
        approval_id=approval_id,
    )
    return approval_id
