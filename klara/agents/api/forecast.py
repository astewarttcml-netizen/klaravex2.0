"""
app/api/forecast.py
────────────────────
phase13-003 — pipeline forecast endpoint.

  GET /api/v1/admin/forecast    (X-API-Key)

Projects expected won deals over the next 30/60/90 days based on:
  - current monthly cold-outreach volume (extrapolated from last 30d)
  - per-stage conversion rates measured over the same window
  - whether enough historical data exists (warn when sparse)

This is a back-of-envelope projection, not a model. Useful for "are we
on pace?" sanity-checking, not for committed forecasts.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.database import get_db
from app.models.lead import Lead, LeadStatus
from app.models.prospected_lead import ProspectedLead
from app.models.proposal import Proposal, ProposalStatus

logger = structlog.get_logger(__name__)
router = APIRouter()


class ForecastHorizon(BaseModel):
    horizon_days: int
    expected_won_deals: float
    expected_revenue_eur: float


class ForecastResponse(BaseModel):
    generated_at: datetime
    confidence: str                       # "low" | "moderate" | "high"
    sample_window_days: int
    sample_prospects_sent: int
    sample_deals_won: int
    overall_conversion_rate: float        # prospects_sent → won
    avg_deal_size_eur: float
    horizons: List[ForecastHorizon]


@router.get("", response_model=ForecastResponse)
async def forecast(
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> ForecastResponse:
    now = datetime.now(timezone.utc)
    sample_days = 30
    cutoff = now - timedelta(days=sample_days)

    # Stage counts over the sample window
    sent_q = await db.execute(
        select(func.count(ProspectedLead.id)).where(
            ProspectedLead.outreach_sent_at.is_not(None),
            ProspectedLead.outreach_sent_at >= cutoff,
        )
    )
    prospects_sent = int(sent_q.scalar() or 0)

    won_q = await db.execute(
        select(func.count(Lead.id)).where(
            Lead.status == LeadStatus.won.value,
            Lead.updated_at >= cutoff,
        )
    )
    deals_won = int(won_q.scalar() or 0)

    avg_deal_q = await db.execute(
        select(func.coalesce(func.avg(Lead.monthly_retainer_amount), 0)).where(
            Lead.status == LeadStatus.won.value,
            Lead.monthly_retainer_amount.is_not(None),
            Lead.monthly_retainer_amount > 0,
            Lead.updated_at >= cutoff,
        )
    )
    avg_monthly_retainer = float(avg_deal_q.scalar() or 0.0)
    avg_deal_size_eur = round(avg_monthly_retainer * 12.0, 2)

    overall_rate = round(deals_won / prospects_sent, 4) if prospects_sent else 0.0

    # Daily run-rate from the sample
    daily_prospects = prospects_sent / max(sample_days, 1)

    # Confidence heuristic — small samples are warned
    if prospects_sent < 20 or deals_won < 2:
        confidence = "low"
    elif prospects_sent < 100:
        confidence = "moderate"
    else:
        confidence = "high"

    horizons: List[ForecastHorizon] = []
    for d in (30, 60, 90):
        projected_prospects = daily_prospects * d
        projected_won = projected_prospects * overall_rate
        projected_revenue = projected_won * avg_deal_size_eur
        horizons.append(ForecastHorizon(
            horizon_days=d,
            expected_won_deals=round(projected_won, 2),
            expected_revenue_eur=round(projected_revenue, 2),
        ))

    return ForecastResponse(
        generated_at=now,
        confidence=confidence,
        sample_window_days=sample_days,
        sample_prospects_sent=prospects_sent,
        sample_deals_won=deals_won,
        overall_conversion_rate=overall_rate,
        avg_deal_size_eur=avg_deal_size_eur,
        horizons=horizons,
    )
