"""
app/agents/platform_client_converter.py
──────────────────────────────────────────
PlatformClientConverterAgent (P2) — converts a won freelance platform bid
into a Klara AI Lead and triggers the client onboarding pipeline.

Called when:
  - Anthony manually marks a bid as won via the admin dashboard
    PATCH /api/v1/admin/freelance/bids/{id}/mark-won
  - Or: a platform webhook confirms a contract was awarded (future integration)

Flow:
  1. Load PlatformBid + FreelanceProject.
  2. Check if a Lead already exists with the same platform client email
     (idempotency guard — never create duplicate leads).
  3. Create a new Lead record:
       - source = "freelance_<platform>"   (e.g. "freelance_upwork")
       - name  = client_name from project
       - email = client_email from project (if available)
       - status = HOT
       - tier   = HOT
       - message = project title + description excerpt
       - company = inferred from client_name
  4. Link PlatformBid.lead_id → new Lead.
  5. Set PlatformBid.status = won, won_at = now.
  6. Set FreelanceProject.status = won, won_at = now.
  7. Fire client_onboarding agent inline.
  8. Return { lead_id, was_duplicate, onboarding_result }.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import structlog
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.freelance_project import FreelanceProject, FreelanceProjectStatus
from app.models.platform_bid import PlatformBid, PlatformBidStatus

logger = structlog.get_logger(__name__)


class PlatformClientConverterAgent(BaseAgent):
    name = "platform_client_converter"
    description = (
        "Converts a won freelance platform bid into a Klara AI Lead record and triggers "
        "client onboarding. Deduplicates by client email. "
        "P2 — no approval gate."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        input_data:
          bid_id: str  — required — the PlatformBid that was won
          client_name:  str  — override (if not in project record)
          client_email: str  — override (if not in project record)
          client_phone: str  — override

        Returns AgentResult.ok({
            "lead_id": str,
            "was_duplicate": bool,
            "onboarding_triggered": bool
        })
        """
        bid_id = input_data.get("bid_id")
        if not bid_id:
            return AgentResult.fail("platform_client_converter: 'bid_id' is required.")

        # Load bid
        bid_q = await context.db.execute(
            select(PlatformBid).where(PlatformBid.id == bid_id)
        )
        bid = bid_q.scalar_one_or_none()
        if not bid:
            return AgentResult.fail(f"PlatformBid {bid_id} not found.")

        # Load project
        proj_q = await context.db.execute(
            select(FreelanceProject).where(FreelanceProject.id == bid.project_id)
        )
        project = proj_q.scalar_one_or_none()
        if not project:
            return AgentResult.fail(f"FreelanceProject {bid.project_id} not found.")

        # Resolve client info (input_data overrides project fields)
        client_name = (
            input_data.get("client_name")
            or project.client_name
            or "Client"
        )
        client_email = (
            input_data.get("client_email")
            or project.client_email
        )
        client_phone = (
            input_data.get("client_phone")
            or project.client_phone
        )

        # ── Import Lead here to avoid circular at module level ────────────────
        from app.models.lead import Lead

        # ── Idempotency: check for existing lead by email ─────────────────────
        if client_email:
            existing_q = await context.db.execute(
                select(Lead).where(Lead.email == client_email)
            )
            existing_lead = existing_q.scalar_one_or_none()
            if existing_lead:
                # Already in system — just update bid link and status
                bid.lead_id = existing_lead.id
                bid.status = PlatformBidStatus.won
                bid.won_at = datetime.now(tz=timezone.utc)
                project.status = FreelanceProjectStatus.won
                project.won_at = datetime.now(tz=timezone.utc)
                await context.db.commit()

                logger.info(
                    "platform_client_converter.duplicate",
                    bid_id=bid_id,
                    existing_lead_id=existing_lead.id,
                    email=client_email,
                )
                return AgentResult.ok(
                    output={
                        "lead_id": existing_lead.id,
                        "was_duplicate": True,
                        "onboarding_triggered": False,
                    }
                )

        # ── Create new Lead ───────────────────────────────────────────────────
        platform_label = bid.platform.title()
        description_excerpt = (project.description or "")[:500]
        source = f"freelance_{bid.platform}"

        new_lead = Lead(
            name=client_name,
            email=client_email,
            phone=client_phone,
            company=client_name if not client_email else None,
            message=(
                f"[{platform_label} Project] {project.title}\n\n"
                f"{description_excerpt}"
            ),
            source=source,
            status="HOT",
            score=90,   # Won bids are always HOT — they already chose us
            gdpr_consent=True,   # Contractual relationship established
            gdpr_ip="platform_api",
        )
        context.db.add(new_lead)
        await context.db.flush()   # get new_lead.id

        # Link bid → lead
        bid.lead_id = new_lead.id
        bid.status = PlatformBidStatus.won
        bid.won_at = datetime.now(tz=timezone.utc)

        # Update project
        project.status = FreelanceProjectStatus.won
        project.won_at = datetime.now(tz=timezone.utc)
        project.client_email = client_email or project.client_email
        project.client_phone = client_phone or project.client_phone

        await context.db.commit()

        logger.info(
            "platform_client_converter.lead_created",
            bid_id=bid_id,
            lead_id=new_lead.id,
            platform=bid.platform,
            client_name=client_name,
            client_email=client_email,
        )

        # ── Trigger client onboarding inline ─────────────────────────────────
        onboarding_triggered = False
        try:
            from app.agents.registry import get_registry
            registry = get_registry()
            onboarding_agent = registry.get("client_onboarding")

            if onboarding_agent:
                onboard_ctx = AgentContext(
                    db=context.db,
                    settings=context.settings,
                    lead_id=new_lead.id,
                    conversation_id=context.conversation_id,
                    request_id=context.request_id,
                )
                onboard_result = await onboarding_agent.run(
                    onboard_ctx,
                    {"lead_id": new_lead.id, "source": source},
                )
                onboarding_triggered = onboard_result.success
                logger.info(
                    "platform_client_converter.onboarding_result",
                    lead_id=new_lead.id,
                    success=onboard_result.success,
                )
        except Exception as exc:
            logger.error(
                "platform_client_converter.onboarding_error",
                lead_id=new_lead.id,
                error=str(exc),
            )

        return AgentResult.ok(
            output={
                "lead_id": new_lead.id,
                "was_duplicate": False,
                "onboarding_triggered": onboarding_triggered,
                "platform": bid.platform,
                "project_title": project.title,
                "client_name": client_name,
                "client_email": client_email,
            }
        )
