"""A4 archetype — B2B add-on recurring webhook router.

Security awareness training, email security, managed EDR (standalone),
Klara AI concierge, vCIO standalone, vCISO standalone, IR retainer. Mounted at
/api/v1/b2b/addon.
"""

import logging
from typing import Any

from fastapi import APIRouter, Header, Request

from .stripe_webhook import stripe_webhook as unified_stripe_webhook

log = logging.getLogger("klaravex.handlers.A4")
router = APIRouter()

A4_SKUS = {
    "sat", "email-security", "managed-edr",
    "loki-concierge", "vcio-standalone", "vciso-standalone",
    "ir-retainer",
}


@router.post("/webhook")
async def b2b_addon_webhook(request: Request, stripe_signature: str = Header(default="")) -> dict[str, Any]:
    return await unified_stripe_webhook(request, stripe_signature)


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"archetype": "A4", "skus": sorted(A4_SKUS), "status": "ok"}
