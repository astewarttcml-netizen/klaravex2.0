"""
Klaravex escalation HTTP router — T6.0.4.

FastAPI router at /api/v1/escalate.

Accepts a structured escalation request, dispatches Telegram + email via
M365 SMTP (Resend PERMANENTLY REMOVED 2026-07-13 per anthony-directives.md),
logs to klaravex_escalations, and returns which channels succeeded.

Both channels are best-effort; missing credentials skip the channel
gracefully so a bad env var never blocks the escalation record from
being persisted.

Mount with:
    from klara.handlers.escalation import router as escalation_router
    app.include_router(escalation_router, prefix="/api/v1/escalate", tags=["Escalation"])

Required env vars (optional — channels silently skipped if absent):
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
    SMTP_PASS                (M365 SMTP password; email skipped if absent)
    SMTP_USER                default: support@klaravex.com
    APPROVAL_NOTIFY_EMAIL    default: astewart@klaravex.com
"""

import hashlib
import hmac
import json as _json
import logging
import os
from secrets import compare_digest

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from .lib import escalation as escalation_lib

log = logging.getLogger("klaravex.handlers.escalation")
router = APIRouter()


# V4 (pentest 2026-06-12) — /escalate was wide-open public. Now it requires
# either:
#   - x-loki-internal-secret  (server-to-server)
#   - x-klaravex-frontend-token = HMAC-SHA256(KLARAVEX_FRONTEND_HMAC_KEY, body)
#     hex-encoded. WordPress frontend signs every escalate request body with
#     a shared HMAC key; an attacker without the key can't forge a request
#     even if they snooped on the WordPress->API call (HSTS protects but
#     defense-in-depth).
# If BOTH env vars are unset, the endpoint is disabled (503) — fail closed.
def _verify_escalate_auth(request: Request, body_bytes: bytes) -> None:
    internal = os.environ.get("LOKI_INTERNAL_SECRET", "")
    frontend_key = os.environ.get("KLARAVEX_FRONTEND_HMAC_KEY", "")
    if not internal and not frontend_key:
        log.error("escalate auth disabled — no LOKI_INTERNAL_SECRET nor KLARAVEX_FRONTEND_HMAC_KEY")
        raise HTTPException(status_code=503, detail="escalate auth not configured")
    presented_internal = request.headers.get("x-loki-internal-secret", "")
    if internal and presented_internal and compare_digest(presented_internal, internal):
        return  # internal-secret path OK
    presented_frontend = request.headers.get("x-klaravex-frontend-token", "")
    if frontend_key and presented_frontend:
        expected = hmac.new(
            frontend_key.encode("utf-8"),
            body_bytes,
            hashlib.sha256,
        ).hexdigest()
        if compare_digest(presented_frontend.lower(), expected.lower()):
            return  # HMAC path OK
    raise HTTPException(status_code=401, detail="invalid escalate credentials")

# APPROVAL_NOTIFY_EMAIL overrides the default Anthony alert target for
# this router. Lib uses ANTHONY_ALERT_EMAIL; we read both and prefer the
# portal-specific one so they can be routed differently in future.
_NOTIFY_EMAIL = (
    os.environ.get("APPROVAL_NOTIFY_EMAIL")
    or os.environ.get("ANTHONY_ALERT_EMAIL")
    or "astewart@klaravex.com"
)


class EscalationRequest(BaseModel):
    ticket_id: str = Field(min_length=1, max_length=64)
    severity: str = Field(pattern="^(low|standard|high|emergency)$")
    summary: str = Field(min_length=1, max_length=2000)
    client_name: str | None = Field(default=None, max_length=200)
    client_email: EmailStr


class EscalationResponse(BaseModel):
    escalated: bool
    channels: list[str]
    escalation_id: str | None = None


@router.post("", response_model=EscalationResponse)
async def escalate_endpoint(request: Request) -> EscalationResponse:
    """
    Escalate a ticket to Anthony.

    V4 (pentest 2026-06-12): requires either x-loki-internal-secret OR a
    valid x-klaravex-frontend-token HMAC over the raw request body.

    - Posts a Telegram message (if TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID present).
    - Sends email via M365 SMTP (if SMTP_PASS present).
    - Logs escalation row to klaravex_escalations.
    - Returns which channels delivered successfully.
    """
    # Read raw body once for HMAC verification, then parse as JSON.
    body_bytes = await request.body()
    _verify_escalate_auth(request, body_bytes)
    try:
        payload_dict = _json.loads(body_bytes) if body_bytes else {}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON body: {exc}") from exc
    try:
        payload = EscalationRequest(**payload_dict)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"validation: {exc}") from exc
    client_label = payload.client_name or str(payload.client_email)
    try:
        result = await escalation_lib.escalate(
            ticket_id=payload.ticket_id,
            client_email=str(payload.client_email),
            severity=payload.severity,
            summary=payload.summary,
            attempted=f"Escalation submitted for {client_label}",
            recommended=f"Review ticket {payload.ticket_id} and contact {client_label}",
        )
    except Exception as exc:
        log.exception("escalation failed for ticket %s: %s", payload.ticket_id, exc)
        raise HTTPException(status_code=500, detail=f"escalation failed: {exc}") from exc

    delivered = result.get("delivered_via", {})
    channels: list[str] = []
    if delivered.get("telegram"):
        channels.append("telegram")
    if delivered.get("email"):
        channels.append("email")

    return EscalationResponse(
        escalated=True,
        channels=channels,
        escalation_id=result.get("escalation_id"),
    )


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "handler": "escalation"}
