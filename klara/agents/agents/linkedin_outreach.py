"""
app/agents/linkedin_outreach.py
────────────────────────────────
phase20-002 — LinkedIn InMail draft generator.

P3 — drafts a LinkedIn outreach message for a ProspectedLead with a
contact_linkedin URL. Output is capped at LinkedIn's 300-char InMail
limit (or 200 for non-InMail messages — we target the more permissive
InMail format and let Anthony trim).

The agent does NOT send. Output is persisted to linkedin_drafts and
surfaced in the admin dashboard for Anthony to copy-paste into LinkedIn
manually. ToS-friendly, no LinkedIn API needed.

Idempotency: UNIQUE(prospected_lead_id) on linkedin_drafts. Re-running
for the same prospect returns the existing row.
"""
from __future__ import annotations

import json
from uuid import uuid4
from typing import Optional

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.linkedin_draft import LinkedinDraft, LinkedinDraftStatus
from klara.rarv.prospected_lead import ProspectedLead

logger = structlog.get_logger(__name__)


DRAFT_PROMPT = """\
You are Anthony Stewart writing a LinkedIn InMail to a cold prospect.

Rules:
  - Maximum 280 characters (InMail is 300; leave margin)
  - One-sentence personalisation hook based on the prospect's company/title
  - One value-prop sentence about Klaravex (M365/Azure/Intune)
  - One soft CTA — propose a 15-min call (NOT "30 minutes" — InMail is shorter ask)
  - Sign off: "—Anthony"
  - Do NOT include "Hi {{name}}" greetings — InMail header already shows the name
  - Plain text only, no emoji, no formatting

Output ONLY JSON: {{"body": "..."}}

Prospect:
  Company:  {company}
  Title:    {title}
  Industry: {industry}
  Signal:   {signal}
"""


class LinkedinOutreachAgent(BaseAgent):
    name = "linkedin_outreach"
    description = (
        "Drafts a LinkedIn InMail message for a ProspectedLead. P3 — output "
        "is persisted but Anthony sends manually (no LinkedIn API). "
        "Idempotent — one draft per prospect."
    )
    permission_level = PermissionLevel.P3

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        prospect_id = input_data.get("prospect_id")
        if not prospect_id:
            return AgentResult.fail("Missing prospect_id")

        # Idempotency: existing draft?
        existing_q = await context.db.execute(
            select(LinkedinDraft).where(LinkedinDraft.prospected_lead_id == prospect_id)
        )
        existing = existing_q.scalar_one_or_none()
        if existing is not None:
            return AgentResult.ok(output={
                "id": existing.id,
                "prospect_id": prospect_id,
                "body": existing.draft_body,
                "status": existing.status,
                "cached": True,
            })

        prospect_q = await context.db.execute(
            select(ProspectedLead).where(ProspectedLead.id == prospect_id)
        )
        prospect = prospect_q.scalar_one_or_none()
        if prospect is None:
            return AgentResult.fail(f"ProspectedLead {prospect_id} not found")
        if not prospect.contact_linkedin:
            return AgentResult.fail("Prospect has no contact_linkedin URL")

        prompt = DRAFT_PROMPT.format(
            company=prospect.company_name or prospect.domain,
            title=prospect.contact_title or "",
            industry=prospect.industry or "technology",
            signal=prospect.signal or "Berlin-based IT modernisation candidate",
        )

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        model_name = context.settings.anthropic_model
        try:
            response = await client.messages.create(
                model=model_name, max_tokens=400, temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            parsed = json.loads(raw)
            from klara.rarv.runtime.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name, model=model_name,
                response=response, lead_id=prospect_id,
            )
        except Exception as exc:
            logger.error("linkedin_outreach.claude_error", error=str(exc), prospect_id=prospect_id)
            return AgentResult.fail(str(exc))

        body = (parsed.get("body") or "").strip()
        if not body:
            return AgentResult.fail("Claude returned empty body")
        body = body[:300]   # hard cap

        draft = LinkedinDraft(
            id=str(uuid4()),
            prospected_lead_id=prospect_id,
            draft_body=body,
            status=LinkedinDraftStatus.draft,
            model=model_name,
        )
        context.db.add(draft)
        await context.db.flush()

        logger.info("linkedin_outreach.drafted", prospect_id=prospect_id, length=len(body))
        return AgentResult.ok(output={
            "id": draft.id, "prospect_id": prospect_id, "body": body,
            "status": draft.status, "cached": False,
        })
