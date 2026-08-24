"""
app/agents/loki_orchestrator.py
────────────────────────────────
Klara AI — the master orchestrator.

Klara AI receives every incoming request and decides:
  1. Which pipeline to run (chat intake → qualify → score → route → draft)
  2. Whether to escalate to a human via the approval_manager
  3. How to compose agent results into a final response

Every task now travels inside a TaskEnvelope that carries risk metadata.
The route() method enforces the full policy/approval lifecycle before any
agent action is executed.

Pipelines:
  - chat_pipeline:     chat → qualify → score → route
                       (routing fires outreach_email internally for HOT/WARM)
  - form_pipeline:     form_intake → qualify → score → route
  - proposal_pipeline: lead_id → proposal_drafting (P4, approval required)
  - webhook_pipeline:  wp_webhook → context_manager → qualify
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from app.agents.confidence import FallbackAction, get_fallback_action
from app.agents.manifests import AGENT_MANIFESTS, AgentManifest
from app.agents.rollout_mode import enforce_mode
from klara.rarv.runtime import get_settings
from klara.rarv.runtime import PermissionLevel

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class RiskTier(str, Enum):
    low       = "low"        # log-only; auto-execute
    medium    = "medium"     # create draft; human reviews
    high      = "high"       # require explicit approval before any action
    forbidden = "forbidden"  # never execute; log and alert


class ApprovalState(str, Enum):
    not_required = "not_required"
    pending      = "pending"
    approved     = "approved"
    rejected     = "rejected"


# ─────────────────────────────────────────────────────────────────────────────
# TaskEnvelope
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TaskEnvelope:
    """All context needed to route and execute a single unit of work."""
    task_id: str
    actor: str                        # agent name or "human"
    action: str                       # what to do (e.g. "send_email")
    object_type: str                  # "lead", "invoice", "content", "proposal", …
    object_id: str | None             # ID of the object being acted on
    risk_tier: RiskTier               # resolved by _classify_risk
    approval_state: ApprovalState     # lifecycle state for high/medium tasks
    dependencies: list[str]           # task_ids that must complete first
    payload: dict                     # action-specific data
    created_at: datetime
    deadline: datetime | None = None
    context: str | None = None        # human-readable why

    @classmethod
    def create(
        cls,
        actor: str,
        action: str,
        object_type: str,
        payload: dict,
        object_id: str | None = None,
        dependencies: list[str] | None = None,
        deadline: datetime | None = None,
        context: str | None = None,
    ) -> "TaskEnvelope":
        """Factory — auto-assigns task_id, timestamps, and classifies risk."""
        risk = _classify_risk(action, object_type)
        approval = (
            ApprovalState.not_required
            if risk in (RiskTier.low, RiskTier.forbidden)
            else ApprovalState.pending
        )
        return cls(
            task_id=str(uuid.uuid4()),
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=object_id,
            risk_tier=risk,
            approval_state=approval,
            dependencies=dependencies or [],
            payload=payload,
            created_at=datetime.now(timezone.utc),
            deadline=deadline,
            context=context,
        )


# ─────────────────────────────────────────────────────────────────────────────
# TaskResult
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TaskResult:
    task_id: str
    status: str          # "executed" | "draft_created" | "awaiting_approval"
                         # | "blocked" | "rejected" | "failed"
    approval_id: str | None = None
    output: dict | None = None
    error: str | None = None
    logged_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def executed(cls, task_id: str, output: dict | None = None) -> "TaskResult":
        return cls(task_id=task_id, status="executed", output=output)

    @classmethod
    def draft_created(cls, task_id: str, approval_id: str, output: dict | None = None) -> "TaskResult":
        return cls(task_id=task_id, status="draft_created", approval_id=approval_id, output=output)

    @classmethod
    def awaiting_approval(cls, task_id: str, approval_id: str) -> "TaskResult":
        return cls(task_id=task_id, status="awaiting_approval", approval_id=approval_id)

    @classmethod
    def blocked(cls, task_id: str, reason: str) -> "TaskResult":
        return cls(task_id=task_id, status="blocked", error=reason)

    @classmethod
    def rejected(cls, task_id: str, reason: str) -> "TaskResult":
        return cls(task_id=task_id, status="rejected", error=reason)

    @classmethod
    def failed(cls, task_id: str, error: str) -> "TaskResult":
        return cls(task_id=task_id, status="failed", error=error)


# ─────────────────────────────────────────────────────────────────────────────
# Risk classification table
# ─────────────────────────────────────────────────────────────────────────────

# (action_prefix_or_exact, object_type_or_None) → RiskTier
# Evaluated top-to-bottom; first match wins.  None object_type = any.
_RISK_TABLE: list[tuple[str, str | None, RiskTier]] = [
    # Forbidden
    ("delete_client_data", None,         RiskTier.forbidden),
    ("wipe_database",      None,         RiskTier.forbidden),

    # High — explicit approval required
    ("send_email",         "client",     RiskTier.high),
    ("send_email",         "lead",       RiskTier.high),
    ("send_cold_outreach", None,         RiskTier.high),
    ("publish_content",    None,         RiskTier.high),
    ("create_invoice",     None,         RiskTier.high),
    ("process_payment",    None,         RiskTier.high),

    # Medium — draft + human review
    ("create_proposal",       None,      RiskTier.medium),
    ("update_project_status", None,      RiskTier.medium),

    # Low — auto-execute
    ("update_lead_status", None,         RiskTier.low),
    ("generate_draft",     None,         RiskTier.low),
    ("read_",              None,         RiskTier.low),   # prefix match
]


def _classify_risk(action: str, object_type: str) -> RiskTier:
    """
    Return a RiskTier for (action, object_type).

    Matching rules (in order):
    1. Exact match on (action, object_type)
    2. Exact match on (action, None)  — object_type wildcard
    3. Prefix match on action (e.g. "read_")
    4. Default → low
    """
    action_lower = action.lower()
    obj_lower = object_type.lower() if object_type else ""

    for rule_action, rule_obj, tier in _RISK_TABLE:
        if rule_action.endswith("_"):
            # prefix match
            if action_lower.startswith(rule_action):
                return tier
        else:
            # exact action match
            if action_lower != rule_action:
                continue
            if rule_obj is None or obj_lower == rule_obj:
                return tier

    return RiskTier.low


# ─────────────────────────────────────────────────────────────────────────────
# In-progress task store (in-process; swap for Redis/DB in prod)
# ─────────────────────────────────────────────────────────────────────────────

# task_id → "completed" | "in_progress" | "blocked"
_TASK_STATES: dict[str, str] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

class LokiOrchestratorAgent(BaseAgent):
    name = "loki_orchestrator"
    description = (
        "Master orchestrator. Routes requests through the correct agent pipeline, "
        "enforces risk-tier approval gates, and assembles final responses."
    )
    permission_level = PermissionLevel.P2

    # Pipeline registry: pipeline_name → ordered list of agent names
    PIPELINES: dict[str, list[str]] = {
        "chat":     ["context_manager", "chat_intake", "lead_qualification", "lead_scoring", "routing"],
        "form":     ["context_manager", "form_intake", "lead_qualification", "lead_scoring", "routing"],
        "proposal": ["context_manager", "proposal_drafting"],
        "webhook":  ["context_manager", "lead_qualification"],
        # Consumer personal IT support — Atera PSA for ticketing + remote sessions.
        # No lead qualification; ends at ticket creation when ready.
        "consumer": ["context_manager", "consumer_intake", "atera_ticket_creator"],
    }

    # ── Envelope routing ─────────────────────────────────────────────────────

    async def route(self, envelope: TaskEnvelope, agent_context: AgentContext) -> TaskResult:
        """
        Route a task envelope through the policy/execution pipeline.

        Flow:
        1. Check dependencies — if any incomplete, return blocked
        2. Re-classify risk if not already set (belt-and-suspenders)
        3. forbidden → log + reject, never execute
        4. high      → create/check ApprovalRequest; if pending → awaiting_approval
        5. medium    → create draft ApprovalRequest; return draft_created
        6. low       → execute directly, return executed
        """
        log = logger.bind(
            task_id=envelope.task_id,
            action=envelope.action,
            object_type=envelope.object_type,
            risk_tier=envelope.risk_tier,
        )

        # 1. Dependency check
        for dep_id in envelope.dependencies:
            state = _TASK_STATES.get(dep_id)
            if state != "completed":
                reason = f"Dependency {dep_id} is not completed (state={state!r})"
                log.warning("loki.route.blocked", reason=reason)
                return TaskResult.blocked(envelope.task_id, reason)

        # 2. Re-classify (idempotent if already set correctly)
        if envelope.risk_tier is None:
            envelope.risk_tier = _classify_risk(envelope.action, envelope.object_type)

        # 2b. Agent-manifest blocked_actions override: if the acting agent's
        #     manifest explicitly lists this action as blocked, escalate to
        #     RiskTier.forbidden regardless of the global risk table.
        actor_manifest = self.get_agent_manifest(envelope.actor)
        if actor_manifest and envelope.action in actor_manifest.blocked_actions:
            log.error(
                "loki.route.manifest_blocked",
                actor=envelope.actor,
                action=envelope.action,
                blocked_by="agent_manifest",
            )
            envelope.risk_tier = RiskTier.forbidden

        # 2c. Rollout mode enforcement — checked before risk/confidence pipeline
        mode_action = enforce_mode(
            get_settings().loki_mode,
            envelope.action,
            envelope.risk_tier.value,
        )
        if mode_action == FallbackAction.draft_only:
            # Shadow mode observation log
            logger.info(
                "orchestrator.shadow_observe",
                task_id=envelope.task_id,
                action=envelope.action,
                risk_tier=envelope.risk_tier,
                mode=get_settings().loki_mode,
            )
            return TaskResult.draft_created(
                envelope.task_id,
                approval_id=envelope.task_id,
                output={"observation": "shadow_mode"},
            )
        elif mode_action == FallbackAction.escalate:
            await self.escalate(
                envelope,
                reason=f"mode={get_settings().loki_mode} requires approval",
                agent_context=agent_context,
            )
            return TaskResult.awaiting_approval(envelope.task_id, approval_id=envelope.task_id)
        elif mode_action == FallbackAction.stop:
            return TaskResult.failed(envelope.task_id, error="Forbidden in current mode")
        # else FallbackAction.execute → fall through to normal risk/confidence check

        # 3. Forbidden — log and hard-stop
        if envelope.risk_tier == RiskTier.forbidden:
            log.error(
                "loki.route.forbidden",
                actor=envelope.actor,
                action=envelope.action,
                object_type=envelope.object_type,
            )
            await self._audit(agent_context, {
                "event_type": "task.forbidden",
                "task_id": envelope.task_id,
                "actor": envelope.actor,
                "action": envelope.action,
                "object_type": envelope.object_type,
            })
            return TaskResult.rejected(envelope.task_id, "Action is forbidden by policy")

        # 4. High — must have an approved ApprovalRequest
        if envelope.risk_tier == RiskTier.high:
            approval_id = await self._ensure_approval_request(
                agent_context,
                envelope,
                action_type="approval",
                justification=envelope.context,
            )
            if envelope.approval_state != ApprovalState.approved:
                log.info("loki.route.awaiting_approval", approval_id=approval_id)
                return TaskResult.awaiting_approval(envelope.task_id, approval_id)
            # Approved — fall through to execute below

        # 5. Medium — create draft + approval record, do not execute yet
        if envelope.risk_tier == RiskTier.medium:
            approval_id = await self._ensure_approval_request(
                agent_context,
                envelope,
                action_type="draft_review",
                justification=envelope.context,
            )
            log.info("loki.route.draft_created", approval_id=approval_id)
            return TaskResult.draft_created(envelope.task_id, approval_id)

        # 6. Low (or high+approved) — execute directly
        log.info("loki.route.execute")
        _TASK_STATES[envelope.task_id] = "in_progress"
        try:
            output = await self._execute_envelope(agent_context, envelope)
            _TASK_STATES[envelope.task_id] = "completed"
            log.info("loki.route.executed")
            return TaskResult.executed(envelope.task_id, output)
        except Exception as exc:
            _TASK_STATES[envelope.task_id] = "blocked"
            log.error("loki.route.failed", error=str(exc))
            return TaskResult.failed(envelope.task_id, str(exc))

    async def escalate(self, envelope: TaskEnvelope, reason: str, agent_context: AgentContext) -> None:
        """
        Escalate a blocked or ambiguous task.
        - Creates an ApprovalRequest with action_name="escalation"
        - Logs orchestrator.escalation
        - Does NOT execute the underlying action
        """
        log = logger.bind(task_id=envelope.task_id, risk_tier=envelope.risk_tier)
        log.warning("loki.escalation", reason=reason, actor=envelope.actor)

        await self._ensure_approval_request(
            agent_context,
            envelope,
            action_type="escalation",
            justification=f"ESCALATION: {reason}",
        )
        await self._audit(agent_context, {
            "event_type": "orchestrator.escalation",
            "task_id": envelope.task_id,
            "reason": reason,
            "risk_tier": envelope.risk_tier,
            "actor": envelope.actor,
        })

    # ── Manifest helpers ──────────────────────────────────────────────────────

    def get_agent_manifest(self, agent_name: str) -> AgentManifest | None:
        """Return the AgentManifest for agent_name, or None if not registered."""
        return AGENT_MANIFESTS.get(agent_name)

    # ── Legacy pipeline dispatch (wraps through route()) ─────────────────────

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        Legacy entry point — still supported for pipeline-style calls.

        input_data expected keys:
          pipeline  (str)  — one of PIPELINES keys
          payload   (dict) — pipeline-specific input

        Optionally accepts:
          actor     (str)  — who initiated (default "human")
          task_context (str) — human-readable why
        """
        pipeline_name = input_data.get("pipeline", "chat")
        payload = input_data.get("payload", {})
        actor = input_data.get("actor", "human")
        task_context = input_data.get("task_context")

        if pipeline_name not in self.PIPELINES:
            return AgentResult.fail(f"Unknown pipeline: '{pipeline_name}'")

        # Build a TaskEnvelope for the pipeline dispatch
        envelope = TaskEnvelope.create(
            actor=actor,
            action=f"run_pipeline.{pipeline_name}",
            object_type="pipeline",
            payload={"pipeline": pipeline_name, **payload},
            context=task_context,
        )

        # Route through policy checks
        task_result = await self.route(envelope, context)

        if task_result.status in ("blocked", "rejected", "failed"):
            return AgentResult.fail(task_result.error or task_result.status)

        if task_result.status == "awaiting_approval":
            return AgentResult.needs_approval(
                approval_id=task_result.approval_id,
                action=f"pipeline.{pipeline_name}",
            )

        if task_result.status == "draft_created":
            return AgentResult.needs_approval(
                approval_id=task_result.approval_id,
                action=f"pipeline.{pipeline_name}.draft",
            )

        # Executed — run the actual pipeline steps
        return await self._run_pipeline(context, pipeline_name, payload)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _run_pipeline(
        self,
        context: AgentContext,
        pipeline_name: str,
        payload: dict,
    ) -> AgentResult:
        """Execute ordered agent steps for a named pipeline."""
        from app.agents.registry import registry
        from app.agents.audit_logger import AuditLoggerAgent

        agent_names = self.PIPELINES[pipeline_name]
        audit: AuditLoggerAgent = registry.get("audit_logger")  # type: ignore
        log = logger.bind(pipeline=pipeline_name, conversation=context.conversation_id)
        log.info("loki.pipeline_start", steps=agent_names)

        current_payload = payload
        pipeline_results: list[dict] = []

        for agent_name in agent_names:
            agent = registry.get(agent_name)
            log.debug("loki.step", agent=agent_name)

            result = await agent(context, current_payload)

            pipeline_results.append(
                {"agent": agent_name, "success": result.success, "output": result.output}
            )

            # ── Confidence / fallback check ───────────────────────────────────
            if isinstance(result.output, dict):
                _confidence = result.output.get("confidence")
                _workflow   = result.output.get("workflow")
                if _confidence is not None and _workflow is not None:
                    fallback = get_fallback_action(_workflow, float(_confidence))
                    if fallback == FallbackAction.draft_only:
                        log.info(
                            "loki.confidence.draft_only",
                            agent=agent_name,
                            workflow=_workflow,
                            confidence=_confidence,
                        )
                        # Surface as a draft — caller treats this like a
                        # medium-risk draft_created result.
                        return AgentResult.ok(
                            output={
                                "pipeline": pipeline_name,
                                "steps": pipeline_results,
                                "status": "draft_created",
                                "confidence": _confidence,
                                "workflow": _workflow,
                            }
                        )
                    elif fallback == FallbackAction.escalate:
                        log.warning(
                            "loki.confidence.escalate",
                            agent=agent_name,
                            workflow=_workflow,
                            confidence=_confidence,
                        )
                        # Build a minimal envelope for the escalation call
                        _envelope = TaskEnvelope.create(
                            actor=agent_name,
                            action=f"pipeline.{pipeline_name}.confidence_escalation",
                            object_type="pipeline",
                            payload={"pipeline": pipeline_name, **current_payload},
                            context=f"confidence={_confidence:.2f} below threshold",
                        )
                        await self.escalate(
                            _envelope,
                            reason=f"confidence={_confidence:.2f} below threshold",
                            agent_context=context,
                        )
                        return AgentResult.needs_approval(
                            approval_id=_envelope.task_id,
                            action=f"pipeline.{pipeline_name}.{agent_name}",
                        )
                    elif fallback == FallbackAction.stop:
                        log.warning(
                            "orchestrator.low_confidence_stop",
                            agent=agent_name,
                            workflow=_workflow,
                            confidence=_confidence,
                        )
                        return AgentResult.fail(
                            error=(
                                f"Agent '{agent_name}' returned confidence={_confidence:.2f} "
                                f"for workflow '{_workflow}', which is below the minimum "
                                f"threshold. Action stopped."
                            )
                        )
                    # FallbackAction.execute → fall through normally
            # ─────────────────────────────────────────────────────────────────

            if result.approval_required:
                log.info("loki.approval_gate", agent=agent_name, approval_id=result.approval_id)
                await audit(
                    context,
                    {
                        "event_type": "pipeline.approval_gate",
                        "agent_name": agent_name,
                        "pipeline": pipeline_name,
                        "approval_id": result.approval_id,
                    },
                )
                return AgentResult.needs_approval(
                    approval_id=result.approval_id,
                    action=f"{pipeline_name}.{agent_name}",
                )

            if not result.success:
                log.warning("loki.step_failed", agent=agent_name, error=result.error)
                await audit(
                    context,
                    {
                        "event_type": "pipeline.step_failed",
                        "agent_name": agent_name,
                        "pipeline": pipeline_name,
                        "error": result.error,
                    },
                )
                break

            if isinstance(result.output, dict):
                current_payload = {**current_payload, **result.output}

        log.info("loki.pipeline_complete", steps_run=len(pipeline_results))
        return AgentResult.ok(
            output={"pipeline": pipeline_name, "steps": pipeline_results, "final": current_payload}
        )

    async def _execute_envelope(self, context: AgentContext, envelope: TaskEnvelope) -> dict[str, Any]:
        """
        Execute the action described in a TaskEnvelope.

        For pipeline actions: performs policy validation only and returns {}.
        Actual pipeline execution is owned by run(), which calls _run_pipeline()
        directly *after* route() completes. This separation ensures the pipeline
        runs exactly once and that AgentResult.needs_approval signals (e.g. from
        the routing agent creating a P4 approval) propagate back to the caller
        without being silently dropped by the dict return type here.

        For direct agent actions, calls the named agent.
        """
        from app.agents.registry import registry

        action = envelope.action

        if action.startswith("run_pipeline."):
            pipeline_name = action.split(".", 1)[1]
            if pipeline_name not in self.PIPELINES:
                raise ValueError(f"Unknown pipeline: {pipeline_name!r}")
            # Policy checks passed — signal OK to run().  Do NOT call _run_pipeline()
            # here: run() calls it directly so that needs_approval results (P4 gate
            # from routing) surface as AgentResult.needs_approval rather than being
            # silently converted to an empty dict by this method's return type.
            return {}

        # Direct agent dispatch: action = agent_name
        if action in {a.name for a in registry.all()}:
            agent = registry.get(action)
            result = await agent(context, envelope.payload)
            if not result.success:
                raise RuntimeError(result.error or "Agent returned failure")
            return result.output or {}

        raise ValueError(f"Cannot execute envelope action: {action!r}")

    async def _ensure_approval_request(
        self,
        context: AgentContext,
        envelope: TaskEnvelope,
        action_type: str,
        justification: str | None,
    ) -> str:
        """
        Create an ApprovalRequest row for this envelope (if one doesn't exist).
        Returns the approval_id.
        """
        from klara.rarv.approval import ApprovalRequest, ApprovalStatus, RiskLevel

        # Map RiskTier → RiskLevel
        _tier_to_level = {
            RiskTier.low:       RiskLevel.p2,
            RiskTier.medium:    RiskLevel.p3,
            RiskTier.high:      RiskLevel.p4,
            RiskTier.forbidden: RiskLevel.p5,
        }
        risk_level = _tier_to_level.get(envelope.risk_tier, RiskLevel.p3)

        action_name = f"{action_type}:{envelope.action}:{envelope.object_type}"
        if envelope.object_id:
            action_name += f":{envelope.object_id}"

        approval = ApprovalRequest(
            action_name=action_name,
            risk_level=risk_level.value,
            payload=json.dumps({
                "task_id": envelope.task_id,
                "actor": envelope.actor,
                "action": envelope.action,
                "object_type": envelope.object_type,
                "object_id": envelope.object_id,
                "payload": envelope.payload,
                "context": envelope.context,
            }),
            justification=justification or envelope.context,
            requested_by_agent=self.name,
            lead_id=envelope.payload.get("lead_id"),
            conversation_id=envelope.payload.get("conversation_id"),
            status=ApprovalStatus.pending.value,
        )
        context.db.add(approval)
        await context.db.flush()   # get the ID without committing
        logger.info(
            "loki.approval_created",
            approval_id=approval.id,
            action_name=action_name,
            risk_level=risk_level.value,
        )
        return approval.id

    async def _audit(self, context: AgentContext, event: dict) -> None:
        """Best-effort audit log — never raises."""
        try:
            from app.agents.registry import registry
            audit = registry.get("audit_logger")
            await audit(context, event)
        except Exception as exc:
            logger.warning("loki.audit_failed", error=str(exc))
