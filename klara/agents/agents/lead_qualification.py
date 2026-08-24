"""
app/agents/lead_qualification.py
──────────────────────────────────
Uses Claude to classify a lead against Klaravex's ICP
(Ideal Customer Profile) and extract structured qualification data.

ICP for Klaravex:
  - SME or mid-market in Berlin / DACH region (5–500 employees)
  - Uses or migrating to Microsoft 365 / Azure
  - Needs networking, security, or device management help
  - English-comfortable or international team
  - Has a decision maker involved

Outputs a structured qualification dict + QUALIFIED / DISQUALIFIED / NEEDS_MORE_INFO.
"""
from __future__ import annotations

import json

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.lead import Lead, LeadSource, LeadStatus

logger = structlog.get_logger(__name__)

QUALIFICATION_PROMPT = """\
You are a lead qualification specialist for Klaravex.

Given the information below, output a JSON object with these fields:
  qualified: bool          — true if this is a good ICP fit
  confidence: 0.0–1.0      — how confident are you in the qualification
  company_size_est: str    — "1-10" | "10-50" | "50-200" | "200-500" | "500+"
  services_fit: list[str]  — matching services from: azure, m365, intune, meraki, networking, security, ai_automation
  decision_maker: bool     — is the contact likely a decision maker?
  urgency: str             — "immediate" | "1-3 months" | "3-6 months" | "exploratory"
  disqualify_reason: str   — if qualified=false, brief reason; else null
  next_step: str           — recommended next action

Respond ONLY with valid JSON. No markdown fences.

Lead data:
{lead_data}
"""


class LeadQualificationAgent(BaseAgent):
    name = "lead_qualification"
    description = (
        "Classifies leads against Klaravex ICP using Claude. "
        "Updates the lead status in the database."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        lead_id = context.lead_id or input_data.get("lead_id")
        lead = None  # may be populated in the lead_id branch below

        # Build lead summary from either DB or input_data
        if lead_id:
            result = await context.db.execute(
                select(Lead).where(Lead.id == lead_id)
            )
            lead = result.scalar_one_or_none()
            if not lead:
                return AgentResult.fail(f"Lead {lead_id} not found.")
            lead_data = {
                "name": lead.name,
                "company": lead.company,
                "message": lead.message,
                "services_interest": lead.services_interest,
                "budget_range": lead.budget_range,
                "timeline": lead.timeline,
                "source": lead.source,
            }
        else:
            # Chat pipeline path — no Lead row exists yet.
            lead_data = {
                "message": input_data.get("message", ""),
                "company": input_data.get("company"),
                "services_interest": input_data.get("services_interest"),
                "name": input_data.get("visitor_name"),
                "email": input_data.get("visitor_email"),
            }

        # phase13-002: register prompt template for drift detection
        try:
            from app.services.prompt_registry import register_prompt
            await register_prompt(
                context.db, agent_name=self.name,
                prompt_name="QUALIFICATION_PROMPT",
                content=QUALIFICATION_PROMPT,
            )
        except Exception:
            pass

        # Call Claude for qualification
        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            response = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=512,
                messages=[{
                    "role": "user",
                    "content": QUALIFICATION_PROMPT.format(
                        lead_data=json.dumps(lead_data, indent=2)
                    )
                }],
            )
            qual = json.loads(response.content[0].text)
            from app.services.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=response, lead_id=lead_id,
            )
        except json.JSONDecodeError as exc:
            logger.error("lead_qualification.json_parse_error", error=str(exc))
            return AgentResult.fail(f"Could not parse qualification response: {exc}")
        except Exception as exc:
            logger.error("lead_qualification.claude_error", error=str(exc))
            return AgentResult.fail(str(exc))

        # ── Create Lead row for the chat pipeline path ────────────────────────
        # When a visitor chats, no Lead exists until qualification completes.
        # We create it here so that lead_scoring, outreach_email, routing,
        # lead_alert, and calendar_integration all receive a valid lead_id.
        # GDPR: policy_guard ran before this agent and verified consent.
        if not lead_id:
            new_lead = Lead(
                source=LeadSource.chat,
                status=(
                    LeadStatus.qualified if qual.get("qualified")
                    else LeadStatus.disqualified
                ),
                message=lead_data.get("message"),
                company=lead_data.get("company"),
                services_interest=json.dumps(qual.get("services_fit", [])),
                gdpr_consent=True,
            )
            # Stamp visitor identity if provided by the widget — never overwrite
            # data that was already present (guards against future code paths).
            visitor_name = input_data.get("visitor_name")
            visitor_email = input_data.get("visitor_email")
            if not new_lead.name and visitor_name:
                new_lead.name = visitor_name
            if not new_lead.email and visitor_email:
                new_lead.email = visitor_email
            context.db.add(new_lead)
            await context.db.flush()
            lead_id = new_lead.id
            # Propagate to all downstream agents in this pipeline run.
            context.lead_id = lead_id
            logger.info(
                "lead_qualification.lead_created",
                lead_id=lead_id,
                source="chat",
                qualified=qual.get("qualified"),
                has_visitor_name=bool(visitor_name),
                has_visitor_email=bool(visitor_email),
            )

        # ── Update status on existing leads (form / webhook paths) ────────────
        if lead is not None:
            lead.status = (
                LeadStatus.qualified if qual.get("qualified") else LeadStatus.disqualified
            )
            await context.db.flush()

        logger.info(
            "lead_qualification.complete",
            lead_id=lead_id,
            qualified=qual.get("qualified"),
            confidence=qual.get("confidence"),
        )

        return AgentResult.ok(output={"qualification": qual, "lead_id": lead_id})
