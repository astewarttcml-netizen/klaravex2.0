"""
app/api/webhooks_email.py
──────────────────────────
Inbound-reply webhook from the email provider (phase3-002).

  POST /api/v1/webhooks/inbound-reply
  Headers: X-Email-Signature: sha256=<hmac_of_body>
  Body:    { "from": "<email>", "to": "<email>", "subject": "...", "text": "..." }

When a prospect replies to a cold-outreach email, the email provider relays
the message to this endpoint. We match the from-address against
ProspectedLead.contact_email and mark the prospect as 'replied' so the
phase3-001 Day-3 follow-up scheduler suppresses any pending step-2 row.
"""
from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentContext
from app.agents.registry import registry
from app.config import get_settings
from app.core.security import verify_email_webhook_signature
from app.database import get_db
from app.models.prospected_lead import ProspectedLead
from app.services.engagement_tracker import record_reply
from app.services.outreach_reply_suppression import (
    suppress_pending_followups_for_reply,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post("/inbound-reply")
async def inbound_reply(
    request: Request,
    x_email_signature: str | None = Header(default=None, alias="X-Email-Signature"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    body = await request.body()

    if not verify_email_webhook_signature(body, x_email_signature or ""):
        logger.warning(
            "inbound_reply.invalid_signature",
            sig_present=bool(x_email_signature),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )

    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    from_email = (payload.get("from") or "").strip().lower()
    if not from_email:
        raise HTTPException(status_code=400, detail="Missing 'from' address")

    # Match by lowercased contact_email — providers normalize case.
    result = await db.execute(
        select(ProspectedLead).where(
            ProspectedLead.contact_email.is_not(None),
            ProspectedLead.contact_email == from_email,
        ).limit(1)
    )
    prospect = result.scalar_one_or_none()

    if prospect is None:
        # Verified signature but no matching prospect — could be a forwarded
        # mail or a different inbox. Acknowledge so the provider doesn't
        # retry; log for diagnostics.
        logger.info("inbound_reply.no_match", from_email=from_email)
        return {"status": "no_match"}

    await record_reply(db, prospect)

    # phase19-006: cancel any pending/approved future OutreachSequence steps for
    # this prospect — the reply makes the cadence moot, and a lingering
    # pending_approval row would otherwise clutter the approval inbox.
    # Failures here MUST NOT fail the webhook: the reply has already been
    # recorded and that is the engagement-suppression signal of record.
    try:
        suppressed = await suppress_pending_followups_for_reply(db, prospect)
        if suppressed:
            logger.info(
                "inbound_reply.followups_suppressed",
                prospect_id=prospect.id,
                count=suppressed,
            )
    except Exception as exc:
        logger.error(
            "inbound_reply.suppression_exception",
            prospect_id=prospect.id,
            error=str(exc),
        )

    # phase4-001: classify the reply intent so downstream agents (phase4-002
    # auto-draft, phase4-003 conversion, phase4-004 OOO, phase4-005 unsub)
    # can route on the result. P1 — read-only, runs in-line. Failures are
    # logged but do NOT fail the webhook — the reply has already been
    # recorded by record_reply() and that's what matters for engagement
    # suppression.
    reply_body = (payload.get("text") or payload.get("body") or "").strip()
    classification_result: dict | None = None
    draft_result: dict | None = None
    if reply_body:
        ctx = AgentContext(db=db, settings=get_settings())
        try:
            classifier = registry.get("reply_intent")
            cls_res = await classifier.run(
                ctx,
                {"prospect_id": prospect.id, "reply_body": reply_body},
            )
            if cls_res.success:
                classification_result = cls_res.output
            else:
                logger.warning(
                    "inbound_reply.classification_failed",
                    prospect_id=prospect.id,
                    error=cls_res.error,
                )
        except Exception as exc:
            logger.error(
                "inbound_reply.classification_exception",
                prospect_id=prospect.id,
                error=str(exc),
            )

        # phase4-002: chain reply_draft after reply_intent. The draft is gated
        # by a P3 ApprovalRequest — nothing goes out without Anthony's review.
        # Failures here also do NOT fail the webhook; the reply is already
        # recorded and the classification is on file.
        if classification_result is not None:
            try:
                drafter = registry.get("reply_draft")
                draft_res = await drafter.run(
                    ctx,
                    {
                        "prospect_id": prospect.id,
                        "intent": classification_result.get("intent"),
                        "reply_body": reply_body,
                        "classification_id": classification_result.get("id"),
                    },
                )
                if draft_res.success:
                    draft_result = draft_res.output
                else:
                    logger.warning(
                        "inbound_reply.draft_failed",
                        prospect_id=prospect.id,
                        error=draft_res.error,
                    )
            except Exception as exc:
                logger.error(
                    "inbound_reply.draft_exception",
                    prospect_id=prospect.id,
                    error=str(exc),
                )

    await db.commit()

    response: dict = {"status": "recorded", "prospect_id": prospect.id}
    if classification_result is not None:
        response["classification"] = {
            "intent": classification_result.get("intent"),
            "confidence": classification_result.get("confidence"),
        }
    if draft_result is not None:
        response["draft"] = {
            "id": draft_result.get("id"),
            "approval_id": draft_result.get("approval_id"),
            "skipped": draft_result.get("skipped", False),
        }
    return response
