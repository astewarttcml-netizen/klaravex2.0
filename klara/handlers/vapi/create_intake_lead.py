"""Vapi tool — create_intake_lead.

Captures a NEW-LEAD phone caller's contact + need + urgency and routes into
one of the existing intake handlers:

  segment=consumer + urgency in {high, emergency}      -> intake_per_incident
  segment=consumer + urgency in {low, medium, standard} -> intake_consumer
  segment=b2b                                          -> intake_b2b

The existing intake handlers already:
  - persist to klaravex_tickets (via tickets_lib.create_ticket)
  - fire an alert email to ANTHONY_ALERT_EMAIL via send_email(...)
  - escalate on emergency

We do NOT reimplement any of that; we just adapt the Vapi voice-tool arg
schema onto the existing Pydantic models and call the handlers in-process
so a caller hang-up doesn't stop the ticket landing.

Wired into the unified dispatcher at
`infra/klara.handlers/vapi/tool_call.py::_dispatch`. Behind x-vapi-secret
(mounted in vapi/router.py).
"""
import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field, ValidationError

from ..intake_b2b import B2BIntake, b2b_intake as _b2b_intake_wrapped
from ..intake_consumer import ConsumerIntake, consumer_intake as _consumer_intake_wrapped
from ..intake_per_incident import PerIncidentIntake, per_incident_intake as _per_incident_wrapped

# The intake endpoints are wrapped by slowapi's @limiter.limit(...) decorator,
# which requires a real starlette Request. We're being called in-process from
# the Vapi tool-call dispatcher (already rate-limited via x-vapi-secret gate),
# so we bypass the rate limiter by targeting the underlying function via
# __wrapped__ (falls back to the wrapped callable if not decorated).
_consumer_intake = getattr(_consumer_intake_wrapped, "__wrapped__", _consumer_intake_wrapped)
_b2b_intake = getattr(_b2b_intake_wrapped, "__wrapped__", _b2b_intake_wrapped)
_per_incident_intake = getattr(_per_incident_wrapped, "__wrapped__", _per_incident_wrapped)

log = logging.getLogger("klaravex.vapi.create_intake_lead")
router = APIRouter()


# Voice tool argument schema — kept small + LLM-friendly.
class CreateIntakeLeadRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=40)
    segment: Literal["consumer", "b2b"] = "consumer"
    need: str = Field(min_length=2, max_length=2000)
    urgency: Literal["low", "medium", "high", "critical"] = "medium"
    company_name: Optional[str] = Field(default=None, max_length=200)
    employee_count: Optional[int] = Field(default=None, ge=1, le=100000)


# Vapi voice tool urgency -> internal intake urgency vocab (low|standard|high|emergency).
_URGENCY_MAP = {
    "low": "low",
    "medium": "standard",
    "high": "high",
    "critical": "emergency",
}

# Human-friendly follow-up window per urgency (spoken to caller).
_FOLLOWUP_LINE = {
    "critical": "within one hour",
    "high": "within two hours",
    "medium": "within one business day",
    "low": "within one business day",
}


def _speak_confirmation(urgency: str, name: str) -> str:
    window = _FOLLOWUP_LINE.get(urgency, "within one business day")
    first = (name or "").strip().split(" ", 1)[0] or "there"
    return (
        f"Thanks {first} — I've routed your info to our team. "
        f"Someone will follow up {window}. Anything else I can help with?"
    )


async def create_intake_lead(req: CreateIntakeLeadRequest, request: Optional[Request] = None) -> dict[str, Any]:
    """Fan the voice-captured lead into the correct existing intake handler.

    Returns {"status": "ok"|"error", "reason"?, "ticket_id"?, "spoken": <str>}.
    The caller (tool_call dispatcher) surfaces `spoken` back to Vapi.
    """
    internal_urgency = _URGENCY_MAP.get(req.urgency, "standard")

    # For "critical" consumer calls we prefer the per-incident intake because
    # its next-step-line is 30 minutes and it is the only path that supports
    # anonymous "call-me-back" tickets. For everyone else we use the standard
    # segmented intake.
    try:
        if req.segment == "b2b":
            if not (req.company_name and req.company_name.strip()):
                return {
                    "status": "error",
                    "reason": "missing company_name for b2b lead",
                    "spoken": (
                        "I just need the name of your company before I can route this. "
                        "What's the company name?"
                    ),
                }
            payload = B2BIntake(
                name=req.name,
                email=req.email,
                company=req.company_name.strip(),
                employee_count=req.employee_count or 1,
                primary_cloud="other",
                primary_concern=req.need,
                urgency=internal_urgency,
            )
            result = await _b2b_intake(request=request, payload=payload)  # type: ignore[arg-type]

        elif req.urgency == "critical":
            payload_pi = PerIncidentIntake(
                issue_description=req.need,
                urgency=internal_urgency,
                screen_share_ok=False,
                contact_email=req.email,
                contact_name=req.name,
                contact_phone=req.phone,
            )
            result = await _per_incident_intake(request=request, payload=payload_pi)  # type: ignore[arg-type]

        else:
            payload_c = ConsumerIntake(
                name=req.name,
                email=req.email,
                phone=req.phone,
                primary_issue=req.need,
                urgency=internal_urgency,
            )
            result = await _consumer_intake(request=request, payload=payload_c)  # type: ignore[arg-type]

    except ValidationError as ve:
        log.warning("create_intake_lead validation failed: %s", ve)
        return {
            "status": "error",
            "reason": f"validation error: {ve}",
            "spoken": (
                "I didn't quite catch one of those details. "
                "Could you repeat your email and the best callback number?"
            ),
        }
    except Exception as exc:  # noqa: BLE001
        log.exception("create_intake_lead intake dispatch failed: %s", exc)
        return {
            "status": "error",
            "reason": f"intake dispatch failed: {exc}",
            "spoken": (
                "I couldn't file that right this second, but I've flagged our team. "
                "Someone will call you back at the number you're on."
            ),
        }

    ticket_id = ""
    if isinstance(result, dict):
        ticket_id = str(result.get("ticket_id") or "")

    log.info(
        "create_intake_lead ok segment=%s urgency=%s ticket=%s",
        req.segment,
        req.urgency,
        ticket_id or "(none)",
    )

    return {
        "status": "ok",
        "ticket_id": ticket_id,
        "segment": req.segment,
        "urgency": req.urgency,
        "spoken": _speak_confirmation(req.urgency, req.name),
    }


@router.post("/create_intake_lead")
async def create_intake_lead_endpoint(request: Request, payload: CreateIntakeLeadRequest) -> dict[str, Any]:
    """Direct REST wrapper — mirrors the dispatch path for smoke tests."""
    return await create_intake_lead(payload, request=request)
