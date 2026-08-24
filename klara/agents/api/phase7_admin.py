"""
app/api/phase7_admin.py
────────────────────────
Admin endpoints for Phase 7 agents:

  Reporting
  ─────────
  GET  /weekly-report              → WeeklyReportAgent
  GET  /kpi                        → KPIDashboardAgent

  Market intelligence
  ───────────────────
  POST /competitor-monitor         → CompetitorMonitorAgent
  POST /seo-opportunity            → SEOOpportunityAgent

  Content & lifecycle
  ───────────────────
  POST /content-calendar           → ContentCalendarAgent
  POST /contract-renewal           → ContractRenewalAgent
  POST /contract-renewal/dry-run   → ContractRenewalAgent (dry_run=True)

  Batch operations
  ────────────────
  POST /lead-scoring-refresh       → LeadScoringRefreshAgent

All endpoints require ADMIN_TOKEN header.
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Security
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


def _check(result: Any, agent_name: str) -> Any:
    """Raise 500 if agent failed, otherwise return result.output."""
    if not result.success:
        logger.error("phase7.agent_failed", agent=agent_name, error=result.error)
        raise HTTPException(status_code=500, detail=result.error or f"{agent_name} failed")
    return result.output


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/weekly-report",
    summary="Generate and optionally email the weekly business summary",
    dependencies=[Security(verify_api_key)],
)
async def get_weekly_report(
    override_recipient: str | None = Query(None, description="Send to this email instead of default"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Generates a structured weekly report covering new leads, pipeline movement,
    revenue collected, deals won, proposals sent, and outstanding invoices.
    Covers the previous Monday–Sunday window (Europe/Berlin time).
    Emails the report if approval_notify_email is configured.
    """
    agent = registry.get("weekly_report")
    context = _make_context(db, settings)
    input_data: dict = {}
    if override_recipient:
        input_data["override_recipient"] = override_recipient
    result = await agent(context, input_data)
    return _check(result, "weekly_report")


@router.get(
    "/kpi",
    summary="Current business KPI snapshot",
    dependencies=[Security(verify_api_key)],
)
async def get_kpi_dashboard(
    window_days: int = Query(30, ge=1, le=365, description="Lookback window for recent-leads metric"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Point-in-time KPI snapshot: pipeline count/value, conversion rate,
    average deal size, total revenue, outstanding invoices, and satisfaction score.
    No side-effects — pure read.
    """
    agent = registry.get("kpi_dashboard")
    context = _make_context(db, settings)
    result = await agent(context, {"window_days": window_days})
    return _check(result, "kpi_dashboard")


# ─────────────────────────────────────────────────────────────────────────────
# Market intelligence
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/competitor-monitor",
    summary="Fetch competitor websites and generate competitive intelligence report",
    dependencies=[Security(verify_api_key)],
)
async def run_competitor_monitor(
    competitors: list[str] = Body(default=[], description="Competitor homepage URLs to analyse"),
    focus_areas: list[str] = Body(default=[], description="Analysis focus e.g. ['pricing','services']"),
    notify: bool = Body(default=True, description="Email report to approval_notify_email"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Fetches each competitor URL, extracts visible text, and passes all snippets
    to Claude for a structured competitive analysis.  Falls back to built-in
    placeholder list if `competitors` is empty.
    """
    agent = registry.get("competitor_monitor")
    context = _make_context(db, settings)
    result = await agent(context, {
        "competitors": competitors,
        "focus_areas": focus_areas,
        "notify": notify,
    })
    return _check(result, "competitor_monitor")


@router.post(
    "/seo-opportunity",
    summary="Analyse site pages + lead demand to surface SEO keyword opportunities",
    dependencies=[Security(verify_api_key)],
)
async def run_seo_opportunity(
    page_urls: list[str] = Body(default=[], description="Page URLs to analyse; defaults to homepage+services+kontakt"),
    notify: bool = Body(default=True, description="Email report to approval_notify_email"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Combines live page content with aggregate services_interest from the CRM
    to generate keyword opportunities, content gaps, and SEO quick wins.
    """
    agent = registry.get("seo_opportunity")
    context = _make_context(db, settings)
    result = await agent(context, {"page_urls": page_urls, "notify": notify})
    return _check(result, "seo_opportunity")


# ─────────────────────────────────────────────────────────────────────────────
# Content & lifecycle
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/content-calendar",
    summary="Generate a bilingual content calendar based on CRM lead demand",
    dependencies=[Security(verify_api_key)],
)
async def run_content_calendar(
    weeks: int = Body(default=4, ge=1, le=8, description="Number of weeks to plan"),
    focus_topics: list[str] = Body(default=[], description="Optional topic overrides"),
    notify: bool = Body(default=True, description="Email calendar to approval_notify_email"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Produces a structured content calendar (Blog, LinkedIn, Instagram) with
    bilingual EN/DE headlines, target keywords, and CTAs, driven by
    services_interest frequencies in the lead database.
    """
    agent = registry.get("content_calendar")
    context = _make_context(db, settings)
    result = await agent(context, {
        "weeks": weeks,
        "focus_topics": focus_topics,
        "notify": notify,
    })
    return _check(result, "content_calendar")


@router.post(
    "/contract-renewal",
    summary="Identify clients approaching renewal and send personalised outreach",
    dependencies=[Security(verify_api_key)],
)
async def run_contract_renewal(
    renewal_months: int = Body(default=12, ge=1, le=36, description="Assumed contract length in months"),
    renewal_lookforward_days: int = Body(default=30, ge=1, le=90, description="Days ahead to look"),
    notify_consultant: bool = Body(default=True, description="Send batch summary to approval_notify_email"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Finds won clients whose estimated renewal date falls within
    `renewal_lookforward_days`.  Drafts and sends personalised renewal emails
    (EN or DE based on client signals) via Resend.
    """
    agent = registry.get("contract_renewal")
    context = _make_context(db, settings)
    result = await agent(context, {
        "renewal_months": renewal_months,
        "renewal_lookforward_days": renewal_lookforward_days,
        "dry_run": False,
        "notify_consultant": notify_consultant,
    })
    return _check(result, "contract_renewal")


@router.post(
    "/contract-renewal/dry-run",
    summary="Preview renewal candidates without sending emails",
    dependencies=[Security(verify_api_key)],
)
async def dry_run_contract_renewal(
    renewal_months: int = Body(default=12, ge=1, le=36),
    renewal_lookforward_days: int = Body(default=30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Same as POST /contract-renewal but with dry_run=True — returns the list
    of candidates without sending any emails.  Use to validate before a live run.
    """
    agent = registry.get("contract_renewal")
    context = _make_context(db, settings)
    result = await agent(context, {
        "renewal_months": renewal_months,
        "renewal_lookforward_days": renewal_lookforward_days,
        "dry_run": True,
        "notify_consultant": False,
    })
    return _check(result, "contract_renewal")


# ─────────────────────────────────────────────────────────────────────────────
# Batch operations
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/lead-scoring-refresh",
    summary="Re-run lead scoring over all active leads (or a specific subset)",
    dependencies=[Security(verify_api_key)],
)
async def run_lead_scoring_refresh(
    lead_ids: list[str] = Body(default=[], description="Specific lead IDs; empty = all active"),
    dry_run: bool = Body(default=False, description="Compute without writing scores"),
    status_filter: list[str] = Body(
        default=[],
        description="Override active statuses; default: new, qualified, discovery_done, proposal_sent",
    ),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Iterates over active leads and re-invokes the lead_scoring agent for each.
    Returns per-lead old/new score delta.  Runs via Celery beat nightly at 02:00 CET
    or can be triggered on-demand here.
    """
    agent = registry.get("lead_scoring_refresh")
    context = _make_context(db, settings)
    input_data: dict = {"dry_run": dry_run}
    if lead_ids:
        input_data["lead_ids"] = lead_ids
    if status_filter:
        input_data["status_filter"] = status_filter
    result = await agent(context, input_data)
    return _check(result, "lead_scoring_refresh")
