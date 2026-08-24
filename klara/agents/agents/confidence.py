"""
app/agents/confidence.py
─────────────────────────
Confidence thresholds and fallback policies per workflow type.

Agents return a confidence score (0.0–1.0) with every output.
The orchestrator uses these thresholds to decide whether to:
  - EXECUTE: proceed with the action
  - DRAFT_ONLY: create a draft but don't send/publish
  - ESCALATE: stop and create an Approval record for human review
  - STOP: do nothing, log the uncertainty

Threshold precedence: workflow-specific > global default.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FallbackAction(str, Enum):
    execute    = "execute"     # Confidence high enough to proceed
    draft_only = "draft_only"  # Create draft, require approval to send
    escalate   = "escalate"    # Create escalation Approval record
    stop       = "stop"        # Do nothing, log uncertainty


@dataclass
class ConfidencePolicy:
    workflow: str
    execute_threshold: float    # >= this → execute
    draft_threshold: float      # >= this (but < execute) → draft_only
    escalate_threshold: float   # >= this (but < draft) → escalate
    # below escalate_threshold → stop


CONFIDENCE_POLICIES: dict[str, ConfidencePolicy] = {
    "lead_qualification": ConfidencePolicy(
        workflow="lead_qualification",
        execute_threshold=0.85,
        draft_threshold=0.60,
        escalate_threshold=0.40,
    ),
    "proposal_drafting": ConfidencePolicy(
        workflow="proposal_drafting",
        execute_threshold=0.90,
        draft_threshold=0.70,
        escalate_threshold=0.50,
    ),
    "content_audit": ConfidencePolicy(
        workflow="content_audit",
        execute_threshold=0.95,   # very high bar for content changes
        draft_threshold=0.75,
        escalate_threshold=0.50,
    ),
    "lead_prospecting": ConfidencePolicy(
        workflow="lead_prospecting",
        execute_threshold=0.80,
        draft_threshold=0.60,
        escalate_threshold=0.40,
    ),
    "outreach_email": ConfidencePolicy(
        workflow="outreach_email",
        execute_threshold=0.85,
        draft_threshold=0.65,
        escalate_threshold=0.45,
    ),
    # Default policy for unlisted workflows
    "default": ConfidencePolicy(
        workflow="default",
        execute_threshold=0.80,
        draft_threshold=0.60,
        escalate_threshold=0.40,
    ),
}


def get_fallback_action(workflow: str, confidence: float) -> FallbackAction:
    """Determine what to do given a workflow and confidence score."""
    policy = CONFIDENCE_POLICIES.get(workflow, CONFIDENCE_POLICIES["default"])
    if confidence >= policy.execute_threshold:
        return FallbackAction.execute
    elif confidence >= policy.draft_threshold:
        return FallbackAction.draft_only
    elif confidence >= policy.escalate_threshold:
        return FallbackAction.escalate
    else:
        return FallbackAction.stop
