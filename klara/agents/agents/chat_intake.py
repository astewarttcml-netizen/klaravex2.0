"""
app/agents/chat_intake.py
─────────────────────────
Processes incoming chat messages via Claude.

Responsibilities:
  - Persist the user message
  - Call Claude with a system prompt scoped to Klaravex
  - Persist the assistant reply
  - Extract any structured signals (services mentioned, urgency, language)

Permission: P2 — the LLM call is internal.
The *reply* to the user is P2 (chat widget, internal).
Sending an external email based on the chat would be P3 — handled downstream.
"""
from __future__ import annotations

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.conversation import Conversation, Message, MessageRole
from app.services.known_problem_matcher import DEFAULT_AGENT_MIN_RANK, find_matches

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT_BASE = """\
You are Klara AI, the AI assistant for Klaravex — a senior-level IT consulting and managed
services firm.  Our services include:
  • Microsoft Azure architecture & migration
  • Microsoft 365 / Exchange / Teams administration
  • Microsoft Intune & device management (MDM/MAM)
  • Cisco Meraki networking & SD-WAN
  • Network security & firewall configuration
  • AI automation & workflow optimisation

Your role in this conversation:
  1. Understand the visitor's IT challenge or request.
  2. Ask clarifying questions to identify the best service fit.
  3. Qualify the lead (company size, timeline, budget awareness, decision maker).
  4. {language_instruction}
  5. Never promise specific prices — invite them to schedule a discovery call.
  6. Never discuss competitors by name.
  7. GDPR: never ask for more personal data than necessary for qualification.

When you have gathered enough information, end your message with one of these tags
so downstream agents can process it:
  [QUALIFIED] — ready to pass to human consultant
  [NEEDS_MORE_INFO] — still gathering requirements
  [NOT_A_FIT] — outside our service scope
"""

# Proactive opener prompts — used by POST /api/v1/chat/start when the AI speaks first.
# The trigger string "__INTAKE_START__:<source>" is sent as the "user" turn so Claude
# generates an opening message that begins the intake conversation.
INTAKE_OPENER_PROMPTS: dict[str, str] = {
    "discovery_call": (
        "The visitor has just clicked 'Book a Discovery Call' on the Klaravex website. "
        "You are starting the conversation — the visitor has not typed anything yet. "
        "Write a warm, concise opening message (2–3 sentences max). "
        "Greet them, briefly say you'll help get things ready for Anthony, "
        "then ask TWO questions in the same message: "
        "(1) their first name and company name, and "
        "(2) the main IT challenge or goal they're hoping to address. "
        "Do NOT use bullet points. Keep it conversational and professional."
    ),
    "contact_us": (
        "The visitor has just clicked 'Contact Us' on the Klaravex website. "
        "You are starting the conversation. "
        "Write a warm, concise opening message (2–3 sentences max). "
        "Ask their name, company, and what they need help with. "
        "Keep it conversational."
    ),
    "assessment": (
        "The visitor has just clicked 'Get a Free IT Assessment' on the Klaravex website. "
        "You are starting the conversation. "
        "Tell them you'll walk through a quick IT health check together. "
        "Ask their name, company name, and how many employees they have. "
        "2–3 sentences, conversational."
    ),
}

INTAKE_START_TRIGGER = "__INTAKE_START__"

LANGUAGE_INSTRUCTIONS = {
    "de": (
        "The visitor is on the GERMAN version of the site. "
        "You MUST respond exclusively in German for this entire conversation. "
        "Keep technical product names in English (e.g. Microsoft 365, Azure, Intune, Meraki). "
        "If the visitor switches to English, continue in German unless they explicitly ask you to switch."
    ),
    "en": (
        "The visitor is on the English version of the site. "
        "Respond in English throughout this conversation. "
        "If the visitor writes in German, you may briefly acknowledge it and reply in English, "
        "or ask if they'd prefer German."
    ),
}


KNOWLEDGE_PREAMBLE = (
    "\n\nINTERNAL REFERENCE — Know-How Library matches for the visitor's message:\n"
    "These are entries from our internal technical knowledge base that resemble the\n"
    "visitor's described issue. Use them only to:\n"
    "  • show informed familiarity with the problem space,\n"
    "  • ask sharper qualifying questions,\n"
    "  • decide whether the request is a fit for our services.\n"
    "Do NOT paste fix steps verbatim, quote diagnoses word-for-word, or promise a\n"
    "resolution in chat — always invite the visitor to a discovery call for any\n"
    "remediation work. Treat this section as confidential context, not user-visible\n"
    "content.\n"
)


def _format_knowledge_block(matches: list[dict]) -> str:
    """
    Render Know-How Library matches as a compact reference block for the
    Claude system prompt. Each entry is collapsed to a single line per field
    so the LLM can scan them quickly without inflating the prompt.

    The block is intentionally tagged "INTERNAL REFERENCE" — see KNOWLEDGE_PREAMBLE
    for the usage policy the LLM is bound to. Long symptom/diagnosis strings are
    truncated so a few verbose entries cannot blow out the prompt budget.
    """
    if not matches:
        return ""

    def _trim(s: object, n: int = 400) -> str:
        text = str(s or "").strip()
        return text if len(text) <= n else text[: n - 1].rstrip() + "…"

    lines: list[str] = [KNOWLEDGE_PREAMBLE]
    for i, m in enumerate(matches, start=1):
        lines.append(
            f"\n[{i}] product={_trim(m.get('product'), 80)} "
            f"(rank={m.get('rank')})"
        )
        lines.append(f"    symptom:   {_trim(m.get('symptom'))}")
        lines.append(f"    diagnosis: {_trim(m.get('diagnosis'))}")
        lines.append(f"    fix:       {_trim(m.get('fix'))}")
    return "".join(lines)


def build_system_prompt(
    language: str = "en",
    knowledge_matches: list[dict] | None = None,
    prompt_override: str = "",
) -> str:
    """
    Build the Claude system prompt for ChatIntakeAgent.

    When `knowledge_matches` is non-empty, the top Know-How Library entries are
    appended as an INTERNAL REFERENCE block so the LLM can ground its reply in
    things we already know about the symptom — without leaking the fix verbatim.
    The block is always appended *after* the base prompt and language clause so
    the language and tone instructions still take precedence.
    """
    lang = language.lower()[:2] if language else "en"
    instruction = LANGUAGE_INSTRUCTIONS.get(lang, LANGUAGE_INSTRUCTIONS["en"])
    base = prompt_override if prompt_override else SYSTEM_PROMPT_BASE
    prompt = base.format(language_instruction=instruction) if "{language_instruction}" in base else base
    if knowledge_matches:
        prompt += _format_knowledge_block(knowledge_matches)
    return prompt


class ChatIntakeAgent(BaseAgent):
    name = "chat_intake"
    description = (
        "Processes chat messages through Claude, persists conversation history, "
        "and extracts qualification signals."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        message_text = input_data.get("message", "").strip()
        history = input_data.get("history", [])
        language = input_data.get("language", "en")

        if not message_text:
            return AgentResult.fail("chat_intake: 'message' is required.")

        db = context.db
        conversation_id = context.conversation_id

        if not conversation_id:
            return AgentResult.fail("chat_intake: no conversation_id in context.")

        # Persist user message
        user_msg = Message(
            conversation_id=conversation_id,
            role=MessageRole.user,
            content=message_text,
        )
        db.add(user_msg)
        await db.flush()

        # Know-How Library suggestions (prod-004).
        # Match the visitor's free-text message against KnownProblem.search_vector
        # BEFORE the LLM call so the top entries can be injected into the system
        # prompt as INTERNAL REFERENCE context — this grounds Claude's reply in
        # things we already know without leaking the fix verbatim. Failure here
        # MUST NOT block the chat reply: a missing FTS index in dev or a transient
        # DB hiccup should leave the suggestion list empty rather than fail the
        # user-visible response.
        knowledge_matches: list[dict] = []
        try:
            matches = await find_matches(
                db, message_text, top_n=3, min_rank=DEFAULT_AGENT_MIN_RANK
            )
            knowledge_matches = [m.to_summary() for m in matches]
            if knowledge_matches:
                logger.info(
                    "chat_intake.knowledge_matches",
                    conversation=conversation_id,
                    match_count=len(knowledge_matches),
                    top_rank=knowledge_matches[0]["rank"],
                )
        except Exception as exc:
            logger.warning(
                "chat_intake.knowledge_match_failed",
                conversation=conversation_id,
                error=str(exc),
            )

        # Build message list for Claude
        messages = history + [{"role": "user", "content": message_text}]

        # Call Claude
        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            from app.services.prompt_registry import register_prompt
            await register_prompt(
                context.db, agent_name=self.name,
                prompt_name="build_system_prompt",
                content=str(build_system_prompt(language, knowledge_matches, context.settings.brand_intake_prompt_override)),
            )
        except Exception:
            pass

        try:
            response = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=context.settings.anthropic_max_tokens,
                system=build_system_prompt(language, knowledge_matches, context.settings.brand_intake_prompt_override),
                messages=messages,
            )
            reply_text = response.content[0].text
            from app.services.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=response, lead_id=context.lead_id,
            )
        except Exception as exc:
            logger.error("chat_intake.claude_error", error=str(exc))
            return AgentResult.fail(f"LLM error: {exc}")

        # Persist assistant reply
        assistant_msg = Message(
            conversation_id=conversation_id,
            role=MessageRole.assistant,
            content=reply_text,
            agent_name=self.name,
        )
        db.add(assistant_msg)
        await db.flush()

        # Extract qualification tag
        qualification_status = "NEEDS_MORE_INFO"
        for tag in ["[QUALIFIED]", "[NOT_A_FIT]", "[NEEDS_MORE_INFO]"]:
            if tag in reply_text:
                qualification_status = tag.strip("[]")
                break

        logger.info(
            "chat_intake.complete",
            conversation=conversation_id,
            qualification=qualification_status,
            tokens_used=response.usage.output_tokens,
        )

        return AgentResult.ok(
            output={
                "reply": reply_text,
                "qualification_status": qualification_status,
                "message_id": assistant_msg.id,
                "knowledge_matches": knowledge_matches,
            }
        )
