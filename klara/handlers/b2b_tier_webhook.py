"""A3 archetype — B2B managed tier subscription webhook router.

Foundation / Assurance / Directive + co-managed variants. Mounted at
/api/v1/b2b/tier.
"""

import logging
from typing import Any

from fastapi import APIRouter, Header, Request

from .stripe_webhook import stripe_webhook as unified_stripe_webhook

log = logging.getLogger("klaravex.handlers.A3")
router = APIRouter()

A3_SKUS = {
    "foundation", "foundation-annual", "foundation-comanaged",
    "assurance", "assurance-annual", "assurance-comanaged",
    "directive", "directive-annual", "directive-comanaged",
}


@router.post("/webhook")
async def b2b_tier_webhook(request: Request, stripe_signature: str = Header(default="")) -> dict[str, Any]:
    return await unified_stripe_webhook(request, stripe_signature)


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"archetype": "A3", "skus": sorted(A3_SKUS), "status": "ok"}
