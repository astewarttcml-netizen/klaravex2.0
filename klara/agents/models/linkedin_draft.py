"""
app/models/linkedin_draft.py
─────────────────────────────
phase20-001 — LinkedinDraft model.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from klara.rarv.runtime import Base


class LinkedinDraftStatus:
    draft = "draft"
    sent = "sent"
    replied = "replied"
    declined = "declined"


class LinkedinDraft(Base):
    __tablename__ = "linkedin_drafts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    prospected_lead_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("prospected_leads.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    draft_body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=LinkedinDraftStatus.draft, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    replied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reply_text: Mapped[Optional[str]] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
