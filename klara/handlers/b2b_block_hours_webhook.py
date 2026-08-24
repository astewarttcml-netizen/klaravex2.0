"""A7 archetype — B2B block-hours support webhook router.

10-hour and 25-hour remote support blocks. Mounted at /api/v1/b2b/block-hours.
On successful payment the unified webhook also calls into the ledger to
credit hours to the client (handled via stripe_webhook's tickets_lib path).
"""

import logging
from typing import Any

from fastapi import APIRouter, Header, Request

from .stripe_webhook import stripe_webhook as unified_stripe_webhook

log = logging.getLogger("klaravex.handlers.A7")
router = APIRouter()

A7_SKUS = {"remote-block-10hr", "remote-block-25hr"}


@router.post("/webhook")
async def b2b_block_hours_webhook(request: Request, stripe_signature: str = Header(default="")) -> dict[str, Any]:
    return await unified_stripe_webhook(request, stripe_signature)


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"archetype": "A7", "skus": sorted(A7_SKUS), "status": "ok"}
