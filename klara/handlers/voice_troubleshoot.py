"""A9 Twilio voice: post-payment troubleshooting.

Gathers the caller's issue description via speech, runs a KB lookup via the
existing /api/v1/chat/message endpoint, and reads the answer back to the
caller via TwiML <Say>. Offers escalation if the KB answer is insufficient.

See WORKFLOWS.md §A9.5.
"""

import logging
import os
import re
from typing import Annotated

import httpx
import stripe
from fastapi import APIRouter, Form, Response

from . import voice_session_store as store

log = logging.getLogger("klaravex.voice.troubleshoot")
router = APIRouter()

BASE_URL = os.environ.get("API_BASE_URL", "https://api.klaravex.com")
# Internal base for same-process KB calls (avoid external round-trip if local)
INTERNAL_BASE = os.environ.get("INTERNAL_API_BASE_URL", "http://127.0.0.1:8002")


@router.post("/troubleshoot")
async def voice_troubleshoot(
    CallSid: Annotated[str, Form()] = "",
    From: Annotated[str, Form()] = "",
    SpeechResult: Annotated[str, Form()] = "",
    Digits: Annotated[str, Form()] = "",
) -> Response:
    """Gather issue description on first hit; look up KB and read answer back."""
    # Use pre-collected issue description if available (stored during gather_issue step)
    effective_speech = SpeechResult or store.get_value(CallSid, "issue")
    log.info("troubleshoot sid=%s speech=%r stored=%r", CallSid, SpeechResult, effective_speech)

    gather_url = f"{BASE_URL}/api/v1/voice/troubleshoot_answer"
    escalate_url = f"{BASE_URL}/api/v1/voice/escalate"
    callback_url = f"{BASE_URL}/api/v1/voice/callback_options"

    # No speech yet and nothing stored — gather the issue description
    if not effective_speech:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather action="{gather_url}" method="POST" input="speech"
          speechTimeout="5" timeout="12">
    <Say voice="Polly.Joanna">
      Let me start on your issue right now. What device, what error, and when did it start?
      Take your time.
    </Say>
  </Gather>
  <Redirect method="POST">{callback_url}</Redirect>
</Response>"""
        return Response(content=twiml, media_type="application/xml")

    SpeechResult = effective_speech

    # Have speech — run KB lookup
    kb_result = await _kb_lookup(SpeechResult)

    if kb_result is not None:
        kb_answer, citations = kb_result
        cite_line = ""
        if citations:
            titles = [c.get("title", "") for c in citations[:2] if c.get("title")]
            if titles:
                cite_line = " I found this in our knowledge base: " + "; ".join(titles) + "."

        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    Got it.{cite_line} Here's what I recommend: {kb_answer}
  </Say>
  <Gather action="{escalate_url}" method="POST" input="speech dtmf"
          timeout="12" speechTimeout="3">
    <Say voice="Polly.Joanna">
      Did that help? Press 1 or say yes if you're all set.
      Press 2 or say no and I will connect you with a tech.
    </Say>
  </Gather>
  <Redirect method="POST">{callback_url}</Redirect>
</Response>"""
        await _capture_payment(CallSid)
        return Response(content=twiml, media_type="application/xml")

    else:
        # LLM fallback: KB miss → call chat endpoint
        loki_reply = await _llm_fallback(SpeechResult, CallSid)

        if loki_reply is not None:
            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    {loki_reply}
  </Say>
  <Gather action="{escalate_url}" method="POST" input="speech dtmf"
          timeout="12" speechTimeout="3">
    <Say voice="Polly.Joanna">Did that help? Press 1 or say yes if you're all set. Press 2 or say no and I will connect you with a tech.</Say>
  </Gather>
  <Redirect method="POST">{callback_url}</Redirect>
</Response>"""
            await _capture_payment(CallSid)
        else:
            # KB miss + LLM fail — caller paid, escalate directly to a tech
            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">
    Let me connect you with a tech right now who can work through this with you.
  </Say>
  <Redirect method="POST">{escalate_url}</Redirect>
</Response>"""
        return Response(content=twiml, media_type="application/xml")


@router.post("/troubleshoot_answer")
async def voice_troubleshoot_answer(
    CallSid: Annotated[str, Form()] = "",
    From: Annotated[str, Form()] = "",
    SpeechResult: Annotated[str, Form()] = "",
) -> Response:
    """Accept the gathered issue description and route into the KB handler."""
    # Delegate back to /troubleshoot with SpeechResult filled in
    return await voice_troubleshoot(
        CallSid=CallSid,
        From=From,
        SpeechResult=SpeechResult,
        Digits="",
    )


async def _kb_lookup(query: str) -> tuple[str, list[dict]] | None:
    """Call the internal /api/v1/chat/message endpoint for a KB-grounded reply.

    Returns a (reply, citations) tuple when the KB has a real match, or None
    when nothing matched (so the caller can trigger the LLM fallback).
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{INTERNAL_BASE}/api/v1/chat/message",
                json={"message": query},
            )
            if r.status_code == 200:
                data = r.json()
                reply = data.get("reply") or ""
                citations = data.get("citations") or []
                if reply and citations:
                    # Trim to something speakable (~400 chars), breaking at a word boundary.
                    return _truncate_at_word(reply, 400), citations
    except Exception as e:  # noqa: BLE001
        log.warning("kb lookup failed: %s", e)
    # No KB match found — signal caller to use LLM fallback
    return None


# LLM fallback: KB miss → call chat endpoint
def _strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", text)


def _truncate_at_word(text: str, max_chars: int = 300) -> str:
    """Truncate text to max_chars, breaking at the last word boundary."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated


_NEGATIVE_REPLY_PATTERNS = (
    "no knowledge-base",
    "no knowledge base",
    "no article",
    "no match",
    "couldn't find",
    "can't find",
    "cannot find",
    "not found",
    "don't have information",
    "do not have information",
    "no information",
)


def _is_negative_reply(text: str) -> bool:
    lower = text.lower()
    return any(p in lower for p in _NEGATIVE_REPLY_PATTERNS)


async def _capture_payment(call_sid: str) -> None:
    """Capture the manually-authorized payment after diagnosis is delivered."""
    if not stripe.api_key or not call_sid:
        return
    try:
        sessions = stripe.checkout.Session.list(limit=20)
        for session in sessions.auto_paging_iter():
            meta = session.get("metadata") or {}
            if meta.get("call_sid") == call_sid and session.get("payment_status") == "paid":
                pi_id = session.get("payment_intent")
                if pi_id:
                    stripe.PaymentIntent.capture(pi_id)
                    log.info("payment captured sid=%s pi=%s", call_sid, pi_id)
                    return
    except Exception as e:
        log.warning("capture failed sid=%s: %s", call_sid, e)


async def _llm_fallback(query: str, call_sid: str) -> str | None:
    """Call the Klara AI chat endpoint with the caller's speech and return a
    truncated, speakable reply, or None if the call fails or returns a
    negative/internal message that shouldn't be read aloud.
    """
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.post(
                f"{BASE_URL}/api/v1/chat/message",
                json={"message": query, "session_id": call_sid},
            )
            if r.status_code == 200:
                data = r.json()
                reply = data.get("reply") or ""
                if reply:
                    reply = _strip_html(reply)
                    if _is_negative_reply(reply):
                        log.info("llm fallback negative reply sid=%s; escalating", call_sid)
                        return None
                    return _truncate_at_word(reply, 300)
    except Exception as e:  # noqa: BLE001
        log.warning("llm fallback failed sid=%s: %s", call_sid, e)
    return None
