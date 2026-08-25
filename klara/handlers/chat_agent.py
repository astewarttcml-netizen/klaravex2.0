"""Agentic web chat backend — tool-calling parity with the Vapi phone assistants.

Full build-out (loki-mode, 2026-07-16): the web chat widget on klaravex.com
(business) and personal.klaravex.com (consumer) previously talked to a
stateless, tool-less KB-lookup endpoint (see main.py git history). This
module gives it real conversation state plus the same capabilities the Vapi
phone assistants have — payment links, a real RustDesk remote-session
kickoff, lead intake, escalation, scam-is-free routing — by reusing the
EXISTING tool implementations Vapi's tool_call.py dispatches to, called
directly in-process (no HTTP round trip, no Vapi-specific envelope).

Session state lives in klaravex_chat_agent_sessions (migration 030) keyed by
the session_token the widget already generates via /api/v1/chat/start and
already sends on every /api/v1/chat/message call — the old handler just
never read it.

Portal session bridging (2026-07-26): when a logged-in portal customer uses
the chat widget, the handler accepts the `klaravex_portal` cookie value,
validates it server-side against klaravex_portal_tokens, and if valid
pre-populates the agent's context with the client's profile (name, email,
subscription tier, open/recent tickets).  This skips the anonymous
lookup_client / payment-gate flow for recognised portal users.
"""

import hashlib
import json
import logging
import os
import re
from typing import Any

from .lib.db import get_pool

log = logging.getLogger("klaravex.chat_agent")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# LLM calls route through the local LiteLLM proxy (:8000, Anthropic
# /v1/messages served — 2026-08-21: migrated off fcc-server :8090), NOT
# directly to the Anthropic API. ANTHROPIC_API_KEY doubles as the proxy
# auth key (set to the LiteLLM master key in the worker .env).
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://host.docker.internal:8000").rstrip("/")
CHAT_AGENT_MODEL = os.environ.get("CHAT_AGENT_MODEL", "local-qwen-coder")
MAX_STORED_MESSAGES = 40   # trim oldest turns beyond this per session
MAX_TOOL_ITERATIONS = 4    # safety cap on tool-calling round-trips per user turn
MAX_OUTPUT_TOKENS = 700    # chat replies should stay short — this is a widget, not an essay

# ---------------------------------------------------------------------------
# System prompts — business vs personal, mirroring the Vapi Triage assistant's
# tone split (klara-widget-DEPLOYED.js vs klara-personal-DEPLOYED.js copy) and
# its scam/identity-theft-is-free exception (added to Triage's prompt this
# session — must stay consistent across every Klaravex-AI surface).
# ---------------------------------------------------------------------------

# Scam/identity-theft-is-free exception, split per surface. The BUSINESS
# surface keeps paging Anthony (escalate_to_anthony). The PERSONAL surface
# routes exclusively to Sam's Identity Recovery team (escalate_to_sam) and
# collects reachable contact details so Sam can actually follow up.
_SCAM_EXCEPTION_PERSONAL = """
EXCEPTION — SCAM / IDENTITY THEFT / FRAUD / ACCOUNT TAKEOVER IS FREE.
Use this ONLY for: an active scam call/text in progress, identity theft,
confirmed account takeover (email/bank locked out by an attacker), or
suspected fraud where money/credentials were already stolen.

Do NOT use this for: "spyware" worries, slow computer, malware concern,
virus suspicion, pop-ups, or "I think I have something bad on my Mac/PC"
when there is no active scam or stolen-account story. Those are normal
paid per-incident sessions (Apple/Windows cleanup) — diagnose first, then
the $29 paid flow below. Never invent an "Identity Recovery team is contacting
you" handoff for a slow-Mac / spyware-worry case.

When the free exception DOES apply: do NOT collect payment and do NOT call
send_payment_link. Say something like: "This one's on us — no charge for
this, let's get you help right now." Collect a reachable email (and phone
if they'll share it). Then call escalate_to_sam with severity="critical"
and caller_email, caller_phone, and caller_name, plus a summary that names
the scam/takeover. Keep talking warmly while help is dispatched. Never say
they were "obviously scammed" — be gentle: "That does sound like something
to be careful about, let's get you help right away."
""".strip()

_SCAM_EXCEPTION_BUSINESS = """
EXCEPTION — SCAM / IDENTITY THEFT / FRAUD / ACCOUNT TAKEOVER IS FREE.
Use this ONLY for active scam, identity theft, account takeover, or
suspected fraud with stolen credentials/money — NOT for generic malware
or slow-PC worries.

Do NOT collect payment and do NOT call send_payment_link. Say something
like: "This one's on us — no charge for this, let's get you help right
now." Then call escalate_to_anthony with severity="critical" and a summary
that mentions the scam, and keep talking warmly while help is paged. Never
tell someone they were "obviously scammed" — be gentle: "That does sound
like something to be careful about, let's get you help right away."
""".strip()

PERSONAL_SYSTEM_PROMPT = f"""
You are Klara, Klaravex's AI tech support assistant, chatting in the website
widget on personal.klaravex.com. The person you're chatting with is a real
consumer, often not very technical, sometimes older or anxious about
something being broken. Be warm, plain-English, patient. Never say
"simply", "just", or "easy" — they make people feel worse when something
isn't working for them. Never say "router" — say "your internet box."

{_SCAM_EXCEPTION_PERSONAL}

HOW THIS WORKS (there is no phone-transfer squad in chat — you handle the
whole thing yourself, continuously, in one thread):
1. Ask what device (Windows / Mac / iPhone or iPad / Android / other) and
   what's wrong, in their own words.
2. Confirm back what you heard in one short message before doing anything
   else.
3. DIAGNOSE BEFORE ANY PAYMENT TALK (except the free scam/takeover
   exception above). Ask 1–3 short triage questions (when it started,
   pop-ups or odd extensions, recent downloads/installs, constant vs
   only during certain tasks). Then name the likely issue in plain
   English (e.g. "sounds like a slow-Mac / possible malware cleanup").
   Slow Mac + virus/spyware worry = paid Apple cleanup — NOT Identity
   Recovery. Do NOT ask for email or money until you've done this light
   diagnosis. Do NOT give DIY fix steps ("try restarting", "click X")
   before payment either.
4. ONLY AFTER that diagnosis: offer the paid session — flat $29, no
   matter how long it takes, full refund if it doesn't get sorted. Ask
   for their email. Once you have it, call send_payment_link with
   sku="per-incident" (or the right subscription SKU if that's what they
   asked about — essentials, family-senior, home-membership,
   resume-basic/premium/executive, tech-kit, solo-launch, ai-coaching,
   identity-privacy, deep-clean, fresh-start) and caller_email. Tell them
   you emailed TWO links in ONE email: the payment page, and
   https://support.klaravex.com for remote help after they pay. Repeat
   their exact email from the tool result (klara_say / caller_email).
   If send_payment_link fails, say so briefly, offer one retry or
   +1 (424) 348-6010 — do NOT pivot into a free malware walkthrough.
5. After they say they paid, you MUST call check_payment_status. If
   paid is not true, do NOT congratulate them — say you don't see the
   payment yet, they can wait a minute or open the payment link again.
   Promotion codes (e.g. E2EFREE) are entered on the Stripe page.
6. Once paid=true: malware / pop-ups / slow Mac / "virus" needs screen
   control. Call start_remote_session with their email and a short
   problem summary, then tell them to open https://support.klaravex.com
   (same link already in the payment email), download Klaravex Support
   for Mac, open it, and click yes if the Mac asks. Do NOT start a
   DIY Chrome walkthrough. You may also call open_support_ticket.
7. Returning customers: if they mention a customer code or ask "do you have
   my info on file", call lookup_client with whatever code/phone they give.
8. At the end of a resolved or handed-off session, call log_session_outcome
   with a short outcome summary.

You also have search_knowledge_base — use it any time you want to ground an
answer in Klaravex's actual published guidance (pricing pages, how-to
articles) instead of guessing.

NEW-LEAD / JUST BROWSING: if they're asking about pricing or "what do you
offer" rather than describing something broken, just answer naturally from
what you know (per-incident $29, Essentials $29/mo, Family & Senior
$39/mo) — no need to open a ticket for casual browsing.

JOB-LOSS DISCOUNT: if someone mentions they were recently laid off, lost
their job, or are actively job-hunting AND they're asking about AI Skills
Coaching (ai-coaching) or a Resume/Job-Hunt Kit (resume-basic, resume-premium,
resume-executive), briefly acknowledge it and ask one direct question: "Were
you recently laid off or are you actively job-searching right now?" If they
confirm yes, let them know there's a 50% discount for people in that
situation — no documentation needed, just their word. Then call
send_payment_link with job_loss_attested=true for the relevant SKU.
Do NOT apply this discount for any other SKU or if they don't explicitly
confirm job loss.

Never claim to be a human. If asked, say plainly: "I'm Klara, Klaravex's AI
assistant." If they want a human, call escalate_to_anthony with
reason="human_requested" and explain that Klaravex's human team responds by
email within one business day — there's no live phone hand-off from chat.

Keep messages short — this is a chat window, not a phone call or an essay.
One idea per message. Use **bold** for emphasis (the widget renders it).
Write bare URLs plainly (e.g. "https://support.klaravex.com") — do NOT use
markdown link syntax like [text](url), the widget does not render it.

HARD OUTPUT RULES (never break these):
- When confirming email, restate the EXACT address they typed. Copy it
  from send_payment_link's caller_email field. NEVER write [EMAIL],
  [YOUR EMAIL], [NAME], [PHONE], or any other bracketed placeholder.
- Do NOT invent titles or gender from an email ("Mr. Stewart", "Mrs.").
  Use their first name only if they gave one; otherwise say "you" / "your".
- Never claim a specialist team "will call you shortly" unless you just
  successfully called escalate_to_sam or escalate_to_anthony for a real
  free-scam/takeover or human_requested case.
""".strip()

BUSINESS_SYSTEM_PROMPT = f"""
You are Klara, Klaravex's AI assistant, chatting in the website widget on
klaravex.com — a B2B managed IT / security / compliance-readiness provider.
The person chatting is evaluating Klaravex or already a client. Be
professional, efficient, confident — a business buyer, not someone afraid
of technology.

{_SCAM_EXCEPTION_BUSINESS}

YOUR JOB: answer honestly, then qualify and route — you do not close deals
or negotiate pricing yourself.
1. For general questions about services/pricing/what Klaravex does, answer
   briefly from what you know: Klaravex leads with the Directive tier
   (compliance + MDR + vCISO), Foundation and Assurance also exist; HIPAA /
   SOC 2 / ISO 27001 readiness, Microsoft 365 / Google Workspace / AWS,
   Ubiquiti UniFi network management. Use search_knowledge_base to ground
   specifics instead of guessing.
2. The moment they show real buying intent (want a quote, want to talk to
   someone, ready to sign up, have a compliance deadline, describe their
   company's IT situation) — collect: company name, their name/role, rough
   employee/seat count, current IT setup in one sentence, their pain
   point, and urgency (not urgent / this week / today / right now). Then
   call create_b2b_lead with everything you collected.
3. Immediately after create_b2b_lead succeeds, call send_booking_link so
   they can grab a time on the calendar directly — that's the fastest path
   to a real conversation with Anthony's team.
4. If it's clearly urgent (active security incident, breach in progress,
   ransomware, "we're locked out right now") — skip the full intake. Call
   escalate_to_anthony immediately with severity="critical" and a one-line
   summary, then tell them help is being paged right now.
5. Existing clients asking for support on something under contract: use
   lookup_client if they give you a code, otherwise escalate_to_anthony
   describing what they need.

Never invent numbers you don't actually have (uptime %, staff count,
specific case studies) — speak in ranges/facts you know. Never claim to be
human; if asked, say "I'm Klara, Klaravex's AI assistant."

Keep messages tight and professional. Use **bold** for emphasis; write bare
URLs (no markdown link syntax — the widget does not render [text](url)).
Never write a bracketed placeholder like "[EMAIL]" in a reply — restate the
actual address they gave you, or just say "your email". Do not invent
Mr./Mrs. from an email local-part.
""".strip()


def system_prompt_for(is_business: bool) -> str:
    return BUSINESS_SYSTEM_PROMPT if is_business else PERSONAL_SYSTEM_PROMPT


_PLACEHOLDER_RE = re.compile(
    r"[\[\(\{<【［](?:YOUR\s+)?(?:EMAIL|NAME|PHONE|NUMBER|ADDRESS|COMPANY)[\]\)\}>】］]",
    re.I,
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_MR_MS_FROM_EMAIL_RE = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss)\.\s+[A-Z][a-z]+\b",
)


def _last_customer_email(working: list[dict[str, Any]]) -> str | None:
    """Prefer send_payment_link's caller_email, else last user-typed address."""
    for msg in reversed(working):
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") == "send_payment_link":
                    em = (block.get("input") or {}).get("caller_email")
                    if isinstance(em, str) and "@" in em:
                        return em.strip()
        if msg.get("role") == "user" and isinstance(content, str):
            found = _EMAIL_RE.findall(content)
            if found:
                return found[-1]
    return None


def _sanitize_customer_facing(text: str, *, email: str | None = None) -> str:
    """Strip leaked model placeholders / invented honorifics before the widget sees them."""
    replacement = email.strip() if email and "@" in email else "your email"
    out = _PLACEHOLDER_RE.sub(replacement, text)
    out = _MR_MS_FROM_EMAIL_RE.sub("you", out)
    return out


# ---------------------------------------------------------------------------
# Tool schemas (Anthropic tool-calling format)
# ---------------------------------------------------------------------------

_CONSUMER_SKUS = [
    "per-incident", "essentials", "family-senior", "home-membership",
    "resume-basic", "resume-premium", "resume-executive", "tech-kit",
    "solo-launch", "ai-coaching", "identity-privacy", "deep-clean", "fresh-start",
]

TOOLS_PERSONAL: list[dict[str, Any]] = [
    {
        "name": "send_payment_link",
        "description": (
            "Create a Stripe checkout link and email it. Also emails the "
            "RustDesk remote-support page (https://support.klaravex.com) in a "
            "second message. Always call this once you have their email."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string", "enum": _CONSUMER_SKUS},
                "caller_email": {"type": "string", "description": "Customer's email address"},
                "job_loss_attested": {
                    "type": "boolean",
                    "description": (
                        "Set to true ONLY when the customer has explicitly confirmed "
                        "they were recently laid off or are actively job-seeking AND the "
                        "SKU is ai-coaching or resume-basic/premium/executive. "
                        "Applies a 50% job-loss discount. Do not infer — they must confirm it."
                    ),
                },
            },
            "required": ["sku", "caller_email"],
        },
    },
    {
        "name": "send_support_link",
        "description": (
            "Email the RustDesk remote-support page (https://support.klaravex.com). "
            "Call this after payment is confirmed if they did not get the download "
            "email, or anytime they ask for the remote-help link."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "caller_email": {"type": "string"},
            },
            "required": ["caller_email"],
        },
    },
    {
        "name": "check_payment_status",
        "description": (
            "Check Stripe for this chat session. You MUST call this after they "
            "say they paid. Only treat payment as done if the result has paid=true. "
            "If paid=false, say you do not see it yet — never congratulate."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "open_support_ticket",
        "description": "Open a support ticket and get a KB-grounded starting point for troubleshooting. Call this once payment is confirmed, before walking the customer through fix steps.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device": {"type": "string", "enum": ["windows", "mac", "iphone", "ipad", "android", "other"]},
                "issue": {"type": "string", "description": "Short plain-English description of the problem"},
            },
            "required": ["device", "issue"],
        },
    },
    {
        "name": "start_remote_session",
        "description": "Start a real RustDesk remote-control session so a human/AI can see and control the customer's screen. Only use when a spoken/typed walkthrough genuinely isn't enough. Returns a download link and instructions to read back verbatim (adapted to chat).",
        "input_schema": {
            "type": "object",
            "properties": {
                "caller_email": {"type": "string"},
                "problem_summary": {"type": "string", "description": "3-500 char plain-English summary"},
                "region": {"type": "string", "enum": ["us", "eu", "other"], "default": "us"},
            },
            "required": ["caller_email", "problem_summary"],
        },
    },
    {
        "name": "lookup_client",
        "description": "Look up a returning customer by their customer code or phone number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_code": {"type": "string"},
                "caller_phone": {"type": "string"},
            },
        },
    },
    {
        "name": "escalate_to_anthony",
        "description": "Page the Klaravex team for an emergency, active scam, or when the customer explicitly asks for a human. Not a live transfer — async page; non-urgent asks get an email reply within one business day.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "summary": {"type": "string"},
                "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            },
            "required": ["reason", "summary", "severity"],
        },
    },
    {
        "name": "escalate_to_sam",
        "description": "Escalate an active scam, identity theft, suspected fraud, or account-compromise case to Sam's Identity Recovery team. Used ONLY for the personal surface scam exception — the case is free, no payment collected. Alerts Sam's team by email and opens a Critical support ticket.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "summary": {"type": "string"},
                "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "caller_email": {"type": "string", "description": "Customer's reachable email address so Sam's team can follow up. Collect it if not already known."},
                "caller_phone": {"type": "string", "description": "Customer's phone number, if they're willing to share it."},
                "caller_name": {"type": "string", "description": "Customer's name."},
            },
            "required": ["reason", "summary", "severity"],
        },
    },
    {
        "name": "log_session_outcome",
        "description": "Record the outcome of this chat session at the end.",
        "input_schema": {
            "type": "object",
            "properties": {
                "outcome": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["outcome"],
        },
    },
    {
        "name": "search_knowledge_base",
        "description": "Search Klaravex's published knowledge base / pricing articles to ground an answer in real content.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
]

TOOLS_BUSINESS: list[dict[str, Any]] = [
    {
        "name": "create_b2b_lead",
        "description": "Create a B2B lead record once you've collected company/contact/need/urgency details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company": {"type": "string"},
                "caller_name": {"type": "string"},
                "caller_role": {"type": "string"},
                "seat_count": {"type": "integer"},
                "current_it_setup": {"type": "string"},
                "pain_points": {"type": "string"},
                "urgency": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["company", "caller_name", "pain_points", "email"],
        },
    },
    {
        "name": "send_booking_link",
        "description": "Send the customer a Calendly booking link by email, right after creating a lead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "caller_email": {"type": "string"},
                "company": {"type": "string"},
            },
            "required": ["caller_email"],
        },
    },
    {
        "name": "lookup_client",
        "description": "Look up an existing client by their customer code.",
        "input_schema": {
            "type": "object",
            "properties": {"customer_code": {"type": "string"}, "caller_phone": {"type": "string"}},
        },
    },
    {
        "name": "escalate_to_anthony",
        "description": "Page the Klaravex team immediately for an active security incident or urgent request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "summary": {"type": "string"},
                "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            },
            "required": ["reason", "summary", "severity"],
        },
    },
    {
        "name": "search_knowledge_base",
        "description": "Search Klaravex's published knowledge base / service articles to ground an answer in real content.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
]


def tools_for(is_business: bool) -> list[dict[str, Any]]:
    return TOOLS_BUSINESS if is_business else TOOLS_PERSONAL


# ---------------------------------------------------------------------------
# Tool dispatcher — reuses the EXISTING Vapi tool implementations in-process.
# ---------------------------------------------------------------------------

async def _run_tool(name: str, args: dict[str, Any], *, session_token: str, is_business: bool) -> dict[str, Any]:
    try:
        if name == "send_payment_link":
            from .vapi.payment_link import create_payment_link, PaymentLinkRequest
            req = PaymentLinkRequest(
                sku=args.get("sku", "per-incident"),
                call_sid=session_token,
                caller_email=args.get("caller_email"),
                delivery="email",
                job_loss_attested=bool(args.get("job_loss_attested", False)),
            )
            return await create_payment_link(req)

        if name == "send_support_link":
            from .vapi.send_support_link import send_support_link, SendSupportLinkRequest
            return await send_support_link(SendSupportLinkRequest(
                call_sid=session_token,
                caller_email=args.get("caller_email", ""),
                delivery="email",
            ))

        if name == "check_payment_status":
            from .vapi.check_payment_status import check_payment_status, CheckRequest
            return await check_payment_status(CheckRequest(call_sid=session_token))

        if name == "open_support_ticket":
            from .vapi.start_troubleshooting import start_troubleshooting, TroubleshootRequest
            req = TroubleshootRequest(
                call_sid=session_token,
                caller_email=args.get("caller_email"),
                issue_description=args.get("issue", ""),
                sku="per-incident",
            )
            return await start_troubleshooting(req)

        if name == "start_remote_session":
            from rustdesk_controller.voice_tools import start_rustdesk_session, StartRequest
            req = StartRequest(
                customer_email=args["caller_email"],
                problem_summary=args.get("problem_summary", "")[:500] or "chat customer needs remote help",
                customer_region=args.get("region", "us"),
            )
            return await start_rustdesk_session(req)

        if name == "lookup_client":
            from .vapi.lookup_client import lookup_client, LookupClientRequest
            req = LookupClientRequest(
                call_sid=session_token,
                customer_code=args.get("customer_code", ""),
                caller_phone=args.get("caller_phone", ""),
            )
            return await lookup_client(req)

        if name == "escalate_to_anthony":
            from .vapi.escalate_to_anthony import escalate_to_anthony, EscalateRequest
            req = EscalateRequest(
                call_sid=session_token,
                reason=args.get("reason", "chat escalation"),
                summary=args.get("summary", ""),
                severity=args.get("severity", "high"),
                bridge_call=False,
            )
            return await escalate_to_anthony(req)

        if name == "escalate_to_sam":
            from .vapi.escalate_to_sam import escalate_to_sam, EscalateToSamRequest
            req = EscalateToSamRequest(
                call_sid=session_token,
                reason=args.get("reason", "scam escalation"),
                summary=args.get("summary", ""),
                severity=args.get("severity", "high"),
                caller_email=args.get("caller_email", ""),
                caller_phone=args.get("caller_phone", ""),
                caller_name=args.get("caller_name", ""),
            )
            return await escalate_to_sam(req)

        if name == "log_session_outcome":
            from .vapi.log_session_outcome import log_session_outcome, LogSessionOutcomeRequest
            req = LogSessionOutcomeRequest(
                call_sid=session_token,
                specialist="klara_chat",
                outcome=args.get("outcome", "unknown"),
                notes=args.get("notes"),
            )
            return await log_session_outcome(req)

        if name == "create_b2b_lead":
            from .vapi.create_b2b_lead import create_b2b_lead, CreateB2BLeadRequest
            req = CreateB2BLeadRequest(call_sid=session_token, **{
                k: v for k, v in args.items()
                if k in CreateB2BLeadRequest.model_fields
            })
            return await create_b2b_lead(req)

        if name == "send_booking_link":
            from .vapi.send_booking_link import send_booking_link, SendBookingLinkRequest
            req = SendBookingLinkRequest(
                call_sid=session_token,
                caller_email=args.get("caller_email", ""),
                company=args.get("company", ""),
            )
            return await send_booking_link(req)

        if name == "search_knowledge_base":
            from .lib import kb as kb_lib
            hits = await kb_lib.search(args.get("query", ""), k=3)
            return {
                "status": "ok",
                "results": [
                    {"title": h.get("source_title"), "url": h.get("source_url"), "excerpt": (h.get("content") or "")[:400]}
                    for h in hits
                ],
            }

        return {"status": "error", "detail": f"unknown tool: {name}"}
    except Exception as exc:  # noqa: BLE001 — tool failures must go back to the model, not crash the turn
        log.warning("chat_agent tool %s failed: %s", name, exc)
        return {"status": "error", "detail": str(exc)[:400]}


# ---------------------------------------------------------------------------
# Portal session bridge
# ---------------------------------------------------------------------------

def _hash_portal_token(plaintext: str) -> bytes:
    """SHA-256 hash of the portal session cookie value — matches portal/router.py."""
    return hashlib.sha256(plaintext.encode("utf-8")).digest()


async def resolve_portal_session(cookie_value: str | None) -> str | None:
    """Validate a klaravex_portal cookie server-side.

    Returns the authenticated email on success, None on any failure (expired,
    used, unknown, or empty).  Intentionally mirrors `_validate_session` in
    portal/router.py without importing it (avoids circular dependency between
    the chat and portal modules).

    Security: we never trust the raw cookie value — we only trust the email
    returned after the DB lookup confirms the SHA-256 hash maps to a live,
    non-expired session-purpose row.
    """
    if not cookie_value:
        return None
    try:
        token_hash = _hash_portal_token(cookie_value)
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT email
                  FROM klaravex_portal_tokens
                 WHERE token_hash = $1
                   AND purpose = 'session'
                   AND expires_at > now()
                """,
                token_hash,
            )
        return row["email"] if row else None
    except Exception as exc:  # noqa: BLE001
        log.warning("portal session bridge lookup failed: %s", exc)
        return None


async def _load_portal_client_profile(email: str) -> dict[str, Any]:
    """Fetch client profile and recent ticket summary for a verified portal user.

    Returns a dict with keys: name, email, segment, company, open_tickets,
    recent_tickets (list of subject + status strings, capped at 5).
    Falls back gracefully — a failed DB query returns minimal profile.
    """
    profile: dict[str, Any] = {"email": email}
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            client_row = await conn.fetchrow(
                "SELECT name, segment, company FROM klaravex_clients WHERE email = $1",
                email.lower(),
            )
            if client_row:
                profile.update({
                    "name": client_row["name"],
                    "segment": client_row["segment"],
                    "company": client_row["company"],
                })

            ticket_rows = await conn.fetch(
                """
                SELECT subject, status, created_at
                  FROM klaravex_tickets
                 WHERE client_email = $1
                 ORDER BY created_at DESC
                 LIMIT 5
                """,
                email.lower(),
            )
            open_count = sum(1 for r in ticket_rows if r["status"] in ("open", "escalated"))
            profile["open_tickets"] = open_count
            profile["recent_tickets"] = [
                {"subject": r["subject"], "status": r["status"]}
                for r in ticket_rows
            ]
    except Exception as exc:  # noqa: BLE001
        log.warning("portal client profile fetch failed for %s: %s", email, exc)
    return profile


def _portal_context_block(profile: dict[str, Any]) -> str:
    """Build a compact context paragraph injected at the top of the system prompt.

    This tells the agent who they're talking to without leaking internal IDs.
    """
    name = profile.get("name") or "this customer"
    email = profile["email"]
    segment = profile.get("segment") or "unknown"
    company = profile.get("company")
    open_count = profile.get("open_tickets", 0)
    recent = profile.get("recent_tickets", [])

    company_part = f" ({company})" if company else ""
    ticket_part = ""
    if recent:
        lines = "; ".join(f'"{t["subject"]}" [{t["status"]}]' for t in recent[:3])
        ticket_part = f" Recent tickets: {lines}."

    return (
        f"PORTAL SESSION ACTIVE — verified client on file.\n"
        f"Name: {name}{company_part}\n"
        f"Email: {email}\n"
        f"Tier/segment: {segment}\n"
        f"Open support tickets: {open_count}.{ticket_part}\n\n"
        f"Because this customer is already authenticated via the client portal, "
        f"do NOT ask them to verify their identity and do NOT require payment "
        f"before helping with support questions covered by their subscription. "
        f"Address them by their first name when appropriate. "
        f"If they ask about a ticket, you already have their email — use it.\n"
    )


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------

async def _load_session(
    session_token: str,
    *,
    origin: str,
    is_business: bool,
) -> tuple[list[dict[str, Any]], str | None]:
    """Load chat history for this session.  Returns (messages, stored_client_email).

    stored_client_email is non-None when a previous turn already stamped the
    portal-verified email onto the session row — so we can restore portal
    context even if the cookie is absent on this turn (e.g. widget re-opened).
    """
    if not session_token:
        return [], None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT messages, client_email FROM klaravex_chat_agent_sessions WHERE session_token = $1",
            session_token,
        )
        if row is None:
            await conn.execute(
                """
                INSERT INTO klaravex_chat_agent_sessions (session_token, origin, is_business)
                VALUES ($1, $2, $3)
                ON CONFLICT (session_token) DO NOTHING
                """,
                session_token, origin, is_business,
            )
            return [], None
        raw = row["messages"]
        msgs = json.loads(raw) if isinstance(raw, str) else (raw or [])
        return msgs, row["client_email"]


async def _save_session(
    session_token: str,
    messages: list[dict[str, Any]],
    *,
    client_email: str | None = None,
) -> None:
    if not session_token:
        return
    trimmed = messages[-MAX_STORED_MESSAGES:]
    pool = await get_pool()
    async with pool.acquire() as conn:
        if client_email:
            # Stamp the verified portal email on the session row so subsequent
            # turns can restore portal context without re-validating the cookie.
            await conn.execute(
                """
                UPDATE klaravex_chat_agent_sessions
                SET messages = $2::jsonb, client_email = $3, updated_at = now()
                WHERE session_token = $1
                """,
                session_token, json.dumps(trimmed), client_email.lower(),
            )
        else:
            await conn.execute(
                """
                UPDATE klaravex_chat_agent_sessions
                SET messages = $2::jsonb, updated_at = now()
                WHERE session_token = $1
                """,
                session_token, json.dumps(trimmed),
            )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_chat_agent(
    *,
    message: str,
    session_token: str,
    origin: str,
    is_business: bool,
    portal_cookie: str | None = None,
) -> dict[str, Any]:
    """Run one user turn through the tool-calling agent loop.

    Returns {"reply": str, "session_token": str}. Falls back to a plain
    apology (never raises) so a Claude/DB hiccup degrades gracefully instead
    of taking the whole widget down.

    portal_cookie: raw value of the klaravex_portal session cookie forwarded
    from the HTTP request.  When present and valid, the agent receives the
    client's profile as pre-populated context and skips the anonymous
    verification / payment gate for subscription-covered requests.
    """
    if not LITELLM_BASE_URL:
        return {
            "reply": "I'm having a technical issue right now — please try again in a moment, "
                     "or reach us at " + ("hello@klaravex.com" if is_business else "hello@klaravex.com") + ".",
            "session_token": session_token,
        }

    import anthropic  # already a backend dependency (see classifier.py)

    history, stored_client_email = await _load_session(
        session_token, origin=origin, is_business=is_business
    )

    # ── Portal session bridge ────────────────────────────────────────────────
    # Priority 1: fresh cookie on this request — validate server-side.
    # Priority 2: email already stamped on the session row from a prior turn.
    # Either way: never trust the raw cookie value; only trust the DB lookup.
    portal_email: str | None = await resolve_portal_session(portal_cookie)
    if portal_email:
        log.info(
            "chat portal bridge (cookie): session=%s email=%s",
            session_token[:8] + "…",
            portal_email,
        )
    elif portal_cookie:
        # Cookie present but invalid/expired — log for audit, fall through silently.
        log.info(
            "chat portal bridge: cookie present but invalid/expired session=%s",
            session_token[:8] + "…",
        )

    # Fall back to email stamped on session row (cookie may be absent on refresh).
    effective_portal_email = portal_email or stored_client_email
    portal_profile: dict[str, Any] | None = None
    if effective_portal_email:
        if not portal_email and stored_client_email:
            log.info(
                "chat portal bridge (session row): session=%s email=%s",
                session_token[:8] + "…",
                stored_client_email,
            )
        portal_profile = await _load_portal_client_profile(effective_portal_email)

    history.append({"role": "user", "content": message})

    # LLM calls route through the local fcc-server LiteLLM proxy (same path as
    # kb.py / services/litellm_client.py). ANTHROPIC_API_KEY doubles as the
    # proxy auth key (kb.py convention); "fcc-server-local" is the accepted
    # literal when the env var is unset.
    client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY or "fcc-server-local",
        base_url=LITELLM_BASE_URL,
    )
    tools = tools_for(is_business)

    # Inject portal context as a prefix to the base system prompt when verified.
    base_system = system_prompt_for(is_business)
    if portal_profile:
        system = _portal_context_block(portal_profile) + base_system
    else:
        system = base_system

    final_text = ""
    working = list(history)
    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            resp = client.messages.create(
                model=CHAT_AGENT_MODEL,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system,
                tools=tools,
                messages=working,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("chat_agent Claude call failed: %s", exc)
            final_text = ("I'm having a technical issue right now — please try again in a moment, "
                          "or email us at hello@klaravex.com.")
            break

        assistant_content = [block.model_dump() for block in resp.content]
        working.append({"role": "assistant", "content": assistant_content})

        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            final_text = "".join(b.text for b in resp.content if b.type == "text").strip()
            break

        tool_results = []
        for tu in tool_uses:
            result = await _run_tool(tu.name, tu.input or {}, session_token=session_token, is_business=is_business)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result, default=str),
            })
        working.append({"role": "user", "content": tool_results})
    else:
        # Hit MAX_TOOL_ITERATIONS without a final text response — surface
        # whatever text blocks the last response had, or a safe fallback.
        text_blocks = [b for b in working[-2].get("content", []) if isinstance(b, dict) and b.get("type") == "text"]
        final_text = " ".join(b.get("text", "") for b in text_blocks).strip()

    if not final_text:
        final_text = "Sorry, I didn't quite catch that — could you rephrase?"

    final_text = _sanitize_customer_facing(final_text, email=_last_customer_email(working))

    working.append({"role": "assistant", "content": final_text})
    await _save_session(session_token, working, client_email=effective_portal_email)

    return {
        "reply": final_text,
        "session_token": session_token,
        # portal_bridged is informational — callers can use it to adjust UI
        # (e.g. show the client's name in the widget header) without exposing
        # the raw session token or internal DB IDs.
        "portal_bridged": effective_portal_email is not None,
    }
