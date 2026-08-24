"""OpenAI function-calling tool definitions for the Klaravex voice pipeline.

Each tool maps to a Vapi handler at http://100.75.10.114:8002/api/v1/vapi/{name}.

Usage:
    from tools_registry import TOOL_DEFINITIONS, execute_tool
    result = await execute_tool("open_ticket", {"subject": "VPN down", ...})
"""
from __future__ import annotations

import json, logging, os
from typing import Any

import httpx

log = logging.getLogger("klaravex.voice.tools")
VAPI_API_BASE = os.environ.get("VAPI_API_BASE", "https://api.klaravex.com/api/v1/vapi")
VAPI_SHARED_SECRET = os.environ.get("VAPI_SHARED_SECRET", "")
_HTTP_TIMEOUT = 12.0


def _p(desc: str, typ: str = "string", **kw: Any) -> dict[str, Any]:
    """Build a JSON Schema property dict."""
    d: dict[str, Any] = {"type": typ, "description": desc}
    d.update(kw)
    return d


def _fn(name: str, desc: str, props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """Build an OpenAI function-calling tool entry."""
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required},
    }}


# ── Definitions ──────────────────────────────────────────────────────

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    _fn("payment_link",
        "Generate a Stripe payment link for a service SKU and deliver it via SMS or email.",
        {"sku":              _p("Product SKU, e.g. 'per-incident', 'essentials', 'resume-basic'."),
         "caller_email":     _p("Caller's email for checkout pre-fill and delivery."),
         "caller_phone":     _p("Caller's phone in E.164 for SMS delivery."),
         "delivery":         _p("Delivery channel. Defaults to 'sms'.", enum=["sms", "email"]),
         "call_sid":         _p("Active call session ID."),
         "job_loss_attested": _p("Caller attested recent job loss (50% discount on eligible SKUs).", "boolean")},
        ["sku"]),

    _fn("lookup_client",
        "Authenticate a B2B client by their 6-8 digit customer code. Returns trust level and metadata.",
        {"customer_code": _p("6-8 digit customer code entered or spoken by the caller."),
         "caller_phone":  _p("Caller's phone number for trust-level verification."),
         "call_sid":      _p("Active call session ID.")},
        ["customer_code"]),

    _fn("escalate_to_anthony",
        "Escalate to a human. Pages via Telegram/email, optionally bridges the live call.",
        {"reason":      _p("Why the caller needs a human, e.g. 'billing dispute'."),
         "summary":     _p("Brief summary of the call so far for the human."),
         "severity":    _p("Urgency level. Defaults to 'high'.", enum=["low", "high", "critical"]),
         "bridge_call": _p("True to dial Anthony and bridge into the live call.", "boolean"),
         "call_sid":    _p("Active call session ID.")},
        ["reason"]),

    _fn("send_booking_link",
        "Send a Calendly discovery-call booking link to the caller via SMS or email.",
        {"caller_email": _p("Email address to send the booking link to."),
         "caller_phone": _p("Phone number for SMS delivery."),
         "company":      _p("Caller's company name for personalizing the message."),
         "lead_id":      _p("Lead UUID if one was created during this call."),
         "call_sid":     _p("Active call session ID.")},
        []),

    _fn("start_troubleshooting",
        "Start a KB-driven troubleshooting session. Creates a ticket and returns the first step.",
        {"issue_description": _p("What the caller described as their problem."),
         "caller_email":      _p("Caller's email for ticket creation."),
         "sku":               _p("Service SKU, defaults to 'per-incident'."),
         "call_sid":          _p("Active call session ID.")},
        ["issue_description"]),

    _fn("open_ticket",
        "Create a support ticket from the voice call (advice notes, work requests, callbacks, security).",
        {"archetype":    _p("Ticket type.", enum=["advice_note", "work_request", "callback",
                                                   "security_note", "unauthenticated_callback"]),
         "subject":      _p("Short ticket subject line (max 200 chars)."),
         "summary":      _p("Detailed summary of the issue or request."),
         "client_id":    _p("Client UUID if authenticated via lookup_client."),
         "client_email": _p("Client email (required if client_id is missing)."),
         "severity":     _p("Priority. Auto-set by archetype if omitted.", enum=["P1", "P2", "P3", "P4"]),
         "pillar":       _p("Service pillar.", enum=["managed_security", "microsoft_365",
                             "regulatory_readiness", "ai_adoption", "strategic_advisory",
                             "infrastructure_support"]),
         "caller_phone": _p("Caller's phone number."),
         "call_sid":     _p("Active call session ID.")},
        ["archetype", "subject"]),

    _fn("search_knowledge_vault",
        "Search the Klaravex knowledge base for decisions, change records, and technical notes.",
        {"query": _p("Natural-language search query."),
         "limit": _p("Max results to return (1-5, default 3).", "integer")},
        ["query"]),

    _fn("advise_client",
        "Ask a pillar engineer a domain question on behalf of an authenticated business caller.",
        {"call_sid":       _p("Active call session ID."),
         "customer_code":  _p("6-digit customer code (re-verified server-side)."),
         "caller_phone":   _p("Caller's phone number for trust-level verification."),
         "question":       _p("The domain question the caller asked."),
         "trust_hint":     _p("Best read on trust from prior lookup_client ('full' or 'verify').")},
        ["customer_code", "question"]),

    _fn("create_b2b_lead",
        "Capture a new-business caller's qualifying info and create a B2B lead record.",
        {"call_sid":          _p("Active call session ID."),
         "company":           _p("Company name (required)."),
         "caller_name":       _p("Caller's full name."),
         "caller_role":       _p("Caller's role or title."),
         "seat_count":        _p("Number of seats/employees.", "integer"),
         "current_it_setup":  _p("Description of their current IT environment."),
         "pain_points":       _p("What problems they're facing."),
         "urgency":           _p("How urgent — e.g. 'immediate', 'this quarter'."),
         "phone":             _p("Caller's phone number."),
         "email":             _p("Caller's email address."),
         "notes":             _p("Free-form notes from the conversation.")},
        ["company"]),

    _fn("create_intake_lead",
        "Capture a new caller's contact info, need, and urgency, then route to the correct intake handler.",
        {"name":            _p("Caller's full name."),
         "email":           _p("Caller's email address."),
         "phone":           _p("Caller's phone number."),
         "segment":         _p("Caller segment.", enum=["consumer", "b2b"]),
         "need":            _p("What the caller needs help with (2-2000 chars)."),
         "urgency":         _p("How urgent the request is.", enum=["low", "medium", "high", "critical"]),
         "company_name":    _p("Company name (required for b2b segment)."),
         "employee_count":  _p("Number of employees (b2b only).", "integer")},
        ["name", "email", "need"]),

    _fn("start_rustdesk_session",
        "Start a RustDesk remote-support session with the caller.",
        {"customer_email":       _p("Caller's email address."),
         "problem_summary":      _p("Short summary of the issue (3-500 chars)."),
         "customer_region":      _p("Caller's region.", enum=["us", "eu", "other"]),
         "customer_rustdesk_id": _p("Caller's 9-digit RustDesk ID.")},
        ["customer_email", "problem_summary", "customer_rustdesk_id"]),

    _fn("send_support_link",
        "Send the Klaravex remote-support page link (support.klaravex.com) via SMS or email.",
        {"call_sid":           _p("Active call session ID."),
         "caller_phone":       _p("Caller's phone number for SMS delivery."),
         "caller_email":       _p("Caller's email for email delivery."),
         "caller_first_name":  _p("Caller's first name for personalizing the message."),
         "delivery":           _p("Delivery channel.", enum=["sms", "email", "both"])},
        []),

    _fn("log_session_outcome",
        "Log the outcome of a specialist voice session (called at end of every consumer call).",
        {"call_sid":          _p("Active call session ID."),
         "specialist":        _p("Which specialist is logging the outcome."),
         "outcome":           _p("Session outcome.", enum=["resolved", "fixed", "needs_followup",
                                  "couldnt_fix", "escalated", "abandoned", "caller_hung_up"]),
         "notes":             _p("1-3 sentence summary of what happened."),
         "duration_seconds":  _p("Call duration in seconds.", "integer")},
        ["call_sid", "specialist", "outcome"]),

]

# ── VIP pre-check (called directly, not through LLM) ────────────────

async def check_vip(caller_number: str, call_sid: str) -> dict:
    """Pre-greeting VIP check — fail-open."""
    url = f"{VAPI_API_BASE}/vip_access"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if VAPI_SHARED_SECRET:
        headers["x-vapi-secret"] = VAPI_SHARED_SECRET
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(url, json={
                "from_number_e164": caller_number,
                "call_sid": call_sid,
            }, headers=headers)
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        log.warning("VIP check failed (fail-open): %s", e)
    return {"is_vip": False}


# ── Dispatcher ───────────────────────────────────────────────────────

_ENDPOINT_MAP = {
    "search_knowledge_vault": "search-knowledge-vault",
    "vapi_vip_access": "vip_access",
    "send_payment_link": "payment_link",
}
# Accept both canonical names and LLM-hallucinated aliases
_VALID_TOOLS = {t["function"]["name"] for t in TOOL_DEFINITIONS} | {
    "vapi_vip_access", "send_payment_link",
    "transfer_to_biz_intake", "transfer_to_specialist",
}

# Stub responses for hallucinated transfer tools
_STUB_RESPONSES: dict[str, str] = {
    "transfer_to_biz_intake": '{"result": "STOP CALLING THIS TOOL. Transfers are disabled. YOU are the business intake. Ask the caller about their company and IT needs directly."}',
    "transfer_to_specialist": '{"result": "STOP CALLING THIS TOOL. Transfers are disabled. YOU are the specialist. Help the caller directly."}',
    "check_payment_status": '{"result": "Payment not yet received. Ask the caller if they have completed the payment link you sent to their email."}',
}


async def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """Call the Vapi HTTP API for *name* and return the JSON response string."""
    if name not in _VALID_TOOLS:
        return json.dumps({"error": f"unknown tool: {name}"})

    # Return stub for hallucinated transfer tools
    if name in _STUB_RESPONSES:
        return _STUB_RESPONSES[name]

    endpoint = _ENDPOINT_MAP.get(name, name)
    url = f"{VAPI_API_BASE}/{endpoint}"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if VAPI_SHARED_SECRET:
        headers["x-vapi-secret"] = VAPI_SHARED_SECRET

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(url, json=arguments, headers=headers)
            resp.raise_for_status()
            return resp.text
    except httpx.TimeoutException:
        log.warning("tool %s timed out at %s", name, url)
        return json.dumps({"error": f"tool '{name}' timed out"})
    except httpx.HTTPStatusError as exc:
        log.warning("tool %s http %s: %s", name, exc.response.status_code, exc.response.text[:200])
        return json.dumps({"error": f"tool '{name}' returned {exc.response.status_code}"})
    except Exception as exc:
        log.exception("tool %s failed: %s", name, exc)
        return json.dumps({"error": f"tool '{name}' failed: {exc}"})
