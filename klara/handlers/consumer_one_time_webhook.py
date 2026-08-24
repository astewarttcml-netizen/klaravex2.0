"""A2 archetype — consumer one-time purchase webhook router.

Per-incident, resume packages, job-hunt tech kit, solo-business launch kit,
AI skills coaching, identity & privacy hardening. Mounted at
/api/v1/consumer/one-time.
"""

import logging
from typing import Any

from fastapi import APIRouter, Header, Request

from .stripe_webhook import stripe_webhook as unified_stripe_webhook

log = logging.getLogger("klaravex.handlers.A2")
router = APIRouter()

A2_SKUS = {
    "per-incident",
    "resume-essentials", "resume-pro", "resume-executive",
    "tech-kit-basic", "tech-kit-pro",
    "solo-launch-starter", "solo-launch-pro",
    "ai-coaching-session",
    "identity-privacy-basic", "identity-privacy-pro",
}


@router.post("/webhook")
async def consumer_one_time_webhook(request: Request, stripe_signature: str = Header(default="")) -> dict[str, Any]:
    return await unified_stripe_webhook(request, stripe_signature)


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"archetype": "A2", "skus": sorted(A2_SKUS), "status": "ok"}
