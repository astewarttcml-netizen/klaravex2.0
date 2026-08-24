"""
app/agents/reply_intent.py
──────────────────────────
ReplyIntentAgent (phase4-001) — P1, read-only.

Classifies the body text of an inbound cold-outreach reply into one of:
  INTERESTED      — wants to engage (book call, hear more, share details)
  NOT_NOW         — interested in principle but timing is wrong
  WRONG_PERSON    — recipient is not the right contact; refers elsewhere
  OUT_OF_OFFICE   — auto-reply or vacation message (extracts return_date)
  UNSUBSCRIBE     — explicit opt-out request
  OTHER           — anything else (no clear intent / spam / etc.)

The agent persists exactly one ReplyClassification row per ProspectedLead.
Re-running is a no-op — the existing row is returned. The UNIQUE index on
reply_classifications.prospected_lead_id makes this safe under concurrent
webhook deliveries.

P1 (read-only) — never blocks for human approval; Claude is invoked
synchronously from the inbound-reply webhook handler.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.prospected_lead import ProspectedLead
from app.models.reply_classification import ReplyClassification, ReplyIntent

logger = structlog.get_logger(__name__)


CLASSIFICATION_PROMPT = """\
You classify replies to cold sales outreach for Klaravex.

Given the reply body below, output a JSON object with these fields:
  intent: one of "INTERESTED", "NOT_NOW", "WRONG_PERSON", "OUT_OF_OFFICE", "UNSUBSCRIBE", "OTHER"
  confidence: float between 0.0 and 1.0 (your certainty in the intent label)
  summary: one-sentence English summary of what the reply says
  suggested_next_action: one short sentence on what we should do next
  return_date: ISO-8601 YYYY-MM-DD if intent=OUT_OF_OFFICE and a return date is mentioned, else null

Intent guidance:
  INTERESTED     — explicit interest, asks to schedule, requests more info, asks pricing
  NOT_NOW        — polite "not right now", "maybe in Q3", "circle back later"
  WRONG_PERSON   — "not me, contact X", "I'm not the right person", "forwarded to..."
  OUT_OF_OFFICE  — automated vacation/OOO replies, away messages
  UNSUBSCRIBE    — "remove me", "stop emailing", "opt out", "unsubscribe"
  OTHER          — anything else

Respond ONLY with valid JSON. No markdown fences. No commentary.

Reply body:
{reply_body}
"""


def _coerce_intent(value: Any) -> str:
    if isinstance(value, str) and value.upper() in ReplyIntent.ALL:
        return value.upper()
    return ReplyIntent.OTHER


def _coerce_confidence(value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))


def _coerce_return_date(value: Any) -> Optional[date]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


class ReplyIntentAgent(BaseAgent):
    name = "reply_intent"
    description = (
        "Claude-powered classifier for inbound cold-outreach replies. "
        "Persists one ReplyClassification row per ProspectedLead. P1 — read-only."
    )
    permission_level = PermissionLevel.P1

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        prospect_id = input_data.get("prospect_id")
        reply_body = (input_data.get("reply_body") or "").strip()

        if not prospect_id:
            return AgentResult.fail("Missing prospect_id in input_data.")
        if not reply_body:
            return AgentResult.fail("Missing reply_body in input_data.")

        # Idempotency: if a classification already exists for this prospect,
        # return it without re-calling Claude. The unique index on
        # prospected_lead_id makes the post-insert check race-safe.
        existing = await context.db.execute(
            select(ReplyClassification).where(
                ReplyClassification.prospected_lead_id == prospect_id
            )
        )
        existing_row = existing.scalar_one_or_none()
        if existing_row is not None:
            logger.info(
                "reply_intent.cached",
                prospect_id=prospect_id,
                intent=existing_row.intent,
            )
            return AgentResult.ok(output=_serialise(existing_row))

        # Verify the prospect actually exists before burning a Claude call.
        prospect_q = await context.db.execute(
            select(ProspectedLead).where(ProspectedLead.id == prospect_id)
        )
        prospect = prospect_q.scalar_one_or_none()
        if prospect is None:
            return AgentResult.fail(f"ProspectedLead {prospect_id} not found.")

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        model_name = context.settings.anthropic_model
        # phase13-002: register prompt template for drift detection (no-op on
        # duplicate checksum, never raises)
        try:
            from app.services.prompt_registry import register_prompt
            await register_prompt(
                context.db, agent_name=self.name,
                prompt_name="CLASSIFICATION_PROMPT",
                content=CLASSIFICATION_PROMPT,
            )
        except Exception:
            pass
        try:
            response = await client.messages.create(
                model=model_name,
                max_tokens=512,
                temperature=0,
                messages=[{
                    "role": "user",
                    "content": CLASSIFICATION_PROMPT.format(reply_body=reply_body),
                }],
            )
            raw_text = response.content[0].text
            parsed = json.loads(raw_text)
            # phase9-001: track LLM cost. record_llm_call NEVER raises.
            try:
                from app.services.llm_cost import record_llm_call
                usage = getattr(response, "usage", None)
                if usage is not None:
                    await record_llm_call(
                        context.db,
                        agent_name=self.name,
                        model=model_name,
                        input_tokens=getattr(usage, "input_tokens", 0) or 0,
                        output_tokens=getattr(usage, "output_tokens", 0) or 0,
                        lead_id=prospect_id,
                    )
            except Exception:
                pass
        except json.JSONDecodeError as exc:
            logger.error(
                "reply_intent.json_parse_error",
                prospect_id=prospect_id,
                error=str(exc),
            )
            return AgentResult.fail(f"Could not parse Claude response: {exc}")
        except Exception as exc:
            logger.error(
                "reply_intent.claude_error",
                prospect_id=prospect_id,
                error=str(exc),
            )
            return AgentResult.fail(str(exc))

        intent = _coerce_intent(parsed.get("intent"))
        confidence = _coerce_confidence(parsed.get("confidence"))
        return_date = _coerce_return_date(parsed.get("return_date"))

        row = ReplyClassification(
            prospected_lead_id=prospect_id,
            intent=intent,
            confidence=confidence,
            summary=(parsed.get("summary") or None),
            suggested_next_action=(parsed.get("suggested_next_action") or None),
            return_date=return_date,
            raw_response=raw_text,
            model=model_name,
        )
        context.db.add(row)
        await context.db.flush()

        logger.info(
            "reply_intent.classified",
            prospect_id=prospect_id,
            intent=intent,
            confidence=confidence,
            has_return_date=return_date is not None,
        )

        # phase4-003: auto-promote INTERESTED replies to qualified Lead rows.
        # The threshold + idempotency are enforced inside convert_to_lead;
        # failures are logged but never fail the classification path.
        converted_lead_id: Optional[str] = None
        try:
            from app.services.prospect_conversion import convert_to_lead
            converted = await convert_to_lead(
                context, prospect, _serialise(row),
            )
            if converted is not None:
                converted_lead_id = converted.id
        except Exception as exc:
            logger.error(
                "reply_intent.conversion_exception",
                prospect_id=prospect_id,
                error=str(exc),
            )

        # phase4-004: reschedule pending follow-ups past the OOO window.
        rescheduled_count: Optional[int] = None
        if intent == ReplyIntent.OUT_OF_OFFICE and return_date is not None:
            try:
                from app.services.followup_reschedule import reschedule_after_ooo
                rescheduled_count = await reschedule_after_ooo(
                    context.db, prospect, return_date,
                )
            except Exception as exc:
                logger.error(
                    "reply_intent.reschedule_exception",
                    prospect_id=prospect_id,
                    error=str(exc),
                )

        # phase4-005: on UNSUBSCRIBE, add the prospect's email to the global
        # suppression list AND stamp the existing engagement column. Failures
        # are logged but never fail the classification path.
        suppressed = False
        if intent == ReplyIntent.UNSUBSCRIBE and prospect.contact_email:
            try:
                from app.services.suppression import add_to_suppression
                from app.services.engagement_tracker import record_unsubscribe
                from app.models.email_suppression import SuppressionSource
                suppressed = await add_to_suppression(
                    context.db,
                    prospect.contact_email,
                    source=SuppressionSource.unsubscribed_reply,
                    reason=f"Classified as UNSUBSCRIBE (confidence={confidence})",
                )
                if prospect.unsubscribed_at is None:
                    await record_unsubscribe(context.db, prospect)
            except Exception as exc:
                logger.error(
                    "reply_intent.suppression_exception",
                    prospect_id=prospect_id,
                    error=str(exc),
                )

        output = _serialise(row)
        if converted_lead_id:
            output["converted_lead_id"] = converted_lead_id
        if rescheduled_count is not None:
            output["rescheduled_followups"] = rescheduled_count
        if suppressed:
            output["suppression_added"] = True
        return AgentResult.ok(output=output)


def _serialise(row: ReplyClassification) -> dict:
    return {
        "id": row.id,
        "prospect_id": row.prospected_lead_id,
        "intent": row.intent,
        "confidence": row.confidence,
        "summary": row.summary,
        "suggested_next_action": row.suggested_next_action,
        "return_date": row.return_date.isoformat() if row.return_date else None,
        "model": row.model,
        "classified_at": row.classified_at.isoformat() if row.classified_at else None,
    }
