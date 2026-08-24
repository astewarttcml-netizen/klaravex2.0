"""
app/tasks/research_prospect.py
───────────────────────────────
Celery task: run web research on a ProspectedLead before handing off to
ProspectingOutreachAgent.

Flow:
  1. Load ProspectedLead from DB by prospect_id.
  2. Call gather_research(prospect, settings) from app.services.research.orchestrator.
  3. Persist the research bundle as JSON in prospect.research_data (JSONB column).
  4. Chain directly to prospecting_outreach agent, passing the research_bundle in input_data.

The outreach agent already handles the case where research_bundle is absent (legacy path),
so this task is strictly additive — existing prospects without research data continue
to work unchanged.
"""
from __future__ import annotations

import asyncio
import uuid

import structlog

from app.tasks.celery_app import celery_app
from app.config import get_settings
from app.database import db_context

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="app.tasks.research_prospect.run_research",
    bind=True,
    max_retries=1,
    default_retry_delay=120,
)
def run_research(self, prospect_id: str):
    """
    Celery task entry point (synchronous wrapper around async implementation).

    Args:
        prospect_id: UUID string of the ProspectedLead to research and send.
    """
    try:
        asyncio.run(_research_and_outreach(prospect_id))
    except Exception as exc:
        logger.error(
            "research_prospect.task_failed",
            prospect_id=prospect_id,
            error=str(exc),
            exc_info=True,
        )
        raise self.retry(exc=exc)


async def _research_and_outreach(prospect_id: str) -> None:
    """Async implementation — runs inside Celery worker's event loop."""
    from sqlalchemy import select

    from app.agents.base import AgentContext
    from app.agents.registry import registry
    from app.models.prospected_lead import ProspectedLead, ProspectedLeadStatus

    settings = get_settings()

    async with db_context() as db:
        # ── 1. Load prospect ──────────────────────────────────────────────────
        result = await db.execute(
            select(ProspectedLead).where(ProspectedLead.id == prospect_id)
        )
        prospect = result.scalar_one_or_none()
        if not prospect:
            logger.error(
                "research_prospect.not_found",
                prospect_id=prospect_id,
            )
            return

        if prospect.status != ProspectedLeadStatus.new:
            logger.info(
                "research_prospect.skipped",
                prospect_id=prospect_id,
                status=prospect.status,
                reason="already processed",
            )
            return

        # ── 2. Gather research bundle ──────────────────────────────────────────
        research_bundle: dict = {}
        try:
            from app.services.research.orchestrator import gather_research
            raw_bundle = await gather_research({"domain": prospect.domain, "company_name": prospect.company_name, "apollo_org_id": getattr(prospect, "apollo_organization_id", "") or "", "linkedin_url": getattr(prospect, "contact_linkedin", "") or ""}, settings)
            research_bundle = raw_bundle.to_copy_context() if hasattr(raw_bundle, "to_copy_context") else (vars(raw_bundle) if hasattr(raw_bundle, "__dict__") else {})
            logger.info(
                "research_prospect.research_complete",
                prospect_id=prospect_id,
                domain=prospect.domain,
                signals=list(research_bundle.keys()),
            )
        except ImportError:
            # Orchestrator not yet implemented — proceed without research data
            logger.warning(
                "research_prospect.orchestrator_not_available",
                prospect_id=prospect_id,
                domain=prospect.domain,
            )
        except Exception as exc:
            # Research failure is non-fatal — fall back to signal-only outreach
            logger.warning(
                "research_prospect.research_failed",
                prospect_id=prospect_id,
                domain=prospect.domain,
                error=str(exc),
            )

        # ── 3. Persist research bundle to prospect record ─────────────────────
        if research_bundle:
            try:
                prospect.research_data = research_bundle  # type: ignore[attr-defined]
                await db.flush()
                logger.info(
                    "research_prospect.research_stored",
                    prospect_id=prospect_id,
                    domain=prospect.domain,
                )
            except Exception as exc:
                # Column may not exist in older deployments — log and continue
                logger.warning(
                    "research_prospect.research_store_failed",
                    prospect_id=prospect_id,
                    error=str(exc),
                )

        # ── 4. Chain to outreach agent ─────────────────────────────────────────
        context = AgentContext(
            db=db,
            settings=settings,
            conversation_id=uuid.uuid4(),
            request_id=uuid.uuid4(),
            lead_id=None,
        )

        outreach_agent = registry.get("prospecting_outreach")
        outreach_result = await outreach_agent.run(
            context,
            {
                "prospect_id": prospect_id,
                "research_bundle": research_bundle or None,
            },
        )

        if outreach_result.success:
            logger.info(
                "research_prospect.outreach_dispatched",
                prospect_id=prospect_id,
                domain=prospect.domain,
                sent=outreach_result.output.get("sent"),
                subject=outreach_result.output.get("subject"),
            )
        else:
            logger.warning(
                "research_prospect.outreach_failed",
                prospect_id=prospect_id,
                domain=prospect.domain,
                error=outreach_result.error,
            )
