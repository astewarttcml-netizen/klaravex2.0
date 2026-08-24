"""
app/agents/manifests.py
────────────────────────
Machine-readable manifest registry for all specialist agents.

Each manifest defines:
  - name: the agent's registry key
  - purpose: one-sentence description
  - scope: what objects/domains the agent may touch
  - allowed_actions: actions the agent may execute without approval
  - approval_required_actions: actions requiring human approval first
  - blocked_actions: actions this agent must never take
  - default_risk_tier: default risk for tasks initiated by this agent

Used by:
  - LokiOrchestrator._classify_risk() — override table lookup with agent-specific rules
  - AuditLog — stamp every log entry with agent name
  - Admin dashboard — show agent permission summary
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentManifest:
    name: str
    purpose: str
    scope: list[str]                    # ["leads", "clients", "proposals", ...]
    allowed_actions: list[str]          # can do without approval
    approval_required_actions: list[str]  # must create Approval record first
    blocked_actions: list[str]          # absolutely forbidden
    default_risk_tier: str              # RiskTier value ("low" | "medium" | "high" | "forbidden")


# ─────────────────────────────────────────────────────────────────────────────
# Manifest definitions
# ─────────────────────────────────────────────────────────────────────────────

AGENT_MANIFESTS: dict[str, AgentManifest] = {

    # ── Intake ────────────────────────────────────────────────────────────────

    "form_intake": AgentManifest(
        name="form_intake",
        purpose="Parse and normalise inbound contact-form submissions into Lead records.",
        scope=["leads", "conversations", "gdpr_consent"],
        allowed_actions=[
            "create_lead",
            "update_lead",
            "read_lead",
        ],
        approval_required_actions=[
            "send_proposal",
        ],
        blocked_actions=[
            "send_email",
            "delete_lead",
            "update_invoice",
            "publish_content",
            "process_payment",
        ],
        default_risk_tier="low",
    ),

    "chat_intake": AgentManifest(
        name="chat_intake",
        purpose="Classify incoming chat messages via Claude, persist conversation history, and extract qualification signals.",
        scope=["leads", "conversations", "messages"],
        allowed_actions=[
            "create_lead",
            "update_lead",
            "create_message",
            "read_conversation",
        ],
        approval_required_actions=[
            "send_proposal",
        ],
        blocked_actions=[
            "delete_lead",
            "update_invoice",
            "publish_content",
            "process_payment",
        ],
        default_risk_tier="low",
    ),

    # ── Qualification pipeline ────────────────────────────────────────────────

    "lead_qualification": AgentManifest(
        name="lead_qualification",
        purpose="Classify and score inbound leads against ICP using Claude; update lead status in the database.",
        scope=["leads", "approvals"],
        allowed_actions=[
            "update_lead",
            "create_approval",
            "read_lead",
        ],
        approval_required_actions=[
            "send_proposal",
        ],
        blocked_actions=[
            "update_invoice",
            "delete_lead",
            "process_payment",
            "publish_content",
        ],
        default_risk_tier="low",
    ),

    "lead_scoring": AgentManifest(
        name="lead_scoring",
        purpose="Compute a 0–100 numeric lead quality score from qualification data and persist it to the Lead record.",
        scope=["leads"],
        allowed_actions=[
            "update_lead",
            "read_lead",
        ],
        approval_required_actions=[],
        blocked_actions=[
            "send_email",
            "delete_lead",
            "update_invoice",
            "publish_content",
            "process_payment",
        ],
        default_risk_tier="low",
    ),

    "routing": AgentManifest(
        name="routing",
        purpose="Route qualified leads to the correct next action (proposal, notify, or no-op) based on score tier.",
        scope=["leads", "tasks", "approvals"],
        allowed_actions=[
            "update_task_state",
            "read_lead",
            "create_approval",
        ],
        approval_required_actions=[],
        blocked_actions=[
            "send_email",
            "delete_lead",
            "update_invoice",
            "publish_content",
            "process_payment",
        ],
        default_risk_tier="low",
    ),

    # ── Output / outbound ─────────────────────────────────────────────────────

    "proposal_drafting": AgentManifest(
        name="proposal_drafting",
        purpose="Generate a structured Markdown IT consulting proposal for a qualified lead via Claude.",
        scope=["leads", "proposals"],
        allowed_actions=[
            "create_proposal_draft",
            "read_lead",
        ],
        approval_required_actions=[
            "send_proposal",
        ],
        blocked_actions=[
            "publish_content",
            "delete_lead",
            "update_invoice",
            "process_payment",
        ],
        default_risk_tier="medium",
    ),

    "outreach_email": AgentManifest(
        name="outreach_email",
        purpose="Draft and queue personalised cold-outreach or follow-up emails for HOT/WARM leads and prospected contacts.",
        scope=["leads", "prospected_leads", "approvals"],
        allowed_actions=[
            "create_prospected_lead",
            "update_prospected_lead",
            "create_approval",
            "read_lead",
        ],
        approval_required_actions=[
            "send_outreach_email",
        ],
        blocked_actions=[
            "send_to_existing_client",
            "delete_lead",
            "update_invoice",
            "publish_content",
            "process_payment",
        ],
        default_risk_tier="medium",
    ),

    # ── Reporting ─────────────────────────────────────────────────────────────

    "daily_report": AgentManifest(
        name="daily_report",
        purpose="Generate the daily operational report covering lead funnel, approvals, proposals, and outreach metrics.",
        scope=["leads", "approvals", "proposals", "reports"],
        allowed_actions=[
            "create_report",
            "read_lead",
            "read_approval",
            "read_proposal",
        ],
        approval_required_actions=[],
        blocked_actions=[
            "update_invoice",
            "delete_lead",
            "process_payment",
            "publish_content",
            "send_email",
        ],
        default_risk_tier="low",
    ),

    # ── Prospecting ───────────────────────────────────────────────────────────

    "lead_prospector": AgentManifest(
        name="lead_prospector",
        purpose="Find new ICP-matched leads via the Apollo API, deduplicate against existing records, and persist ProspectedLead rows.",
        scope=["prospected_leads"],
        allowed_actions=[
            "create_prospected_lead",
            "read_prospected_lead",
        ],
        approval_required_actions=[],
        blocked_actions=[
            "update_existing_lead",
            "delete_lead",
            "update_invoice",
            "send_email",
            "publish_content",
            "process_payment",
        ],
        default_risk_tier="low",
    ),

    # ── Infrastructure ────────────────────────────────────────────────────────

    "context_manager": AgentManifest(
        name="context_manager",
        purpose="Resolve or create a Conversation record and load message history into shared context before pipeline execution.",
        scope=["conversations", "messages"],
        allowed_actions=[
            "create_conversation",
            "update_conversation",
            "read_conversation",
            "read_message",
        ],
        approval_required_actions=[],
        blocked_actions=[
            "delete_lead",
            "send_email",
            "update_invoice",
            "publish_content",
            "process_payment",
        ],
        default_risk_tier="low",
    ),

    "policy_guard": AgentManifest(
        name="policy_guard",
        purpose="Evaluate proposed actions against the permission policy table and block or escalate violations.",
        scope=["policy", "approvals", "audit"],
        allowed_actions=[
            "read_policy",
            "create_approval",
            "create_audit_entry",
        ],
        approval_required_actions=[],
        blocked_actions=[
            "bypass_approval",
            "delete_lead",
            "update_invoice",
            "process_payment",
        ],
        default_risk_tier="low",
    ),

    "approval_manager": AgentManifest(
        name="approval_manager",
        purpose="Create, read, and update ApprovalRequest records; enforce the approval lifecycle for P3/P4/P5 actions.",
        scope=["approvals"],
        allowed_actions=[
            "create_approval",
            "update_approval",
            "read_approval",
        ],
        approval_required_actions=[],
        blocked_actions=[
            "bypass_approval",
            "delete_lead",
            "send_email",
            "update_invoice",
            "process_payment",
            "publish_content",
        ],
        default_risk_tier="low",
    ),

    "audit_logger": AgentManifest(
        name="audit_logger",
        purpose="Persist immutable audit log entries for every agent action and approval lifecycle event.",
        scope=["audit"],
        allowed_actions=[
            "create_audit_entry",
            "read_audit_entry",
        ],
        approval_required_actions=[],
        blocked_actions=[
            "delete_audit_entry",
            "update_audit_entry",
            "send_email",
            "update_invoice",
            "process_payment",
            "publish_content",
        ],
        default_risk_tier="low",
    ),

    # ── Orchestrator ──────────────────────────────────────────────────────────

    "loki_orchestrator": AgentManifest(
        name="loki_orchestrator",
        purpose="Orchestrate tasks across all agents: route pipelines, enforce risk-tier approval gates, and assemble final responses.",
        scope=["leads", "proposals", "approvals", "tasks", "pipelines", "audit"],
        allowed_actions=[
            "route_task",
            "create_approval",
            "read_lead",
            "read_approval",
        ],
        approval_required_actions=[],
        blocked_actions=[
            "bypass_approval",
            "delete_lead",
            "update_invoice",
            "process_payment",
            "publish_content",
        ],
        default_risk_tier="low",
    ),
}
