"""
app/core/permissions.py
───────────────────────
Permission levels P1–P5 for agent actions.

  P1  — READ-ONLY / informational
        Examples: fetch knowledge base, read lead data, classify intent
        Approval: never required

  P2  — INTERNAL WRITES (no external side-effects)
        Examples: create/update lead record, log conversation, score a lead
        Approval: never required

  P3  — OUTBOUND / PUBLISHING
        Examples: send email, post to CRM, publish WordPress content, chat reply
        Approval: REQUIRED (human must approve before action executes)

  P4  — LEGAL / BILLING / SENSITIVE
        Examples: generate binding proposal, access billing system,
                  edit service agreement, create invoice
        Approval: REQUIRED + must include justification

  P5  — CLIENT ENVIRONMENT CHANGES
        Examples: Intune policy push, Azure config change, Meraki VLAN update,
                  M365 tenant modification, firewall rule change
        Approval: REQUIRED + second approver (2-of-2)

Usage in agent code:
    from klara.rarv.runtime import require_approval, PermissionLevel

    @require_approval(PermissionLevel.P3, action_name="send_proposal_email")
    async def send_proposal_email(lead_id: str, ...):
        ...
"""
import enum
import functools
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import structlog

from klara.rarv.runtime import get_settings

logger = structlog.get_logger(__name__)


class PermissionLevel(str, enum.Enum):
    P1 = "P1"   # read-only
    P2 = "P2"   # internal write
    P3 = "P3"   # outbound / publish
    P4 = "P4"   # legal / billing
    P5 = "P5"   # client environment


# Map each permission level to whether approval is required
APPROVAL_REQUIRED: dict[PermissionLevel, bool] = {
    PermissionLevel.P1: False,
    PermissionLevel.P2: False,
    PermissionLevel.P3: True,
    PermissionLevel.P4: True,
    PermissionLevel.P5: True,
}

# P5 actions additionally require a second approver
SECOND_APPROVER_REQUIRED: dict[PermissionLevel, bool] = {
    PermissionLevel.P1: False,
    PermissionLevel.P2: False,
    PermissionLevel.P3: False,
    PermissionLevel.P4: False,
    PermissionLevel.P5: True,
}


class ApprovalRequired(Exception):
    """
    Raised by require_approval when an action needs human sign-off.
    The calling code should catch this, create an ApprovalRequest row,
    and return a 202 Accepted response to the caller.
    """

    def __init__(
        self,
        action_name: str,
        level: PermissionLevel,
        payload: dict,
        justification: str | None = None,
    ):
        self.action_name = action_name
        self.level = level
        self.payload = payload
        self.justification = justification
        super().__init__(
            f"Action '{action_name}' at level {level.value} requires human approval."
        )


def require_approval(
    level: PermissionLevel,
    action_name: str | None = None,
    justification: str | None = None,
) -> Callable:
    """
    Decorator that gates an async function behind the permission model.

    If the action's level requires approval AND we are not in dev/debug mode,
    raise ApprovalRequired instead of executing the function.

    The decorated function receives the same args/kwargs and should be an
    async function.  Callers must handle ApprovalRequired.

    Example:
        @require_approval(PermissionLevel.P3, action_name="send_email")
        async def send_email(lead_id: str, body: str, db: AsyncSession): ...
    """
    def decorator(func: Callable) -> Callable:
        resolved_name = action_name or func.__qualname__

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            settings = get_settings()
            needs_approval = APPROVAL_REQUIRED[level]

            if needs_approval and settings.is_production:
                # Build a sanitised payload for the approval record
                payload = {
                    "args_count": len(args),
                    "kwargs_keys": list(kwargs.keys()),
                }
                logger.warning(
                    "approval.gate_triggered",
                    action=resolved_name,
                    level=level.value,
                )
                raise ApprovalRequired(
                    action_name=resolved_name,
                    level=level,
                    payload=payload,
                    justification=justification,
                )

            # In dev/staging, or for P1/P2 actions, proceed directly
            logger.debug(
                "permission.allowed",
                action=resolved_name,
                level=level.value,
                production=settings.is_production,
            )
            return await func(*args, **kwargs)

        wrapper._permission_level = level  # type: ignore[attr-defined]
        wrapper._action_name = resolved_name  # type: ignore[attr-defined]
        return wrapper

    return decorator


def action_meta(level: PermissionLevel, description: str = "") -> dict:
    """Helper to attach permission metadata to agent action definitions."""
    return {
        "level": level.value,
        "approval_required": APPROVAL_REQUIRED[level],
        "second_approver": SECOND_APPROVER_REQUIRED[level],
        "description": description,
    }
