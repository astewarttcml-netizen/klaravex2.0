"""
app/agents/routing.py
──────────────────────
Decides what happens next after a lead is qualified and scored.

Routing logic:
  Score >= 60  (HOT)   → lead_alert (P2, immediate email to Anthony)
                          calendar_integration (P2, booking invite to lead)
                          outreach_email (P3 approval, personalised email draft)
                          approval_manager (P4 gate for proposal_drafting)
  Score 35–59  (WARM)  → lead_alert + calendar_integration + outreach_email
                          (no proposal gate)
  Score <  35  (COLD)  → log and no further action

outreach_email is called here (not in the pipeline list) so that:
  a) It fires correctly for HOT leads even when the pipeline halts at the P4
     approval gate.
  b) It is skipped for NEEDS_MORE_INFO flows where no Lead row exists yet
     (lead_id guard).

Content-aware side-channel routing (runs ALONGSIDE the tier pipeline):
  FAQ signals       → faq_responder  (P2, non-fatal)
  Objection signals → objection_handler (P2, non-fatal)

Both side-channel agents run before tier-based branching so their output is
always present in the final result regardless of lead score.  Neither can
block the hot path — both are wrapped in isolated try/except blocks.

Signal detection is keyword-based to avoid an extra LLM call on every message.
False positives are acceptable: faq_responder and objection_handler both
short-circuit cleanly when the message does not actually match their domain.
"""
from __future__ import annotations

import structlog

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel

logger = structlog.get_logger(__name__)

# Module-level handle to the agent registry singleton. Populated lazily on
# first run() to avoid the circular import at module-load time (registry
# imports RoutingAgent during its own _bootstrap()). Exposed at module level
# so tests can `patch("app.agents.routing.registry")`.
registry = None  # type: ignore[assignment]

# ── FAQ signal keywords ───────────────────────────────────────────────────────
# Matches questions about services, technology, process, and pricing.
_FAQ_KEYWORDS: tuple[str, ...] = (
    # Technology surface area
    "microsoft 365", "m365", "office 365", "teams", "sharepoint", "onedrive",
    "azure", "entra", "entra id", "azure ad",
    "intune", "mdm", "device management", "autopilot",
    "meraki", "vpn", "network", "sd-wan",
    # Service / process questions
    "what do you do", "what do you offer", "what services",
    "how does it work", "how do you work", "how long does it take",
    "what is included", "what's included",
    # Pricing
    "how much", "wie viel", "pricing", "price", "preis", "kosten", "cost",
    "quote", "angebot", "rate", "retainer", "monthly",
    # General FAQ triggers
    "do you", "can you", "is it possible", "können sie", "machen sie",
)

# ── Objection signal keywords ─────────────────────────────────────────────────
# Matches price resistance, competitor mentions, trust gaps, and timeline pushback.
_OBJECTION_KEYWORDS: tuple[str, ...] = (
    # Price objections
    "too expensive", "zu teuer", "cheaper", "günstiger", "over budget",
    "can't afford", "nicht leisten", "better price", "lower price",
    # Competitor mentions
    "we already have", "wir haben bereits", "we use", "wir nutzen",
    "we have someone", "someone else", "another provider", "anderer anbieter",
    "competitor", "mitbewerber", "alternative", "instead of you",
    "vs ", "versus", "compared to",
    # Trust / qualification
    "how do i know", "wie weiß ich", "references", "referenzen",
    "who are you", "wer sind sie", "experience", "erfahrung",
    "qualified", "certified", "prove", "proven",
    # Timeline / urgency friction
    "too slow", "zu langsam", "takes too long", "dauert zu lange",
    "need it faster", "more urgent", "not fast enough",
)


def _has_faq_signal(message: str) -> bool:
    """Return True if the lowercased message contains any FAQ keyword."""
    msg = message.lower()
    return any(kw in msg for kw in _FAQ_KEYWORDS)


def _has_objection_signal(message: str) -> bool:
    """Return True if the lowercased message contains any objection keyword."""
    msg = message.lower()
    return any(kw in msg for kw in _OBJECTION_KEYWORDS)


class RoutingAgent(BaseAgent):
    name = "routing"
    description = (
        "Routes qualified leads to the correct next action based on score tier. "
        "HOT and WARM leads receive an immediate internal email alert (lead_alert). "
        "HOT leads additionally trigger proposal drafting (P4 approval gate). "
        "Also dispatches faq_responder and objection_handler when the incoming "
        "message contains matching content signals — both run alongside the normal "
        "tier pipeline and their outputs are included in the result."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        score = input_data.get("score", 0)
        tier = input_data.get("tier", "COLD")
        lead_id = context.lead_id or input_data.get("lead_id")
        qualification = input_data.get("qualification", {})

        # The pipeline merges all prior step outputs into input_data, so
        # 'message' and 'company' are available directly from the accumulated payload.
        message: str = input_data.get("message", "")
        company: str = input_data.get("company") or qualification.get("company", "unknown")

        # language is not a first-class field in the pipeline payload; default to
        # English — objection_handler will match the prospect's language internally.
        language: str = input_data.get("language", "en")

        log.info(
            "routing.decision",
            tier=tier,
            score=score,
            lead_id=lead_id,
            has_message=bool(message),
        )

        global registry
        if registry is None:
            from app.agents.registry import registry as _registry_singleton
            registry = _registry_singleton

        # ── Side-channel: content-aware dispatch ─────────────────────────────
        # These run unconditionally before tier branching.  Both are P2 and
        # non-fatal.  Their outputs are collected and merged into the final
        # AgentResult so downstream callers (e.g. the chat API) can surface
        # the drafted response without a second round-trip.

        faq_output: dict | None = None
        objection_output: dict | None = None

        if message and _has_faq_signal(message):
            log.info("routing.faq_signal_detected")
            try:
                faq_agent = registry.get("faq_responder")
                faq_result = await faq_agent(
                    context,
                    {
                        "message": message,
                        "lead_id": lead_id,
                    },
                )
                if faq_result.success:
                    faq_output = faq_result.output
                    log.info(
                        "routing.faq_responder_ok",
                        tokens=faq_output.get("tokens_used"),
                    )
                else:
                    log.warning("routing.faq_responder_failed", error=faq_result.error)
            except Exception as exc:
                log.error("routing.faq_responder_error", error=str(exc))

        if message and _has_objection_signal(message):
            log.info("routing.objection_signal_detected")
            try:
                obj_agent = registry.get("objection_handler")
                obj_result = await obj_agent(
                    context,
                    {
                        "message": message,
                        "company": company,
                        "services_interest": ", ".join(
                            qualification.get("services_fit", [])
                        ) or "IT consulting",
                        "language": language,
                        "lead_id": lead_id,
                    },
                )
                if obj_result.success:
                    objection_output = obj_result.output
                    log.info(
                        "routing.objection_handler_ok",
                        objection_type=objection_output.get("objection_type"),
                        detected=objection_output.get("objection_detected"),
                    )
                else:
                    log.warning("routing.objection_handler_failed", error=obj_result.error)
            except Exception as exc:
                log.error("routing.objection_handler_error", error=str(exc))

        # ── Tier-based hot path ───────────────────────────────────────────────
        # Unchanged behaviour.  Side-channel results are merged into the output
        # dict at each return site via _merge_content_outputs().

        if tier in ("HOT", "WARM"):
            alert_payload = {
                "lead_id": lead_id,
                "tier": tier,
                "score": score,
                "qualification": qualification,
            }

            # ── Step 1: Immediate internal alert (P2, non-fatal) ─────────────
            try:
                alert = registry.get("lead_alert")
                await alert(context, alert_payload)
            except Exception as exc:
                log.error("routing.lead_alert_error", lead_id=lead_id, tier=tier, error=str(exc))

            # ── Step 2: Booking invite to the lead (P2, non-fatal) ───────────
            try:
                cal = registry.get("calendar_integration")
                await cal(context, alert_payload)
            except Exception as exc:
                log.error("routing.calendar_error", lead_id=lead_id, tier=tier, error=str(exc))

            # ── Step 3: Personalised outreach email (P3 approval, non-fatal) ─
            # Only fires when a Lead row exists (lead_id is set).
            # Skipped automatically for NEEDS_MORE_INFO flows where qualification
            # produced a WARM/HOT score but no lead was persisted yet.
            if lead_id:
                try:
                    outreach = registry.get("outreach_email")
                    await outreach(
                        context,
                        {
                            "lead_id": lead_id,
                            "tier": tier,
                            "score": score,
                            "qualification": qualification,
                        },
                    )
                except Exception as exc:
                    log.error(
                        "routing.outreach_email_error",
                        lead_id=lead_id,
                        tier=tier,
                        error=str(exc),
                    )

        if tier == "HOT":
            # ── Step 3 (HOT only): P4 approval gate for proposal drafting ────
            if context.settings.is_production:
                approval_mgr = registry.get("approval_manager")
                approval_result = await approval_mgr(
                    context,
                    {
                        "action": "create",
                        "action_name": "proposal_drafting.draft",
                        "risk_level": "P4",
                        "payload": {
                            "lead_id": lead_id,
                            "score": score,
                            "services": qualification.get("services_fit", []),
                        },
                        "justification": (
                            f"HOT lead (score={score}) ready for proposal. "
                            f"Services: {qualification.get('services_fit', [])}"
                        ),
                        "requested_by": self.name,
                    },
                )
                if approval_result.success:
                    approval_id = approval_result.output["approval_id"]
                    log.info("routing.approval_created", approval_id=approval_id)
                    return AgentResult.needs_approval(
                        approval_id=approval_id,
                        action="proposal_drafting.draft",
                    )

            # Dev/staging: proceed immediately without approval gate
            return AgentResult.ok(
                output=_merge_content_outputs(
                    {
                        "next_action": "proposal_drafting",
                        "tier": tier,
                        "lead_id": lead_id,
                    },
                    faq_output=faq_output,
                    objection_output=objection_output,
                )
            )

        elif tier == "WARM":
            # Alert already fired above — no additional approval gate needed.
            # lead_alert IS the consultant notification for WARM leads.
            return AgentResult.ok(
                output=_merge_content_outputs(
                    {
                        "next_action": "lead_alert",
                        "tier": tier,
                        "lead_id": lead_id,
                    },
                    faq_output=faq_output,
                    objection_output=objection_output,
                )
            )

        else:
            # COLD — no further action
            return AgentResult.ok(
                output=_merge_content_outputs(
                    {
                        "next_action": "none",
                        "tier": "COLD",
                        "lead_id": lead_id,
                    },
                    faq_output=faq_output,
                    objection_output=objection_output,
                )
            )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _merge_content_outputs(
    base: dict,
    *,
    faq_output: dict | None,
    objection_output: dict | None,
) -> dict:
    """
    Merge faq_responder and objection_handler outputs into the routing result dict.

    Keys added when present:
      faq_answer        — the drafted FAQ response text
      faq_question      — the original question echoed back
      objection_detected — bool
      objection_type     — PRICE | COMPETITOR | TRUST | TIMELINE | NONE
      objection_response — the drafted objection-handling text
    """
    result = dict(base)
    if faq_output:
        result["faq_answer"] = faq_output.get("answer")
        result["faq_question"] = faq_output.get("question")
    if objection_output:
        result["objection_detected"] = objection_output.get("objection_detected", False)
        result["objection_type"] = objection_output.get("objection_type")
        result["objection_response"] = objection_output.get("draft_response")
    return result
