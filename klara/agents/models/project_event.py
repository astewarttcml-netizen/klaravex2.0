"""
app/models/project_event.py
───────────────────────────
ProjectStatusEvent — immutable audit record of every project stage change.

Rules (docs/policies.md §3.3):
- INSERT-only: rows are never updated or deleted.
- Every status change on Project must produce a ProjectStatusEvent row.
- new_stage must be a value from portal.ProjectStatus (validated at write time
  by the service layer; the DB stores the string value for forward-compat).
- actor_type distinguishes system-driven changes from admin-initiated ones.
- client_visible controls whether the event is surfaced in the portal timeline.
"""
import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from klara.rarv.runtime import Base


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class ActorType(str, enum.Enum):
    system = "system"   # automated pipeline action
    admin  = "admin"    # Anthony / staff making a manual change
    agent  = "agent"    # Klara AI agent-triggered transition


# ─────────────────────────────────────────────────────────────────────────────
# Allowed stage transitions
# ─────────────────────────────────────────────────────────────────────────────

# Explicit forward-progress whitelist.  Any transition not in this set must be
# approved before it can be recorded.  The service layer enforces this; the
# model just documents the contract.
ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    "new_request":       ["in_assessment"],
    "in_assessment":     ["draft_ready", "waiting_on_client"],
    "draft_ready":       ["awaiting_approval", "in_progress"],
    "awaiting_approval": ["in_progress", "draft_ready"],
    "in_progress":       ["waiting_on_client", "complete"],
    "waiting_on_client": ["in_progress", "complete"],
    "complete":          [],  # terminal — no automatic transition out
}

VALID_STAGES: frozenset[str] = frozenset(ALLOWED_TRANSITIONS.keys())


def validate_stage(stage: str) -> str:
    """Raise ValueError if stage is not a recognised ProjectStatus value."""
    if stage not in VALID_STAGES:
        raise ValueError(
            f"Invalid project stage '{stage}'. "
            f"Allowed: {sorted(VALID_STAGES)}"
        )
    return stage


# ─────────────────────────────────────────────────────────────────────────────
# ProjectStatusEvent
# ─────────────────────────────────────────────────────────────────────────────

class ProjectStatusEvent(Base):
    """
    Immutable stage-change record for a portal project.

    Columns:
    - project_id:      FK to portal_projects.id
    - client_id:       denormalized for fast ownership checks
    - old_stage:       stage before this transition (nullable on first event)
    - new_stage:       stage after this transition — must be in VALID_STAGES
    - actor_type:      system | admin | agent
    - actor_id:        free-text identifier for the actor (agent name, user id)
    - note:            optional human-readable reason / context
    - client_visible:  whether this event appears in the client's portal timeline
    - recorded_at:     server timestamp when the event was written
    """
    __tablename__ = "project_status_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── Links ─────────────────────────────────────────────────────────────────
    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True
    )
    client_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True
    )

    # ── Stage transition ──────────────────────────────────────────────────────
    old_stage: Mapped[str | None] = mapped_column(String(50))   # null on creation
    new_stage: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # ── Actor ─────────────────────────────────────────────────────────────────
    actor_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ActorType.system
    )
    actor_id: Mapped[str | None] = mapped_column(String(255))   # agent name / user id

    # ── Context ───────────────────────────────────────────────────────────────
    note: Mapped[str | None] = mapped_column(Text)
    client_visible: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, server_default="true"
    )

    # ── Timestamp ─────────────────────────────────────────────────────────────
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectStatusEvent id={self.id} project={self.project_id} "
            f"{self.old_stage} -> {self.new_stage} by={self.actor_type}>"
        )
