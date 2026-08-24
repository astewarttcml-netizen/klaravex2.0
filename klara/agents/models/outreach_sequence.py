"""
app/models/outreach_sequence.py
────────────────────────────────
Multi-touch outreach scheduling (phase3-001).

One OutreachSequence row per scheduled step in a prospect's outreach sequence:
  step_number = 1   initial cold email   (created by lead_prospector, sent immediately)
  step_number = 2   Day-3 follow-up      (created by outreach_followup, sent after approval)
  step_number = 3+  reserved for future cadence steps

All steps that belong to one logical "sequence" share the same approval_id.
Approving one ApprovalRequest gates every step it covers — the operator
does not approve each follow-up individually.

Unique (prospect_id, step_number) prevents the scheduler from creating two
step-2 rows for the same prospect (idempotency under retry).
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from klara.rarv.runtime import Base


class OutreachSequenceStatus:
    """String constants — kept loose-typed to match the existing pattern in
    ProspectedLeadStatus elsewhere in the codebase."""
    scheduled        = "scheduled"          # row created, waiting for approval
    pending_approval = "pending_approval"   # ApprovalRequest fired, awaiting review
    approved         = "approved"           # operator approved → next sweep sends
    sent             = "sent"               # delivered to provider
    suppressed       = "suppressed"         # engagement signal arrived; do not send
    cancelled        = "cancelled"          # operator rejected the sequence


class OutreachSequence(Base):
    __tablename__ = "outreach_sequences"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    prospect_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True
    )

    # 1 = initial cold email · 2 = Day-3 follow-up · 3+ = reserved
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Bilingual content — both languages always generated per outreach_email pattern
    subject_en: Mapped[str | None] = mapped_column(String(500))
    subject_de: Mapped[str | None] = mapped_column(String(500))
    body_en:    Mapped[str | None] = mapped_column(Text)
    body_de:    Mapped[str | None] = mapped_column(Text)

    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # State machine — see OutreachSequenceStatus
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=OutreachSequenceStatus.scheduled,
        index=True,
    )

    # Sequence-level approval: every row sharing this approval_id is gated by
    # one ApprovalRequest. Sequence-level approval is the phase3-001 contract.
    approval_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), index=True
    )

    suppress_reason: Mapped[str | None] = mapped_column(String(80))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<OutreachSequence id={self.id} prospect={self.prospect_id} "
            f"step={self.step_number} status={self.status}>"
        )
