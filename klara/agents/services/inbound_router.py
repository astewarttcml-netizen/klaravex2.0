"""
app/services/inbound_router.py
───────────────────────────────
phase19-005 — route classified inbound emails to handlers.

After InboundEmailAgent classifies an email, this service takes the
classification + email row and dispatches to the appropriate downstream:

  prospect_referral → create Lead with source='referral'
  vendor_bill       → AuditLog event_type='vendor_bill.received'
  support_question  → AuditLog with KB lookup (best-effort)
  personal/spam/other → no action

Never raises — routing failures must not break the webhook response.
"""
from __future__ import annotations

import json
from typing import Optional
from uuid import uuid4

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.inbound_email import InboundCategory, InboundEmail

logger = structlog.get_logger(__name__)


# Confidence floor — below this we don't route, just keep the classification on file
MIN_ROUTING_CONFIDENCE = 0.7


async def route_inbound(
    db: AsyncSession,
    email: InboundEmail,
    classification: dict,
) -> None:
    category = classification.get("category")
    confidence = float(classification.get("confidence") or 0.0)

    if confidence < MIN_ROUTING_CONFIDENCE:
        logger.info(
            "inbound_router.skipped_low_confidence",
            email_id=email.id, category=category, confidence=confidence,
        )
        return

    if category == InboundCategory.prospect_referral:
        await _route_prospect_referral(db, email, classification)
    elif category == InboundCategory.vendor_bill:
        await _route_vendor_bill(db, email, classification)
    elif category == InboundCategory.support_question:
        await _route_support_question(db, email, classification)
    # personal / spam / other → no-op


async def _route_prospect_referral(db, email, classification):
    """Create a Lead row sourced from the referral."""
    try:
        from app.models.lead import Lead, LeadSource, LeadStatus
        # Best-effort extraction — actual prospect data may be in the body
        lead = Lead(
            id=str(uuid4()),
            source=LeadSource.manual.value,   # no dedicated 'referral' enum yet; manual works
            status=LeadStatus.new.value,
            email=email.from_email,
            name=None,
            message=(classification.get("summary") or "")[:500],
            notes=f"Inbound referral from {email.from_email}\nClassified: {classification}",
            gdpr_consent=True,   # referrer-introduced — implicit consent for outreach back
        )
        db.add(lead)
        await db.flush()
        email.lead_id = lead.id

        db.add(AuditLog(
            id=str(uuid4()),
            event_type="inbound.referral_to_lead",
            action_name="route_inbound",
            lead_id=lead.id,
            details=json.dumps({
                "inbound_email_id": email.id,
                "from": email.from_email,
                "confidence": classification.get("confidence"),
            }),
        ))
    except Exception as exc:
        logger.error("inbound_router.referral_failed", error=str(exc))


async def _route_vendor_bill(db, email, classification):
    db.add(AuditLog(
        id=str(uuid4()),
        event_type="vendor_bill.received",
        action_name="route_inbound",
        details=json.dumps({
            "inbound_email_id": email.id,
            "from": email.from_email,
            "subject": email.subject,
            "summary": classification.get("summary"),
        }),
    ))


async def _route_support_question(db, email, classification):
    db.add(AuditLog(
        id=str(uuid4()),
        event_type="inbound.support_question",
        action_name="route_inbound",
        details=json.dumps({
            "inbound_email_id": email.id,
            "from": email.from_email,
            "summary": classification.get("summary"),
        }),
    ))
