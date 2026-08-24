"""
app/agents/reply_draft.py
──────────────────────────
ReplyDraftAgent (phase4-002) — P3, requires human approval before send.

Consumes ReplyClassification output and produces an intent-aware draft
response. The draft is stored in reply_drafts with status='pending' and
a paired ApprovalRequest row (action='reply_draft.send') is created so
Anthony can review and approve before anything goes out.

Per-intent templates:
  INTERESTED    → propose a 30-min discovery call + Calendly link
  NOT_NOW       → thank, ask to revisit at the suggested time
  WRONG_PERSON  → polite request for the right contact
  OTHER         → generic clarifying question, marked for manual review
  OUT_OF_OFFICE → SKIPPED (phase4-004 reschedule handles this)
  UNSUBSCRIBE   → SKIPPED (phase4-005 suppression handles this)

Idempotency: the UNIQUE index on reply_drafts.prospected_lead_id +
this agent's lookup-before-insert pattern ensure exactly one draft per
prospect. Concurrent webhook deliveries cannot create duplicates.
"""
from __future__ import annotations

import json
from typing import Any, Optional
from uuid import uuid4

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.approval import ApprovalRequest, ApprovalStatus, RiskLevel
from app.models.prospected_lead import ProspectedLead
from app.models.reply_classification import ReplyClassification, ReplyIntent
from app.models.reply_draft import ReplyDraft, ReplyDraftStatus

logger = structlog.get_logger(__name__)


# Intents we do NOT draft for. OOO is handled by phase4-004 reschedule;
# UNSUBSCRIBE is handled by phase4-005 suppression. Drafting a reply to
# either would be wrong (UNSUB) or wasteful (OOO — the prospect can't read it).
_SKIP_INTENTS = frozenset({ReplyIntent.OUT_OF_OFFICE, ReplyIntent.UNSUBSCRIBE})


PROMPTS: dict[str, str] = {
    ReplyIntent.INTERESTED: """\
You are drafting a warm, brief response on behalf of Anthony Stewart (IT
Experts Berlin) to a prospect who replied with interest to a cold outreach
email. The prospect's reply is below.

Your goals:
  1. Acknowledge their interest naturally.
  2. Propose a 30-minute discovery call. Suggest Calendly:
     {booking_url}
  3. Keep it to 4-6 short sentences. No long preamble.
  4. Sign off as: Anthony Stewart · Klaravex.

Output ONLY valid JSON with these fields:
  subject: string (reply subject, often starts with "Re:")
  body_html: string (HTML body with <p> paragraphs)
  body_text: string (plain text version)

Prospect reply:
{reply_body}

Prospect details:
  name: {contact_name}
  company: {company_name}
""",
    ReplyIntent.NOT_NOW: """\
You are drafting a graceful response to a prospect who replied saying the
timing is wrong but they may want to talk later. Reply on behalf of
Anthony Stewart (Klaravex).

Goals:
  1. Thank them for the honest reply.
  2. Briefly acknowledge their stated reason (if mentioned).
  3. Propose a follow-up date 3-4 months out (or whatever timing they
     hinted at).
  4. Make it easy to revive — invite them to reach out anytime sooner.
  5. Keep it to 3-5 short sentences. No pressure.
  6. Sign off as: Anthony Stewart · Klaravex.

Output ONLY valid JSON with these fields:
  subject: string
  body_html: string
  body_text: string

Prospect reply:
{reply_body}

Prospect details:
  name: {contact_name}
  company: {company_name}
""",
    ReplyIntent.WRONG_PERSON: """\
You are drafting a polite response to a prospect who replied saying they
are NOT the right contact and may have referred someone else. Reply on
behalf of Anthony Stewart (Klaravex).

Goals:
  1. Thank them for the redirect.
  2. Ask for an introduction or contact details for the right person, IF
     they did not already provide them. If they did name someone, just
     thank them and say you'll reach out directly.
  3. Keep it to 2-4 short sentences.
  4. Sign off as: Anthony Stewart · Klaravex.

Output ONLY valid JSON with these fields:
  subject: string
  body_html: string
  body_text: string

Prospect reply:
{reply_body}

Prospect details:
  name: {contact_name}
  company: {company_name}
""",
    ReplyIntent.OTHER: """\
You are drafting a clarifying response to a cold-outreach reply that did
not fit a standard pattern. Reply on behalf of Anthony Stewart (IT Experts
Berlin). Anthony will review and edit before sending.

Goals:
  1. Acknowledge their message.
  2. Ask one clear clarifying question to move the conversation forward.
  3. Avoid assumptions — the reply was ambiguous.
  4. Keep it to 2-4 short sentences.
  5. Sign off as: Anthony Stewart · Klaravex.

Output ONLY valid JSON with these fields:
  subject: string
  body_html: string
  body_text: string

Prospect reply:
{reply_body}

Prospect details:
  name: {contact_name}
  company: {company_name}
""",
}


def _serialise(row: ReplyDraft) -> dict:
    return {
        "id": row.id,
        "prospect_id": row.prospected_lead_id,
        "intent": row.intent,
        "subject": row.draft_subject,
        "body_html": row.draft_body_html,
        "body_text": row.draft_body_text,
        "status": row.status,
        "approval_id": row.approval_id,
        "model": row.model,
    }


class ReplyDraftAgent(BaseAgent):
    name = "reply_draft"
    description = (
        "Claude-powered draft generator for inbound cold-outreach replies. "
        "Creates a ReplyDraft + ApprovalRequest pair. P3 — requires approval."
    )
    permission_level = PermissionLevel.P3

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        prospect_id = input_data.get("prospect_id")
        intent = input_data.get("intent")
        reply_body = (input_data.get("reply_body") or "").strip()
        classification_id = input_data.get("classification_id")

        if not prospect_id:
            return AgentResult.fail("Missing prospect_id in input_data.")
        if not intent:
            return AgentResult.fail("Missing intent in input_data.")
        if intent not in ReplyIntent.ALL:
            return AgentResult.fail(f"Unknown intent: {intent!r}.")

        # Phase4 skip-intents: nothing to draft.
        if intent in _SKIP_INTENTS:
            logger.info(
                "reply_draft.skipped_by_intent",
                prospect_id=prospect_id,
                intent=intent,
            )
            return AgentResult.ok(output={"skipped": True, "intent": intent})

        # Idempotency: existing draft short-circuits Claude.
        existing = await context.db.execute(
            select(ReplyDraft).where(
                ReplyDraft.prospected_lead_id == prospect_id
            )
        )
        existing_row = existing.scalar_one_or_none()
        if existing_row is not None:
            logger.info(
                "reply_draft.cached",
                prospect_id=prospect_id,
                status=existing_row.status,
            )
            return AgentResult.ok(output=_serialise(existing_row))

        # Verify prospect exists.
        pl = await context.db.execute(
            select(ProspectedLead).where(ProspectedLead.id == prospect_id)
        )
        prospect = pl.scalar_one_or_none()
        if prospect is None:
            return AgentResult.fail(f"ProspectedLead {prospect_id} not found.")

        if not reply_body:
            return AgentResult.fail("Missing reply_body in input_data.")

        # Build per-intent prompt.
        template = PROMPTS.get(intent)
        if template is None:
            return AgentResult.fail(f"No prompt template for intent {intent!r}.")
        prompt = template.format(
            reply_body=reply_body,
            contact_name=prospect.contact_name or "there",
            company_name=prospect.company_name or "your team",
            booking_url=context.settings.booking_url,
        )

        # phase13-002: register the per-intent template under a unique name
        try:
            from app.services.prompt_registry import register_prompt
            await register_prompt(
                context.db, agent_name=self.name,
                prompt_name=f"PROMPT_{intent}",
                content=template,
            )
        except Exception:
            pass

        # Call Claude.
        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        model_name = context.settings.anthropic_model
        try:
            response = await client.messages.create(
                model=model_name,
                max_tokens=1024,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = response.content[0].text
            parsed = json.loads(raw_text)
            from app.services.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name, model=model_name,
                response=response, lead_id=prospect_id,
            )
        except json.JSONDecodeError as exc:
            logger.error(
                "reply_draft.json_parse_error",
                prospect_id=prospect_id,
                error=str(exc),
            )
            return AgentResult.fail(f"Could not parse Claude response: {exc}")
        except Exception as exc:
            logger.error(
                "reply_draft.claude_error",
                prospect_id=prospect_id,
                error=str(exc),
            )
            return AgentResult.fail(str(exc))

        subject = (parsed.get("subject") or "").strip()
        body_html = (parsed.get("body_html") or "").strip()
        body_text = (parsed.get("body_text") or "").strip() or None
        if not subject or not body_html:
            return AgentResult.fail(
                "Claude returned an empty subject or body_html."
            )

        # Build the ApprovalRequest first so we have its id for the draft FK.
        approval_payload = {
            "prospect_id": prospect_id,
            "to_email": prospect.contact_email,
            "to_name": prospect.contact_name,
            "subject": subject,
            "body_html": body_html,
            "body_text": body_text,
            "intent": intent,
            "company_name": prospect.company_name,
        }
        # Set IDs explicitly so the chained FK (draft.approval_id) is populated
        # without relying on SQLAlchemy's default-firing during flush. The
        # model defaults remain in place as a safety net.
        approval_id = str(uuid4())
        approval = ApprovalRequest(
            id=approval_id,
            action_name="reply_draft.send",
            risk_level=RiskLevel.p3.value,
            payload=json.dumps(approval_payload),
            justification=(
                f"Auto-drafted response to {intent} reply from "
                f"{prospect.contact_email or prospect.contact_name or prospect_id}."
            ),
            requested_by_agent=self.name,
            status=ApprovalStatus.pending.value,
        )
        context.db.add(approval)
        await context.db.flush()

        draft_id = str(uuid4())
        draft = ReplyDraft(
            id=draft_id,
            prospected_lead_id=prospect_id,
            classification_id=classification_id,
            intent=intent,
            draft_subject=subject,
            draft_body_html=body_html,
            draft_body_text=body_text,
            status=ReplyDraftStatus.pending,
            approval_id=approval_id,
            model=model_name,
        )
        context.db.add(draft)
        await context.db.flush()

        logger.info(
            "reply_draft.created",
            prospect_id=prospect_id,
            intent=intent,
            approval_id=approval.id,
            draft_id=draft.id,
        )

        return AgentResult(
            success=True,
            output=_serialise(draft),
            approval_required=True,
            approval_id=approval.id,
            metadata={"pending_action": "reply_draft.send"},
        )
