"""AI Resolver Agent — generates and delivers step-by-step fix instructions via SMS/email."""

import json
import logging
import os
import uuid
from typing import Any

import anthropic
import asyncpg
import httpx

from ..classifier import classify_intent, ESCALATE_INTENTS  # noqa: F401 — re-exported for SMS inbound
from ..lib.db import normalize_dsn

log = logging.getLogger("klaravex.agents.resolver")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.environ.get("TWILIO_FROM_NUMBER", "+14243486010")
MAX_ATTEMPTS = 3


async def _query_kb(issue: str) -> str:
    """Query the KB via the internal search endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "http://localhost:8000/api/v1/kb/search",
                json={"query": issue, "top_k": 3},
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                return "\n\n".join(r.get("content", "") for r in results)
    except Exception as e:
        log.warning("kb search failed: %s", e)
    return ""


async def _generate_steps(issue: str, kb_context: str, attempt: int = 0) -> list[str]:
    """Use Claude Haiku to generate numbered fix steps."""
    if not ANTHROPIC_API_KEY:
        return ["Please restart your device and try again.", "If the issue persists, reply STUCK."]

    _gateway = getattr(__import__('settings').settings, 'litellm_base_url', 'http://127.0.0.1:8090')
    client = anthropic.Anthropic(api_key="unused", base_url=_gateway)

    retry_note = ""
    if attempt > 0:
        retry_note = f"\n\nThis is attempt {attempt + 1} — the previous steps did not work. Try a different approach."

    prompt = f"""You are a concise IT support specialist. A client needs help with: {issue}

Knowledge base context:
{kb_context or "No specific KB article found — use general IT knowledge."}
{retry_note}

Generate exactly 3-5 numbered fix steps. Rules:
- Each step must be a single short sentence
- Use plain language — no jargon
- Be specific (click X, go to Y, press Z)
- Steps must be actionable on a phone or computer without any tools
- Do not include a step 0 or preamble
- Format: just the numbered steps, nothing else"""

    message = client.messages.create(
        model="anthropic/nvidia_nim/deepseek-ai/deepseek-v4-flash-0731",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )

    text = message.content[0].text.strip()
    steps = [line.strip() for line in text.split("\n") if line.strip() and line.strip()[0].isdigit()]
    return steps if steps else [text]


async def _send_sms(to: str, body: str) -> bool:
    """Delegates to the gated lib.sms helper so SMS_ENABLED is honored centrally."""
    from ..lib.sms import send_sms as _gated
    ok, _err = await _gated(to, body, source="resolver")
    return ok


async def _send_reply(phone: str, body: str, channel: str) -> bool:
    """Dispatch an outbound message on the correct channel.

    channel="sms"       → Twilio SMS via _send_sms
    channel="whatsapp"  → Twilio WhatsApp via send_whatsapp_message

    Imported lazily to avoid a circular-import with whatsapp_inbound.
    """
    if channel == "whatsapp":
        # Lazy import avoids circular dependency:
        # resolver ← whatsapp_inbound ← resolver (would be circular at module load time)
        from klara.handlers.whatsapp_inbound import send_whatsapp_message  # noqa: PLC0415
        return await send_whatsapp_message(phone, body)
    return await _send_sms(phone, body)


async def start_session(
    phone: str,
    issue: str,
    client_id: str | None = None,
    ticket_id: str | None = None,
    channel: str = "sms",
) -> dict[str, Any]:
    """Create a new resolver session and send the first round of fix steps."""
    kb_context = await _query_kb(issue)
    steps = await _generate_steps(issue, kb_context, attempt=0)

    steps_text = "\n".join(steps)
    message = (
        f"Hi! Klaravex AI support here. Here are the steps to fix your {issue} issue:\n\n"
        f"{steps_text}\n\n"
        "Reply YES when done, or STUCK if a step isn't working."
    )

    sent = await _send_reply(phone, message, channel)

    db = await asyncpg.connect(normalize_dsn(DATABASE_URL))
    try:
        session_id = str(uuid.uuid4())
        await db.execute("""
            INSERT INTO klaravex_sms_sessions
              (id, phone, client_id, ticket_id, channel, issue, current_step, attempt_count, steps_sent, status)
            VALUES ($1, $2, $3, $4, $5, $6, 0, 1, $7, 'active')
        """, session_id, phone, client_id, ticket_id, channel, issue,
            json.dumps([{"attempt": 1, "steps": steps, "sent": sent}]))
        log.info("resolver session started id=%s phone=%s", session_id, phone)
        return {"session_id": session_id, "steps_sent": steps, "sms_sent": sent}
    finally:
        await db.close()


async def handle_reply(phone: str, reply: str, channel: str = "sms") -> dict[str, Any]:
    """Process a client reply (YES/STUCK/DONE/FIXED) for their active session.

    channel: originating channel of the inbound message — "sms" or "whatsapp".
    When a session already exists, its stored channel takes precedence for outbound
    replies so the client always gets a response on the same channel they opened.
    If no session exists, the supplied channel is used for the no-session notice.
    """
    db = await asyncpg.connect(normalize_dsn(DATABASE_URL))
    try:
        session = await db.fetchrow("""
            SELECT * FROM klaravex_sms_sessions
            WHERE phone = $1 AND status = 'active'
            ORDER BY created_at DESC LIMIT 1
        """, phone)

        if not session:
            await _send_reply(phone,
                "Hi, this is Klaravex support. It looks like you don't have an active support session. "
                "Call +1 (424) 348-6010 or email support@klaravex.com to get started.",
                channel)
            return {"action": "no_session"}

        reply_lower = reply.lower().strip()
        session_id = str(session["id"])
        steps_sent = json.loads(session["steps_sent"])
        attempt_count = session["attempt_count"]

        # Use the channel stored on the session — the client opened it on that channel
        # and expects replies there, regardless of which channel this inbound arrived on.
        reply_channel = session["channel"] or channel

        # Resolved
        if any(w in reply_lower for w in ("done", "fixed", "resolved", "working", "yes", "ok", "works")):
            await db.execute("""
                UPDATE klaravex_sms_sessions SET status='resolved', updated_at=now() WHERE id=$1
            """, session_id)
            await _send_reply(phone,
                "Great — glad we got that sorted! For $24/month you get unlimited support like this "
                "plus device monitoring. Interested? Reply YES or call +1 (424) 348-6010.",
                reply_channel)
            return {"action": "resolved", "session_id": session_id}

        # Stuck — try again or escalate
        if any(w in reply_lower for w in ("stuck", "no", "doesn't work", "not working", "help", "failed")):
            if attempt_count >= MAX_ATTEMPTS:
                # Escalate
                await db.execute("""
                    UPDATE klaravex_sms_sessions SET status='escalated', updated_at=now() WHERE id=$1
                """, session_id)
                await _send_reply(phone,
                    "No problem — a specialist from our team will review your case and follow up "
                    "within 24 hours. You will hear from us at this number or by email.",
                    reply_channel)
                return {"action": "escalated", "session_id": session_id}

            # Generate new steps
            new_steps = await _generate_steps(
                session["issue"],
                await _query_kb(session["issue"]),
                attempt=attempt_count
            )
            steps_text = "\n".join(new_steps)
            message = (
                f"Let's try a different approach:\n\n{steps_text}\n\n"
                "Reply YES when done, or STUCK if this still isn't working."
            )
            sent = await _send_reply(phone, message, reply_channel)

            steps_sent.append({"attempt": attempt_count + 1, "steps": new_steps, "sent": sent})
            await db.execute("""
                UPDATE klaravex_sms_sessions
                SET attempt_count = attempt_count + 1,
                    steps_sent = $2,
                    updated_at = now()
                WHERE id = $1
            """, session_id, json.dumps(steps_sent))

            return {"action": "retry", "attempt": attempt_count + 1, "session_id": session_id}

        # Unclear reply — prompt them
        await _send_reply(phone,
            "Reply YES if the steps worked, or STUCK if you need a different approach.",
            reply_channel)
        return {"action": "prompted", "session_id": session_id}

    finally:
        await db.close()
