"""
app/agents/inbound_email.py
────────────────────────────
phase19-002 — InboundEmailAgent classifier.

Classifies arbitrary inbound email into 6 categories:
  vendor_bill        — invoice/bill from a vendor (utilities, SaaS, tax)
  prospect_referral  — someone says "you should talk to X" or forwards a contact
  support_question   — technical question / "how do I..."
  personal           — non-business correspondence
  spam               — unsolicited mass mail
  other              — anything else

P1 — read-only classification. Idempotent: re-classifying the same
email row by id is a no-op.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.inbound_email import InboundCategory, InboundEmail

logger = structlog.get_logger(__name__)


CLASSIFICATION_PROMPT = """\
Classify this inbound email into ONE category. Output JSON only.

Categories:
  vendor_bill        — invoice or bill from a vendor (utilities, SaaS, accountant, tax authority)
  prospect_referral  — someone introducing a new contact / saying "you should talk to X"
  support_question   — technical or service question from an existing or prospective client
  personal           — non-business correspondence
  spam               — unsolicited mass mail or obvious phishing
  other              — anything that doesn't clearly fit above

Output JSON: {{"category": "...", "confidence": 0.0-1.0, "summary": "one-sentence summary"}}

Email:
From:    {from_email}
Subject: {subject}
Body:
{body}
"""


def _coerce_category(value: Any) -> str:
    if isinstance(value, str) and value.lower() in InboundCategory.ALL:
        return value.lower()
    return InboundCategory.other


def _coerce_confidence(value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))


class InboundEmailAgent(BaseAgent):
    name = "inbound_email"
    description = (
        "Claude-powered classifier for arbitrary inbound emails. "
        "Categorises into vendor_bill / prospect_referral / support_question / "
        "personal / spam / other. P1 — read-only."
    )
    permission_level = PermissionLevel.P1

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        email_id = input_data.get("inbound_email_id")
        if not email_id:
            return AgentResult.fail("Missing inbound_email_id in input_data.")

        row_q = await context.db.execute(
            select(InboundEmail).where(InboundEmail.id == email_id)
        )
        row = row_q.scalar_one_or_none()
        if row is None:
            return AgentResult.fail(f"InboundEmail {email_id} not found.")

        # Idempotency
        if row.category and row.classified_at:
            return AgentResult.ok(output={
                "id": row.id, "category": row.category,
                "confidence": row.confidence, "summary": row.summary,
                "cached": True,
            })

        prompt = CLASSIFICATION_PROMPT.format(
            from_email=row.from_email,
            subject=row.subject or "",
            body=(row.body or "")[:2000],
        )

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        model_name = context.settings.anthropic_model
        try:
            response = await client.messages.create(
                model=model_name,
                max_tokens=300,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = response.content[0].text
            parsed = json.loads(raw_text)
            # phase9 cost tracking
            from app.services.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name, model=model_name,
                response=response, lead_id=row.lead_id,
            )
        except json.JSONDecodeError as exc:
            logger.error("inbound_email.json_parse_error", email_id=email_id, error=str(exc))
            return AgentResult.fail(f"Could not parse Claude response: {exc}")
        except Exception as exc:
            logger.error("inbound_email.claude_error", email_id=email_id, error=str(exc))
            return AgentResult.fail(str(exc))

        category = _coerce_category(parsed.get("category"))
        confidence = _coerce_confidence(parsed.get("confidence"))
        summary = (parsed.get("summary") or None)

        row.category = category
        row.confidence = confidence
        row.summary = summary
        row.classified_at = datetime.now(timezone.utc)
        await context.db.flush()

        logger.info(
            "inbound_email.classified",
            email_id=email_id, category=category, confidence=confidence,
        )

        return AgentResult.ok(output={
            "id": row.id, "category": category,
            "confidence": confidence, "summary": summary,
            "cached": False,
        })
