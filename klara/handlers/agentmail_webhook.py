"""AgentMail inbound webhook handler — M7 (CANONICAL).

Receives POSTs from AgentMail when any of the 9 ai.klaravex.com inboxes
receive a message, verifies the HMAC-SHA256 signature, and routes the
payload to the appropriate agent brain by recipient local-part.

This is the authoritative implementation — mounted in infra/main.py at
prefix /api/v1/agentmail.  The variant at loki-agents/app/api/webhooks_agentmail.py
is superseded and kept only for reference (DB persistence, agent-registry
integration).

Mount with:
    from klara.handlers.agentmail_webhook import router as agentmail_router
    app.include_router(agentmail_router, prefix="/api/v1/agentmail")

Security — fail-CLOSED rules
-----------------------------
- AGENTMAIL_WEBHOOK_SECRET unset       → 503  (server misconfigured)
- X-AgentMail-Signature header missing → 401
- HMAC mismatch                        → 401  (constant-time compare)

AgentMail sends the signature as:  X-AgentMail-Signature: sha256=<hex_digest>
This handler accepts both the sha256= prefix and a bare hex digest.

All comparisons use hmac.compare_digest to defeat timing oracles.

Env vars required (Anthony-gated — Azure Container App):
  AGENTMAIL_WEBHOOK_SECRET  — shared secret from AgentMail dashboard
  Until set, the endpoint returns 503 for every request (fail-closed).

Agent inbox → brain mapping
---------------------------
  klara     → general triage / AI support coordinator
  sam       → identity & recovery
  cipher    → security engineer
  echo      → Microsoft 365 & cloud
  lex       → compliance engineer
  iris      → AI adoption engineer
  atlas     → strategy & vCIO
  workflow  → internal workflow coordination
  approvals → internal approvals queue
"""

import hashlib
import hmac
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

log = logging.getLogger("klaravex.agentmail_webhook")
router = APIRouter()

# The 9 AgentMail inboxes on ai.klaravex.com.
# Values are human-readable agent role labels used in log context and
# response payloads — they do NOT appear on consumer surfaces.
_AGENT_ROLES: dict[str, str] = {
    "klara":     "AI Support Coordinator",
    "sam":       "Identity & Recovery Engineer",
    "cipher":    "Security Engineer",
    "echo":      "Microsoft 365 & Cloud Engineer",
    "lex":       "Compliance Engineer",
    "iris":      "AI Adoption Engineer",
    "atlas":     "Strategy & vCIO",
    "workflow":  "Workflow Coordinator",
    "approvals": "Approvals Queue",
}

_ESCALATE_INBOX = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")

# Sam Identity Recovery inbound handling (M8). Case-tag markers in Atera
# ticket titles let the webhook dedupe inbound mail against the ticket
# created at chat time by escalate_to_sam, instead of opening a duplicate.
_CASE_TAG_CHAT_SCAM = "[chat-scam]"
_CASE_TAG_INBOX = "[inbox]"
_INTERNAL_SENDER_SUFFIXES = ("@klaravex.com", "@ai.klaravex.com")


def _verify_signature(body: bytes, header_value: str | None) -> None:
    """Verify HMAC-SHA256 signature from AgentMail.

    AgentMail signs the raw request body with the webhook secret and
    sends the hex digest in X-AgentMail-Signature as:
        X-AgentMail-Signature: sha256=<hex_digest>

    Both the sha256= prefix and bare hex digests are accepted so the
    handler tolerates format drift without a deploy.

    Fails CLOSED:
      - AGENTMAIL_WEBHOOK_SECRET unset → 503
      - header missing or empty        → 401
      - digest mismatch                → 401
    """
    secret = os.environ.get("AGENTMAIL_WEBHOOK_SECRET", "")
    if not secret:
        log.error("AGENTMAIL_WEBHOOK_SECRET is not set; rejecting inbound webhook")
        raise HTTPException(
            status_code=503,
            detail="agentmail webhook disabled — signing secret not configured",
        )
    if not header_value:
        raise HTTPException(status_code=401, detail="missing X-AgentMail-Signature")

    # AgentMail sends "sha256=<hex>"; also accept bare hex for forward compat.
    sig = header_value.strip()
    if sig.lower().startswith("sha256="):
        sig = sig[7:]

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="invalid signature")


def _extract_local_part(address: str) -> str:
    """Return the local-part (before @) of an email address, lowercased."""
    if not address or "@" not in address:
        return ""
    return address.split("@", 1)[0].lower().strip()


def _resolve_agent(recipient: str) -> tuple[str, str] | None:
    """Map a recipient address to (local_part, role).

    Returns None if the recipient is not one of the 9 known agent inboxes.
    Accepts either a bare local-part or a full address.
    """
    local = _extract_local_part(recipient) if "@" in recipient else recipient.lower().strip()
    if local in _AGENT_ROLES:
        return local, _AGENT_ROLES[local]
    return None


def _is_internal_sender(from_addr: str) -> bool:
    """True when the sender is a Klaravex-owned address (chat-time escalation
    email echo, internal notifications) — those cases are already tracked and
    must NOT produce a fresh Atera contact/ticket."""
    a = from_addr.strip().lower()
    return any(a.endswith(sfx) for sfx in _INTERNAL_SENDER_SUFFIXES)


def _name_from_email(display_name: str, email: str) -> tuple[str, str]:
    """Best-effort (firstname, lastname) from a display name, else the email
    local-part — Atera contacts need a name."""
    raw = (display_name or "").strip()
    if not raw and email:
        raw = email.split("@", 1)[0].replace(".", " ").replace("_", " ").strip().title()
    parts = (raw.split(" ", 1) + [""])[:2]
    return (parts[0] or "Unknown"), (parts[1] or "Client")


async def _sam_open_atera_ticket(
    from_addr: str,
    from_name: str,
    subject: str,
    body_text: str,
) -> dict[str, Any]:
    """Open (or dedupe) an Identity Recovery Atera ticket for external mail to
    sam@ai.klaravex.com.

    Dedupe: if the contact already has a [chat-scam] ticket (created at chat
    time by escalate_to_sam), do NOT open a second one — return the existing
    ticket marked deduped. Otherwise open a [inbox] ticket for this thread.

    Failures return {} so the webhook still acknowledges (202) — a down Atera
    must not create an AgentMail retry storm.
    """
    api_key = os.environ.get("ATERA_API_KEY", "")
    if not api_key:
        log.warning("agentmail sam: ATERA_API_KEY unset — no ticket opened")
        return {}

    try:
        from services.atera_client import AteraClient  # lazy — avoids import cycles

        client = AteraClient(api_key)
        customer_id = await client.get_or_create_personal_customer()
        firstname, lastname = _name_from_email(from_name, from_addr)
        contact_id = await client.get_or_create_contact(
            customer_id=customer_id,
            email=from_addr,
            firstname=firstname,
            lastname=lastname,
        )

        existing = await client.list_tickets_for_contact(contact_id, limit=10)
        for t in existing:
            if _CASE_TAG_CHAT_SCAM in (t.get("TicketTitle") or ""):
                log.info(
                    "agentmail sam: dedupe hit — existing [chat-scam] ticket",
                    extra={"ticket_id": t.get("TicketID")},
                )
                return {
                    "ticket_id": t.get("TicketID"),
                    "ticket_number": t.get("TicketNumber"),
                    "deduped": True,
                }

        ticket = await client.create_ticket(
            end_user_id=contact_id,
            title=f"{_CASE_TAG_INBOX} Identity recovery — {subject[:60]}",
            first_comment=(body_text[:2000] or subject),
            priority="High",
        )
        return {
            "ticket_id": ticket["ticket_id"],
            "ticket_number": ticket["ticket_number"],
            "deduped": False,
        }
    except Exception:  # noqa: BLE001 — webhook must not fail open mail routing
        log.exception("agentmail sam: Atera ticket creation failed")
        return {}


async def _route_to_agent(
    agent: str,
    role: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch the parsed email to the appropriate agent brain.

    Phase 13 M7 — initial implementation routes all agents through the
    shared KB + resolver pipeline (same as the email agent) and returns
    a structured acknowledgement. Per-agent specialisation is layered on
    in M8 when the Phase 12 B2B squad tools are wired to their inboxes.

    The caller-facing response never leaks agent internal names or routing
    decisions — that detail lives in the log and in the structured return
    value consumed internally.
    """
    from .agents.resolver import _query_kb, _generate_steps  # lazy — avoids import cycles

    message = payload.get("message") or {}
    subject: str = message.get("subject") or ""
    body_text: str = message.get("text") or message.get("body") or ""
    from_name: str = (message.get("from") or {}).get("name") or ""
    from_addr: str = (
        (message.get("from") or {}).get("address")
        or message.get("from_address")
        or ""
    )

    log.info(
        "agentmail inbound agent=%s from=%s subject=%r",
        agent, from_addr, subject[:80],
    )

    issue = f"{subject}: {body_text[:400]}".strip(": ")
    kb_context = await _query_kb(issue) if issue else ""
    steps = await _generate_steps(issue, kb_context, attempt=0) if issue else []

    result: dict[str, Any] = {
        "agent": agent,
        "role": role,
        "from": from_addr,
        "subject": subject,
        "steps_generated": len(steps),
        "kb_hit": bool(kb_context),
    }

    # Sam — Identity Recovery. Genuine external customer mail opens (or
    # dedupes against) an Atera ticket. Internal senders (e.g. the chat-time
    # escalation email echo from support@klaravex.com) are already tracked at
    # chat time, so we skip ticket creation — never a bogus contact/ticket.
    if agent == "sam":
        if _is_internal_sender(from_addr):
            result["sam_action"] = "skipped_internal_sender"
        else:
            ticket = await _sam_open_atera_ticket(from_addr, from_name, subject, body_text)
            if ticket:
                result["sam_action"] = "deduped" if ticket.get("deduped") else "ticket_created"
                result["ticket_id"] = ticket.get("ticket_id")
                result["ticket_number"] = ticket.get("ticket_number")
            else:
                result["sam_action"] = "no_ticket_atera_unavailable"

    return result


@router.post("/inbound", status_code=202, tags=["AgentMail"])
async def agentmail_inbound(request: Request) -> dict[str, Any]:
    """Receive an inbound email event from AgentMail.

    1. Verify HMAC-SHA256 signature — fail CLOSED (503/401 on any problem).
    2. Parse the JSON payload.
    3. Determine which of the 9 agent inboxes received the message.
    4. Route to the appropriate agent brain.
    5. Return a structured acknowledgement.

    Unknown recipients (not in the 9 inbox roster) are accepted (202) but
    logged as unrouted rather than rejected, so a misconfigured AgentMail
    webhook does not create a delivery-failure loop.
    """
    raw = await request.body()
    _verify_signature(raw, request.headers.get("X-AgentMail-Signature"))

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    # AgentMail sends `event_type` and nests the message under `message`.
    # The `to` field is a list of recipient objects: [{"address": "klara@ai.klaravex.com"}]
    event_type: str = payload.get("event_type") or payload.get("event") or "unknown"
    if event_type not in {"message.received", "MESSAGE_RECEIVED"}:
        log.debug("agentmail webhook ignored event_type=%s", event_type)
        return {"status": "ignored", "event_type": event_type}

    message = payload.get("message") or {}
    to_list: list[dict[str, Any]] = message.get("to") or payload.get("to") or []

    # Find the first recipient that maps to a known agent inbox.
    matched_agent: str | None = None
    matched_role: str | None = None
    for recipient_obj in to_list:
        addr: str = (
            recipient_obj.get("address") or recipient_obj.get("email") or ""
            if isinstance(recipient_obj, dict)
            else str(recipient_obj)
        )
        result = _resolve_agent(addr)
        if result:
            matched_agent, matched_role = result
            break

    if matched_agent is None:
        # Log and acknowledge — do not reject (avoids AgentMail retry storms).
        log.warning(
            "agentmail inbound: no matching agent inbox for recipients=%r event=%s",
            [
                (r.get("address") if isinstance(r, dict) else r)
                for r in to_list
            ],
            event_type,
        )
        return {"status": "unrouted", "event_type": event_type}

    result = await _route_to_agent(matched_agent, matched_role, payload)
    return {"status": "ok", **result}
