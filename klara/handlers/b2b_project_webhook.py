"""A6 archetype — B2B project-based engagement webhook router.

M365 setup, Azure project, Intune rollout, Windows server / AD project,
backup + DR build, PowerShell automation, monitoring deployment, firewall
deployment, IT procurement, AI automation, M365 migration, office IT
relocation, onboarding fee. Mounted at /api/v1/b2b/project.
"""

import logging
from typing import Any

from fastapi import APIRouter, Header, Request

from .stripe_webhook import stripe_webhook as unified_stripe_webhook

log = logging.getLogger("klaravex.handlers.A6")
router = APIRouter()

A6_SKUS = {
    "m365-setup", "m365-migration",
    "azure-project",
    "intune-rollout",
    "windows-server-project",
    "backup-dr-setup",
    "powershell-project",
    "monitoring-setup",
    "firewall-deploy",
    "procurement-flat",
    "ai-automation-project",
    "office-it-relocation",
    "onboarding-fee",
}


@router.post("/webhook")
async def b2b_project_webhook(request: Request, stripe_signature: str = Header(default="")) -> dict[str, Any]:
    return await unified_stripe_webhook(request, stripe_signature)


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"archetype": "A6", "skus": sorted(A6_SKUS), "status": "ok"}
