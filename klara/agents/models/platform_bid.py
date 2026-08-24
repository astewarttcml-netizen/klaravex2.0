"""
app/models/platform_bid.py
───────────────────────────
A bid submitted (or queued) on a freelance platform against a FreelanceProject.

Status lifecycle:
  draft → queued → submitted → shortlisted | won | lost | withdrawn

When status → won, PlatformClientConverterAgent creates a Lead record
and populates lead_id.

vapi_call_id is populated by VoiceCallAgent after an outbound call is placed.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from klara.rarv.runtime import Base


class PlatformBidStatus:
    draft = "draft"
    queued = "queued"
    submitted = "submitted"
    shortlisted = "shortlisted"
    won = "won"
    lost = "lost"
    withdrawn = "withdrawn"
    submit_failed = "submit_failed"


class PlatformBid(Base):
    __tablename__ = "platform_bids"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── Foreign keys ──────────────────────────────────────────────────────────
    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("freelance_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── Platform reference ────────────────────────────────────────────────────
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    platform_bid_id: Mapped[Optional[str]] = mapped_column(
        String(255)  # platform's own reference after successful submission
    )

    # ── Bid content ───────────────────────────────────────────────────────────
    cover_letter: Mapped[Optional[str]] = mapped_column(Text)
    bid_amount: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    bid_currency: Mapped[str] = mapped_column(String(10), default="EUR")
    delivery_days: Mapped[Optional[int]] = mapped_column()

    # ── Status ────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(50), default=PlatformBidStatus.draft, index=True
    )
    submit_error: Mapped[Optional[str]] = mapped_column(
        Text  # last submission error if status=submit_failed
    )

    # ── Voice call tracking ───────────────────────────────────────────────────
    vapi_call_id: Mapped[Optional[str]] = mapped_column(String(255))
    call_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    call_outcome: Mapped[Optional[str]] = mapped_column(
        String(50)  # "interested" | "not_interested" | "no_answer" | "voicemail"
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    won_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    def __repr__(self) -> str:
        return (
            f"<PlatformBid {self.platform} project={self.project_id[:8]} "
            f"status={self.status} amount={self.bid_amount}>"
        )
