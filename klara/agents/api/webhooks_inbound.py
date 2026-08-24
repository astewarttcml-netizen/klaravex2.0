"""
app/api/webhooks_inbound.py
────────────────────────────
phase19-003 — generic inbound-email webhook.

  POST /api/v1/webhooks/inbound-email
  Header: X-Email-Signature (HMAC of body, same secret as webhooks_email)
  Body:   {from, to, subject, text, raw?}

Persists an InboundEmail row, then fires the inbound_email agent to
classify. The classifier runs in-line so the webhook response carries
the classification — but if it fails, we still persist the email and
return 200 (Claude is the most likely failure point).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import AgentContext
from app.agents.registry import registry
from klara.rarv.runtime import get_settings
from app.core.security import verify_email_webhook_signature
from klara.rarv.runtime import get_db
from klara.rarv.inbound_email import InboundEmail

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post("/inbound-email")
async def inbound_email(
    request: Request,
    x_email_signature: str | None = Header(default=None, alias="X-Email-Signature"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    body = await request.body()

    if not verify_email_webhook_signature(body, x_email_signature or ""):
        logger.warning("inbound_email.invalid_signature")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")

    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    from_email = (payload.get("from") or "").strip().lower()
    if not from_email:
        raise HTTPException(status_code=400, detail="Missing 'from'")

    row = InboundEmail(
        id=str(uuid4()),
        from_email=from_email,
        to_email=(payload.get("to") or "").strip().lower() or None,
        subject=(payload.get("subject") or "")[:500],
        body=(payload.get("text") or payload.get("body") or "")[:50_000],
        raw_payload=body.decode("utf-8", errors="replace")[:100_000],
    )
    db.add(row)
    await db.flush()

    # Classify in-line. Failure logs but doesn't fail the webhook.
    classification: dict | None = None
    try:
        agent = registry.get("inbound_email")
        ctx = AgentContext(db=db, settings=get_settings())
        result = await agent.run(ctx, {"inbound_email_id": row.id})
        if result.success:
            classification = result.output
        else:
            logger.warning(
                "inbound_email.classification_failed",
                email_id=row.id, error=result.error,
            )
    except Exception as exc:
        logger.error("inbound_email.classification_exception", error=str(exc))

    # phase19-005: route based on category
    if classification and classification.get("category"):
        try:
            from klara.rarv.runtime.inbound_router import route_inbound
            await route_inbound(db, row, classification)
        except Exception as exc:
            logger.error("inbound_email.route_exception", error=str(exc))

    await db.commit()

    response: dict = {"status": "received", "id": row.id}
    if classification:
        response["classification"] = {
            "category": classification.get("category"),
            "confidence": classification.get("confidence"),
        }
    return response
