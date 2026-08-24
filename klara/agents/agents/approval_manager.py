"""
app/agents/approval_manager.py
────────────────────────────────
Creates, retrieves, and resolves ApprovalRequest rows.

This agent is the ONLY writer to the approval_requests table.
All other agents call it when they catch ApprovalRequired.

Permission levels:
  - Creating an approval request:  P2 (internal write, no approval needed)
  - Approving/rejecting a request: P4 (management action — only via authenticated endpoint)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.approval import ApprovalRequest, ApprovalStatus, RiskLevel

logger = structlog.get_logger(__name__)


class ApprovalManagerAgent(BaseAgent):
    name = "approval_manager"
    description = (
        "Creates and resolves approval requests for P3/P4/P5 actions. "
        "The single writer to the approval_requests table."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        Dispatch on input_data['action']:
          create   — create a new pending approval request
          approve  — mark an existing request approved
          reject   — mark an existing request rejected
          status   — return current status of a request
        """
        action = input_data.get("action", "create")

        if action == "create":
            return await self._create(context, input_data)
        elif action == "approve":
            return await self._resolve(context, input_data, ApprovalStatus.approved)
        elif action == "reject":
            return await self._resolve(context, input_data, ApprovalStatus.rejected)
        elif action == "status":
            return await self._status(context, input_data)
        else:
            return AgentResult.fail(f"Unknown approval action: '{action}'")

    async def _create(self, context: AgentContext, data: dict) -> AgentResult:
        settings = context.settings
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=settings.approval_timeout_seconds
        )

        req = ApprovalRequest(
            action_name=data.get("action_name", "unknown"),
            risk_level=data.get("risk_level", RiskLevel.p3),
            payload=json.dumps(data.get("payload", {})),
            justification=data.get("justification"),
            requested_by_agent=data.get("requested_by", "unknown"),
            lead_id=str(context.lead_id) if context.lead_id else None,
            conversation_id=str(context.conversation_id) if context.conversation_id else None,
            expires_at=expires_at,
        )
        context.db.add(req)
        await context.db.flush()

        logger.info(
            "approval_manager.created",
            approval_id=req.id,
            action=req.action_name,
            level=req.risk_level,
        )
        return AgentResult.ok(output={"approval_id": req.id, "expires_at": expires_at.isoformat()})

    async def _resolve(
        self, context: AgentContext, data: dict, new_status: ApprovalStatus
    ) -> AgentResult:
        approval_id = data.get("approval_id")
        if not approval_id:
            return AgentResult.fail("approval_id required for approve/reject.")

        result = await context.db.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
        )
        req = result.scalar_one_or_none()

        if not req:
            return AgentResult.fail(f"Approval request '{approval_id}' not found.")

        if req.status != ApprovalStatus.pending:
            return AgentResult.fail(
                f"Request is already '{req.status}' — cannot change to '{new_status}'."
            )

        req.status = new_status
        req.reviewed_by = data.get("reviewed_by", "system")
        req.review_note = data.get("note")
        req.reviewed_at = datetime.now(timezone.utc)

        logger.info(
            "approval_manager.resolved",
            approval_id=approval_id,
            status=new_status,
            reviewer=req.reviewed_by,
        )
        return AgentResult.ok(output={"approval_id": approval_id, "status": new_status})

    async def _status(self, context: AgentContext, data: dict) -> AgentResult:
        approval_id = data.get("approval_id")
        if not approval_id:
            return AgentResult.fail("approval_id required for status check.")

        result = await context.db.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
        )
        req = result.scalar_one_or_none()

        if not req:
            return AgentResult.fail(f"Approval request '{approval_id}' not found.")

        return AgentResult.ok(
            output={
                "approval_id": req.id,
                "status": req.status,
                "action_name": req.action_name,
                "risk_level": req.risk_level,
                "created_at": req.created_at.isoformat(),
                "expires_at": req.expires_at.isoformat() if req.expires_at else None,
                "reviewed_by": req.reviewed_by,
                "review_note": req.review_note,
            }
        )
