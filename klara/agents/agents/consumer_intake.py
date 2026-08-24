"""
app/agents/consumer_intake.py
──────────────────────────────
P2 agent — consumer personal IT support intake.

Unlike the business chat_intake (which qualifies sales leads), this agent
focuses on residential / personal IT help:
  - Understand the visitor's device and specific problem
  - Collect name and email for the Atera ticket
  - Get consent for a remote support session
  - Output structured consumer_info when ready for ticket creation

Tags in replies (stripped before display):
  [CONSUMER_READY]    — has device + problem + name + email; ready for ticket
  [NEEDS_MORE_INFO]   — still gathering required details
  [NOT_A_FIT]         — request outside scope (enterprise, custom dev, etc.)

When [CONSUMER_READY], the AI also appends a <consumer_data> block that is
parsed here for structured handoff to atera_ticket_creator.

Flow: consumer_intake → (on CONSUMER_READY) → atera_ticket_creator
"""
from __future__ import annotations

import re
import structlog
from anthropic import AsyncAnthropic

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.conversation import Conversation, Message, MessageRole

logger = structlog.get_logger(__name__)

_CONSUMER_SYSTEM_PROMPT = """\
You are Klara AI, the AI assistant for Klaravex — a remote IT support service.
Klaravex helps everyday people with their personal tech problems via secure remote sessions.

Services we offer to individuals:
  • Windows PC & Mac troubleshooting and tune-ups
  • Slow computer / virus / malware removal
  • Email and account setup (Microsoft 365, Gmail, Outlook)
  • Wi-Fi and home network issues
  • iPhone, iPad, Android setup and troubleshooting
  • Printer, scanner, peripheral setup
  • Data backup and recovery
  • Software installation and updates
  • Security hardening for home users

We do NOT handle: custom software development, enterprise infrastructure, or anything that \
requires physical hardware replacement.

Your goal is to collect the following — one or two questions per message, conversationally:
  1. The visitor's first name
  2. Their email address (for the support ticket and session link)
  3. What device they're having trouble with (Windows PC / Mac / iPhone / Android / other)
  4. A clear description of the problem
  5. Whether they're comfortable with a secure remote session (a Klaravex technician will connect to their \
screen to fix it)
  6. Their phone number (optional — only ask if it feels natural; mention it enables a quick \
callback if they prefer that over email)

Session pricing:
  • Quick fixes (under 30 min): $50
  • Standard session (up to 1 hr): $100
  • Extended (over 1 hr): $150/hr billed to the nearest 30 min
  Payment is taken after the session by credit card or PayPal.

Rules:
  • Be warm, clear, and jargon-free — this is for everyday users, not IT professionals.
  • Never collect payment details in chat.
  • Once you have name + email + device + problem description + remote consent, write \
your confirmation reply, then end with exactly this block (nothing else after it):

[CONSUMER_READY]
<consumer_data>
name: [visitor's full name]
email: [visitor's email address]
phone: [E.164 format if provided, e.g. +12125551234 — omit this line if not given]
device: [device type and OS, e.g. "Windows 11 laptop"]
problem: [one-sentence problem description]
</consumer_data>

  • If you're still missing information, end with: [NEEDS_MORE_INFO]
  • If the request is outside our scope (e.g. server management, coding, enterprise IT), \
explain why politely and end with: [NOT_A_FIT]
  • Respond in the same language the visitor uses.
"""

_CONSUMER_DATA_RE = re.compile(
    r"\[CONSUMER_READY\]\s*<consumer_data>\s*(.*?)\s*</consumer_data>",
    re.DOTALL,
)
_TAG_RE = re.compile(r"\[(CONSUMER_READY|NEEDS_MORE_INFO|NOT_A_FIT)\]")


def _parse_consumer_data(reply_text: str) -> tuple[str, dict]:
    """
    Strip the [CONSUMER_READY]/<consumer_data> block from reply_text and
    parse the key:value pairs into a dict.  Also strips loose [STATUS] tags.
    Returns (clean_reply, data_dict).
    """
    data: dict = {}
    m = _CONSUMER_DATA_RE.search(reply_text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                data[key.strip()] = val.strip()
        reply_text = reply_text[:m.start()].strip()

    # Strip any remaining loose tags
    reply_text = _TAG_RE.sub("", reply_text).strip()
    return reply_text, data


class ConsumerIntakeAgent(BaseAgent):
    name = "consumer_intake"
    description = (
        "Personal IT support intake for residential/consumer visitors. "
        "Collects name, email, phone, device info, problem description, and remote session consent. "
        "Outputs [CONSUMER_READY] when all required info is gathered. P2 — internal only."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        message_text = input_data.get("message", "").strip()
        history = input_data.get("history", [])
        language = input_data.get("language", "en")

        if not message_text:
            return AgentResult.fail("consumer_intake: 'message' is required.")

        db = context.db
        conversation_id = context.conversation_id
        if not conversation_id:
            return AgentResult.fail("consumer_intake: no conversation_id in context.")

        # Persist user message
        user_msg = Message(
            conversation_id=conversation_id,
            role=MessageRole.user,
            content=message_text,
        )
        db.add(user_msg)
        await db.flush()

        messages = history + [{"role": "user", "content": message_text}]

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            response = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=600,
                system=_CONSUMER_SYSTEM_PROMPT,
                messages=messages,
            )
            reply_text = response.content[0].text
            from klara.rarv.runtime.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=response, lead_id=context.lead_id,
            )
        except Exception as exc:
            logger.error("consumer_intake.claude_error", error=str(exc))
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

        # Determine intake status from raw reply (before stripping tags)
        consumer_status = "NEEDS_MORE_INFO"
        for tag in ("[CONSUMER_READY]", "[NOT_A_FIT]", "[NEEDS_MORE_INFO]"):
            if tag in reply_text:
                consumer_status = tag.strip("[]")
                break

        # Strip tags and parse structured data block
        clean_reply, consumer_data = _parse_consumer_data(reply_text)

        # Prefer API-provided fields (widget may supply them), then fall back
        # to what the AI extracted from conversation into <consumer_data>.
        visitor_name = (
            input_data.get("visitor_name")
            or consumer_data.get("name")
        )
        visitor_email = (
            input_data.get("visitor_email")
            or consumer_data.get("email")
        )
        phone = (
            input_data.get("phone")
            or consumer_data.get("phone")
            or ""
        )
        device = consumer_data.get("device", input_data.get("device", ""))
        problem = consumer_data.get("problem", input_data.get("problem", ""))

        logger.info(
            "consumer_intake.complete",
            conversation=conversation_id,
            status=consumer_status,
            tokens=response.usage.output_tokens,
            has_email=bool(visitor_email),
            has_phone=bool(phone),
        )

        output = {
            "reply": clean_reply,
            "consumer_status": consumer_status,
            "visitor_name": visitor_name,
            "visitor_email": visitor_email,
            "phone": phone,
            "device": device,
            "problem": problem,
            "consumer_info": consumer_data,
        }

        return AgentResult.ok(output=output)
