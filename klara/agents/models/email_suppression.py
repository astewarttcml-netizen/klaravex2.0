"""
app/models/email_suppression.py
───────────────────────────────
Email suppression list (phase4-005).

One row per suppressed email address. The email column is stored lowercased
and has a UNIQUE constraint so add_to_suppression() can be idempotent
without a pre-read.

Sources:
  unsubscribed_reply          — UNSUBSCRIBE intent classified by reply_intent
  unsubscribed_at_backfill    — bootstrap from prospected_leads.unsubscribed_at
  bounced                     — provider hard-bounce notification
  manual                      — operator added via admin UI
  abuse_report                — provider abuse/spam complaint
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SuppressionSource:
    unsubscribed_reply = "unsubscribed_reply"
    unsubscribed_at_backfill = "unsubscribed_at_backfill"
    bounced = "bounced"
    manual = "manual"
    abuse_report = "abuse_report"


class EmailSuppression(Base):
    __tablename__ = "email_suppression_list"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    email: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)

    suppressed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
