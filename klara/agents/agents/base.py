"""
app/agents/base.py
──────────────────
BaseAgent — all agents inherit from this.

Every agent:
  - Has a unique name (snake_case)
  - Declares its permission level
  - Receives a shared AgentContext (db session, settings, audit hook)
  - Returns an AgentResult
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.permissions import PermissionLevel

logger = structlog.get_logger(__name__)


@dataclass
class AgentContext:
    """Shared context passed to every agent invocation."""
    db: AsyncSession
    settings: Settings
    conversation_id: str | None = None
    lead_id: str | None = None
    request_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    """Standardised return from every agent run() call."""
    success: bool
    output: Any = None           # structured output (dict / str / model)
    error: str | None = None
    approval_required: bool = False
    approval_id: str | None = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def ok(cls, output: Any = None, **meta) -> "AgentResult":
        return cls(success=True, output=output, metadata=meta)

    @classmethod
    def fail(cls, error: str, **meta) -> "AgentResult":
        return cls(success=False, error=error, metadata=meta)

    @classmethod
    def needs_approval(cls, approval_id: str, action: str) -> "AgentResult":
        return cls(
            success=False,
            approval_required=True,
            approval_id=approval_id,
            metadata={"pending_action": action},
        )


class BaseAgent(abc.ABC):
    """
    Abstract base for all Klara AI agents.

    Subclasses must implement:
      - name: str            — snake_case identifier
      - description: str     — human-readable purpose
      - permission_level     — default PermissionLevel for this agent's actions
      - run(context, input)  — main entry point
    """

    name: str
    description: str
    permission_level: PermissionLevel = PermissionLevel.P1

    @abc.abstractmethod
    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """Execute the agent's primary action."""
        ...

    async def __call__(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(agent=self.name, conversation=context.conversation_id)
        log.debug("agent.start")
        try:
            result = await self.run(context, input_data)
            log.info(
                "agent.complete",
                success=result.success,
                approval_required=result.approval_required,
            )
            return result
        except Exception as exc:
            log.error("agent.error", error=str(exc), exc_info=True)
            return AgentResult.fail(error=str(exc))

    def meta(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "permission_level": self.permission_level.value,
            "approval_required": self.permission_level.value in ("P3", "P4", "P5"),
        }
