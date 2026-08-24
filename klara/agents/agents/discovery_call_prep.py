"""
app/agents/discovery_call_prep.py
──────────────────────────────────
DiscoveryCallPrepAgent — P1 read-only intelligence.

Generates a structured call preparation document for Anthony before a
discovery call with a HOT/WARM lead.

Input:  lead_id (required), qualification dict (optional)
Output: summary, 5 talking points, context flags, recommended approach,
        services focus — all specific to this lead.

Permission: P1 — read-only, no external side-effects.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.lead import Lead

logger = structlog.get_logger(__name__)

_PREP_PROMPT = """\
You are an assistant helping Anthony Stewart, an IT consultant in Berlin,
prepare for a discovery call with a potential client.

Lead details:
  Name:           {name}
  Company:        {company}
  Email:          {email}
  Score:          {score}/100 ({tier})
  Enquiry:        {message}
  Services:       {services}
  Urgency:        {urgency}
  Company size:   {company_size}
  Decision maker: {decision_maker}
  Confidence:     {confidence}

Anthony's expertise: Azure, Entra ID, Intune, Meraki, VMware, M365,
PowerShell, IT security, hybrid cloud infrastructure, enterprise IT consulting.

Produce a call prep document in JSON with these exact keys:
{{
  "summary": "<2-3 sentence overview of who this lead is and what they need>",
  "talking_points": ["<question or topic 1>", "<q2>", "<q3>", "<q4>", "<q5>"],
  "context_flags": ["<flag 1>", "<flag 2>"],
  "recommended_approach": "<one paragraph on how to position this call>",
  "services_focus": ["<service 1>", "<service 2>"]
}}

Be specific to this lead. Output valid JSON only.
"""


class DiscoveryCallPrepAgent(BaseAgent):
    name = "discovery_call_prep"
    description = (
        "Generates a structured discovery-call prep doc: summary, 5 talking points, "
        "context flags, recommended approach, and services focus — all specific to "
        "the given lead. P1 — read-only, no external side-effects."
    )
    permission_level = PermissionLevel.P1

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        lead_id = input_data.get("lead_id") or context.lead_id
        if not lead_id:
            return AgentResult.fail("discovery_call_prep: lead_id required", agent=self.name)

        result = await context.db.execute(select(Lead).where(Lead.id == lead_id))
        lead: Lead | None = result.scalar_one_or_none()
        if not lead:
            return AgentResult.fail("discovery_call_prep: lead not found", agent=self.name)

        qual = input_data.get("qualification", {})
        prompt = _PREP_PROMPT.format(
            name=lead.name or "Unknown",
            company=lead.company or "Unknown",
            email=lead.email or "Unknown",
            score=int(lead.score or 0),
            tier=input_data.get("tier", "WARM"),
            message=(lead.message or "")[:400],
            services=qual.get("services_fit") or lead.services_interest or "Not specified",
            urgency=qual.get("urgency") or lead.timeline or "Not specified",
            company_size=qual.get("company_size_est") or "Unknown",
            decision_maker="Yes" if qual.get("decision_maker") else "Unknown",
            confidence=f"{int((qual.get('confidence') or 0) * 100)}%",
        )

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            from app.services.prompt_registry import register_prompt
            await register_prompt(
                context.db, agent_name=self.name,
                prompt_name="_PREP_PROMPT",
                content=str(_PREP_PROMPT),
            )
        except Exception:
            pass

        try:
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.rsplit("```", 1)[0].strip()
            prep = json.loads(raw)
            from app.services.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model="claude-haiku-4-5-20251001",
                response=response, lead_id=context.lead_id,
            )
        except json.JSONDecodeError as exc:
            logger.error("discovery_call_prep.json_error", error=str(exc))
            return AgentResult.fail(f"discovery_call_prep: JSON parse error — {exc}", agent=self.name)
        except Exception as exc:
            logger.error("discovery_call_prep.claude_error", error=str(exc))
            return AgentResult.fail(f"discovery_call_prep: LLM error — {exc}", agent=self.name)

        # Stamp call_prep_sent_at so LeadEnrichmentAgent knows to sweep this lead
        if lead.call_prep_sent_at is None:
            lead.call_prep_sent_at = datetime.now(timezone.utc)
            await context.db.flush()

        logger.info("discovery_call_prep.done", lead_id=lead_id, agent=self.name)
        return AgentResult.ok(
            output={"lead_id": lead_id, "lead_name": lead.name, "lead_company": lead.company, **prep},
            agent=self.name,
        )
