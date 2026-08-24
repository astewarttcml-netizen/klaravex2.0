"""
app/agents/proposal_drafting.py
────────────────────────────────
Generates a structured IT consulting proposal using Claude.

Permission: P4 — creates a document that will be sent to a client.
In production this action REQUIRES human approval before execution.
The approval gate is triggered by routing.py before this agent runs.

Once approved, the agent:
  1. Loads full lead + qualification data
  2. Calls Claude with a proposal generation prompt
  3. Returns the proposal as Markdown (to be rendered / emailed separately)
  4. Writing to a file or sending via email is a separate P3/P4 action
"""
from __future__ import annotations

import json

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.lead import Lead

logger = structlog.get_logger(__name__)

PROPOSAL_PROMPT = """\
You are a senior IT consultant at Klaravex writing a discovery call
follow-up proposal for a prospective client.

Write a professional, concise proposal in Markdown (~400–600 words) covering:

1. **Understanding Your Challenge**   — reflect back the client's stated needs
2. **Our Recommended Approach**       — map their needs to our specific services
3. **Why Klaravex**          — 3 concrete differentiators (English-first,
   Berlin-based, Microsoft Gold Partner capability, fast response SLA)
4. **Proposed Engagement**            — engagement phases with rough timelines
5. **Investment Overview**            — ranges only (e.g., "starting from €X/month"),
   never exact figures
6. **Next Steps**                     — clear call-to-action: schedule discovery call

Tone: professional, confident, not salesy. Avoid buzzwords.
GDPR: do not include personal contact details in the document body.

Client context:
{lead_context}
"""


class ProposalDraftingAgent(BaseAgent):
    name = "proposal_drafting"
    description = (
        "Generates a Markdown IT consulting proposal for a qualified lead. "
        "P4 — requires approval before execution in production."
    )
    permission_level = PermissionLevel.P4

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        lead_id = context.lead_id or input_data.get("lead_id")
        if not lead_id:
            return AgentResult.fail("proposal_drafting: 'lead_id' is required.")

        # Load lead
        result = await context.db.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()
        if not lead:
            return AgentResult.fail(f"Lead {lead_id} not found.")

        lead_context = {
            "company": lead.company or "Unknown",
            "message": lead.message or "",
            "services_interest": lead.services_interest or "[]",
            "budget_range": lead.budget_range or "Not specified",
            "timeline": lead.timeline or "Not specified",
            "score": lead.score,
            "score_reason": lead.score_reason,
            "qualification": input_data.get("qualification", {}),
        }

        # phase13-002: register prompt template for drift detection
        try:
            from app.services.prompt_registry import register_prompt
            await register_prompt(
                context.db, agent_name=self.name,
                prompt_name="PROPOSAL_PROMPT",
                content=PROPOSAL_PROMPT,
            )
        except Exception:
            pass

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            response = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": PROPOSAL_PROMPT.format(
                        lead_context=json.dumps(lead_context, indent=2)
                    ),
                }],
            )
            proposal_md = response.content[0].text
            from app.services.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=response, lead_id=lead_id,
            )
        except Exception as exc:
            logger.error("proposal_drafting.claude_error", error=str(exc))
            return AgentResult.fail(str(exc))

        logger.info(
            "proposal_drafting.complete",
            lead_id=lead_id,
            tokens=response.usage.output_tokens,
        )

        return AgentResult.ok(
            output={
                "proposal_markdown": proposal_md,
                "lead_id": lead_id,
                "company": lead.company,
                "tokens_used": response.usage.output_tokens,
            }
        )
