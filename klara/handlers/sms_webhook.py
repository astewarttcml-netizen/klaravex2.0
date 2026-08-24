"""Inbound SMS channel — routes Twilio SMS webhooks through the chat agent.

This gives the same AI conversation capability as the web widget (klaravex.com
chat) to customers who prefer to text rather than call or open a browser.
Session state is stored in klaravex_chat_agent_sessions keyed by E.164 phone
number so conversation context survives across messages.

Route: POST /api/v1/sms/chat
(The existing /api/v1/sms/inbound handles the patch-delay / resolver workflow;
this new endpoint is the chat-agent-backed channel for full Klara conversations
over SMS.)

Security:
- Twilio webhook signature verified at dependency level (same guard as sms_inbound).
- Rate limit: max 10 inbound messages per phone per hour, tracked in-memory
  with a sliding 1-hour window (resets on process restart — acceptable for
  single-replica deploy).

Reply format: TwiML <Response><Message>…</Message></Response> — Twilio will
send this as an outbound SMS reply to the caller without any extra API call.

SMS-specific prompt tweaks:
- No markdown (no **bold**, no bare URL directives — SMS is plain text).
- No payment links over SMS by default — send a link to klaravex.com instead
  so the customer completes payment on a real browser checkout page.
- Max reply length: 320 chars (two SMS segments) to keep costs down and UX
  usable on a phone screen. The agent system prompt enforces this.
"""

import json
import logging
import os
import time
from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response

from .chat_agent import (
    _load_session,
    _run_tool,
    _save_session,
    tools_for,
    ANTHROPIC_API_KEY,
    MAX_TOOL_ITERATIONS,
)
from .lib.twilio_verify import verify_twilio_signature

log = logging.getLogger("klaravex.sms_webhook")

# ── Config ──────────────────────────────────────────────────────────────────

SMS_CHAT_MODEL = os.environ.get("CHAT_AGENT_MODEL", "anthropic/nvidia_nim/deepseek-ai/deepseek-v4-flash-0731")
SMS_MAX_OUTPUT_TOKENS = 320  # ~2 SMS segments
SMS_RATE_LIMIT_PER_HOUR = 10  # inbound messages per phone number per hour

# In-memory rate tracker: phone → list of unix timestamps within the last hour.
# Single-process (Azure Container App single replica) — acceptable tradeoff.
# Resets on process restart, which is fine (rate window resets with it).
_rate_tracker: dict[str, list[float]] = defaultdict(list)

# ── System prompts ───────────────────────────────────────────────────────────

_SMS_SCAM_EXCEPTION = (
    "EXCEPTION — SCAM / IDENTITY THEFT / ACCOUNT COMPROMISE IS FREE. "
    "If the issue is a scam or account takeover, do NOT ask for payment. "
    "Say: 'This is on us — no charge. Let us get you help now.' "
    "Then call escalate_to_anthony with severity=critical."
)

SMS_PERSONAL_SYSTEM_PROMPT = f"""
You are Klara, Klaravex's AI tech support assistant, replying to a customer
over SMS. Keep every reply under 300 characters — the customer is on a phone.
One idea per message. Plain text only: no asterisks, no markdown, no
parenthetical URLs in [text](url) format. Write URLs as plain text if needed.

{_SMS_SCAM_EXCEPTION}

How this works over SMS:
1. Ask what device and what's wrong, in plain language.
2. Confirm what you heard in one short reply.
3. PAYMENT BEFORE HELP: the per-incident fix is $29 flat. Do NOT give fix
   steps before payment. Collect their email, then tell them to visit
   klaravex.com/pay to complete checkout — do NOT call send_payment_link
   (SMS links are unreliable). Once they say they paid, call
   check_payment_status.
4. After payment confirmed: call open_support_ticket, then walk them through
   it one step at a time over SMS.
5. For remote screen control: tell them to visit support.klaravex.com on
   a computer, then call start_remote_session with their email.
6. Returning customer with a code: call lookup_client.
7. At session end: call log_session_outcome.

Use search_knowledge_base to ground answers in real Klaravex content.

If they ask for a human: call escalate_to_anthony with reason=human_requested.
Tell them the team replies by email within one business day.

Never claim to be human. If asked: "I'm Klara, Klaravex's AI assistant."
Never use "simply", "just", or "easy".
Never say "router" — say "internet box".
""".strip()

SMS_BUSINESS_SYSTEM_PROMPT = f"""
You are Klara, Klaravex's AI assistant, replying over SMS to a B2B prospect
or client. Keep every reply under 300 characters. Plain text only — no
markdown, no formatted URLs.

{_SMS_SCAM_EXCEPTION}

Your job:
1. General questions: answer briefly from what you know — Directive tier
   (compliance + MDR + vCISO), Foundation and Assurance also available;
   HIPAA / SOC 2 / ISO 27001 readiness, M365 / GWorkspace / AWS, UniFi
   network management. Use search_knowledge_base for specifics.
2. Buying intent (quote, talk, sign up, compliance deadline): collect company,
   name, seat count, pain point, urgency. Call create_b2b_lead. Then tell them
   to visit klaravex.com/contact or reply with their email for a booking link.
3. Urgent / active incident: call escalate_to_anthony immediately with
   severity=critical.
4. Existing client support: call lookup_client or escalate_to_anthony.

Never invent numbers. Never claim to be human.
""".strip()


def _sms_system_prompt(is_business: bool) -> str:
    return SMS_BUSINESS_SYSTEM_PROMPT if is_business else SMS_PERSONAL_SYSTEM_PROMPT


# ── Rate limiting (per phone, in-memory sliding window) ──────────────────────

def _check_and_record_rate(phone: str) -> bool:
    """Return True (and record the hit) if within the hourly limit, False if over.

    Slides a 1-hour window over the timestamp list for this phone.
    Thread-safe for single-process use (asyncio event loop is single-threaded).
    """
    now = time.time()
    cutoff = now - 3600
    recent = [t for t in _rate_tracker[phone] if t > cutoff]
    if len(recent) >= SMS_RATE_LIMIT_PER_HOUR:
        _rate_tracker[phone] = recent  # prune but don't record
        return False
    recent.append(now)
    _rate_tracker[phone] = recent
    return True


def _sms_session_token(phone: str) -> str:
    """Derive a stable session token from a phone number.

    Prefixed so it's distinguishable from widget sessions in the DB.
    """
    return f"sms:{phone}"


# ── TwiML helpers ────────────────────────────────────────────────────────────

def _twiml_reply(text: str) -> Response:
    """Wrap a plain-text reply in a TwiML <Message> response."""
    # Truncate hard at 1600 chars (10 SMS segments) as an absolute safety cap.
    safe = (text or "")[:1600]
    xml = f"<Response><Message>{_xml_escape(safe)}</Message></Response>"
    return Response(content=xml, media_type="application/xml")


def _twiml_empty() -> Response:
    """Return an empty TwiML response (no outbound SMS)."""
    return Response(content="<Response/>", media_type="application/xml")


def _xml_escape(s: str) -> str:
    """Minimal XML entity escaping for TwiML body text."""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&apos;")
    )


# ── Router ───────────────────────────────────────────────────────────────────

router = APIRouter(dependencies=[Depends(verify_twilio_signature)])


@router.post("/sms/chat")
async def sms_chat_inbound(
    request: Request,
    From: Annotated[str, Form()] = "",
    Body: Annotated[str, Form()] = "",
    MessageSid: Annotated[str, Form()] = "",
) -> Response:
    """Twilio inbound SMS webhook — chat agent channel.

    Receives a Twilio form-encoded POST, routes the message through the same
    chat_agent tool loop as the klaravex.com widget, and returns a TwiML
    <Message> so Twilio sends the reply as an outbound SMS to the caller.

    Rate limited: 10 messages per phone per hour.
    Signature verified: X-Twilio-Signature (dependency above).
    """
    log.info("sms_chat from=%s sid=%s body=%r", From, MessageSid, Body[:80])

    if not From or not Body:
        return _twiml_empty()

    message = Body.strip()
    if not message:
        return _twiml_empty()

    # ── Rate limit check ─────────────────────────────────────────────────────
    if not _check_and_record_rate(From):
        log.warning("sms_chat rate limit exceeded for phone=%s", From)
        return _twiml_reply(
            "We're receiving too many messages from this number. "
            "Please wait an hour and try again, or email hello@klaravex.com."
        )

    if not ANTHROPIC_API_KEY:
        log.error("sms_chat: ANTHROPIC_API_KEY not set")
        return _twiml_reply(
            "We're having a technical issue. Please try again in a moment "
            "or email hello@klaravex.com."
        )

    # ── Determine channel type ───────────────────────────────────────────────
    # SMS on klaravex numbers is always consumer (personal.klaravex.com parity).
    # Flip to business if a B2B Twilio number is ever provisioned by checking
    # env var SMS_BUSINESS_NUMBER or falling back to consumer.
    _business_number = os.environ.get("SMS_BUSINESS_NUMBER", "").strip()
    _to_number = request.headers.get("X-Twilio-To", "") or ""
    # Also available as the "To" form field from Twilio
    is_business = bool(_business_number and _business_number == _to_number)

    session_token = _sms_session_token(From)

    # ── Load (or create) session ─────────────────────────────────────────────
    history, _stored_email = await _load_session(
        session_token,
        origin="sms",
        is_business=is_business,
    )

    # ── Chat agent loop ──────────────────────────────────────────────────────
    import anthropic

    history.append({"role": "user", "content": message})
    system = _sms_system_prompt(is_business)
    tools = tools_for(is_business)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    final_text = ""
    working = list(history)

    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            resp = client.messages.create(
                model=SMS_CHAT_MODEL,
                max_tokens=SMS_MAX_OUTPUT_TOKENS,
                system=system,
                tools=tools,
                messages=working,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("sms_chat Claude call failed: %s", exc)
            final_text = (
                "We're having a technical issue. Please try again in a moment "
                "or email hello@klaravex.com."
            )
            break

        assistant_content = [block.model_dump() for block in resp.content]
        working.append({"role": "assistant", "content": assistant_content})

        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            final_text = "".join(
                b.text for b in resp.content if b.type == "text"
            ).strip()
            break

        tool_results = []
        for tu in tool_uses:
            result = await _run_tool(
                tu.name,
                tu.input or {},
                session_token=session_token,
                is_business=is_business,
            )
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result, default=str),
            })
        working.append({"role": "user", "content": tool_results})
    else:
        # Hit iteration cap — surface any text blocks from last assistant turn
        text_blocks = [
            b for b in working[-2].get("content", [])
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        final_text = " ".join(b.get("text", "") for b in text_blocks).strip()

    if not final_text:
        final_text = "Sorry, I didn't quite catch that — could you rephrase?"

    working.append({"role": "assistant", "content": final_text})
    await _save_session(session_token, working)

    return _twiml_reply(final_text)
