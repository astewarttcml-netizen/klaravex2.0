"""
app/agents/objection_handler.py
─────────────────────────────────
P2 agent — detects and handles price/competitor objections in inbound chat messages.

Triggered by: routing agent when lead message contains objection signals.
Also callable directly via POST /api/v1/agents/run with agent="objection_handler".

Flow:
  1. Classify the objection type (price, competitor, trust, timeline, scope)
  2. Generate a measured, professional response tailored to the objection
  3. Return draft response for immediate use in chat flow

Objection types handled:
  - PRICE     — "too expensive", "cheaper alternative", "over budget"
  - COMPETITOR— "we use X", "X also does this", competitor name detected
  - TRUST     — "how do I know you're qualified", "references", "past work"
  - TIMELINE  — "too slow", "need it faster", "urgent deadline"
  - SCOPE     — "do you do X", "can you handle Y", scoping uncertainty

Permission: P2 — inline chat response, no external send. Low risk.
"""
from __future__ import annotations

import textwrap

import structlog
from anthropic import AsyncAnthropic

from klara.rarv.runtime import BaseAgent, AgentContext, AgentResult, PermissionLevel

logger = structlog.get_logger(__name__)

# Keywords for lightweight objection classification
_PRICE_SIGNALS = [
    "too expensive", "zu teuer", "cheaper", "günstiger", "budget", "cost",
    "kosten", "preis", "price", "affordable", "quote", "angebot",
]
_COMPETITOR_SIGNALS = [
    "competitor", "mitbewerber", "alternative", "andere anbieter", "also looked at",
    "vs ", "versus", "compared to", "instead of", "rather than",
]
_TRUST_SIGNALS = [
    "reference", "referenz", "portfolio", "past work", "experience", "erfahrung",
    "qualified", "certified", "zertifikat", "proven", "who are you",
]
_TIMELINE_SIGNALS = [
    "too slow", "zu langsam", "urgent", "dringend", "asap", "sofort",
    "deadline", "quickly", "schnell", "when can you start",
]

_OBJECTION_PROMPT = textwrap.dedent("""\
You are Anthony Stewart, senior IT consultant at Klaravex (klaravex.de), a Berlin-based managed IT services firm.
A prospect has raised an objection. Respond professionally and confidently.

Prospect message: {message}
Objection type:   {objection_type}
Company:          {company}
Services interest:{services}

Response guidelines:
- Acknowledge the concern without being defensive
- Reframe around value, expertise, or risk reduction (not just cost)
- Keep it concise: 2–3 short paragraphs max
- End with a soft call to action (book a call, ask a clarifying question)
- Tone: confident, helpful, honest — never pushy
- Language: match the prospect's language ({language})

For PRICE objections: focus on ROI and risk of cheaper solutions
For COMPETITOR objections: acknowledge strengths, differentiate on specialisation and support
For TRUST objections: offer to share specific case studies and certifications
For TIMELINE objections: acknowledge urgency, propose expedited scoping call

Output only the response text. No meta-commentary.
""")


class ObjectionHandlerAgent(BaseAgent):
    name = "objection_handler"
    permission_level = PermissionLevel.P2
    description = (
        "Detects price, competitor, trust, or timeline objections in inbound messages "
        "and generates a measured, professional response for use in the chat flow. "
        "Classifies objection type then uses Claude to draft a tailored reply. P2 — "
        "inline response only, no external send."
    )

    async def run(self, context: AgentContext, payload: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        message = payload.get("message", "")
        if not message:
            return AgentResult.fail("objection_handler: 'message' is required.")

        company = payload.get("company", "unknown")
        services = payload.get("services_interest", "IT consulting")
        language = payload.get("language", "en")

        objection_type = _classify_objection(message)
        if objection_type == "NONE":
            return AgentResult.ok({
                "objection_detected": False,
                "message": message,
            })

        log.info("objection_handler.detected",
                 objection_type=objection_type,
                 conversation=context.conversation_id)

        prompt = _OBJECTION_PROMPT.format(
            message=message,
            objection_type=objection_type,
            company=company,
            services=services,
            language=language,
        )

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            from klara.rarv.runtime.prompt_registry import register_prompt
            await register_prompt(
                context.db, agent_name=self.name,
                prompt_name="_OBJECTION_PROMPT",
                content=str(_OBJECTION_PROMPT),
            )
        except Exception:
            pass

        try:
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            try:
                from klara.rarv.runtime.llm_cost import track_response
                await track_response(
                    context.db, agent_name=self.name,
                    model="claude-haiku-4-5-20251001",
                    response=response, lead_id=getattr(context, 'lead_id', None),
                )
            except Exception:
                pass
            draft_response = response.content[0].text.strip()
        except Exception as exc:
            log.error("objection_handler.claude_error", error=str(exc))
            return AgentResult.fail(str(exc))

        log.info("objection_handler.response_drafted",
                 objection_type=objection_type,
                 tokens=response.usage.output_tokens)

        return AgentResult.ok({
            "objection_detected": True,
            "objection_type": objection_type,
            "draft_response": draft_response,
            "tokens_used": response.usage.output_tokens,
        })


def _classify_objection(message: str) -> str:
    """Return objection type string or 'NONE'."""
    msg = message.lower()
    if any(s in msg for s in _PRICE_SIGNALS):
        return "PRICE"
    if any(s in msg for s in _COMPETITOR_SIGNALS):
        return "COMPETITOR"
    if any(s in msg for s in _TRUST_SIGNALS):
        return "TRUST"
    if any(s in msg for s in _TIMELINE_SIGNALS):
        return "TIMELINE"
    return "NONE"
