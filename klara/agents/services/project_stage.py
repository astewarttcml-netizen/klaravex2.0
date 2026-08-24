"""
app/services/project_stage.py
─────────────────────────────
Service helper for project stage transitions (portal-211).

Every stage change on a portal Project must:
  1. Be a valid ProjectStatus value (validated against VALID_STAGES).
  2. Be a permitted transition from the current stage (ALLOWED_TRANSITIONS).
  3. Produce an immutable ProjectStatusEvent row recording the change.
  4. Update Project.status atomically alongside the event row.

This module is the single entry point for stage changes — admin endpoints,
agent code, and Celery tasks should call `record_stage_change()` rather
than mutating Project.status directly. That guarantees the timeline shown
in the client portal (see GET /api/v1/portal/projects/{id}.timeline) is
always the truth.

Failure modes:
  - InvalidStageError: new_stage is not a recognised ProjectStatus.
  - DisallowedTransitionError: new_stage is not reachable from project.status
    per the forward-progress whitelist. Caller must explicitly request an
    override (force=True) to bypass — used for admin corrections.
"""
from __future__ import annotations

from typing import Optional
from uuid import uuid4

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portal import Project
from app.models.project_event import (
    ALLOWED_TRANSITIONS,
    ActorType,
    ProjectStatusEvent,
    VALID_STAGES,
)

logger = structlog.get_logger(__name__)


class InvalidStageError(ValueError):
    """new_stage is not a recognised ProjectStatus value."""


class DisallowedTransitionError(ValueError):
    """The transition from project.status to new_stage is not in the whitelist."""


def _validate_transition(current: str, new_stage: str) -> None:
    """
    Raise if new_stage is unknown or not reachable from current.

    Re-stating the same stage (current == new_stage) is rejected — every
    event must represent a real change.
    """
    if new_stage not in VALID_STAGES:
        raise InvalidStageError(
            f"Invalid project stage '{new_stage}'. "
            f"Allowed: {sorted(VALID_STAGES)}"
        )
    if current == new_stage:
        raise DisallowedTransitionError(
            f"No-op transition rejected: project is already in '{new_stage}'."
        )
    allowed = ALLOWED_TRANSITIONS.get(current, [])
    if new_stage not in allowed:
        raise DisallowedTransitionError(
            f"Transition '{current}' → '{new_stage}' is not allowed. "
            f"Permitted next stages: {allowed or '(none — terminal)'}."
        )


async def record_stage_change(
    db: AsyncSession,
    project: Project,
    new_stage: str,
    *,
    actor_type: str = ActorType.system.value,
    actor_id: Optional[str] = None,
    note: Optional[str] = None,
    client_visible: bool = True,
    force: bool = False,
) -> ProjectStatusEvent:
    """
    Record a stage transition: insert the audit event AND update Project.status
    in the same transaction. Caller is responsible for db.commit() so this can
    participate in a larger transaction (e.g. when an agent transitions stage
    as part of a multi-step pipeline).

    Set `force=True` to skip the ALLOWED_TRANSITIONS whitelist (admin override).
    The stage value itself is still validated. Force overrides are logged at
    WARNING level so they show up in audit.

    Returns the inserted ProjectStatusEvent (already added to the session).
    """
    old_stage = project.status

    if force:
        if new_stage not in VALID_STAGES:
            raise InvalidStageError(
                f"Invalid project stage '{new_stage}' (force=True does not "
                f"bypass stage validation). Allowed: {sorted(VALID_STAGES)}"
            )
        if old_stage == new_stage:
            raise DisallowedTransitionError(
                f"No-op transition rejected: project is already in '{new_stage}'."
            )
        logger.warning(
            "project_stage.force_transition",
            project_id=project.id,
            client_id=project.client_id,
            old_stage=old_stage,
            new_stage=new_stage,
            actor_type=actor_type,
            actor_id=actor_id,
        )
    else:
        _validate_transition(old_stage, new_stage)

    event = ProjectStatusEvent(
        id=str(uuid4()),
        project_id=project.id,
        client_id=project.client_id,
        old_stage=old_stage,
        new_stage=new_stage,
        actor_type=actor_type,
        actor_id=actor_id,
        note=note,
        client_visible=client_visible,
    )
    db.add(event)

    # Update the Project's denormalised current status. The event row is the
    # source of truth for the timeline; Project.status is a fast-read cache.
    project.status = new_stage

    logger.info(
        "project_stage.recorded",
        project_id=project.id,
        client_id=project.client_id,
        old_stage=old_stage,
        new_stage=new_stage,
        actor_type=actor_type,
        client_visible=client_visible,
    )
    return event
