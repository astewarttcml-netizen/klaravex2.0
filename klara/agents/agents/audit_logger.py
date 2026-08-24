"""
app/agents/audit_logger.py
──────────────────────────
Writes immutable audit log entries.

Called by Klara AI and other agents after every significant action.
The audit log is INSERT-only — rows are never updated.
GDPR: the 'details' field must be sanitised — no raw PII.
"""
from __future__ import annotations

import json

import structlog

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.audit import AuditLog

logger = structlog.get_logger(__name__)


class AuditLoggerAgent(BaseAgent):
    name = "audit_logger"
    description = "Writes immutable audit log entries. Called after every significant action."
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        input_data keys:
          event_type   (str, required)  — e.g. "lead.qualified"
          agent_name   (str)
          action_name  (str)
          details      (dict)           — sanitised, no raw PII
          success      (bool)
          error_message (str)
          ip_address   (str)
          user_agent   (str)
        """
        event_type = input_data.get("event_type")
        if not event_type:
            return AgentResult.fail("audit_logger requires 'event_type'.")

        details = input_data.get("details", {})
        if isinstance(details, dict):
            details_str = json.dumps(details)
        else:
            details_str = str(details)

        entry = AuditLog(
            event_type=event_type,
            agent_name=input_data.get("agent_name"),
            action_name=input_data.get("action_name"),
            lead_id=str(context.lead_id) if context.lead_id else input_data.get("lead_id"),
            conversation_id=str(context.conversation_id) if context.conversation_id else input_data.get("conversation_id"),
            approval_id=input_data.get("approval_id"),
            details=details_str,
            ip_address=input_data.get("ip_address"),
            user_agent=input_data.get("user_agent"),
            success=input_data.get("success", True),
            error_message=input_data.get("error_message"),
        )
        context.db.add(entry)
        await context.db.flush()

        logger.debug(
            "audit_logger.wrote",
            audit_event_type=event_type,
            audit_id=entry.id,
            lead=context.lead_id,
        )
        return AgentResult.ok(output={"audit_id": entry.id})
