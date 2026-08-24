"""
app/agents/engineering_division.py
────────────────────────────────────
EngineeringDivisionAgent — P2 coordinator for technical delivery.

Orchestrates the client-facing engineering lifecycle by sequencing the
appropriate sub-agents based on the trigger type:

  client_onboarding     → client_onboarding → project_kickoff
  project_kickoff       → project_kickoff
  network_monitor_setup → network_monitor_onboarding
  patch_report          → patch_compliance_reporter
  security_scoping      → security_scoping
  kb_lookup             → kb_lookup
  task_automation       → task_automator
  post_call             → post_call_processor

This agent is designed to be the single entry-point for all engineering
delivery actions from the admin dashboard or LokiOrchestratorAgent.

Permission level: P2 — the coordinator itself makes no outbound or legal
decisions.  Sub-agents carry their own permission levels (e.g. P3 for
network_monitor_onboarding which sends external emails).  The coordinator
will surface approval requirements from sub-agents up to the caller.
"""
from __future__ import annotations

import structlog

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel

logger = structlog.get_logger(__name__)

# ── Trigger constants ─────────────────────────────────────────────────────────
TRIGGER_CLIENT_ONBOARDING     = "client_onboarding"
TRIGGER_PROJECT_KICKOFF       = "project_kickoff"
TRIGGER_NETWORK_MONITOR_SETUP = "network_monitor_setup"
TRIGGER_PATCH_REPORT          = "patch_report"
TRIGGER_SECURITY_SCOPING      = "security_scoping"
TRIGGER_KB_LOOKUP             = "kb_lookup"
TRIGGER_TASK_AUTOMATION       = "task_automation"
TRIGGER_POST_CALL             = "post_call"

VALID_TRIGGERS = {
    TRIGGER_CLIENT_ONBOARDING,
    TRIGGER_PROJECT_KICKOFF,
    TRIGGER_NETWORK_MONITOR_SETUP,
    TRIGGER_PATCH_REPORT,
    TRIGGER_SECURITY_SCOPING,
    TRIGGER_KB_LOOKUP,
    TRIGGER_TASK_AUTOMATION,
    TRIGGER_POST_CALL,
}


class EngineeringDivisionAgent(BaseAgent):
    name = "engineering_division"
    description = (
        "High-level engineering delivery coordinator. Accepts a trigger "
        "(client_onboarding | project_kickoff | network_monitor_setup | "
        "patch_report | security_scoping | kb_lookup | task_automation | post_call) "
        "and orchestrates the correct sub-agent sequence. Single entry-point for "
        "all engineering delivery actions from the admin dashboard or orchestrator."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        trigger: str = input_data.get("trigger", TRIGGER_CLIENT_ONBOARDING)
        lead_id: str | None = context.lead_id or input_data.get("lead_id")

        log.info("engineering_division.start", trigger=trigger, lead_id=lead_id)

        if trigger not in VALID_TRIGGERS:
            return AgentResult.fail(
                error=f"Unknown trigger '{trigger}'. Valid: {sorted(VALID_TRIGGERS)}"
            )

        from app.agents.registry import registry

        # ── Dispatch table ─────────────────────────────────────────────────────
        if trigger == TRIGGER_CLIENT_ONBOARDING:
            return await self._run_client_onboarding(context, input_data, registry, log)

        elif trigger == TRIGGER_PROJECT_KICKOFF:
            return await self._run_project_kickoff(context, input_data, registry, log)

        elif trigger == TRIGGER_NETWORK_MONITOR_SETUP:
            return await self._run_network_monitor_setup(context, input_data, registry, log)

        elif trigger == TRIGGER_PATCH_REPORT:
            return await self._run_patch_report(context, input_data, registry, log)

        elif trigger == TRIGGER_SECURITY_SCOPING:
            return await self._run_security_scoping(context, input_data, registry, log)

        elif trigger == TRIGGER_KB_LOOKUP:
            return await self._run_kb_lookup(context, input_data, registry, log)

        elif trigger == TRIGGER_TASK_AUTOMATION:
            return await self._run_task_automation(context, input_data, registry, log)

        elif trigger == TRIGGER_POST_CALL:
            return await self._run_post_call(context, input_data, registry, log)

        return AgentResult.fail(error=f"Unhandled trigger: {trigger}")

    # ── Trigger handlers ───────────────────────────────────────────────────────

    async def _run_client_onboarding(self, context, input_data, registry, log) -> AgentResult:
        """
        Full client onboarding sequence.
        client_onboarding → project_kickoff → portal_notifier
        """
        lead_id = context.lead_id or input_data.get("lead_id")
        if not lead_id:
            return AgentResult.fail(error="client_onboarding trigger requires lead_id")

        steps_completed: list[str] = []
        output: dict = {"trigger": TRIGGER_CLIENT_ONBOARDING}

        # Step 1: Client onboarding (creates portal account, welcome email)
        try:
            onboarding = registry.get("client_onboarding")
            result = await onboarding(context, input_data)
            if result.success:
                output["onboarding"] = result.output
                steps_completed.append("client_onboarding")
                log.info("engineering_division.onboarding_ok", lead_id=lead_id)
            else:
                log.error("engineering_division.onboarding_failed", error=result.error)
                return AgentResult.fail(
                    error=f"Client onboarding failed: {result.error}",
                    steps_completed=steps_completed,
                )
        except Exception as exc:
            log.error("engineering_division.onboarding_error", error=str(exc))
            return AgentResult.fail(error=f"Client onboarding error: {exc}")

        # Step 2: Project kickoff (sets up project structure, kickoff email)
        try:
            kickoff = registry.get("project_kickoff")
            result = await kickoff(context, input_data)
            if result.success:
                output["kickoff"] = result.output
                steps_completed.append("project_kickoff")
                log.info("engineering_division.kickoff_ok")
            else:
                log.warning("engineering_division.kickoff_failed", error=result.error)
                # Non-fatal — onboarding completed, kickoff can be retried
        except Exception as exc:
            log.warning("engineering_division.kickoff_error", error=str(exc))

        # Step 3: Portal notifier (non-fatal)
        try:
            notifier = registry.get("portal_notifier")
            result = await notifier(context, {**input_data, "event": "onboarding_complete"})
            if result.success:
                steps_completed.append("portal_notifier")
        except Exception as exc:
            log.warning("engineering_division.portal_notifier_error", error=str(exc))

        output["steps_completed"] = steps_completed
        return AgentResult.ok(output=output)

    async def _run_project_kickoff(self, context, input_data, registry, log) -> AgentResult:
        """Direct project kickoff — for already-onboarded clients."""
        try:
            kickoff = registry.get("project_kickoff")
            result = await kickoff(context, input_data)
            log.info("engineering_division.kickoff_standalone_ok", success=result.success)
            return AgentResult.ok(
                output={
                    "trigger": TRIGGER_PROJECT_KICKOFF,
                    "steps_completed": ["project_kickoff"],
                    "kickoff": result.output,
                }
            )
        except Exception as exc:
            log.error("engineering_division.kickoff_standalone_error", error=str(exc))
            return AgentResult.fail(error=f"Project kickoff failed: {exc}")

    async def _run_network_monitor_setup(self, context, input_data, registry, log) -> AgentResult:
        """
        Network monitoring onboarding for a new client site.
        Requires client context (lead_id, site details) in input_data.
        P3 sub-agent — will surface approval_required if in production.
        """
        try:
            monitor = registry.get("network_monitor_onboarding")
            result = await monitor(context, input_data)
            if result.approval_required:
                return AgentResult.needs_approval(
                    approval_id=result.approval_id,
                    action="network_monitor_onboarding.setup",
                )
            log.info("engineering_division.network_monitor_ok", success=result.success)
            return AgentResult.ok(
                output={
                    "trigger": TRIGGER_NETWORK_MONITOR_SETUP,
                    "steps_completed": ["network_monitor_onboarding"],
                    "monitor": result.output,
                }
            )
        except Exception as exc:
            log.error("engineering_division.network_monitor_error", error=str(exc))
            return AgentResult.fail(error=f"Network monitor setup failed: {exc}")

    async def _run_patch_report(self, context, input_data, registry, log) -> AgentResult:
        """Generate a patch compliance report for a client environment."""
        try:
            reporter = registry.get("patch_compliance_reporter")
            result = await reporter(context, input_data)
            log.info("engineering_division.patch_report_ok", success=result.success)
            return AgentResult.ok(
                output={
                    "trigger": TRIGGER_PATCH_REPORT,
                    "steps_completed": ["patch_compliance_reporter"],
                    "report": result.output,
                }
            )
        except Exception as exc:
            log.error("engineering_division.patch_report_error", error=str(exc))
            return AgentResult.fail(error=f"Patch report failed: {exc}")

    async def _run_security_scoping(self, context, input_data, registry, log) -> AgentResult:
        """Security scope assessment for a prospective or existing client."""
        try:
            scoping = registry.get("security_scoping")
            result = await scoping(context, input_data)
            log.info("engineering_division.security_scoping_ok", success=result.success)
            return AgentResult.ok(
                output={
                    "trigger": TRIGGER_SECURITY_SCOPING,
                    "steps_completed": ["security_scoping"],
                    "scoping": result.output,
                }
            )
        except Exception as exc:
            log.error("engineering_division.security_scoping_error", error=str(exc))
            return AgentResult.fail(error=f"Security scoping failed: {exc}")

    async def _run_kb_lookup(self, context, input_data, registry, log) -> AgentResult:
        """Knowledge base lookup — P1, always available."""
        query: str = input_data.get("query", "")
        if not query:
            return AgentResult.fail(error="kb_lookup trigger requires 'query' in input_data")

        try:
            kb = registry.get("kb_lookup")
            result = await kb(context, input_data)
            log.info("engineering_division.kb_lookup_ok", success=result.success)
            return AgentResult.ok(
                output={
                    "trigger": TRIGGER_KB_LOOKUP,
                    "steps_completed": ["kb_lookup"],
                    "answer": result.output,
                }
            )
        except Exception as exc:
            log.error("engineering_division.kb_lookup_error", error=str(exc))
            return AgentResult.fail(error=f"KB lookup failed: {exc}")

    async def _run_task_automation(self, context, input_data, registry, log) -> AgentResult:
        """
        Delegate a structured IT task to TaskAutomatorAgent.
        input_data must contain 'task_type' and 'task_payload'.
        """
        if not input_data.get("task_type"):
            return AgentResult.fail(error="task_automation trigger requires 'task_type'")

        try:
            automator = registry.get("task_automator")
            result = await automator(context, input_data)
            if result.approval_required:
                return AgentResult.needs_approval(
                    approval_id=result.approval_id,
                    action=f"task_automator.{input_data['task_type']}",
                )
            log.info("engineering_division.task_automation_ok", success=result.success)
            return AgentResult.ok(
                output={
                    "trigger": TRIGGER_TASK_AUTOMATION,
                    "steps_completed": ["task_automator"],
                    "task_result": result.output,
                }
            )
        except Exception as exc:
            log.error("engineering_division.task_automation_error", error=str(exc))
            return AgentResult.fail(error=f"Task automation failed: {exc}")

    async def _run_post_call(self, context, input_data, registry, log) -> AgentResult:
        """
        Post-call processing — transcript analysis, next steps, CRM update.
        input_data must contain 'call_transcript' or 'vapi_call_id'.
        """
        if not (input_data.get("call_transcript") or input_data.get("vapi_call_id")):
            return AgentResult.fail(
                error="post_call trigger requires 'call_transcript' or 'vapi_call_id'"
            )

        try:
            processor = registry.get("post_call_processor")
            result = await processor(context, input_data)
            log.info("engineering_division.post_call_ok", success=result.success)
            return AgentResult.ok(
                output={
                    "trigger": TRIGGER_POST_CALL,
                    "steps_completed": ["post_call_processor"],
                    "post_call": result.output,
                }
            )
        except Exception as exc:
            log.error("engineering_division.post_call_error", error=str(exc))
            return AgentResult.fail(error=f"Post-call processing failed: {exc}")
