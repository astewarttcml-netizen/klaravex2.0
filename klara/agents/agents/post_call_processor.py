"""
app/agents/post_call_processor.py
──────────────────────────────────
P2 agent — processes discovery call notes submitted by Anthony after a
discovery/intro call with a prospect.

Triggered by: POST /api/v1/leads/{id}/call-notes  (admin API, X-API-Key)

Input (raw call notes from Anthony):
  {
    "raw_notes": "Had a call with Hans at Acme. He needs M365 tenant migration,
                  budget is €3-5k, wants done in 6 weeks. Hot lead, great fit."
  }

Output:
  - lead.call_notes updated with structured JSON:
      {
        "pain_points": [...],
        "budget_range": "...",
        "timeline": "...",
        "next_action": "...",
        "lead_temperature": "HOT|WARM|COLD",
        "confidence": "HIGH|MEDIUM|LOW",
        "summary": "..."
      }
  - lead.call_completed_at stamped
  - lead.status updated to "discovery_done"
  - lead.budget_range / lead.timeline updated if newly discovered
  - Returns structured output + recommended next action

Permission: P2 — reads and updates lead data, no external sends.
Claude model: claude-haiku-4-5-20251001 (fast, structured extraction task)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from klara.rarv.runtime import BaseAgent, AgentContext, AgentResult, PermissionLevel
from klara.rarv.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)

_EXTRACTION_PROMPT = """\
You are an assistant helping an IT consultant structure discovery call notes.

Extract structured information from the raw call notes below.

Raw notes:
{raw_notes}

Lead context (existing data):
  Name:             {name}
  Company:          {company}
  Original message: {message}
  Services:         {services}
  Current budget:   {budget}
  Current timeline: {timeline}

Return ONLY valid JSON (no markdown, no explanation) with this exact schema:
{{
  "pain_points": ["<string>", ...],
  "budget_range": "<string or null>",
  "timeline": "<string or null>",
  "services_confirmed": ["<string>", ...],
  "next_action": "<string>",
  "lead_temperature": "HOT|WARM|COLD",
  "confidence": "HIGH|MEDIUM|LOW",
  "summary": "<1-2 sentence summary of the call>"
}}

Rules:
- pain_points: list of specific problems the prospect mentioned
- budget_range: override existing if notes mention a figure, else keep null
- timeline: override existing if notes mention a timeframe, else keep null
- services_confirmed: services explicitly discussed on the call
- next_action: single most important next step Anthony should take
  (e.g., "Send proposal within 48h", "Send reference case studies", "Follow up in 2 weeks")
- lead_temperature: HOT = urgent/ready to buy, WARM = interested but slower,
  COLD = not a fit or very distant timeline
- confidence: HIGH = clear signals, MEDIUM = some ambiguity, LOW = unclear
"""


class PostCallProcessorAgent(BaseAgent):
    name = "post_call_processor"
    permission_level = PermissionLevel.P2
    description = (
        "Processes Anthony's raw discovery call notes for a lead. "
        "Extracts pain points, budget, timeline, lead temperature, and next action "
        "using Claude. Updates lead.call_notes, call_completed_at, and status → "
        "discovery_done. "
        "Triggered via POST /api/v1/leads/{id}/call-notes."
    )

    async def run(self, context: AgentContext, payload: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        lead_id = context.lead_id or payload.get("lead_id")
        raw_notes = (payload.get("raw_notes") or "").strip()

        if not lead_id:
            return AgentResult.fail("post_call_processor: 'lead_id' is required.")
        if not raw_notes:
            return AgentResult.fail("post_call_processor: 'raw_notes' is required.")
        if len(raw_notes) < 10:
            return AgentResult.fail("post_call_processor: notes are too short to be useful.")

        # Load lead
        result = await context.db.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()

        if not lead:
            return AgentResult.fail(f"Lead {lead_id} not found.")

        if lead.status == "anonymised":
            return AgentResult.fail("Cannot update anonymised lead.")

        log.info("post_call_processor.processing",
                 lead_id=lead_id, notes_length=len(raw_notes))

        # phase13-002: register prompt template for drift detection
        try:
            from klara.rarv.runtime.prompt_registry import register_prompt
            await register_prompt(
                context.db, agent_name=self.name,
                prompt_name="EXTRACTION_PROMPT",
                content=_EXTRACTION_PROMPT,
            )
        except Exception:
            pass

        # Extract structured data via Claude
        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        prompt = _EXTRACTION_PROMPT.format(
            raw_notes=raw_notes,
            name=lead.name or "Unknown",
            company=lead.company or "Unknown",
            message=lead.message or "(none)",
            services=lead.services_interest or "[]",
            budget=lead.budget_range or "(unknown)",
            timeline=lead.timeline or "(unknown)",
        )

        try:
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_json = response.content[0].text.strip()
            structured = json.loads(raw_json)
            from klara.rarv.runtime.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model="claude-haiku-4-5-20251001",
                response=response, lead_id=lead_id,
            )
        except json.JSONDecodeError as exc:
            log.error("post_call_processor.json_parse_error",
                      lead_id=lead_id, error=str(exc))
            return AgentResult.fail(f"Claude returned invalid JSON: {exc}")
        except Exception as exc:
            log.error("post_call_processor.claude_error",
                      lead_id=lead_id, error=str(exc))
            return AgentResult.fail(str(exc))

        now = datetime.now(timezone.utc)

        # Update lead record
        lead_row = (await context.db.execute(
            select(Lead).where(Lead.id == lead_id)
        )).scalar_one_or_none()

        if not lead_row:
            return AgentResult.fail(f"Lead {lead_id} disappeared during processing.")

        lead_row.call_notes = json.dumps(structured, ensure_ascii=False)
        lead_row.call_completed_at = now
        lead_row.status = LeadStatus.discovery_done

        # Update budget/timeline if Claude found better data
        if structured.get("budget_range"):
            lead_row.budget_range = structured["budget_range"]
        if structured.get("timeline"):
            lead_row.timeline = structured["timeline"]

        await context.db.flush()

        log.info(
            "post_call_processor.complete",
            lead_id=lead_id,
            temperature=structured.get("lead_temperature"),
            next_action=structured.get("next_action"),
            tokens=response.usage.output_tokens,
        )

        # phase5-001: auto-queue a proposal_drafting.draft approval for HOT/WARM
        # leads. The trigger service enforces idempotency and the existing P4
        # approval gate. Failures here MUST NOT roll back the post-call work.
        proposal_approval_id: str | None = None
        try:
            from klara.rarv.runtime.proposal_trigger import queue_proposal_draft
            proposal_approval_id = await queue_proposal_draft(
                context.db, lead_row, structured,
            )
        except Exception as exc:
            log.error(
                "post_call_processor.proposal_trigger_exception",
                lead_id=lead_id,
                error=str(exc),
            )

        output = {
            "lead_id": lead_id,
            "status": "discovery_done",
            "call_notes": structured,
            "lead_temperature": structured.get("lead_temperature"),
            "next_action": structured.get("next_action"),
            "summary": structured.get("summary"),
        }
        if proposal_approval_id:
            output["proposal_approval_id"] = proposal_approval_id
        return AgentResult.ok(output)
