"""
app/api/funnel_analytics.py
────────────────────────────
End-to-end revenue funnel analytics (phase5-004).

  GET /api/v1/admin/funnel-analytics?window_days=30   (X-API-Key)

Aggregates eight stages across the cold-outreach → won pipeline,
returning counts, per-stage conversion rates, weekly cohort buckets,
and median velocity (days) between stages.

Stages:
  1. prospects_sent       — prospected_leads.outreach_sent_at IS NOT NULL
  2. prospects_opened     — prospected_leads.opened_at IS NOT NULL
  3. prospects_replied    — prospected_leads.replied_at IS NOT NULL
  4. leads_converted      — prospected_leads.converted_lead_id IS NOT NULL
  5. calls_booked         — leads.meeting_booked_at IS NOT NULL
  6. proposals_sent       — proposals.sent_to_client_at IS NOT NULL
  7. proposals_accepted   — proposals.status = 'accepted'
  8. deals_won            — leads.status = 'won'
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.lead import Lead, LeadStatus
from klara.rarv.proposal import Proposal, ProposalStatus
from klara.rarv.prospected_lead import ProspectedLead

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────


class StageCount(BaseModel):
    stage: str
    count: int


class ConversionStep(BaseModel):
    from_stage: str
    to_stage: str
    rate: float                 # 0.0–1.0
    median_days: Optional[float]


class CohortBucket(BaseModel):
    week_start: str             # YYYY-MM-DD (Monday)
    prospects_sent: int
    prospects_replied: int
    leads_converted: int
    deals_won: int


class RevenueMetrics(BaseModel):
    """phase7-001 — money flowing through the funnel.
    phase9-005 adds LLM cost so we can compute cost-per-conversion."""
    revenue_won_eur:     float        # annualised: sum(monthly_retainer × 12) for won leads in window
    active_mrr_eur:      float        # current MRR (time-independent — all active won + retainer>0)
    avg_deal_size_eur:   float        # mean annualised value per won deal in window
    deals_with_retainer: int          # count of won leads in window that have a retainer set
    llm_cost_eur:        float = 0.0  # phase9-005 — total LLM spend in the window
    cost_per_won_eur:    float = 0.0  # phase9-005 — llm_cost / deals_with_retainer


class SourceBreakdown(BaseModel):
    """phase18-005 — leads by source within the window."""
    source: str
    count: int


class FunnelAnalyticsResponse(BaseModel):
    window_days: int
    generated_at: datetime
    stages: list[StageCount]
    conversions: list[ConversionStep]
    cohorts: list[CohortBucket]
    revenue: RevenueMetrics                                # phase7-001
    prospects_by_source: list[SourceBreakdown] = []        # phase18-005


# ── Helpers ──────────────────────────────────────────────────────────────────


def _rate(numerator: int, denominator: int) -> float:
    if not denominator:
        return 0.0
    return round(numerator / denominator, 4)


def _week_start(d: datetime) -> str:
    """ISO Monday-week start (YYYY-MM-DD)."""
    monday = d - timedelta(days=d.weekday())
    return monday.date().isoformat()


# ── Route ────────────────────────────────────────────────────────────────────


@router.get("", response_model=FunnelAnalyticsResponse)
async def funnel_analytics(
    window_days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> FunnelAnalyticsResponse:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    # ── Stage counts ──────────────────────────────────────────────────────
    sent_q = await db.execute(
        select(func.count(ProspectedLead.id))
        .where(
            ProspectedLead.outreach_sent_at.is_not(None),
            ProspectedLead.outreach_sent_at >= cutoff,
        )
    )
    prospects_sent = int(sent_q.scalar() or 0)

    opened_q = await db.execute(
        select(func.count(ProspectedLead.id))
        .where(
            ProspectedLead.opened_at.is_not(None),
            ProspectedLead.outreach_sent_at >= cutoff,
        )
    )
    prospects_opened = int(opened_q.scalar() or 0)

    replied_q = await db.execute(
        select(func.count(ProspectedLead.id))
        .where(
            ProspectedLead.replied_at.is_not(None),
            ProspectedLead.outreach_sent_at >= cutoff,
        )
    )
    prospects_replied = int(replied_q.scalar() or 0)

    converted_q = await db.execute(
        select(func.count(ProspectedLead.id))
        .where(
            ProspectedLead.converted_lead_id.is_not(None),
            ProspectedLead.outreach_sent_at >= cutoff,
        )
    )
    leads_converted = int(converted_q.scalar() or 0)

    # Leads/proposals are scoped to created_at since they don't have a
    # ProspectedLead.outreach_sent_at column directly.
    calls_q = await db.execute(
        select(func.count(Lead.id))
        .where(
            Lead.created_at >= cutoff,
            getattr(Lead, "meeting_booked_at", Lead.created_at).is_not(None)
            if hasattr(Lead, "meeting_booked_at") else Lead.id.is_(None),
        )
    )
    calls_booked = int(calls_q.scalar() or 0)

    sent_to_client_q = await db.execute(
        select(func.count(Proposal.id))
        .where(
            Proposal.sent_to_client_at.is_not(None),
            Proposal.sent_to_client_at >= cutoff,
        )
    )
    proposals_sent = int(sent_to_client_q.scalar() or 0)

    accepted_q = await db.execute(
        select(func.count(Proposal.id))
        .where(
            Proposal.status == ProposalStatus.accepted.value,
            Proposal.updated_at >= cutoff,
        )
    )
    proposals_accepted = int(accepted_q.scalar() or 0)

    won_q = await db.execute(
        select(func.count(Lead.id))
        .where(
            Lead.status == LeadStatus.won.value,
            Lead.updated_at >= cutoff,
        )
    )
    deals_won = int(won_q.scalar() or 0)

    stages = [
        StageCount(stage="prospects_sent",     count=prospects_sent),
        StageCount(stage="prospects_opened",   count=prospects_opened),
        StageCount(stage="prospects_replied",  count=prospects_replied),
        StageCount(stage="leads_converted",    count=leads_converted),
        StageCount(stage="calls_booked",       count=calls_booked),
        StageCount(stage="proposals_sent",     count=proposals_sent),
        StageCount(stage="proposals_accepted", count=proposals_accepted),
        StageCount(stage="deals_won",          count=deals_won),
    ]

    # ── Conversions (rates only — median_days TBD when EXTRACT works) ─────
    conversions = [
        ConversionStep(from_stage="prospects_sent",     to_stage="prospects_opened",
                       rate=_rate(prospects_opened, prospects_sent), median_days=None),
        ConversionStep(from_stage="prospects_opened",   to_stage="prospects_replied",
                       rate=_rate(prospects_replied, prospects_opened), median_days=None),
        ConversionStep(from_stage="prospects_replied",  to_stage="leads_converted",
                       rate=_rate(leads_converted, prospects_replied), median_days=None),
        ConversionStep(from_stage="leads_converted",    to_stage="calls_booked",
                       rate=_rate(calls_booked, leads_converted), median_days=None),
        ConversionStep(from_stage="calls_booked",       to_stage="proposals_sent",
                       rate=_rate(proposals_sent, calls_booked), median_days=None),
        ConversionStep(from_stage="proposals_sent",     to_stage="proposals_accepted",
                       rate=_rate(proposals_accepted, proposals_sent), median_days=None),
        ConversionStep(from_stage="proposals_accepted", to_stage="deals_won",
                       rate=_rate(deals_won, proposals_accepted), median_days=None),
    ]

    # ── Cohorts: last 4 weeks of prospect-sent activity ───────────────────
    cohorts: list[CohortBucket] = []
    for week_offset in range(4):
        week_end = now - timedelta(days=7 * week_offset)
        week_start_dt = week_end - timedelta(days=7)

        ws_q = await db.execute(
            select(func.count(ProspectedLead.id)).where(
                ProspectedLead.outreach_sent_at >= week_start_dt,
                ProspectedLead.outreach_sent_at < week_end,
            )
        )
        ws = int(ws_q.scalar() or 0)

        wr_q = await db.execute(
            select(func.count(ProspectedLead.id)).where(
                ProspectedLead.replied_at >= week_start_dt,
                ProspectedLead.replied_at < week_end,
            )
        )
        wr = int(wr_q.scalar() or 0)

        wc_q = await db.execute(
            select(func.count(ProspectedLead.id)).where(
                ProspectedLead.converted_lead_id.is_not(None),
                ProspectedLead.updated_at >= week_start_dt,
                ProspectedLead.updated_at < week_end,
            )
        )
        wc = int(wc_q.scalar() or 0)

        ww_q = await db.execute(
            select(func.count(Lead.id)).where(
                Lead.status == LeadStatus.won.value,
                Lead.updated_at >= week_start_dt,
                Lead.updated_at < week_end,
            )
        )
        ww = int(ww_q.scalar() or 0)

        cohorts.append(CohortBucket(
            week_start=_week_start(week_start_dt),
            prospects_sent=ws,
            prospects_replied=wr,
            leads_converted=wc,
            deals_won=ww,
        ))

    # ── Revenue metrics (phase7-001) ──────────────────────────────────────
    # revenue_won_eur: annualised value of leads that became won inside the window
    won_window_q = await db.execute(
        select(func.coalesce(func.sum(Lead.monthly_retainer_amount), 0))
        .where(
            Lead.status == LeadStatus.won.value,
            Lead.monthly_retainer_amount.is_not(None),
            Lead.updated_at >= cutoff,
        )
    )
    won_window_monthly = float(won_window_q.scalar() or 0.0)
    revenue_won_eur = round(won_window_monthly * 12.0, 2)

    # active_mrr_eur: every currently-won lead with a retainer, regardless of when they won.
    active_mrr_q = await db.execute(
        select(func.coalesce(func.sum(Lead.monthly_retainer_amount), 0))
        .where(
            Lead.status == LeadStatus.won.value,
            Lead.monthly_retainer_amount.is_not(None),
            Lead.monthly_retainer_amount > 0,
        )
    )
    active_mrr_eur = round(float(active_mrr_q.scalar() or 0.0), 2)

    # avg_deal_size_eur over the window — only count won leads that actually
    # have a retainer set (others would skew the mean toward zero).
    deals_with_retainer_q = await db.execute(
        select(func.count(Lead.id))
        .where(
            Lead.status == LeadStatus.won.value,
            Lead.monthly_retainer_amount.is_not(None),
            Lead.monthly_retainer_amount > 0,
            Lead.updated_at >= cutoff,
        )
    )
    deals_with_retainer = int(deals_with_retainer_q.scalar() or 0)
    avg_deal_size_eur = (
        round(revenue_won_eur / deals_with_retainer, 2) if deals_with_retainer else 0.0
    )

    # phase9-005 — LLM spend in the same window for cost-per-conversion.
    from klara.rarv.llm_call import LlmCall as _LlmCall
    llm_cost_q = await db.execute(
        select(func.coalesce(func.sum(_LlmCall.cost_eur), 0))
        .where(_LlmCall.called_at >= cutoff)
    )
    llm_cost_eur = float(llm_cost_q.scalar() or 0.0)
    cost_per_won_eur = (
        round(llm_cost_eur / deals_with_retainer, 4) if deals_with_retainer else 0.0
    )

    revenue = RevenueMetrics(
        revenue_won_eur=revenue_won_eur,
        active_mrr_eur=active_mrr_eur,
        avg_deal_size_eur=avg_deal_size_eur,
        deals_with_retainer=deals_with_retainer,
        llm_cost_eur=round(llm_cost_eur, 4),
        cost_per_won_eur=cost_per_won_eur,
    )

    # phase18-005 — leads by source within window
    source_q = await db.execute(
        select(
            Lead.source,
            func.count(Lead.id),
        )
        .where(Lead.created_at >= cutoff)
        .group_by(Lead.source)
        .order_by(func.count(Lead.id).desc())
    )
    prospects_by_source = [
        SourceBreakdown(source=row[0] or "unknown", count=int(row[1] or 0))
        for row in source_q.all()
    ]

    return FunnelAnalyticsResponse(
        window_days=window_days,
        generated_at=now,
        stages=stages,
        conversions=conversions,
        cohorts=cohorts,
        revenue=revenue,
        prospects_by_source=prospects_by_source,
    )
