"""
app/api/webhooks_smartlead.py
──────────────────────────────
Inbound webhook receiver for Smartlead campaign events.

  POST /api/v1/webhooks/smartlead

Smartlead emits one POST per event. Supported event_types:
  - EMAIL_SENT          → mark ProspectedLead.status=sent, persist sent timestamp
  - EMAIL_OPEN          → engagement_tracker.record_open
  - EMAIL_LINK_CLICK    → engagement_tracker.record_click
  - EMAIL_REPLY         → engagement_tracker.record_reply (advances status=replied)
  - EMAIL_BOUNCE        → status=bounced + add_to_suppression
  - LEAD_CATEGORY_UPDATED → log only (no DB change in v1)

Auth: Smartlead webhooks include a `secret_key` field in the JSON body, set
when we registered the webhook. We compare it constant-time against
settings.smartlead_webhook_secret. Smartlead does NOT sign the payload with
HMAC (unlike Stripe/Resend) — the secret is a bearer in the body.

Always returns 200 OK with {ok:true} on success or {ok:true, status:'no_match'}
on unmatchable events (signature OK but no prospect found). Returns 403 only
when the secret_key fails validation — Smartlead will retry non-2xx.

Match strategy: lead lookup is by lowercased ProspectedLead.contact_email
against payload.lead.email or payload.lead_email. Smartlead has slight payload
shape drift across event types so we try both.
"""
from __future__ import annotations

import hmac
import json
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.email_suppression import SuppressionSource
from app.models.prospected_lead import ProspectedLead, ProspectedLeadStatus
from app.services.engagement_tracker import (
    record_click,
    record_open,
    record_reply,
    record_unsubscribe,
)
from app.services.suppression import add_to_suppression

logger = structlog.get_logger(__name__)
router = APIRouter()


def _extract_lead_email(payload: dict) -> Optional[str]:
    """Smartlead's payload shape varies by event type — try both common paths."""
    candidates = [
        payload.get("lead_email"),
        (payload.get("lead") or {}).get("email"),
        (payload.get("to_lead") or {}).get("email"),
    ]
    for c in candidates:
        if c and isinstance(c, str):
            return c.strip().lower()
    return None


async def _lookup_prospect(
    db: AsyncSession, email: str
) -> Optional[ProspectedLead]:
    result = await db.execute(
        select(ProspectedLead)
        .where(
            ProspectedLead.contact_email.is_not(None),
            ProspectedLead.contact_email == email,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.post("/smartlead/{token}")
async def smartlead_event(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings = Depends(get_settings),
) -> dict:
    # ── Verify URL-path secret ────────────────────────────────────────────────
    # Smartlead's webhook API does not support per-webhook secret_key fields
    # (the body-secret field is rejected with 400). Instead we embed the
    # secret as a URL path component — Smartlead POSTs to the full URL, the
    # token comes through the path, we compare constant-time against the
    # value provisioned in settings.smartlead_webhook_secret.
    expected = settings.smartlead_webhook_secret or ""
    if not expected:
        logger.error("smartlead_webhook.secret_not_configured")
        raise HTTPException(
            status_code=503,
            detail="SMARTLEAD_WEBHOOK_SECRET not configured on server.",
        )
    if not hmac.compare_digest(token, expected):
        logger.warning("smartlead_webhook.invalid_token")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook token",
        )

    raw = await request.body()
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_type = (payload.get("event_type") or "").upper()
    if not event_type:
        return {"ok": True, "status": "no_event_type"}

    lead_email = _extract_lead_email(payload)
    if not lead_email:
        logger.info("smartlead_webhook.no_lead_email", event_type=event_type)
        return {"ok": True, "status": "no_lead_email"}

    prospect = await _lookup_prospect(db, lead_email)
    if prospect is None:
        # Verified payload but the address isn't a Klara AI prospect — could be a
        # warmup-network email or a lead added outside Klara AI. Acknowledge so
        # Smartlead doesn't retry; log for diagnostics.
        logger.info(
            "smartlead_webhook.no_match",
            event_type=event_type,
            lead_email=lead_email,
        )
        return {"ok": True, "status": "no_match"}

    now = datetime.now(timezone.utc)

    # ── Dispatch by event type ────────────────────────────────────────────────
    if event_type == "EMAIL_SENT":
        # First successful dispatch from Smartlead — mark sent if we haven't already.
        if prospect.outreach_sent_at is None:
            prospect.outreach_sent_at = now
        if prospect.status in (
            ProspectedLeadStatus.outreach_queued,
            ProspectedLeadStatus.new,
        ):
            prospect.status = ProspectedLeadStatus.sent
        await db.flush()
        logger.info(
            "smartlead_webhook.sent",
            prospect_id=prospect.id,
            email=lead_email,
        )

    elif event_type == "EMAIL_OPEN":
        await record_open(db, prospect, now=now)

    elif event_type == "EMAIL_LINK_CLICK":
        link = (
            payload.get("link")
            or payload.get("clicked_link")
            or payload.get("url")
            or "unknown"
        )
        await record_click(db, prospect, link, now=now)

    elif event_type == "EMAIL_REPLY":
        await record_reply(db, prospect, now=now)
        # phase19-006 parity: Klara AI's existing inbound-reply handler also cancels
        # any pending follow-up sequence steps. Smartlead handles that on its
        # own side (stop_lead_settings=REPLY_TO_AN_EMAIL), so we just record.

    elif event_type == "EMAIL_BOUNCE":
        bounce_reason = (
            payload.get("bounce_reason")
            or payload.get("reason")
            or "smartlead_bounce_event"
        )
        prospect.status = ProspectedLeadStatus.bounced
        await db.flush()
        await add_to_suppression(
            db,
            lead_email,
            source=SuppressionSource.bounced,
            reason=str(bounce_reason)[:300],
        )
        logger.info(
            "smartlead_webhook.bounce",
            prospect_id=prospect.id,
            email=lead_email,
            reason=str(bounce_reason)[:120],
        )

    elif event_type == "EMAIL_COMPLAINED" or event_type == "SPAM_REPORT":
        # Spam complaint — most severe deliverability signal. Hard-suppress.
        await add_to_suppression(
            db,
            lead_email,
            source=SuppressionSource.abuse_report,
            reason="smartlead_spam_complaint",
        )
        logger.warning(
            "smartlead_webhook.complained",
            prospect_id=prospect.id,
            email=lead_email,
        )

    elif event_type == "LEAD_UNSUBSCRIBE":
        await record_unsubscribe(db, prospect, now=now)
        await add_to_suppression(
            db,
            lead_email,
            source=SuppressionSource.unsubscribed_reply,
            reason="smartlead_unsubscribe",
        )

    elif event_type == "LEAD_CATEGORY_UPDATED":
        # Smartlead's reply intent classifier assigned a category
        # (Interested / Not Interested / OOO / Wrong Person / etc.).
        # v1: log only — surface to dashboard later.
        logger.info(
            "smartlead_webhook.category_updated",
            prospect_id=prospect.id,
            email=lead_email,
            category=payload.get("category") or payload.get("lead_category"),
        )

    else:
        logger.info(
            "smartlead_webhook.unhandled_event_type",
            event_type=event_type,
            email=lead_email,
        )

    return {"ok": True, "event_type": event_type, "prospect_id": prospect.id}
