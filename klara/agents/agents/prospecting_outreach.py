"""
app/agents/prospecting_outreach.py
────────────────────────────────────
ProspectingOutreachAgent (P3) — cold email drafting for outbound prospects.

Called by the prospect_leads Celery task after LeadProspectorAgent creates a
ProspectedLead record.

Flow:
  1. Load ProspectedLead from DB (by prospect_id in input_data).
  2. Validate the record is actionable (status == new, has contact_email).
  3. Call Claude to draft a personalised cold email:
       - ≤ 150 words, American English
       - References company name, industry, employee size, and signal
       - Single CTA: book a 30-minute call via Calendly
  4. Store the draft subject in ProspectedLead.outreach_subject.
  5. Create a P3 ApprovalRequest (action: prospecting_outreach.send) with the
     full email payload so the dashboard can preview and Anthony can one-click send.
  6. Set ProspectedLead.status = outreach_queued.

On failure:
  - Sets ProspectedLead.status = draft_failed.
  - Returns AgentResult.fail() so the Celery task can log and continue.

Permissions:
  - P3 — approval always required before the email is sent.
  - The agent only creates the draft; actual send happens in approvals.py.
"""
from __future__ import annotations

import json
import re
from typing import Optional

import httpx
import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.prospected_lead import ProspectedLead, ProspectedLeadStatus

logger = structlog.get_logger(__name__)

# ── Cold email prompt ─────────────────────────────────────────────────────────

_PROMPT = """\
You are Anthony Stewart, a senior IT consultant at Klaravex.
You specialise in Microsoft 365, Azure, Intune, and network security for
companies and businesses in the DACH region and internationally.

Draft a short, personalised cold outreach email to a potential client.

LANGUAGE SELECTION — apply this rule strictly:
- Look at the contact_title field.
- If the title contains "Leiter", "Geschäftsführer", "Prokurist", "Vorstand",
  or any other clearly German word → write the ENTIRE email in German, using
  the formal "Sie" form throughout (subject, body_text, body_html).
- Otherwise (English titles like "Head of IT", "CIO", "CTO", "IT Director",
  "IT Manager") → write in American English. The prospect signals their
  preferred business language through how they describe their own role.
- Do NOT mix languages within an email. Pick one based on the title above.
- Country alone does NOT determine language — title does.

Rules — follow all of them exactly:
- Length: ≤ 150 words in the body (not counting subject). Count carefully.
- Tone: direct, warm, peer-to-peer — NOT marketing copy. Write like a senior
  consultant reaching out, not a salesperson.
- Personalisation: weave in the company name, their industry or size, and the
  prospecting signal. Do not mention the signal verbatim — turn it into a
  natural sentence.
- Single CTA: invite them to book a free 30-minute call (German: "30-minütigen
  Gesprächstermin"). Include this URL exactly as given: {booking_url}
- No pricing. No bullet points. No buzzwords (German: keine Marketing-Floskeln).
- Opening (English): use the contact's first name if available, otherwise "Hi there,"
- Opening (German): "Sehr geehrter Herr <Nachname>," / "Sehr geehrte Frau <Nachname>,"
  — use first_name only if last_name unavailable, then fall back to "Sehr geehrte Damen und Herren,"
- Sign-off (English): "Best,\nAnthony\nKlaravex\nanthony@klaravex.de"
- Sign-off (German): "Mit freundlichen Grüßen\nAnthony Stewart\nKlaravex\nanthony@klaravex.de"

Prospect data:
{prospect_json}

Return ONLY valid JSON with exactly these three keys:
{{
  "subject": "<compelling subject line, ≤ 60 chars>",
  "body_text": "<plain text body with \\n line breaks>",
  "body_html": "<HTML body — use <p> tags only, no <html>/<head>/<body>>"
}}
"""


class ProspectingOutreachAgent(BaseAgent):
    name = "prospecting_outreach"
    description = (
        "Drafts a personalised cold outreach email (≤150 words, German for DACH "
        "prospects / English otherwise) for a ProspectedLead via Claude. Creates "
        "a P3 ApprovalRequest for Anthony to review before the email is sent. "
        "Sets status to outreach_queued on success."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        prospect_id: Optional[str] = input_data.get("prospect_id")
        if not prospect_id:
            return AgentResult.fail("prospecting_outreach: 'prospect_id' is required.")

        # ── Load prospect ─────────────────────────────────────────────────────
        result = await context.db.execute(
            select(ProspectedLead).where(ProspectedLead.id == prospect_id)
        )
        prospect = result.scalar_one_or_none()
        if not prospect:
            return AgentResult.fail(f"ProspectedLead {prospect_id} not found.")

        if prospect.status != ProspectedLeadStatus.new:
            logger.info(
                "prospecting_outreach.skipped",
                prospect_id=prospect_id,
                status=prospect.status,
                reason="already processed",
            )
            return AgentResult.ok(output={"skipped": True, "status": prospect.status})

        if not prospect.contact_email:
            logger.warning(
                "prospecting_outreach.no_email",
                prospect_id=prospect_id,
                domain=prospect.domain,
            )
            prospect.status = ProspectedLeadStatus.draft_failed
            await context.db.flush()
            return AgentResult.fail(f"No contact email for prospect {prospect.domain}.")

        # ── Build prompt context ──────────────────────────────────────────────
        prospect_data = {
            "company_name": prospect.company_name or prospect.domain,
            "domain": prospect.domain,
            "industry": prospect.industry or "technology",
            "employee_count": prospect.employee_count,
            "city": prospect.city or "Berlin",
            "contact_first_name": prospect.contact_first_name or "",
            "contact_last_name": prospect.contact_last_name or "",
            "contact_title": prospect.contact_title or "",
            "signal": prospect.signal or f"Berlin-based {prospect.industry or 'company'}",
        }

        booking_url = getattr(context.settings, "booking_url", "https://calendly.com/klaravex/45-minute-meeting")

        prompt = _PROMPT.format(
            booking_url=booking_url,
            prospect_json=json.dumps(prospect_data, ensure_ascii=False, indent=2),
        )

        # phase15-001: A/B variant hint appended to prompt. assign_arm is
        # deterministic per prospect_id — subsequent runs get the same arm.
        try:
            from app.services.outreach_experiment import variant_hint_for
            hint = await variant_hint_for(context.db, prospect_id)
            if hint:
                prompt = prompt + "\n\n" + hint
        except Exception:
            pass

        # ── Draft via Claude ──────────────────────────────────────────────────
        # Explicit per-request timeouts prevent the entire prospect_leads
        # batch from hanging on a single stalled connection.
        client = AsyncAnthropic(
            api_key=context.settings.anthropic_api_key,
            timeout=httpx.Timeout(60.0, connect=10.0),
            max_retries=2,
        )
        try:
            from app.services.prompt_registry import register_prompt
            await register_prompt(
                context.db, agent_name=self.name,
                prompt_name="_PROMPT",
                content=str(_PROMPT),
            )
        except Exception:
            pass

        try:
            response = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            from app.services.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=response, lead_id=prospect_id,
            )
        except Exception as exc:
            logger.error(
                "prospecting_outreach.claude_error",
                prospect_id=prospect_id,
                error=str(exc),
            )
            prospect.status = ProspectedLeadStatus.draft_failed
            await context.db.flush()
            return AgentResult.fail(str(exc))

        # ── Parse JSON ────────────────────────────────────────────────────────
        draft = _parse_json(raw)
        if not draft:
            logger.error(
                "prospecting_outreach.parse_error",
                prospect_id=prospect_id,
                raw=raw[:300],
            )
            prospect.status = ProspectedLeadStatus.draft_failed
            await context.db.flush()
            return AgentResult.fail("Could not parse email draft from Claude response.")

        subject = draft.get("subject", "Quick question — IT for your Berlin team")
        body_text = draft.get("body_text", "")
        body_html = draft.get("body_html", "")

        # ── Placeholder lint (catches LLM template leaks before queue) ────────
        from app.services.draft_validator import (
            DraftValidationError,
            validate_no_placeholders,
        )
        try:
            validate_no_placeholders(
                agent_name=self.name,
                fields={"subject": subject, "body_text": body_text, "body_html": body_html},
            )
        except DraftValidationError as exc:
            logger.error(
                "prospecting_outreach.placeholder_lint_failed",
                prospect_id=prospect_id,
                violations=exc.field_violations,
            )
            prospect.status = ProspectedLeadStatus.draft_failed
            await context.db.flush()
            return AgentResult.fail(str(exc))

        # ── Persist subject to prospect record ────────────────────────────────
        prospect.outreach_subject = subject

        # ── Create P3 approval request ────────────────────────────────────────
        from app.agents.registry import registry
        approval_mgr = registry.get("approval_manager")

        contact_display = prospect.contact_name or prospect.contact_email
        company_display = prospect.company_name or prospect.domain

        approval_payload = {
            "prospect_id": str(prospect.id),
            "domain": prospect.domain,
            "company_name": company_display,
            "contact_name": contact_display,
            "contact_email": prospect.contact_email,
            "contact_title": prospect.contact_title or "",
            "signal": prospect.signal or "",
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
            "tokens_used": response.usage.output_tokens,
        }

        approval_result = await approval_mgr(
            context,
            {
                "action": "create",
                "action_name": "prospecting_outreach.send",
                "risk_level": "P3",
                "payload": approval_payload,
                "justification": (
                    f"Cold outreach to {contact_display} ({prospect.contact_title or 'unknown title'}) "
                    f"at {company_display} — {prospect.signal or 'Berlin ICP match'}."
                ),
                "requested_by": self.name,
            },
        )

        if not approval_result.success:
            prospect.status = ProspectedLeadStatus.draft_failed
            await context.db.flush()
            return AgentResult.fail(
                f"Failed to create approval request: {approval_result.error}"
            )

        approval_id = approval_result.output["approval_id"]

        # ── Update status + link draft back to prospect record ────────────────
        prospect.status = ProspectedLeadStatus.outreach_queued
        prospect.outreach_draft = body_text          # plain text for quick preview
        prospect.approval_id = str(approval_id)      # FK link for dashboard lookup
        await context.db.flush()

        logger.info(
            "prospecting_outreach.queued",
            approval_id=approval_id,
            prospect_id=prospect_id,
            domain=prospect.domain,
            company=company_display,
            subject=subject,
            tokens_used=response.usage.output_tokens,
        )

        return AgentResult.ok(
            output={
                "status": "outreach_queued",
                "approval_id": approval_id,
                "prospect_id": str(prospect.id),
                "domain": prospect.domain,
                "company": company_display,
                "subject": subject,
                "tokens_used": response.usage.output_tokens,
            }
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict | None:
    """Extract first JSON object from Claude's response."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None
