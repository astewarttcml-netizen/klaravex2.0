"""A5 archetype — B2B fixed-fee assessment webhook router.

Cyber-insurance readiness, IT security audit, HIPAA gap analysis, Azure
architecture review, pen-test, ISO/SOC 2 readiness, compliance attestation
prep. Mounted at /api/v1/b2b/assessment.
"""

import logging
from typing import Any

from fastapi import APIRouter, Header, Request

from .stripe_webhook import stripe_webhook as unified_stripe_webhook

log = logging.getLogger("klaravex.handlers.A5")
router = APIRouter()

A5_SKUS = {
    "cyber-insurance-readiness",
    "it-security-audit",
    "hipaa-gap-analysis",
    "azure-architecture-review",
    "pen-test",
    "iso27001-readiness",
    "soc2-readiness",
    "attestation-prep",
}


@router.post("/webhook")
async def b2b_assessment_webhook(request: Request, stripe_signature: str = Header(default="")) -> dict[str, Any]:
    return await unified_stripe_webhook(request, stripe_signature)


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"archetype": "A5", "skus": sorted(A5_SKUS), "status": "ok"}
