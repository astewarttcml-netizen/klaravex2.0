"""
app/models/inbound_email.py
────────────────────────────
phase19-001 — InboundEmail + InboundCategory.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InboundCategory:
    vendor_bill = "vendor_bill"
    prospect_referral = "prospect_referral"
    support_question = "support_question"
    personal = "personal"
    spam = "spam"
    other = "other"

    ALL = frozenset({vendor_bill, prospect_referral, support_question, personal, spam, other})


class InboundEmail(Base):
    __tablename__ = "inbound_emails"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    from_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    to_email: Mapped[Optional[str]] = mapped_column(String(255))
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    body: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    raw_payload: Mapped[Optional[str]] = mapped_column(Text)
    lead_id: Mapped[Optional[str]] = mapped_column(String(36))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    classified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
