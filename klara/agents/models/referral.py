"""
app/models/referral.py
───────────────────────
phase18-003 — referral attribution model.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReferralSource:
    """How the referral was captured."""
    manual = "manual"
    client_form = "client_form"
    invite_link = "invite_link"
    word_of_mouth = "word_of_mouth"


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    referring_client_id: Mapped[Optional[str]] = mapped_column(String(36))
    referring_lead_id: Mapped[Optional[str]] = mapped_column(String(36))
    referred_lead_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default=ReferralSource.manual)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
