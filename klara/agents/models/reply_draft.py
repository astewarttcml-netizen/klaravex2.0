"""
app/models/reply_draft.py
─────────────────────────
A Claude-drafted response to an inbound cold-outreach reply (phase4-002).

Created by ReplyDraftAgent (P3) after ReplyIntentAgent classifies the reply.
Gated by a paired ApprovalRequest (action='reply_draft.send'). When the
approval is granted, the approvals API dispatch sends via Resend and
stamps sent_at.

Status lifecycle:
  pending  → approved (sent_at set)
  pending  → rejected (rejected_at set)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReplyDraftStatus:
    pending = "pending"
    approved = "approved"   # set when approval row flips approved (pre-send race window)
    sent = "sent"
    rejected = "rejected"

    ALL = frozenset({pending, approved, sent, rejected})


class ReplyDraft(Base):
    __tablename__ = "reply_drafts"

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
    classification_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("reply_classifications.id", ondelete="SET NULL"),
    )

    intent: Mapped[str] = mapped_column(String(32), nullable=False)
    draft_subject: Mapped[str] = mapped_column(String(500), nullable=False)
    draft_body_html: Mapped[str] = mapped_column(Text, nullable=False)
    draft_body_text: Mapped[Optional[str]] = mapped_column(Text)

    status: Mapped[str] = mapped_column(
        String(30), default=ReplyDraftStatus.pending, nullable=False, index=True
    )
    approval_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("approval_requests.id", ondelete="SET NULL"),
    )

    model: Mapped[str] = mapped_column(String(100), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
