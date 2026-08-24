"""T-AC-06 primary conversion #2: directive_quote_requested (server-side).

POST /directive/request-pricing
    Accepts a Directive-tier pricing-quote request. On success:
      1. Persists a lead-intent record (best-effort; failure does not block).
      2. Fires GA4 Measurement Protocol event `directive_quote_requested`
         with Enhanced-Conversions user_data (hashed PII).
      3. Returns quote_id + acknowledgement.

Frontend contract:
    POST JSON: {
      "email": "buyer@firm.com",
      "first_name": "Jane",
      "last_name": "Doe",
      "phone_e164": "+15551234567",
      "company": "Firm LLC",
      "vertical": "legal" | "healthcare" | "financial" | "general",
      "firm_size": 42,                            # required for Directive quoting
      "regulator": "HIPAA" | "SOC2" | "ISO27001" | "FTC_Safeguards" | "multi",
      "country": "US",
      "postal_code": "10001",
      "utm_source": "google_ads" | ...,
      "utm_medium": "cpc" | ...,
      "utm_campaign": "...",
      "utm_content": "...",
      "gclid": "...",
      "ga_client_id": "GA1.1.xxx"
    }

    Response 200: {
      "ok": true,
      "quote_id": "dq-<uuid>",
      "next_step": "Klaravex team will respond within 1 business day."
    }
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field

from services.ga4_measurement_protocol import (
    _hashed_user_data,
    new_client_id,
    send_event,
)

log = logging.getLogger("klaravex.handlers.directive_quote_intake")
router = APIRouter()

CONVERSION_VALUE_USD = 500


class DirectiveQuoteRequest(BaseModel):
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    phone_e164: str | None = None
    company: str | None = None
    vertical: str = Field(default="general")
    firm_size: int
    regulator: str
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


@router.post("/request-pricing")
async def request_pricing(body: DirectiveQuoteRequest, request: Request) -> dict[str, Any]:
    quote_id = f"dq-{uuid.uuid4().hex[:12]}"
    channel = _channel_from_utm(body.utm_source, body.utm_medium)
    client_id = body.ga_client_id or new_client_id()

    mp_params: dict[str, Any] = {
        "value": CONVERSION_VALUE_USD,
        "currency": "USD",
        "vertical": body.vertical,
        "channel": channel,
        "firm_size": body.firm_size,
        "regulator": body.regulator,
        "quote_id": quote_id,
    }
    if body.utm_content:
        mp_params["source_ad_group"] = body.utm_content
    if body.utm_campaign:
        mp_params["campaign"] = body.utm_campaign
    if body.gclid:
        mp_params["gclid"] = body.gclid

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
        event_name="directive_quote_requested",
        params=mp_params,
        user_id=str(body.email),
        user_data=user_data,
    )

    log.info(
        "directive_quote_requested quote_id=%s vertical=%s firm_size=%s regulator=%s channel=%s mp_ok=%s",
        quote_id,
        body.vertical,
        body.firm_size,
        body.regulator,
        channel,
        mp_result.get("ok"),
    )

    return {
        "ok": True,
        "quote_id": quote_id,
        "next_step": "Klaravex team will respond within 1 business day.",
    }


@router.get("/health")
async def health() -> dict[str, Any]:
    return {
        "handler": "directive_quote_intake",
        "conversion_event": "directive_quote_requested",
        "value_usd": CONVERSION_VALUE_USD,
        "status": "ok",
    }
