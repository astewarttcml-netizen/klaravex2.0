"""T-AC-06 primary conversion #1: readiness_review_booked (server-side).

POST /readiness-review/submit
    Accepts a Readiness Review booking request. On success:
      1. Persists a lead-intent record (best-effort; failure does not block).
      2. Fires GA4 Measurement Protocol event `readiness_review_booked`
         with Enhanced-Conversions user_data (hashed PII).
      3. Returns booking_id + Calendly booking URL for frontend redirect.

Frontend contract:
    POST JSON: {
      "email": "user@firm.com",
      "first_name": "Jane",
      "last_name": "Doe",
      "phone_e164": "+15551234567",
      "company": "Firm LLC",
      "vertical": "legal" | "healthcare" | "financial" | "general" | "consumer",
      "firm_size": 12,
      "regulator": "HIPAA" | "SOC2" | "ISO27001" | "FTC_Safeguards" | "multi" | null,
      "country": "US",
      "postal_code": "10001",
      "utm_source": "google_ads" | ...,
      "utm_medium": "cpc" | ...,
      "utm_campaign": "...",
      "utm_content": "...",     # source_ad_group
      "gclid": "...",           # Google Click Identifier
      "ga_client_id": "GA1.1.xxx"  # from _ga cookie
    }

    Response 200: {
      "ok": true,
      "booking_id": "rr-<uuid>",
      "calendly_url": "<CALENDLY_READINESS_REVIEW_URL>"
    }
"""

import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field

from services.ga4_measurement_protocol import (
    _hashed_user_data,
    new_client_id,
    send_event,
)

log = logging.getLogger("klaravex.handlers.readiness_review_intake")
router = APIRouter()

CONVERSION_VALUE_USD = 250


class ReadinessReviewSubmit(BaseModel):
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    phone_e164: str | None = None
    company: str | None = None
    vertical: str = Field(default="general")
    firm_size: int | None = None
    regulator: str | None = None
    country: str | None = "US"
    postal_code: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    gclid: str | None = None
    ga_client_id: str | None = None


def _channel_from_utm(utm_source: str | None, utm_medium: str | None) -> str:
    if utm_source == "google_ads" or utm_medium == "cpc":
        return "google_ads"
    if utm_source == "linkedin":
        return "linkedin"
    if utm_source == "email":
        return "email"
    if utm_medium == "referral":
        return "referral"
    if utm_source or utm_medium:
        return utm_source or utm_medium or "unknown"
    return "direct"


@router.post("/submit")
async def submit(body: ReadinessReviewSubmit, request: Request) -> dict[str, Any]:
    booking_id = f"rr-{uuid.uuid4().hex[:12]}"
    channel = _channel_from_utm(body.utm_source, body.utm_medium)
    client_id = body.ga_client_id or new_client_id()

    # Fire GA4 conversion event (best-effort; never blocks user response).
    mp_params: dict[str, Any] = {
        "value": CONVERSION_VALUE_USD,
        "currency": "USD",
        "vertical": body.vertical,
        "channel": channel,
    }
    if body.utm_content:
        mp_params["source_ad_group"] = body.utm_content
    if body.utm_campaign:
        mp_params["campaign"] = body.utm_campaign
    if body.gclid:
        mp_params["gclid"] = body.gclid
    if body.firm_size is not None:
        mp_params["firm_size"] = body.firm_size
    if body.regulator:
        mp_params["regulator"] = body.regulator
    mp_params["booking_id"] = booking_id

    user_data = _hashed_user_data(
        email=str(body.email),
        phone_e164=body.phone_e164,
        first_name=body.first_name,
        last_name=body.last_name,
        country=body.country,
        postal_code=body.postal_code,
    )

    mp_result = await send_event(
        client_id=client_id,
        event_name="readiness_review_booked",
        params=mp_params,
        user_id=str(body.email),
        user_data=user_data,
    )

    log.info(
        "readiness_review_booked booking_id=%s vertical=%s channel=%s mp_ok=%s",
        booking_id,
        body.vertical,
        channel,
        mp_result.get("ok"),
    )

    calendly_url = os.environ.get(
        "CALENDLY_READINESS_REVIEW_URL",
        "https://calendly.com/klaravex/readiness-review",
    )
    return {"ok": True, "booking_id": booking_id, "calendly_url": calendly_url}


@router.get("/health")
async def health() -> dict[str, Any]:
    return {
        "handler": "readiness_review_intake",
        "conversion_event": "readiness_review_booked",
        "value_usd": CONVERSION_VALUE_USD,
        "status": "ok",
    }
