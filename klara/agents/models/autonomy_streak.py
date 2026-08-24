"""
app/models/autonomy_streak.py
──────────────────────────────
phase19-010 — Per-agent autonomy-color streak tracker.

The phase3-003 `autonomy_metrics` endpoint computes a `status_color`
(green / amber / red / no_data) for each agent over a trailing window.
This table records how long the current color has been continuously
observed by the daily promotion runner. When green has held for
GREEN_STREAK_DAYS_REQUIRED (=14) consecutive days, the runner emits a
P4 ApprovalRequest proposing P3 -> P2 promotion of that agent.

Distinct from `AutonomyPromotion` (`app/models/autonomy_promotion.py`)
which is the APPEND-ONLY audit ledger of past promotions. This table is
the LIVE streak state, one row per agent, mutable by the runner.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from klara.rarv.runtime import Base


class AutonomyStreak(Base):
    __tablename__ = "autonomy_streaks"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    agent_name: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True
    )
    current_color: Mapped[str] = mapped_column(String(20), nullable=False)
    streak_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # When a P4 promotion ApprovalRequest is in-flight, the runner does not
    # re-request. Cleared when the approval is approved (-> ledger row written
    # in AutonomyPromotion) or rejected.
    pending_promotion_approval_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False)
    )

    def __repr__(self) -> str:
        return (
            f"<AutonomyStreak agent={self.agent_name} color={self.current_color} "
            f"since={self.streak_started_at.isoformat()}>"
        )
