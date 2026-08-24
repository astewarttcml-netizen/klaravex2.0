"""Phase 12 V5 — biz_engineer advisory bridge: advise_client.

Klara (or biz_engineer voice) calls this tool when an authenticated business
caller asks a domain question — "what's our backup retention?", "how do we
prep for HIPAA?", "should we move to Entra Conditional Access?". The handler:

  1. Re-resolves the client by the customer_code the caller just typed (no
     trusting a client_id argument from the LLM — codes are the source of
     truth).
  2. Picks the matching pillar engineer via the existing dispatcher's
     scoring keywords (same logic that routes tickets).
  3. Pulls top-k KB chunks for grounding context.
  4. Calls the engineer's LLM reasoning path with a TRUST-LEVEL-AWARE
     prompt — at `verify` trust the prompt MUST NOT contain any stored
     contact data, environment readback, or seat/ticket facts.
  5. Returns a SHORT voice-friendly answer plus the routed engineer
     identity so the voice agent can credit the response in-call.

Latency target: <8s end-to-end (voice). The engineer LLM call is the
dominant cost; the prompt is intentionally tighter than the ticket
reasoning prompt.

Behind x-vapi-secret (mounted in vapi/router.py).
"""

import asyncio
import hmac
import logging
import os
import re
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..lib.agentmail_notify import notify_agent_inbox, pillar_to_agentmail_inbox

log = logging.getLogger("klaravex.vapi.advise_client")
router = APIRouter()

_CODE_RE = re.compile(r"^\d{6}$")
_PLACEHOLDER_SIDS = {"call_sid_placeholder", "1234567890", "", "{{call.id}}", "unknown"}

# Trust levels (mirrors lookup_client.py).
TRUST_FULL = "full"
TRUST_VERIFY = "verify"
TRUST_INVALID = "invalid"

# Cap KB grounding so we stay under ~8s total.
KB_TOP_K = 3
KB_CHUNK_CHAR_BUDGET = 1800


class AdviseClientRequest(BaseModel):
    call_sid: str = Field(default="")
    customer_code: str = Field(default="")
    caller_phone: str = Field(default="")
    question: str = Field(default="")
    # Klara provides her best read on trust — we re-confirm against DB.
    trust_hint: str = Field(default="")
    test: bool = Field(default=False, alias="_test")


def _route_question_to_pillar(question: str) -> tuple[str, str]:
    """Score the question against every engineer's keywords, pick the top.

    Returns (engineer_name, pillar). Falls back to strategic_advisory when
    no keyword fires (it's the deliberately broad pillar).
    """
    # Lazy import — keeps the test_handler_imports compile-check dependency-free
    # for environments without anthropic / asyncpg installed.
    from ..engineers.dispatcher import ENGINEERS

    fake_ticket = {"subject": question, "summary": "", "sku": ""}
    scored = [(e, e.matches_ticket(fake_ticket)) for e in ENGINEERS]
    scored.sort(key=lambda x: x[1], reverse=True)
    if scored and scored[0][1] > 0:
        best = scored[0][0]
        return best.name, best.pillar
    # Fallback: strategic_advisory — by design, this pillar absorbs
    # broad/uncategorized strategy questions.
    for e in ENGINEERS:
        if e.pillar == "strategic_advisory":
            return e.name, e.pillar
    # Last-resort: first engineer in registry (deterministic).
    return ENGINEERS[0].name, ENGINEERS[0].pillar


def _strip_stored_data_for_verify(prompt: str) -> str:
    """Defense-in-depth: at `verify` trust we already build a prompt that
    excludes stored contact data, but if a developer adds a `{company}` /
    `{email}` / `{phone}` placeholder by mistake we sanitize before send.

    This is positive sanitization, not just a comment.
    """
    sanitized = prompt
    for placeholder in ("{company}", "{email_on_file}", "{phone_on_file}",
                        "{open_tickets}", "{plan_tier}"):
        sanitized = sanitized.replace(placeholder, "")
    return sanitized


def _build_engineer_prompt(
    *,
    engineer_system_prompt: str,
    engineer_display_name: str,
    pillar: str,
    question: str,
    trust_level: str,
    client_company: str,
    plan_tier: str,
    kb_grounding: str,
) -> str:
    """Build the prompt sent to the engineer LLM.

    AT `verify` TRUST: company / plan_tier are blanked. The voice agent gets
    a generic answer with NO readback of stored client identity.
    """
    if trust_level == TRUST_VERIFY:
        client_block = (
            "CLIENT CONTEXT: hidden by trust gate (verify trust — caller's "
            "phone is not on file). Do NOT name a company, do NOT reference "
            "seat counts or plan tiers, do NOT echo back anything that could "
            "only have come from a record on file. Answer the question "
            "GENERICALLY as you would for any Klaravex client."
        )
    else:
        client_block = (
            f"CLIENT CONTEXT (full trust — caller verified):\n"
            f"  Company:   {client_company or 'unstated'}\n"
            f"  Plan tier: {plan_tier or 'unstated'}"
        )

    kb_block = kb_grounding or "(no KB grounding available — answer from your pillar expertise)"

    prompt = f"""
{engineer_system_prompt}

You are the {engineer_display_name} answering a LIVE VOICE call. Optimize for:
  - Spoken brevity (45-90 seconds when read aloud).
  - Concrete, actionable advice — no marketing fluff.
  - One follow-up question max, only if you cannot answer without it.

{client_block}

KNOWLEDGE BASE GROUNDING (verbatim chunks; cite by title in your answer if you use them):
{kb_block}

CALLER QUESTION:
  {question}

Output a JSON object ONLY:
{{
  "answer": "Short voice-friendly answer (2-5 sentences, plain prose, no markdown, no lists).",
  "follow_up_question": "Optional single follow-up to ask the caller, or empty string.",
  "next_action": "Optional concrete next step (e.g. 'open a ticket', 'book a 30-min review', 'no further action'). Empty string if none.",
  "citations": ["KB title 1", "KB title 2"]
}}
""".strip()

    if trust_level == TRUST_VERIFY:
        prompt = _strip_stored_data_for_verify(prompt)
    return prompt


def _voice_safe_reply(reply: dict[str, Any], engineer_display_name: str) -> str:
    """Flatten the engineer JSON to a string Klara can speak."""
    answer = (reply.get("answer") or "").strip()
    follow_up = (reply.get("follow_up_question") or "").strip()
    next_action = (reply.get("next_action") or "").strip()
    pieces = [answer] if answer else []
    if follow_up:
        pieces.append(follow_up)
    if next_action and next_action.lower() not in {"no further action", "none", ""}:
        pieces.append(f"Suggested next step: {next_action}.")
    text = " ".join(pieces) if pieces else (
        f"{engineer_display_name} could not produce an answer right now. "
        "Open a ticket and we'll follow up."
    )
    return text


@router.post("/advise_client")
async def advise_client(req: AdviseClientRequest) -> dict[str, Any]:
    if req.test:
        return {"status": "ok", "test": True, "engineer": "engineer_test", "pillar": "test"}

    question = (req.question or "").strip()
    if not question:
        return {
            "status": "error",
            "reason": "No question provided. Ask the caller to repeat the question.",
        }

    code = (req.customer_code or "").strip()
    call_sid = req.call_sid if req.call_sid not in _PLACEHOLDER_SIDS else ""

    # Re-confirm trust against DB so we never trust an LLM-provided hint.
    trust_level, client_row = await _resolve_trust(code, req.caller_phone)
    if trust_level == TRUST_INVALID:
        return {
            "status": "error",
            "trust_level": TRUST_INVALID,
            "reason": "Caller is not authenticated. Run lookup_client first.",
        }

    # Pick the engineer.
    engineer_name, pillar = _route_question_to_pillar(question)

    # Lazy imports so optional-dep test envs still pass.
    from ..engineers.dispatcher import get_engineer
    from ..lib.kb import search as kb_search

    engineer = get_engineer(engineer_name)
    if engineer is None:
        return {
            "status": "error",
            "reason": "Engineer routing failed — no matching pillar.",
        }

    # KB grounding (best-effort; on failure we ship empty grounding).
    kb_grounding = ""
    try:
        hits = await kb_search(question, k=KB_TOP_K)
        kb_grounding = _format_kb_grounding(hits)
    except Exception as exc:
        log.warning("kb_search failed for advise_client: %s", exc)

    # Build the prompt; pull client context only when full-trust.
    client_company = ""
    plan_tier = ""
    if trust_level == TRUST_FULL and client_row is not None:
        client_company = (client_row.get("name") or "")
        plan_tier = (
            client_row.get("plan_tier")
            or client_row.get("segment")
            or ""
        )

    prompt = _build_engineer_prompt(
        engineer_system_prompt=engineer.system_prompt,
        engineer_display_name=engineer.display_name,
        pillar=engineer.pillar,
        question=question,
        trust_level=trust_level,
        client_company=client_company,
        plan_tier=plan_tier,
        kb_grounding=kb_grounding,
    )

    reply = await engineer._call_claude(
        prompt,
        fallback_title=f"{engineer.display_name} voice advisory",
    )

    spoken = _voice_safe_reply(reply, engineer.display_name)

    # M8: fire-and-forget advice note to the routed engineer's AgentMail inbox.
    # Includes the full answer and citations so the engineer has async context.
    _fire_advice_note(
        call_sid=call_sid,
        engineer=engineer,
        question=question,
        reply=reply,
        spoken=spoken,
        client_company=client_company,
        trust_level=trust_level,
    )

    return {
        "status": "ok",
        "trust_level": trust_level,
        "engineer": engineer.name,
        "pillar": engineer.pillar,
        "answer": spoken,
        "citations": reply.get("citations") or [],
        "call_sid": call_sid,
    }


def _build_advice_note_body(
    *,
    call_sid: str,
    engineer_display_name: str,
    pillar: str,
    question: str,
    reply: dict[str, Any],
    spoken: str,
    client_company: str,
    trust_level: str,
) -> tuple[str, str]:
    """Return (subject, body) for the advice note email."""
    company_line = (
        f"Company : {client_company}" if client_company else "Company : (verify trust — not disclosed)"
    )
    citations = reply.get("citations") or []
    citation_block = "\n".join(f"  - {c}" for c in citations) if citations else "  (none)"
    follow_up = (reply.get("follow_up_question") or "").strip()
    next_action = (reply.get("next_action") or "").strip()

    subject = f"[Klaravex Advice] {engineer_display_name} — call {call_sid or 'unknown'}"
    body = (
        f"Engineer Advisory Note\n"
        f"{'=' * 60}\n\n"
        f"Engineer : {engineer_display_name} ({pillar})\n"
        f"Call SID : {call_sid or '(not available)'}\n"
        f"Trust    : {trust_level}\n"
        f"{company_line}\n\n"
        f"Question asked:\n  {question}\n\n"
        f"Spoken answer:\n  {spoken}\n\n"
        f"Follow-up question:\n  {follow_up or '(none)'}\n\n"
        f"Suggested next action:\n  {next_action or '(none)'}\n\n"
        f"KB citations:\n{citation_block}\n"
    )
    return subject, body


def _fire_advice_note(
    *,
    call_sid: str,
    engineer: Any,
    question: str,
    reply: dict[str, Any],
    spoken: str,
    client_company: str,
    trust_level: str,
) -> None:
    """Schedule the AgentMail notification as a background task.

    Uses asyncio.create_task so the voice call is not delayed.
    Silently skips if there is no running event loop.
    """
    inbox = pillar_to_agentmail_inbox(engineer.pillar)
    subject, body = _build_advice_note_body(
        call_sid=call_sid,
        engineer_display_name=engineer.display_name,
        pillar=engineer.pillar,
        question=question,
        reply=reply,
        spoken=spoken,
        client_company=client_company,
        trust_level=trust_level,
    )
    try:
        asyncio.create_task(notify_agent_inbox(inbox, subject, body))
    except RuntimeError:
        # No running event loop in test environments — log and skip.
        log.debug("_fire_advice_note: no event loop; skipping AgentMail notify")


def _format_kb_grounding(hits: list[dict[str, Any]]) -> str:
    """Compose KB hits into a bounded prompt block."""
    if not hits:
        return ""
    chunks: list[str] = []
    budget = KB_CHUNK_CHAR_BUDGET
    for h in hits:
        title = (h.get("source_title") or "untitled").strip()
        body = (h.get("content") or "").strip()
        if not body:
            continue
        block = f"[{title}] {body}"
        if budget - len(block) < 0:
            block = block[:max(budget, 0)]
        chunks.append(block)
        budget -= len(block)
        if budget <= 0:
            break
    return "\n---\n".join(chunks)


async def _resolve_trust(code: str, caller_phone: str) -> tuple[str, dict[str, Any] | None]:
    """Look up the client by code; decide trust from caller_phone match.

    Returns (trust_level, client_row_or_None). On DB failure we conservatively
    return ("invalid", None) — the voice agent must re-auth via lookup_client.
    """
    if not _CODE_RE.match(code):
        return TRUST_INVALID, None
    try:
        from ..lib.db import get_pool
        from .lookup_client import _phones_match
    except Exception as exc:
        log.warning("advise_client: dependency import failed (%s)", exc)
        return TRUST_INVALID, None

    try:
        pool = await get_pool()
    except Exception as exc:
        log.warning("advise_client: get_pool failed (%s)", exc)
        return TRUST_INVALID, None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name, email, phone, segment,
                   COALESCE(metadata ->> 'plan_tier', segment) AS plan_tier,
                   customer_code
              FROM klaravex_clients
             WHERE customer_code = $1
            """,
            code,
        )

    if row is None:
        return TRUST_INVALID, None

    stored_code = (row["customer_code"] or "")
    if not hmac.compare_digest(stored_code.encode("ascii"), code.encode("ascii")):
        return TRUST_INVALID, None

    client = dict(row)
    if _phones_match(caller_phone, client.get("phone") or ""):
        return TRUST_FULL, client
    return TRUST_VERIFY, client
