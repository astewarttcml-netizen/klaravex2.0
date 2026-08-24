"""
app/api/vapi_webhook.py
────────────────────────
Webhook endpoint for Vapi.ai call events.

Route:
  POST /api/v1/webhooks/vapi

Vapi sends a POST request with a JSON payload for each call event.
We verify the payload using VAPI_WEBHOOK_SECRET (HMAC-SHA256) if configured,
then dispatch to VapiWebhookProcessorAgent.

Event types handled by the processor:
  - end-of-call-report  → extract transcript, fire post_call_processor
  - transcript          → acknowledged, not stored
  - call-started        → acknowledged
  - call-ended          → acknowledged

Security:
  Vapi supports two webhook auth schemes; we accept both so we stay
  compatible regardless of how the assistant is configured:
    1. Static custom header (server.headers)   -> x-vapi-secret: <value>
       Verified by comparing the value to VAPI_WEBHOOK_SECRET.
    2. Signed (server.secret)                  -> x-vapi-signature: sha256=<hmac>
       Verified as HMAC-SHA256 of the raw body.
  If VAPI_WEBHOOK_SECRET is set in .env, we verify whichever header is present.
  If not set, we skip verification (not recommended for production).
"""
from __future__ import annotations

import hashlib
import hmac

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import get_db
from klara.rarv.runtime import AgentContext
from klara.rarv.runtime import get_settings

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post("/webhooks/vapi", tags=["vapi-webhook"])
async def vapi_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive and process Vapi.ai call event webhooks.
    Always returns 200 — Vapi will retry on non-200.
    """
    settings = get_settings()
    raw_body = await request.body()

    # ── Signature verification ────────────────────────────────────────────────
    vapi_secret = getattr(settings, "vapi_webhook_secret", None)
    if vapi_secret:
        static_header = request.headers.get("x-vapi-secret", "")
        sig_header = request.headers.get("x-vapi-signature", "")

        verified = False
        # Scheme 1: static custom header — compare literal value to the secret.
        if static_header and hmac.compare_digest(static_header, vapi_secret):
            verified = True
        # Scheme 2: signed HMAC-SHA256 of the raw body (x-vapi-signature).
        if not verified and sig_header:
            expected = hmac.new(
                vapi_secret.encode(),
                raw_body,
                hashlib.sha256,
            ).hexdigest()
            if hmac.compare_digest(f"sha256={expected}", sig_header):
                verified = True

        if not verified:
            logger.warning(
                "vapi_webhook.signature_invalid",
                received_static=static_header[:20] if static_header else "none",
                received_sig=sig_header[:20] if sig_header else "none",
            )
            # Return 200 anyway to prevent Vapi retry loop,
            # but log as security event
            return {"status": "signature_invalid", "processed": False}

    # ── Parse payload ─────────────────────────────────────────────────────────
    try:
        payload = await request.json()
    except Exception as exc:
        logger.error("vapi_webhook.parse_error", error=str(exc))
        return {"status": "parse_error", "processed": False}

    event_type = (
        payload.get("type")
        or payload.get("message", {}).get("type")
        or "unknown"
    )

    logger.info(
        "vapi_webhook.received",
        event_type=event_type,
        call_id=payload.get("call", {}).get("id") or payload.get("callId", ""),
    )

    # ── Dispatch to VapiWebhookProcessorAgent ──────────────────────────────────
    try:
        from app.agents.registry import registry
        processor = registry.get("vapi_webhook_processor")

        if processor:
            ctx = AgentContext(db=db, settings=settings)
            result = await processor.run(ctx, payload)
            return {
                "status": "ok",
                "processed": result.success,
                "event_type": event_type,
                "output": result.output if result.success else None,
            }
        else:
            logger.error("vapi_webhook.processor_not_found")
            return {"status": "agent_not_found", "processed": False}

    except Exception as exc:
        logger.error("vapi_webhook.processing_error", error=str(exc))
        # Always return 200 to Vapi — never let it retry
        return {"status": "error", "processed": False, "error": str(exc)}
