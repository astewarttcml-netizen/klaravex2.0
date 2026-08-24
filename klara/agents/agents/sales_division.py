"""
app/agents/sales_division.py
──────────────────────────────
SalesDivisionAgent — P2 coordinator for the full sales funnel.

Orchestrates the complete inbound-to-won sales cycle by sequencing the
appropriate sub-agents based on the trigger type:

  inbound_lead        → lead_qualification → lead_scoring → routing
  proposal_request    → proposal_drafting (P4 approval gate)
  followup            → followup_nurture
  reactivation        → lead_reactivation
  discovery_call_prep → discovery_call_prep + objection_handler briefing
  cold_nurture        → cold_nurture

This agent does NOT replace the standard pipeline routers.  It is a
higher-level coordinator designed to be called directly (e.g., from the
admin dashboard or the LokiOrchestratorAgent) when the operator wants a
single entry-point for any sales-domain action.

All sub-agent calls are wrapped in isolated try/except blocks — a failure
in one step is logged and noted in the output but does NOT abort the
division run unless it is a fatal dependency.
"""
from __future__ import annotations

import structlog

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel

logger = structlog.get_logger(__name__)

# ── Trigger constants ─────────────────────────────────────────────────────────
TRIGGER_INBOUND_LEAD        = "inbound_lead"
TRIGGER_PROPOSAL_REQUEST    = "proposal_request"
TRIGGER_FOLLOWUP            = "followup"
TRIGGER_REACTIVATION        = "reactivation"
TRIGGER_DISCOVERY_CALL_PREP = "discovery_call_prep"
TRIGGER_COLD_NURTURE        = "cold_nurture"

VALID_TRIGGERS = {
    TRIGGER_INBOUND_LEAD,
    TRIGGER_PROPOSAL_REQUEST,
    TRIGGER_FOLLOWUP,
    TRIGGER_REACTIVATION,
    TRIGGER_DISCOVERY_CALL_PREP,
    TRIGGER_COLD_NURTURE,
}


class SalesDivisionAgent(BaseAgent):
    name = "sales_division"
    description = (
        "High-level sales coordinator. Accepts a trigger (inbound_lead | "
        "proposal_request | followup | reactivation | discovery_call_prep | "
        "cold_nurture) and orchestrates the correct sub-agent sequence for that "
        "sales scenario. Designed as a single entry-point for all sales-domain "
        "actions from the admin dashboard or LokiOrchestratorAgent."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        trigger: str = input_data.get("trigger", TRIGGER_INBOUND_LEAD)
        lead_id: str | None = context.lead_id or input_data.get("lead_id")

        log.info("sales_division.start", trigger=trigger, lead_id=lead_id)

        if trigger not in VALID_TRIGGERS:
            return AgentResult.fail(
                error=f"Unknown trigger '{trigger}'. Valid: {sorted(VALID_TRIGGERS)}"
            )

        from app.agents.registry import registry

        # ── Dispatch table ─────────────────────────────────────────────────────
        if trigger == TRIGGER_INBOUND_LEAD:
            return await self._run_inbound_lead(context, input_data, registry, log)

        elif trigger == TRIGGER_PROPOSAL_REQUEST:
            return await self._run_proposal_request(context, input_data, registry, log)

        elif trigger == TRIGGER_FOLLOWUP:
            return await self._run_followup(context, input_data, registry, log)

        elif trigger == TRIGGER_REACTIVATION:
            return await self._run_reactivation(context, input_data, registry, log)

        elif trigger == TRIGGER_DISCOVERY_CALL_PREP:
            return await self._run_discovery_call_prep(context, input_data, registry, log)

        elif trigger == TRIGGER_COLD_NURTURE:
            return await self._run_cold_nurture(context, input_data, registry, log)

        # Should not reach here — guard above covers all triggers
        return AgentResult.fail(error=f"Unhandled trigger: {trigger}")

    # ── Trigger handlers ───────────────────────────────────────────────────────

    async def _run_inbound_lead(self, context, input_data, registry, log) -> AgentResult:
        """
        Full qualification pipeline.
        qualification → scoring → routing
        Each step accumulates output into a shared payload.
        """
        steps_completed: list[str] = []
        payload = dict(input_data)

        # Step 1: Lead qualification
        try:
            qual = registry.get("lead_qualification")
            qual_result = await qual(context, payload)
            if qual_result.success and qual_result.output:
                payload.update(qual_result.output)
                steps_completed.append("lead_qualification")
                log.info("sales_division.qualification_ok", tier=qual_result.output.get("tier"))
            else:
                log.warning("sales_division.qualification_failed", error=qual_result.error)
                return AgentResult.fail(
                    error=f"Lead qualification failed: {qual_result.error}",
                    steps_completed=steps_completed,
                )
        except Exception as exc:
            log.error("sales_division.qualification_error", error=str(exc))
            return AgentResult.fail(error=f"Lead qualification error: {exc}")

        # Step 2: Lead scoring
        try:
            scoring = registry.get("lead_scoring")
            score_result = await scoring(context, payload)
            if score_result.success and score_result.output:
                payload.update(score_result.output)
                steps_completed.append("lead_scoring")
                log.info(
                    "sales_division.scoring_ok",
                    score=score_result.output.get("score"),
                    tier=score_result.output.get("tier"),
                )
            else:
                log.warning("sales_division.scoring_failed", error=score_result.error)
                # Non-fatal — carry forward with whatever score qualification assigned
        except Exception as exc:
            log.warning("sales_division.scoring_error", error=str(exc))

        # Step 3: Routing — decides outreach, alerts, and proposal gates
        try:
            routing = registry.get("routing")
            route_result = await routing(context, payload)
            steps_completed.append("routing")
            log.info(
                "sales_division.routing_ok",
                next_action=route_result.output.get("next_action") if route_result.output else None,
                approval_required=route_result.approval_required,
            )

            if route_result.approval_required:
                return AgentResult.needs_approval(
                    approval_id=route_result.approval_id,
                    action="proposal_drafting.draft",
                )

            return AgentResult.ok(
                output={
                    "trigger": TRIGGER_INBOUND_LEAD,
                    "steps_completed": steps_completed,
                    "score": payload.get("score"),
                    "tier": payload.get("tier"),
                    "next_action": route_result.output.get("next_action") if route_result.output else None,
                    "routing": route_result.output,
                }
            )
        except Exception as exc:
            log.error("sales_division.routing_error", error=str(exc))
            return AgentResult.fail(
                error=f"Routing failed: {exc}",
                steps_completed=steps_completed,
            )

    async def _run_proposal_request(self, context, input_data, registry, log) -> AgentResult:
        """
        Direct proposal generation.
        Requires lead_id.  Stops at P4 approval gate in production.
        """
        lead_id = context.lead_id or input_data.get("lead_id")
        if not lead_id:
            return AgentResult.fail(error="proposal_request trigger requires lead_id")

        try:
            # P4 requires approval_manager gate in production
            if context.settings.is_production:
                approval_mgr = registry.get("approval_manager")
                approval_result = await approval_mgr(
                    context,
                    {
                        "action": "create",
                        "action_name": "proposal_drafting.draft",
                        "risk_level": "P4",
                        "payload": {"lead_id": lead_id, **input_data},
                        "justification": input_data.get(
                            "justification", "Manual proposal request via SalesDivisionAgent"
                        ),
                        "requested_by": self.name,
                    },
                )
                if approval_result.success:
                    return AgentResult.needs_approval(
                        approval_id=approval_result.output["approval_id"],
                        action="proposal_drafting.draft",
                    )

            # Dev/staging: fire immediately
            proposal = registry.get("proposal_drafting")
            result = await proposal(context, input_data)
            log.info("sales_division.proposal_complete", success=result.success)
            return AgentResult.ok(
                output={
                    "trigger": TRIGGER_PROPOSAL_REQUEST,
                    "steps_completed": ["proposal_drafting"],
                    "proposal": result.output,
                }
            )
        except Exception as exc:
            log.error("sales_division.proposal_error", error=str(exc))
            return AgentResult.fail(error=f"Proposal request failed: {exc}")

    async def _run_followup(self, context, input_data, registry, log) -> AgentResult:
        """Nurture sequence for existing warm leads."""
        lead_id = context.lead_id or input_data.get("lead_id")
        if not lead_id:
            return AgentResult.fail(error="followup trigger requires lead_id")

        try:
            nurture = registry.get("followup_nurture")
            result = await nurture(context, input_data)
            log.info("sales_division.followup_ok", success=result.success)
            return AgentResult.ok(
                output={
                    "trigger": TRIGGER_FOLLOWUP,
                    "steps_completed": ["followup_nurture"],
                    "nurture": result.output,
                }
            )
        except Exception as exc:
            log.error("sales_division.followup_error", error=str(exc))
            return AgentResult.fail(error=f"Follow-up failed: {exc}")

    async def _run_reactivation(self, context, input_data, registry, log) -> AgentResult:
        """Re-engage cold/stale leads."""
        lead_id = context.lead_id or input_data.get("lead_id")
        if not lead_id:
            return AgentResult.fail(error="reactivation trigger requires lead_id")

        try:
            reactivation = registry.get("lead_reactivation")
            result = await reactivation(context, input_data)
            log.info("sales_division.reactivation_ok", success=result.success)
            return AgentResult.ok(
                output={
                    "trigger": TRIGGER_REACTIVATION,
                    "steps_completed": ["lead_reactivation"],
                    "reactivation": result.output,
                }
            )
        except Exception as exc:
            log.error("sales_division.reactivation_error", error=str(exc))
            return AgentResult.fail(error=f"Reactivation failed: {exc}")

    async def _run_discovery_call_prep(self, context, input_data, registry, log) -> AgentResult:
        """
        Pre-call intelligence package.
        discovery_call_prep + enrichment + objection briefing (non-fatal).
        """
        lead_id = context.lead_id or input_data.get("lead_id")
        steps_completed: list[str] = []
        output: dict = {"trigger": TRIGGER_DISCOVERY_CALL_PREP}

        # Step 1: Lead enrichment (optional pre-call intel)
        try:
            enrichment = registry.get("lead_enrichment")
            enrich_result = await enrichment(context, input_data)
            if enrich_result.success:
                output["enrichment"] = enrich_result.output
                steps_completed.append("lead_enrichment")
        except Exception as exc:
            log.warning("sales_division.enrichment_error", error=str(exc))

        # Step 2: Discovery call prep (primary)
        try:
            prep = registry.get("discovery_call_prep")
            prep_result = await prep(context, input_data)
            if prep_result.success:
                output["call_prep"] = prep_result.output
                steps_completed.append("discovery_call_prep")
            else:
                return AgentResult.fail(
                    error=f"Discovery call prep failed: {prep_result.error}",
                    steps_completed=steps_completed,
                )
        except Exception as exc:
            log.error("sales_division.discovery_prep_error", error=str(exc))
            return AgentResult.fail(error=f"Discovery call prep error: {exc}")

        output["steps_completed"] = steps_completed
        log.info("sales_division.discovery_prep_ok", lead_id=lead_id)
        return AgentResult.ok(output=output)

    async def _run_cold_nurture(self, context, input_data, registry, log) -> AgentResult:
        """3-touch cold nurture sequence."""
        lead_id = context.lead_id or input_data.get("lead_id")
        if not lead_id:
            return AgentResult.fail(error="cold_nurture trigger requires lead_id")

        try:
            nurture = registry.get("cold_nurture")
            result = await nurture(context, input_data)
            log.info("sales_division.cold_nurture_ok", success=result.success)
            return AgentResult.ok(
                output={
                    "trigger": TRIGGER_COLD_NURTURE,
                    "steps_completed": ["cold_nurture"],
                    "nurture": result.output,
                }
            )
        except Exception as exc:
            log.error("sales_division.cold_nurture_error", error=str(exc))
            return AgentResult.fail(error=f"Cold nurture failed: {exc}")
