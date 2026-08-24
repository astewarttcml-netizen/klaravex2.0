"""
app/agents/form_intake.py
─────────────────────────
Processes structured data from the WordPress contact form or
the /api/v1/leads endpoint.

Unlike chat_intake (open dialogue), form_intake receives a validated
schema and creates/updates the Lead record immediately.

Permission: P2 — creating a lead record is an internal write.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.lead import Lead, LeadSource, LeadStatus
from klara.rarv.runtime.known_problem_matcher import DEFAULT_AGENT_MIN_RANK, find_matches

logger = structlog.get_logger(__name__)


class FormIntakeAgent(BaseAgent):
    name = "form_intake"
    description = (
        "Creates or updates a Lead record from structured form data. "
        "Handles GDPR consent recording."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        Expected input_data keys:
          name, email, phone (optional), company (optional),
          message, services_interest (list), budget_range, timeline,
          gdpr_consent (bool, required), gdpr_consent_ip,
          source (default: contact_form)
        """
        email = input_data.get("email", "").strip().lower()
        gdpr_consent = input_data.get("gdpr_consent", False)

        if not email:
            return AgentResult.fail("form_intake: 'email' is required.")

        if not gdpr_consent:
            return AgentResult.fail(
                "GDPR consent is required. Please accept the privacy policy."
            )

        db = context.db

        # Upsert: if same email exists and is not yet qualified, update it
        result = await db.execute(
            select(Lead).where(Lead.email == email).limit(1)
        )
        lead = result.scalar_one_or_none()

        services = input_data.get("services_interest", [])
        services_json = json.dumps(services) if isinstance(services, list) else services

        if lead:
            # Update existing lead
            lead.name = input_data.get("name") or lead.name
            lead.phone = input_data.get("phone") or lead.phone
            lead.company = input_data.get("company") or lead.company
            lead.message = input_data.get("message") or lead.message
            lead.services_interest = services_json or lead.services_interest
            lead.budget_range = input_data.get("budget_range") or lead.budget_range
            lead.timeline = input_data.get("timeline") or lead.timeline
            logger.info("form_intake.updated_lead", lead_id=lead.id, email=email)
        else:
            lead = Lead(
                name=input_data.get("name"),
                email=email,
                phone=input_data.get("phone"),
                company=input_data.get("company"),
                message=input_data.get("message"),
                services_interest=services_json,
                budget_range=input_data.get("budget_range"),
                timeline=input_data.get("timeline"),
                source=input_data.get("source", LeadSource.contact_form),
                status=LeadStatus.new,
                gdpr_consent=True,
                gdpr_consent_timestamp=datetime.now(timezone.utc),
                gdpr_consent_ip=input_data.get("gdpr_consent_ip"),
            )
            db.add(lead)
            await db.flush()
            logger.info("form_intake.created_lead", lead_id=lead.id, email=email)

        context.lead_id = lead.id

        # Link lead to conversation if one exists
        if context.conversation_id:
            from klara.rarv.conversation import Conversation
            from sqlalchemy import update
            await db.execute(
                update(Conversation)
                .where(Conversation.id == context.conversation_id)
                .values(lead_id=lead.id)
            )

        # Know-How Library suggestions (prod-004 slice 2).
        # Match the visitor's free-text message against KnownProblem.search_vector
        # so the downstream agents and the operator inbox see "have we seen this
        # before?" matches. Failure here MUST NOT block the intake — a missing
        # FTS index in dev or a transient DB hiccup should leave the suggestion
        # list empty rather than fail the lead creation.
        knowledge_matches: list[dict] = []
        message_text = (input_data.get("message") or "").strip()
        if message_text:
            try:
                matches = await find_matches(
                    db, message_text, top_n=3, min_rank=DEFAULT_AGENT_MIN_RANK
                )
                knowledge_matches = [m.to_summary() for m in matches]
                if knowledge_matches:
                    logger.info(
                        "form_intake.knowledge_matches",
                        lead_id=lead.id,
                        match_count=len(knowledge_matches),
                        top_rank=knowledge_matches[0]["rank"],
                    )
            except Exception as exc:
                # Don't fail intake on a search backend issue.
                logger.warning(
                    "form_intake.knowledge_match_failed",
                    lead_id=lead.id,
                    error=str(exc),
                )

        return AgentResult.ok(
            output={
                "lead_id": lead.id,
                "email": email,
                "status": lead.status,
                "is_new": lead.id is not None,
                "knowledge_matches": knowledge_matches,
            }
        )
