"""
app/services/prospect_conversion.py
────────────────────────────────────
phase4-003 — promote an INTERESTED ProspectedLead to a qualified Lead row.

Triggered by ReplyIntentAgent when a classification meets the conversion
threshold (intent == INTERESTED and confidence >= CONVERSION_THRESHOLD).

What this service does:
  1. Idempotency check: if prospect.converted_lead_id is set, return the
     existing Lead — never create a duplicate.
  2. Threshold check: intent must be INTERESTED and confidence must be
     at or above 0.75. Below threshold returns None.
  3. Builds a Lead row with source='cold_outreach_reply' (new enum value)
     using the prospect's contact name, email, and company.
  4. Runs the existing lead_scoring agent on the new Lead so it gets a
     score + score_reason in the same row.
  5. Links back: prospect.converted_lead_id = new_lead.id.
  6. Writes an AuditLog entry (event_type='prospect.converted').

Permission level is P2 — internal write only, no outbound action.
"""
from __future__ import annotations

import json
from typing import Optional
from uuid import uuid4

import structlog

from app.agents.base import AgentContext
from app.agents.registry import registry
from app.models.lead import Lead, LeadSource, LeadStatus
from app.models.prospected_lead import ProspectedLead
from app.models.reply_classification import ReplyIntent

logger = structlog.get_logger(__name__)


# Minimum Claude confidence required to auto-promote an INTERESTED reply.
# Anything below this stays in the ProspectedLead funnel; Anthony can
# manually escalate via the dashboard.
CONVERSION_THRESHOLD = 0.75


def _company_size_estimate(employee_count: Optional[int]) -> str:
    """Map Apollo's numeric employee_count → the bucket lead_scoring expects."""
    if employee_count is None or employee_count <= 0:
        return ""
    if employee_count >= 500:
        return "500+"
    if employee_count >= 200:
        return "200-500"
    if employee_count >= 50:
        return "50-200"
    if employee_count >= 10:
        return "10-50"
    return "1-10"


_DM_KEYWORDS = (
    "ceo", "cto", "cfo", "coo", "cio",
    "founder", "owner", "principal",
    "geschäftsführer", "inhaber", "vorstand",
    "director", "head of", "vp ",
)


def _is_decision_maker(title: Optional[str]) -> bool:
    if not title:
        return False
    t = title.lower()
    return any(kw in t for kw in _DM_KEYWORDS)


def _synthesise_qualification(prospect: ProspectedLead) -> dict:
    """
    Build a qualification dict for lead_scoring. We don't have a Claude-grade
    qualification for cold-reply leads, but we have enough prospect metadata
    to compute a reasonable score.

    Defaults reflect that an INTERESTED reply is, by definition, a warm signal.
    """
    return {
        "qualified": True,
        "confidence": 0.85,
        "company_size_est": _company_size_estimate(prospect.employee_count),
        "services_fit": [],
        "decision_maker": _is_decision_maker(prospect.contact_title),
        "urgency": "1-3 months",
        "next_step": "Discovery call",
        "disqualify_reason": None,
    }


async def convert_to_lead(
    context: AgentContext,
    prospect: ProspectedLead,
    intent_result: dict,
) -> Optional[Lead]:
    """
    Promote the given ProspectedLead to a Lead row. Returns the Lead on
    success, None if conversion was skipped (wrong intent, low confidence,
    or already converted). All paths are idempotent.
    """
    intent = intent_result.get("intent")
    confidence = float(intent_result.get("confidence") or 0.0)

    # ── Gate: intent must be INTERESTED at or above the threshold ─────────
    if intent != ReplyIntent.INTERESTED:
        logger.info(
            "prospect_conversion.skipped_wrong_intent",
            prospect_id=prospect.id,
            intent=intent,
        )
        return None
    if confidence < CONVERSION_THRESHOLD:
        logger.info(
            "prospect_conversion.skipped_low_confidence",
            prospect_id=prospect.id,
            confidence=confidence,
            threshold=CONVERSION_THRESHOLD,
        )
        return None

    # ── Idempotency: existing converted_lead_id short-circuits ────────────
    if prospect.converted_lead_id:
        from sqlalchemy import select as sa_select
        result = await context.db.execute(
            sa_select(Lead).where(Lead.id == prospect.converted_lead_id)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            logger.info(
                "prospect_conversion.cached",
                prospect_id=prospect.id,
                lead_id=existing.id,
            )
            return existing
        # FK row vanished (SET NULL on Lead delete); fall through and recreate.

    # ── Build the Lead ────────────────────────────────────────────────────
    lead_id = str(uuid4())
    lead = Lead(
        id=lead_id,
        source=LeadSource.cold_outreach_reply.value,
        status=LeadStatus.new.value,
        name=prospect.contact_name or None,
        email=prospect.contact_email or None,
        company=prospect.company_name or None,
        message=(intent_result.get("summary") or None),
        gdpr_consent=True,  # the prospect replied to our email — implicit consent
    )
    context.db.add(lead)
    await context.db.flush()

    # ── Score the Lead via the existing lead_scoring agent ────────────────
    qualification = _synthesise_qualification(prospect)
    try:
        scoring_agent = registry.get("lead_scoring")
        scoring_ctx = AgentContext(
            db=context.db,
            settings=context.settings,
            lead_id=lead_id,
            request_id=context.request_id,
        )
        scoring_result = await scoring_agent(
            scoring_ctx,
            {"qualification": qualification, "lead_id": lead_id},
        )
        if not scoring_result.success:
            logger.warning(
                "prospect_conversion.scoring_failed",
                lead_id=lead_id,
                error=scoring_result.error,
            )
    except Exception as exc:
        # Scoring failure must NOT roll back the conversion — the Lead row
        # is what matters; score can be backfilled by the lead_scoring_refresh
        # batch agent on the next sweep.
        logger.error(
            "prospect_conversion.scoring_exception",
            lead_id=lead_id,
            error=str(exc),
        )

    # ── Link back ─────────────────────────────────────────────────────────
    prospect.converted_lead_id = lead_id
    await context.db.flush()

    # ── Audit trail ───────────────────────────────────────────────────────
    try:
        audit = registry.get("audit_logger")
        await audit(
            context,
            {
                "event_type": "prospect.converted",
                "agent_name": "reply_intent",
                "action_name": "prospect.converted",
                "details": {
                    "prospect_id": prospect.id,
                    "lead_id": lead_id,
                    "intent": intent,
                    "confidence": confidence,
                    "source": LeadSource.cold_outreach_reply.value,
                },
            },
        )
    except Exception as exc:
        # Audit failure must NOT roll back the conversion — log and move on.
        logger.error(
            "prospect_conversion.audit_exception",
            lead_id=lead_id,
            error=str(exc),
        )

    logger.info(
        "prospect_conversion.created",
        prospect_id=prospect.id,
        lead_id=lead_id,
        confidence=confidence,
    )
    return lead
