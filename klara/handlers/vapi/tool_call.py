"""Unified Vapi tool-call webhook handler.

Vapi POSTs all tool invocations here. This handler unpacks the envelope,
injects real call context (call_id, caller_phone) to replace any
placeholder values GPT-4o may have hallucinated, dispatches to the
correct function, and returns Vapi's required response format.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Request

from .advise_client import AdviseClientRequest, advise_client
from .check_payment_status import CheckRequest, check_payment_status
from .create_b2b_lead import CreateB2BLeadRequest, create_b2b_lead
from .create_intake_lead import CreateIntakeLeadRequest, create_intake_lead
from .escalate_to_anthony import EscalateRequest, escalate_to_anthony
from .generate_splashtop_link import SplashtopRequest, generate_splashtop_link
from .log_session_outcome import LogSessionOutcomeRequest, log_session_outcome
from .lookup_client import LookupClientRequest, lookup_client
from .payment_link import PaymentLinkRequest, create_payment_link
from .send_booking_link import SendBookingLinkRequest, send_booking_link
from .send_support_link import SendSupportLinkRequest, send_support_link
from .start_troubleshooting import TroubleshootRequest, start_troubleshooting

log = logging.getLogger("klaravex.vapi.tool_call")
router = APIRouter()

_PLACEHOLDER_SIDS = {"call_sid_placeholder", "1234567890", "", "{{call.id}}", "unknown"}
_PLACEHOLDER_PHONES = {"+1234567890", "", "{{call.customer.number}}", "unknown"}


@router.post("/tool-call")
async def vapi_tool_call_handler(request: Request) -> dict[str, Any]:
    """Receive Vapi tool-call webhook, dispatch, return results array."""
    body = await request.json()
    msg = body.get("message") or body

    # Extract real call context Vapi provides in the envelope
    call = msg.get("call") or {}
    customer = call.get("customer") or msg.get("customer") or {}
    real_call_id = call.get("id") or msg.get("callId") or ""
    real_phone = customer.get("number") or ""

    tool_calls = msg.get("toolCallList") or msg.get("toolCalls") or []
    results: list[dict[str, str]] = []

    for tc in tool_calls:
        tc_id = tc.get("id") or ""
        fn = tc.get("function") or {}
        tool_name = fn.get("name") or ""
        args_raw = fn.get("arguments") or "{}"

        try:
            args: dict[str, Any] = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
        except Exception:
            args = {}

        # Replace placeholder values GPT-4o may hallucinate with real context
        if real_call_id and args.get("call_sid", "") in _PLACEHOLDER_SIDS:
            args["call_sid"] = real_call_id
        if real_call_id and args.get("session_id", "") in _PLACEHOLDER_SIDS:
            args["session_id"] = real_call_id
        if real_phone and args.get("caller_phone", "") in _PLACEHOLDER_PHONES:
            args["caller_phone"] = real_phone
        if real_phone and args.get("from_number_e164", "") in _PLACEHOLDER_PHONES:
            args["from_number_e164"] = real_phone

        log.info("tool_call name=%s call_id=%s args=%s", tool_name, real_call_id, args)

        try:
            result_str = await _dispatch(tool_name, args)
        except Exception as e:
            log.warning("tool %s failed: %s", tool_name, e)
            result_str = f"error: {e}"

        results.append({"toolCallId": tc_id, "result": result_str})

    return {"results": results}


async def _dispatch(name: str, args: dict[str, Any]) -> str:
    if name == "send_payment_link":
        r = await create_payment_link(PaymentLinkRequest(**args))
        if r.get("url"):
            return "Payment link sent. Caller should receive it on their phone shortly."
        return "Payment link could not be sent — please ask the caller to stay on the line."

    if name == "check_payment_status":
        r = await check_payment_status(CheckRequest(**args))
        return "paid" if r.get("paid") else "not_paid"

    if name == "start_troubleshooting":
        r = await start_troubleshooting(TroubleshootRequest(**args))
        return r.get("answer") or r.get("reply") or "Troubleshooting complete — no specific answer found."

    if name in ("escalate_to_anthony", "escalate_to_team"):
        await escalate_to_anthony(EscalateRequest(**args))
        return "Our team has been notified by email and will follow up with the caller within 24 hours."

    if name in ("generate_splashtop_link", "send_remote_access_link"):
        r = await generate_splashtop_link(SplashtopRequest(**args))
        if r.get("url"):
            return "Remote support link sent to the caller."
        return "Remote support link could not be sent — please advise the caller to check their messages."

    if name == "send_support_link":
        # 2026-06-26 — RustDesk remote-support link (support.klaravex.com),
        # delivered by the channel the caller chose (sms/email). Replaces
        # generate_splashtop_link on the consumer specialists.
        r = await send_support_link(SendSupportLinkRequest(**args))
        if r.get("status") == "ok":
            channels = ", ".join(r.get("channels") or [])
            return (
                f"Support link sent via {channels or 'the chosen channel'}. "
                "Tell the caller to look for it now."
            )
        return r.get("reason") or (
            "Could not send the support link — tell the caller to go to "
            "support.klaravex.com directly."
        )

    if name == "lookup_client":
        # Phase 12 V2 — biz_engineer auth gate.
        r = await lookup_client(LookupClientRequest(**args))
        trust = r.get("trust_level") or "unknown"
        if r.get("authorized") and trust == "full":
            company = (r.get("client") or {}).get("company") or "the account on file"
            tickets = (r.get("client") or {}).get("open_tickets", 0)
            return (
                f"Authenticated at FULL trust for {company}; "
                f"{tickets} open ticket(s). You may discuss specifics."
            )
        if r.get("authorized") and trust == "verify":
            return (
                "Code is valid but the caller's phone is not on file. "
                "Stay in VERIFY trust — open a ticket and advise generically; "
                "do not read back stored contact or environment data."
            )
        if trust == "locked":
            return r.get("reason") or "Authentication locked after too many attempts."
        return r.get("reason") or "Code did not match an account on file."

    if name == "create_b2b_lead":
        # Phase 12 V3 — biz_intake.
        r = await create_b2b_lead(CreateB2BLeadRequest(**args))
        if r.get("status") == "ok":
            lid = r.get("lead_id", "")
            return f"Lead created ({lid}). Next step: send the booking link."
        return r.get("reason") or "Could not create the lead — try again or escalate."

    if name == "advise_client":
        # Phase 12 V5 — biz_engineer voice advisory (trust-level-aware).
        r = await advise_client(AdviseClientRequest(**args))
        if r.get("status") == "ok":
            return r.get("answer") or "Advice produced — no spoken text available."
        return r.get("reason") or "Could not produce advice — escalate to a human engineer."

    if name == "send_booking_link":
        # Phase 12 V4 — static Calendly URL until T0.3 (OAuth) unblocks.
        r = await send_booking_link(SendBookingLinkRequest(**args))
        if r.get("status") == "ok":
            channels = ", ".join(r.get("channels") or [])
            return (
                f"Booking link sent via {channels or 'email'}. "
                "Tell the caller to look for it now."
            )
        return r.get("reason") or "Could not send the booking link automatically."

    if name == "log_session_outcome":
        # Specialists call this at end of session to record what happened.
        # The Pydantic model requires call_sid + specialist + outcome; pass
        # only those, defaulting specialist when the LLM omits it (some
        # specialists' tool schemas mark it optional even though the model
        # marks it required).
        await log_session_outcome(LogSessionOutcomeRequest(
            call_sid=args.get("call_sid", ""),
            specialist=args.get("specialist") or "unspecified",
            outcome=args.get("outcome", "unknown"),
            notes=args.get("notes"),
            duration_seconds=args.get("duration_seconds"),
        ))
        return "Session outcome recorded."

    if name == "create_intake_lead":
        # Step 0a — new-lead intake (shopping/evaluating callers).
        r = await create_intake_lead(CreateIntakeLeadRequest(**args))
        if r.get("status") == "ok":
            return r.get("confirmation") or "Lead captured. Someone from our team will be in touch shortly."
        return r.get("reason") or "Could not save the lead — please try again or escalate."

    # ── RustDesk AI Remote Session voice tools (spec §4) ──────────────
    # Guarded by ImportError so the dispatcher stays operational even if
    # rustdesk_controller is not deployed on this host.
    if name in (
        "start_rustdesk_session",
        "next_screen_action",
        "confirm_action",
        "end_rustdesk_session",
    ):
        try:
            from rustdesk_controller.voice_tools import (
                StartRequest as RDStartRequest,
                NextActionRequest as RDNextActionRequest,
                ConfirmRequest as RDConfirmRequest,
                EndRequest as RDEndRequest,
                start_rustdesk_session,
                next_screen_action,
                confirm_action,
                end_rustdesk_session,
            )
        except ImportError:
            return "RustDesk remote-session module is not available on this host."

        if name == "start_rustdesk_session":
            r = await start_rustdesk_session(RDStartRequest(**args))
            if r.get("status") == "ok":
                return r.get("instructions_for_klara") or (
                    f"Session started ({r.get('session_id', 'unknown')}). "
                    "Tell the caller you can see their screen now."
                )
            return "Could not start the remote session — please try again or escalate."

        if name == "next_screen_action":
            r = await next_screen_action(RDNextActionRequest(**args))
            status = r.get("status", "")
            if status == "killed":
                return r.get("reason") or "Session was terminated."
            desc = r.get("action_description") or "Analyzing the screen now."
            if r.get("awaiting_confirmation"):
                return f"I'd like to do the following: {desc}. Is that okay?"
            return desc

        if name == "confirm_action":
            r = await confirm_action(RDConfirmRequest(**args))
            if r.get("executed"):
                return "Done — the action has been executed on your computer."
            if r.get("status") == "no_pending":
                return "There is no pending action to confirm right now."
            return "Action was not executed."

        if name == "end_rustdesk_session":
            r = await end_rustdesk_session(RDEndRequest(**args))
            summary = r.get("summary") or {}
            outcome = summary.get("outcome", "completed")
            return f"Remote session ended — outcome: {outcome}."

    return f"unknown tool: {name}"
