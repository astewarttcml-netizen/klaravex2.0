"""
app/models/reply_classification.py
───────────────────────────────────
One row per classified inbound reply (phase4-001).

ReplyIntentAgent (P1, Claude-powered) inserts a row here when an inbound
reply arrives via the webhook in app/api/webhooks_email.py.

Idempotency: a UNIQUE index on prospected_lead_id ensures a given prospect
can only have one classification row. The agent uses ON CONFLICT DO NOTHING
semantics so concurrent webhook deliveries don't race-create duplicates.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from klara.rarv.runtime import Base


class ReplyIntent:
    """Enumeration of intent values written by ReplyIntentAgent.

    Not a SQLAlchemy enum — Postgres enum types are painful to evolve. We
    store as String(32) and validate at the agent boundary.
    """
    INTERESTED = "INTERESTED"
    NOT_NOW = "NOT_NOW"
    WRONG_PERSON = "WRONG_PERSON"
    OUT_OF_OFFICE = "OUT_OF_OFFICE"
    UNSUBSCRIBE = "UNSUBSCRIBE"
    OTHER = "OTHER"

    ALL = frozenset({INTERESTED, NOT_NOW, WRONG_PERSON, OUT_OF_OFFICE, UNSUBSCRIBE, OTHER})


class ReplyClassification(Base):
    __tablename__ = "reply_classifications"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    prospected_lead_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("prospected_leads.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    intent: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    suggested_next_action: Mapped[Optional[str]] = mapped_column(Text)
    return_date: Mapped[Optional[date]] = mapped_column(Date)

    raw_response: Mapped[Optional[str]] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(100), nullable=False)

    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
