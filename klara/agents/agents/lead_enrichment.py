"""
app/agents/lead_enrichment.py
───────────────────────────────
P2 agent — enriches a qualified lead with company size and tech stack
data before a discovery call, using public web signals and Claude inference.

Triggered by: Celery beat daily sweep task (finds qualified/discovery_done
  leads where call_prep_sent_at IS NOT NULL but enriched_at IS NULL),
  OR explicitly via POST /api/v1/agents/run with agent="lead_enrichment".

What "enrichment" means in this context:
  - This is an SMB IT consulting business. We don't have paid enrichment APIs
    (Clearbit, ZoomInfo). Instead, we use Claude to infer likely company size
    and tech stack from the data we already have: domain, company name,
    services interest, and optional message content.
  - The result is a *probabilistic inference*, not a data-verified lookup.
    It is clearly labelled as such in the output and in Anthony's briefing.

Output written to lead:
  - enriched_at: timestamp
  - company_size: e.g. "2–10 employees (inferred)"
  - tech_stack: JSON array of likely technologies

Permission: P2 — internal only, read + write to lead record. No external
  send. Claude inference is internal processing, not a third-party API.
"""
from __future__ import annotations

import json
import textwrap
from datetime import datetime, timezone

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from app.agents.base import BaseAgent, AgentContext, AgentResult, PermissionLevel
from app.models.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)

_ENRICH_PROMPT = textwrap.dedent("""\
You are an IT business analyst specialising in European SMBs and international
organisations based in Germany.

Analyse the following lead data and infer the most likely company size category
and current technology stack. Base your inference on the company name, email domain,
services they're interested in, and their message content.

Lead data:
  Company name:    {company}
  Email domain:    {domain}
  Services asked:  {services}
  Budget range:    {budget}
  Message excerpt: {message}

Return a JSON object with EXACTLY these two keys:
{{
  "company_size": "<one of: 1 employee, 2-10 employees, 11-50 employees, 51-200 employees, 200+ employees> (inferred)",
  "tech_stack": ["<technology 1>", "<technology 2>", ...]
}}

Rules:
- company_size must end with " (inferred)"
- tech_stack: list up to 5 likely current technologies (e.g. Google Workspace,
  on-prem Exchange, Sophos, Windows Server, HP/Dell hardware, etc.)
  Focus on what they CURRENTLY USE that Anthony will need to replace or integrate with.
- If there is not enough data to infer, use "unknown (inferred)" for company_size
  and an empty list for tech_stack.
- Return ONLY valid JSON. No markdown, no explanation.
""")


class LeadEnrichmentAgent(BaseAgent):
    name = "lead_enrichment"
    permission_level = PermissionLevel.P2
    description = (
        "Enriches qualified leads before discovery calls with inferred company size "
        "and likely tech stack using Claude Sonnet. Writes enriched_at, company_size, "
        "tech_stack to the lead record. Internal only — inference clearly labelled. "
        "P2 — read+write lead, no external send."
    )

    async def run(self, context: AgentContext, payload: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        # If called explicitly with a lead_id, enrich just that lead.
        # Otherwise sweep for eligible leads.
        explicit_lead_id = context.lead_id or payload.get("lead_id")

        if explicit_lead_id:
            lead = (await context.db.execute(
                select(Lead).where(Lead.id == explicit_lead_id)
            )).scalar_one_or_none()
            candidates = [lead] if lead else []
        else:
            candidates = (await context.db.execute(
                select(Lead)
                .where(Lead.status.in_([
                    LeadStatus.qualified,
                    LeadStatus.discovery_done,
                ]))
                .where(Lead.enriched_at.is_(None))
                .where(Lead.call_prep_sent_at.is_not(None))
                .where(Lead.email.is_not(None))
                .limit(20)  # Safety cap — don't burn tokens on huge batches
            )).scalars().all()

        if not candidates:
            log.info("lead_enrichment.no_candidates")
            return AgentResult.ok({"status": "no_candidates", "enriched": 0})

        log.info("lead_enrichment.candidates", count=len(candidates))

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        enriched_count = 0
        errors = []

        for lead in candidates:
            if lead.status == "anonymised":
                continue

            domain = ""
            if lead.email and "@" in lead.email:
                domain = lead.email.split("@")[1]

            message_excerpt = (lead.message or "")[:400]

            prompt = _ENRICH_PROMPT.format(
                company=lead.company or "Unknown",
                domain=domain or "unknown",
                services=lead.services_interest or "IT consulting",
                budget=lead.budget_range or "not specified",
                message=message_excerpt or "no message provided",
            )

            try:
                response = await client.messages.create(
                    model=context.settings.anthropic_model,
                    max_tokens=300,
                    messages=[{"role": "user", "content": prompt}],
                )
                try:
                    from app.services.llm_cost import track_response
                    await track_response(
                        context.db, agent_name=self.name,
                        model=context.settings.anthropic_model,
                        response=response, lead_id=getattr(context, 'lead_id', None),
                    )
                except Exception:
                    pass
                raw = response.content[0].text.strip()
            except Exception as exc:
                log.error("lead_enrichment.claude_error",
                          lead_id=lead.id, error=str(exc))
                errors.append(str(lead.id))
                continue

            # Parse JSON response
            company_size = None
            tech_stack_json = None
            try:
                parsed = json.loads(raw)
                company_size = str(parsed.get("company_size", ""))[:100]
                tech_stack = parsed.get("tech_stack", [])
                if isinstance(tech_stack, list):
                    tech_stack_json = json.dumps(tech_stack[:5])
                else:
                    tech_stack_json = "[]"
            except Exception:
                log.warning("lead_enrichment.json_parse_error",
                            lead_id=lead.id, raw=raw[:200])
                company_size = "parse error (inferred)"
                tech_stack_json = "[]"

            now = datetime.now(timezone.utc)
            lead_row = (await context.db.execute(
                select(Lead).where(Lead.id == lead.id)
            )).scalar_one_or_none()
            if lead_row:
                lead_row.enriched_at = now
                lead_row.company_size = company_size
                lead_row.tech_stack = tech_stack_json
                await context.db.flush()

            enriched_count += 1
            log.info("lead_enrichment.enriched",
                     lead_id=lead.id,
                     company_size=company_size,
                     tech_stack=tech_stack_json)

        return AgentResult.ok({
            "status": "done",
            "candidates": len(candidates),
            "enriched": enriched_count,
            "errors": errors,
        })
