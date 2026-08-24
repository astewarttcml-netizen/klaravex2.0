"""
app/models/autonomy_promotion.py
─────────────────────────────────
Append-only ledger of permission-level promotions / demotions of registered
agents (phase3-004).

One row per promotion event. Rows are never deleted — this is an audit
trail. Read-only from application code; writes happen via Alembic
migrations or via the explicit `record_promotion()` admin tool.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AutonomyPromotion(Base):
    __tablename__ = "autonomy_promotions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    from_level: Mapped[str] = mapped_column(String(10), nullable=False)   # "P3"
    to_level:   Mapped[str] = mapped_column(String(10), nullable=False)   # "P2"
    reason:        Mapped[str] = mapped_column(Text, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)

    # Metric evidence at time of promotion (may be NULL for overrides taken
    # ahead of the 30-day metric window, e.g. phase3-004 manual override).
    approval_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    error_rate:    Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    rollback_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    window_days:   Mapped[int | None]     = mapped_column(Integer)

    promoted_by: Mapped[str] = mapped_column(String(255), nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # phase21-001 — link back to the ApprovalRequest that triggered this row.
    # NULL on legacy phase8-002 rows (snapshot-gate proposals that predated
    # the approval-driven flow). UNIQUE when set: makes the autonomy.promote
    # handler idempotent under Celery retry.
    approval_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))

    def __repr__(self) -> str:
        return (
            f"<AutonomyPromotion id={self.id} agent={self.agent_name} "
            f"{self.from_level}→{self.to_level} at={self.promoted_at}>"
        )
