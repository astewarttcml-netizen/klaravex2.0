"""A1 archetype — consumer subscription webhook router.

Filters Stripe events for SKUs in the consumer subscription family
(essentials, family-senior, home-membership) and delegates handling to the
unified stripe_webhook. Mounted at /api/v1/consumer/sub.
"""

import logging
from typing import Any

from fastapi import APIRouter, Header, Request

from .stripe_webhook import stripe_webhook as unified_stripe_webhook

log = logging.getLogger("klaravex.handlers.A1")
router = APIRouter()

A1_SKUS = {"essentials", "family-senior", "home-membership"}


@router.post("/webhook")
async def consumer_sub_webhook(request: Request, stripe_signature: str = Header(default="")) -> dict[str, Any]:
    return await unified_stripe_webhook(request, stripe_signature)


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"archetype": "A1", "skus": sorted(A1_SKUS), "status": "ok"}
