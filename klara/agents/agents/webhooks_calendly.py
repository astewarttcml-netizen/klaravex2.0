"""
app/api/webhooks_calendly.py
──────────────────────────────
FastAPI endpoint: POST /api/v1/webhooks/calendly

Receives Calendly webhook events, verifies the HMAC-SHA256 signature,
then delegates to CalendlyWebhookAgent.

Signature verification:
  Calendly sends:  Calendly-Webhook-Signature: t=<epoch>,v1=<hmac-hex>
  Message to sign: <epoch>.<raw-body>
  HMAC key:        CALENDLY_WEBHOOK_SIGNING_KEY (from settings / .env)

If signing key is not configured the endpoint logs a warning and processes
the payload anyway (dev/test behaviour). Set CALENDLY_WEBHOOK_SIGNING_KEY
in .env to enforce verification in production.

Replay protection: 5-minute tolerance on the timestamp (t= field).
"""
from __future__ import annotations

import hashlib
import hmac
import time
import uuid
import json

import structlog
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from klara.rarv.runtime import get_settings, Settings
from klara.rarv.runtime import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()

_MAX_AGE_SECS = 300  # 5 minutes — replay protection window


@router.post("/calendly", status_code=200)
async def calendly_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Receive and process Calendly webhook events."""
    body = await request.body()
    sig_header = request.headers.get("Calendly-Webhook-Signature", "")

    # ── Verify signature if signing key is configured ─────────────────────────
    signing_key = getattr(settings, "calendly_webhook_signing_key", None)
    if signing_key:
        _verify_signature(body, sig_header, signing_key)
    else:
        logger.warning("calendly_webhook.no_signing_key_configured")

    # ── Parse payload ─────────────────────────────────────────────────────────
    try:
        raw = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = raw.get("event", "")
    if event_type not in ("invitee.created", "invitee.canceled"):
        logger.info("calendly_webhook.ignored_event_type", event_type=event_type)
        return {"received": True}

    event_payload = raw.get("payload", {})
    invitee        = event_payload.get("invitee", {})
    scheduled_event = event_payload.get("scheduled_event", {})

    # ── Delegate to agent ─────────────────────────────────────────────────────
    from klara.rarv.runtime import AgentContext
    from app.agents.registry import registry

    context = AgentContext(
        db=db,
        settings=settings,
        conversation_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
    )
    agent = registry.get("calendly_webhook")
    result = await agent(context, {
        "event_type":      event_type,
        "invitee":         invitee,
        "scheduled_event": scheduled_event,
        "event_uri":       scheduled_event.get("uri", ""),
    })

    if not result.success:
        logger.error("calendly_webhook.agent_failed", error=result.error)
        # Return 200 anyway — Calendly will retry on non-2xx
        return {"received": True, "error": result.error}

    logger.info("calendly_webhook.processed",
                event_type=event_type,
                status=result.output.get("status") if result.output else None)
    return {"received": True, "result": result.output}


# ── Signature verification ────────────────────────────────────────────────────

def _verify_signature(body: bytes, sig_header: str, signing_key: str) -> None:
    """
    Parse Calendly-Webhook-Signature: t=<epoch>,v1=<hex>
    Verify HMAC-SHA256(key, "<epoch>.<body>") == v1.
    Raise HTTP 400 on invalid signature, 400 on replay.
    """
    parts = {k: v for k, v in
             (pair.split("=", 1) for pair in sig_header.split(",") if "=" in pair)}

    t   = parts.get("t", "")
    v1  = parts.get("v1", "")

    if not t or not v1:
        logger.warning("calendly_webhook.missing_signature_parts", header=sig_header)
        raise HTTPException(status_code=400, detail="Missing signature")

    # Replay protection
    try:
        ts = int(t)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp in signature")

    age = abs(time.time() - ts)
    if age > _MAX_AGE_SECS:
        logger.warning("calendly_webhook.replay_rejected", age_secs=age)
        raise HTTPException(status_code=400, detail="Webhook timestamp too old")

    # HMAC verification
    message = f"{t}.".encode() + body
    expected = hmac.new(
        signing_key.encode(), message, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, v1):
        logger.warning("calendly_webhook.invalid_signature")
        raise HTTPException(status_code=400, detail="Invalid signature")
