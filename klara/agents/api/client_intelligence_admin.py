"""
app/api/client_intelligence_admin.py
──────────────────────────────────────
Admin endpoints for Phase 6 client intelligence agents:

  GET  /api/v1/admin/client-intelligence/revenue          → RevenueAnalyticsAgent
  GET  /api/v1/admin/client-intelligence/health           → ClientHealthAgent (all clients)
  GET  /api/v1/admin/client-intelligence/health/{lead_id} → ClientHealthAgent (single)
  GET  /api/v1/admin/client-intelligence/upsell           → UpsellOpportunityAgent (all)
  GET  /api/v1/admin/client-intelligence/upsell/{lead_id} → UpsellOpportunityAgent (single)

All endpoints require ADMIN_TOKEN header.
"""
from __future__ import annotations

import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import AgentContext
from app.agents.registry import registry
from klara.rarv.runtime import Settings, get_settings
from app.core.security import verify_api_key
from klara.rarv.runtime import get_db

logger = structlog.get_logger(__name__)
router = APIRouter()


def _make_context(db: AsyncSession, settings: Settings) -> AgentContext:
    return AgentContext(
        db=db,
        settings=settings,
        conversation_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
    )


# ── Revenue analytics ─────────────────────────────────────────────────────────
@router.get(
    "/revenue",
    summary="Revenue KPI snapshot",
    dependencies=[Security(verify_api_key)],
)
async def get_revenue_analytics(
    period_days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Aggregate financial KPIs: pipeline conversion, invoice totals,
    outstanding payments, and client satisfaction.
    """
    agent = registry.get("revenue_analytics")
    context = _make_context(db, settings)
    result = await agent(context, {"period_days": period_days})
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)
    return result.output


# ── Client health (all) ───────────────────────────────────────────────────────
@router.get(
    "/health",
    summary="Health scores for all active clients",
    dependencies=[Security(verify_api_key)],
)
async def get_all_client_health(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Compute health scores and risk levels for every lead with status=client.
    Results sorted worst-first.
    """
    agent = registry.get("client_health")
    context = _make_context(db, settings)
    result = await agent(context, {})
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)
    return result.output


# ── Client health (single) ────────────────────────────────────────────────────
@router.get(
    "/health/{lead_id}",
    summary="Health score for a specific client",
    dependencies=[Security(verify_api_key)],
)
async def get_client_health(
    lead_id: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    agent = registry.get("client_health")
    context = _make_context(db, settings)
    result = await agent(context, {"lead_id": lead_id})
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)
    data = result.output
    if not data["clients"]:
        raise HTTPException(
            status_code=404,
            detail=f"No active client found with lead_id={lead_id}",
        )
    return data["clients"][0]


# ── Upsell opportunities (all) ────────────────────────────────────────────────
@router.get(
    "/upsell",
    summary="Upsell opportunities across all clients",
    dependencies=[Security(verify_api_key)],
)
async def get_all_upsell_opportunities(
    min_nps: float = Query(7.0, ge=0, le=10, description="Minimum NPS threshold"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Scan all active clients for expansion signals.  Returns ranked list of
    upsell opportunities with AI-generated draft outreach per client.
    """
    agent = registry.get("upsell_opportunity")
    context = _make_context(db, settings)
    result = await agent(context, {"min_nps": min_nps})
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)
    return result.output


# ── Upsell opportunities (single) ────────────────────────────────────────────
@router.get(
    "/upsell/{lead_id}",
    summary="Upsell opportunity for a specific client",
    dependencies=[Security(verify_api_key)],
)
async def get_client_upsell_opportunity(
    lead_id: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    agent = registry.get("upsell_opportunity")
    context = _make_context(db, settings)
    result = await agent(context, {"lead_id": lead_id, "min_nps": 0.0})
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)
    data = result.output
    if not data["opportunities"]:
        raise HTTPException(
            status_code=404,
            detail=f"No upsell opportunity found for lead_id={lead_id}",
        )
    return data["opportunities"][0]
