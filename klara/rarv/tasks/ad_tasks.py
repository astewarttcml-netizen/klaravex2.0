"""
app/tasks/ad_tasks.py
────────────────────────────────
Celery tasks for the ad campaign pipeline.

Scheduling (n8n preferred — see n8n-workflows/):
  run_ad_budget_check     — Daily 09:00 ET
  run_ad_optimization     — Weekly Monday 10:00 ET
  run_ad_reporting        — Weekly Monday 08:00 ET

These tasks can also be triggered manually via admin API.
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="app.tasks.ad_tasks.run_ad_budget_check",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
)
def run_ad_budget_check(self: Any) -> dict[str, Any]:
    """
    Daily budget check for all active ad campaigns.
    Alerts if spend approaches budget limit.
    """
    try:
        result = asyncio.run(_check_budgets())
        return result
    except Exception as exc:
        logger.error("ad_tasks.budget_check.error", error=str(exc))
        raise self.retry(exc=exc)


async def _check_budgets() -> dict[str, Any]:
    from app.config import get_settings
    from app.database import db_context
    from app.agents.base import AgentContext
    from app.agents.ad_campaign_manager import AdCampaignManagerAgent

    settings = get_settings()
    async with db_context() as db:
        ctx = AgentContext(db=db, settings=settings)
        agent = AdCampaignManagerAgent()

        platforms = ["google", "meta", "linkedin"]
        results = {}

        for platform in platforms:
            try:
                result = await agent.run(ctx, {
                    "action": "get_report",
                    "platform": platform,
                    "date_range": "YESTERDAY",
                })
                if result.success and result.output:
                    results[platform] = result.output
                else:
                    results[platform] = {"error": result.error or "Unknown error"}
            except Exception as exc:
                results[platform] = {"error": str(exc)}

        # Check for budget alerts
        alerts = []
        for platform, data in results.items():
            if "campaigns" in data:
                for campaign in data["campaigns"]:
                    spend = campaign.get("spend", 0)
                    budget = campaign.get("budget", 100)
                    if spend > budget * 0.9:
                        alerts.append({
                            "platform": platform,
                            "campaign_id": campaign.get("campaign_id"),
                            "spend": spend,
                            "budget": budget,
                            "alert": "Budget 90% exhausted",
                        })

        logger.info(
            "ad_tasks.budget_check.complete",
            platforms_checked=len(platforms),
            alerts=len(alerts),
        )

        return {
            "status": "ok",
            "platforms": results,
            "alerts": alerts,
            "alert_count": len(alerts),
        }


@celery_app.task(
    name="app.tasks.ad_tasks.run_ad_optimization",
    bind=True,
    max_retries=2,
    default_retry_delay=600,
)
def run_ad_optimization(self: Any) -> dict[str, Any]:
    """
    Weekly optimization sweep for all ad campaigns.
    Generates recommendations for budget reallocation and creative updates.
    """
    try:
        result = asyncio.run(_optimize_campaigns())
        return result
    except Exception as exc:
        logger.error("ad_tasks.optimization.error", error=str(exc))
        raise self.retry(exc=exc)


async def _optimize_campaigns() -> dict[str, Any]:
    from app.config import get_settings
    from app.database import db_context
    from app.agents.base import AgentContext
    from app.agents.ad_campaign_manager import AdCampaignManagerAgent

    settings = get_settings()
    async with db_context() as db:
        ctx = AgentContext(db=db, settings=settings)
        agent = AdCampaignManagerAgent()

        platforms = ["google", "meta", "linkedin"]
        recommendations = []

        for platform in platforms:
            try:
                result = await agent.run(ctx, {
                    "action": "optimize",
                    "platform": platform,
                })
                if result.success and result.output:
                    recommendations.append({
                        "platform": platform,
                        "recommendations": result.output.get("recommendations", []),
                    })
            except Exception as exc:
                recommendations.append({
                    "platform": platform,
                    "error": str(exc),
                })

        logger.info(
            "ad_tasks.optimization.complete",
            platforms=len(platforms),
            recommendations=len(recommendations),
        )

        return {
            "status": "ok",
            "recommendations": recommendations,
        }


@celery_app.task(
    name="app.tasks.ad_tasks.run_ad_reporting",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def run_ad_reporting(self: Any) -> dict[str, Any]:
    """
    Weekly ad performance report.
    Aggregates metrics across all platforms and sends summary.
    """
    try:
        result = asyncio.run(_generate_report())
        return result
    except Exception as exc:
        logger.error("ad_tasks.reporting.error", error=str(exc))
        raise self.retry(exc=exc)


async def _generate_report() -> dict[str, Any]:
    from app.config import get_settings
    from app.database import db_context
    from app.agents.base import AgentContext
    from app.agents.ad_campaign_manager import AdCampaignManagerAgent

    settings = get_settings()
    async with db_context() as db:
        ctx = AgentContext(db=db, settings=settings)
        agent = AdCampaignManagerAgent()

        platforms = ["google", "meta", "linkedin"]
        reports = {}

        for platform in platforms:
            try:
                result = await agent.run(ctx, {
                    "action": "get_report",
                    "platform": platform,
                    "date_range": "LAST_7_DAYS",
                })
                if result.success and result.output:
                    reports[platform] = result.output
                else:
                    reports[platform] = {"error": result.error or "Unknown error"}
            except Exception as exc:
                reports[platform] = {"error": str(exc)}

        # Calculate totals
        total_spend = 0
        total_clicks = 0
        total_conversions = 0

        for platform, data in reports.items():
            if "campaigns" in data:
                for campaign in data["campaigns"]:
                    total_spend += campaign.get("spend", 0)
                    total_clicks += campaign.get("clicks", 0)
                    total_conversions += campaign.get("conversions", 0)

        logger.info(
            "ad_tasks.reporting.complete",
            platforms=len(platforms),
            total_spend=total_spend,
            total_clicks=total_clicks,
            total_conversions=total_conversions,
        )

        return {
            "status": "ok",
            "period": "LAST_7_DAYS",
            "platforms": reports,
            "totals": {
                "spend": total_spend,
                "clicks": total_clicks,
                "conversions": total_conversions,
                "cpc": total_spend / total_clicks if total_clicks > 0 else 0,
                "cost_per_conversion": total_spend / total_conversions if total_conversions > 0 else 0,
            },
        }
