"""
app/agents/rollout_mode.py
───────────────────────────
Rollout mode enforcement.

Klara AI operates in three modes:

  shadow (9.2 — current default)
    All agent actions are OBSERVED but not executed.
    Every task is logged as "would_execute: <action>" with full payload.
    No DB writes outside of audit log. No emails sent. No Stripe calls.
    Used to compare proposed actions to human decisions.

  assisted (9.3)
    Agents may create drafts, summaries, and internal updates.
    Public-facing, client-visible, and payment actions remain approval-gated.
    Low-risk internal-only actions auto-execute.

  selective_autonomy (9.4)
    Low-risk actions auto-execute.
    Medium-risk creates drafts for approval.
    High-risk and forbidden remain gated.
    Legal, pricing, refunds, and billing always require approval.

  full_autonomy (9.5)
    Low-risk and medium-risk actions auto-execute.
    High-risk requires explicit approval.
    Forbidden actions are hard-stopped.
    Always-gated actions (billing, pricing, proposals) still require approval.

The mode is read from settings.loki_mode and enforced in the orchestrator
before any agent execution.
"""
from enum import Enum

from app.agents.confidence import FallbackAction


class LokiMode(str, Enum):
    shadow             = "shadow"
    assisted           = "assisted"
    selective_autonomy = "selective_autonomy"
    full_autonomy      = "full_autonomy"


# Actions that are ALWAYS gated regardless of mode
ALWAYS_APPROVAL_REQUIRED = {
    "send_proposal",
    "create_invoice",
    "process_payment",
    "publish_content",
    "send_outreach_email",
    "update_pricing",
    "issue_refund",
}


def enforce_mode(mode: str, action: str, risk_tier: str) -> FallbackAction:
    """
    Given the current mode, action, and risk tier, return what should happen.

    Returns FallbackAction — the orchestrator uses this to decide whether
    to execute, draft, escalate, or stop.
    """
    # Always-gated actions never execute automatically
    if action in ALWAYS_APPROVAL_REQUIRED:
        return FallbackAction.escalate

    if mode == LokiMode.shadow:
        # Shadow mode: NOTHING executes, everything is draft_only for observation
        return FallbackAction.draft_only

    if mode == LokiMode.assisted:
        # Assisted: low-risk internal actions execute; anything touching clients gated
        if risk_tier == "low":
            return FallbackAction.execute
        else:
            return FallbackAction.draft_only

    if mode == LokiMode.selective_autonomy:
        # Selective: low=execute, medium=draft, high=escalate, forbidden=stop
        tier_map = {
            "low":       FallbackAction.execute,
            "medium":    FallbackAction.draft_only,
            "high":      FallbackAction.escalate,
            "forbidden": FallbackAction.stop,
        }
        return tier_map.get(risk_tier, FallbackAction.escalate)

    if mode == LokiMode.full_autonomy:
        # Full autonomy: low + medium auto-execute; high escalates; forbidden stops
        tier_map = {
            "low":       FallbackAction.execute,
            "medium":    FallbackAction.execute,
            "high":      FallbackAction.escalate,
            "forbidden": FallbackAction.stop,
        }
        return tier_map.get(risk_tier, FallbackAction.escalate)

    # Unknown mode → conservative fallback
    return FallbackAction.escalate
