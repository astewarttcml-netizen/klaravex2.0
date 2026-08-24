"""
app/api/agent_promotion.py
──────────────────────────
phase21-001 -- in-session permission_level executor for autonomy promotion.

Klara AI-mode's PRD claimed an "approval-granted handler flips agent
permission_level" -- but no such code existed. Promotion was track-only:
autonomy_promotion_sweep recommends candidates, autonomy_promotions logs
intent, then a developer was expected to edit the source `permission_level`
constant and redeploy.

This endpoint closes that gap honestly:

POST /api/v1/admin/agents/{agent_name}/promote
body: {"to_level": "P2", "reason": "...", "approved_by": "anthony"}

Effect:
  - Mutates registry.get(agent_name).permission_level in-memory (this
    container only).
  - INSERTs a row into autonomy_promotions for audit.
  - Returns a warning: the change is SESSION-SCOPED. To make the
    promotion survive a deploy, edit the agent's `permission_level`
    constant in its source file and ship.

This is intentionally a thin runtime tool, not a full hot-swap. The
caller (Anthony or a future approval-granted webhook) takes responsibility
for the long-term durability via a normal code change.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import registry
from app.core.permissions import PermissionLevel
from app.core.security import verify_api_key
from app.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter()


_LEVELS = {"P1", "P2", "P3", "P4", "P5"}


class PromoteRequest(BaseModel):
    to_level: Literal["P1", "P2", "P3", "P4", "P5"] = Field(
        ..., description="Target permission level."
    )
    reason: str = Field(
        ..., min_length=4, max_length=400,
        description="Human-readable justification. Stored verbatim."
    )
    approved_by: str = Field(
        ..., min_length=1, max_length=80,
        description="Who approved. Free text — typically 'anthony' or an automation tag.",
    )


class PromoteResponse(BaseModel):
    agent_name: str
    from_level: str
    to_level: str
    promoted_at: datetime
    session_scoped: bool
    warning: str
    audit_id: str


@router.post(
    "/{agent_name}/promote",
    response_model=PromoteResponse,
    dependencies=[Depends(verify_api_key)],
)
async def promote_agent(
    agent_name: str,
    payload: PromoteRequest,
    db: AsyncSession = Depends(get_db),
) -> PromoteResponse:
    """Flip an agent's permission_level at runtime + log to autonomy_promotions."""
    agent = registry.get(agent_name)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown agent '{agent_name}'.",
        )

    from_level = agent.permission_level.name
    if from_level == payload.to_level:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent '{agent_name}' is already at {from_level}.",
        )

    try:
        new_level = getattr(PermissionLevel, payload.to_level)
    except AttributeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown permission level '{payload.to_level}'.",
        )

    # ── Mutate in-memory registry. This container only ────────────────────
    agent.permission_level = new_level

    # ── Audit row in autonomy_promotions ──────────────────────────────────
    audit_id = str(uuid4())
    await db.execute(
        text(
            """
            INSERT INTO autonomy_promotions
            (id, agent_name, from_level, to_level, reason, justification,
             approval_rate, error_rate, rollback_rate, window_days,
             promoted_by, promoted_at)
            VALUES
            (:id, :agent, :from_lvl, :to_lvl, :reason, :just,
             NULL, NULL, NULL, NULL,
             :by, :at)
            """
        ),
        {
            "id": audit_id,
            "agent": agent_name,
            "from_lvl": from_level,
            "to_lvl": payload.to_level,
            "reason": payload.reason[:400],
            "just": f"In-session promotion via /api/v1/admin/agents/{agent_name}/promote",
            "by": payload.approved_by[:80],
            "at": datetime.now(timezone.utc),
        },
    )
    await db.commit()

    logger.warning(
        "agent_promotion.applied",
        agent=agent_name,
        from_level=from_level,
        to_level=payload.to_level,
        approved_by=payload.approved_by,
        audit_id=audit_id,
        session_scoped=True,
    )

    return PromoteResponse(
        agent_name=agent_name,
        from_level=from_level,
        to_level=payload.to_level,
        promoted_at=datetime.now(timezone.utc),
        session_scoped=True,
        warning=(
            "Session-scoped: this change lives only in the current worker/api "
            f"container and will revert on restart. To make permanent, edit "
            f"`permission_level` in the agent's source file and redeploy."
        ),
        audit_id=audit_id,
    )
