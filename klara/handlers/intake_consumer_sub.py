"""
Klaravex consumer subscription intake handlers — T6.2.3.

Two endpoints:

  POST /api/v1/intake/consumer-sub
      Pre-purchase interest form (minimal fields). Used by the website contact
      form before a Stripe checkout is created.

  POST /api/v1/intake/consumer-sub/day0
      Day-0 post-subscription intake (A1.2 spec). Sent to the client via the
      welcome+intake email after customer.subscription.created fires. Full
      WORKFLOWS §A1.2 field set: household_size, device_platforms, pain_points,
      urgent_phone, comm_preference. On submit, Klara AI updates the client profile
      and sends a "you're all set" confirmation with the chat link.

Mount with:
    from infra.klara.handlers.intake_consumer_sub import router as consumer_sub_intake
    app.include_router(consumer_sub_intake, prefix="/api/v1/intake")
"""

import os
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from .lib import tickets as tickets_lib
from .lib.email import send_email
from .lib.rate_limit import limiter

log = logging.getLogger("klaravex.intake_consumer_sub")
router = APIRouter()

APPROVAL_NOTIFY_EMAIL = os.environ.get("APPROVAL_NOTIFY_EMAIL", os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com"))
PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "support@klaravex.com")

CONSUMER_SUB_SKUS = {"essentials", "family-senior", "home-membership"}

CHAT_LINK = f"{PORTAL_BASE_URL}/portal/chat"


# ── Pre-purchase interest model (thin) ───────────────────────────────────────

class ConsumerSubIntake(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=40)
    service_interest: str = Field(
        default="essentials",
        description="essentials | family-senior | home-membership",
    )
    device_type: Optional[str] = Field(default=None, max_length=120)
    location: Optional[str] = Field(default=None, max_length=200)


# ── Day-0 post-subscription intake model (full A1.2 spec) ────────────────────

class ConsumerSubDay0Intake(BaseModel):
    """Full A1.2 Day-0 intake. Submitted by the client after clicking the welcome email link."""

    email: EmailStr
    name: str = Field(min_length=2, max_length=120)
    sku: str = Field(
        default="essentials",
        description="essentials | family-senior | home-membership",
    )
    # A1.2 fields
    household_size: Optional[int] = Field(
        default=None,
        ge=1, le=20,
        description="Number of people in the household",
    )
    device_platforms: Optional[List[str]] = Field(
        default=None,
        description="e.g. ['windows', 'macos', 'ios', 'android', 'smart-home']",
    )
    top_pain_points: Optional[List[str]] = Field(
        default=None,
        max_length=3,
        description="Up to 3 current IT pain points",
    )
    urgent_contact_phone: Optional[str] = Field(default=None, max_length=40)
    communication_preference: Optional[str] = Field(
        default="chat-first",
        description="chat-first | email-first | phone-ok",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _send_welcome_email(to: str, name: str, service_interest: str, client_id: str) -> None:
    subject = f"Welcome to Klaravex, {name}!"
    body = (
        f"Hi {name},\n\n"
        f"Thank you for your interest in Klaravex {service_interest}.\n\n"
        f"Your account has been created and our team will be in touch shortly to get you started.\n\n"
        f"If you have any questions in the meantime, reply to this email or reach us at {SUPPORT_EMAIL}.\n\n"
        f"— The Klaravex Team\n\n"
        f"(Reference: {client_id})\n"
    )
    await send_email(to=to, subject=subject, body=body)


async def _send_notify_email(name: str, email: str, payload: ConsumerSubIntake, client_id: str) -> None:
    subject = f"[Klaravex] New consumer sub intake — {name} ({payload.service_interest})"
    body = (
        f"New consumer subscription intake received.\n\n"
        f"Name:             {name}\n"
        f"Email:            {email}\n"
        f"Phone:            {payload.phone or '—'}\n"
        f"Service interest: {payload.service_interest}\n"
        f"Device type:      {payload.device_type or '—'}\n"
        f"Location:         {payload.location or '—'}\n"
        f"Client ID:        {client_id}\n"
    )
    await send_email(to=APPROVAL_NOTIFY_EMAIL, subject=subject, body=body)


async def _send_day0_confirmation(to: str, name: str) -> None:
    """'You're all set' email sent after Day-0 intake submission. Includes chat link."""
    subject = "You're all set with Klaravex — here's your support link"
    body = (
        f"Hi {name},\n\n"
        f"We've got your setup details. You're all set.\n\n"
        f"Here's your direct link to our AI support chat — available 24/7:\n\n"
        f"  {CHAT_LINK}\n\n"
        f"Use it any time a tech question comes up. Most issues are resolved in under\n"
        f"6 minutes. For anything complex, our team jumps in.\n\n"
        f"A monthly summary email will arrive on your billing date covering anything\n"
        f"we handled for you.\n\n"
        f"Questions? Reply here or reach {SUPPORT_EMAIL}.\n\n"
        f"— The Klaravex Team\n"
    )
    await send_email(to=to, subject=subject, body=body)


async def _send_day0_notify(email: str, name: str, payload: ConsumerSubDay0Intake) -> None:
    platforms = ", ".join(payload.device_platforms or []) or "—"
    pain_points = "\n".join(f"  {i+1}. {p}" for i, p in enumerate(payload.top_pain_points or [])) or "  —"
    subject = f"[Klaravex A1] Day-0 intake — {name} ({payload.sku})"
    body = (
        f"Day-0 A1 intake submitted.\n\n"
        f"Name:                 {name}\n"
        f"Email:                {email}\n"
        f"SKU:                  {payload.sku}\n"
        f"Household size:       {payload.household_size or '—'}\n"
        f"Device platforms:     {platforms}\n"
        f"Top pain points:\n{pain_points}\n"
        f"Urgent phone:         {payload.urgent_contact_phone or '—'}\n"
        f"Comm preference:      {payload.communication_preference or '—'}\n"
    )
    await send_email(to=APPROVAL_NOTIFY_EMAIL, subject=subject, body=body)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/consumer-sub", status_code=201)
@limiter.limit("20/minute")
async def intake_consumer_sub(request: Request, payload: ConsumerSubIntake) -> dict[str, str]:
    """Pre-purchase interest intake. Creates client record, sends welcome email."""
    client_id: str | None = None
    try:
        client_id = await tickets_lib.get_or_create_client(
            email=str(payload.email),
            segment="consumer",
            name=payload.name,
            phone=payload.phone,
            metadata={
                "service_interest": payload.service_interest,
                "device_type": payload.device_type,
                "location": payload.location,
                "source": "intake_consumer_sub",
                "intake_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as e:  # noqa: BLE001
        log.warning("client upsert failed (continuing): %s", e)
        client_id = str(uuid.uuid4())

    ticket_id: str | None = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=str(payload.email),
            subject=f"Consumer sub intake: {payload.name} ({payload.service_interest})",
            severity="standard",
            status="open",
            source="intake_consumer",
            archetype="A1",
            sku=payload.service_interest,
            summary=(
                f"Consumer subscription intake. "
                f"Device: {payload.device_type or 'unspecified'}. "
                f"Location: {payload.location or 'unspecified'}."
            ),
            segment_hint="consumer",
            metadata={
                "name": payload.name,
                "phone": payload.phone,
                "device_type": payload.device_type,
                "location": payload.location,
            },
        )
    except Exception as e:  # noqa: BLE001
        log.warning("ticket creation failed (continuing): %s", e)

    try:
        await _send_welcome_email(str(payload.email), payload.name, payload.service_interest, client_id)
    except Exception as e:  # noqa: BLE001
        log.exception("welcome email failed: %s", e)

    try:
        await _send_notify_email(payload.name, str(payload.email), payload, client_id)
    except Exception as e:  # noqa: BLE001
        log.exception("notify email failed: %s", e)

    if not client_id:
        raise HTTPException(status_code=500, detail="client record creation failed")

    return {"client_id": client_id, "status": "onboarding", "ticket_id": ticket_id or ""}


@router.post("/consumer-sub/day0", status_code=200)
@limiter.limit("10/minute")
async def intake_consumer_sub_day0(request: Request, payload: ConsumerSubDay0Intake) -> dict[str, str]:
    """Day-0 post-subscription A1.2 intake.

    The welcome+intake email sent on customer.subscription.created links here.
    Stores full household/device/pain-point profile, sends 'you're all set'
    confirmation with chat link, and notifies Anthony.
    """
    import json as _json

    email = str(payload.email)
    name = payload.name
    client_id: str | None = None

    # Upsert the client profile with the full A1.2 fields.
    try:
        client_id = await tickets_lib.get_or_create_client(
            email=email,
            segment="consumer",
            name=name,
            phone=payload.urgent_contact_phone,
            metadata={
                "sku": payload.sku,
                "household_size": payload.household_size,
                "device_platforms": payload.device_platforms or [],
                "top_pain_points": payload.top_pain_points or [],
                "urgent_contact_phone": payload.urgent_contact_phone,
                "communication_preference": payload.communication_preference,
                "a1_day0_intake_at": datetime.now(timezone.utc).isoformat(),
                "source": "a1_day0_intake",
            },
        )
    except Exception as e:  # noqa: BLE001
        log.warning("client upsert failed (continuing): %s", e)
        client_id = str(uuid.uuid4())

    # Create a workflow ticket for the Day-0 intake event.
    ticket_id: str | None = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=email,
            subject=f"A1 Day-0 intake: {name} ({payload.sku})",
            severity="standard",
            status="resolved",
            source="workflow",
            archetype="A1",
            sku=payload.sku,
            summary=(
                f"Day-0 intake complete. "
                f"Platforms: {', '.join(payload.device_platforms or []) or 'unspecified'}. "
                f"Pain points: {len(payload.top_pain_points or [])} captured. "
                f"Comm preference: {payload.communication_preference or 'unspecified'}."
            ),
            segment_hint="consumer",
            metadata={
                "household_size": payload.household_size,
                "device_platforms": payload.device_platforms,
                "top_pain_points": payload.top_pain_points,
                "urgent_contact_phone": payload.urgent_contact_phone,
                "communication_preference": payload.communication_preference,
            },
        )
    except Exception as e:  # noqa: BLE001
        log.warning("ticket creation failed (continuing): %s", e)

    # Send "you're all set" confirmation with chat link.
    try:
        await _send_day0_confirmation(email, name)
    except Exception as e:  # noqa: BLE001
        log.exception("day0 confirmation email failed: %s", e)

    # Notify Anthony of the completed intake.
    try:
        await _send_day0_notify(email, name, payload)
    except Exception as e:  # noqa: BLE001
        log.exception("day0 notify email failed: %s", e)

    if not client_id:
        raise HTTPException(status_code=500, detail="client record creation failed")

    return {
        "client_id": client_id,
        "status": "onboarded",
        "ticket_id": ticket_id or "",
        "chat_link": CHAT_LINK,
    }
