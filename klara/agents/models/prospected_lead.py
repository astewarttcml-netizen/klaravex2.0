"""
app/models/prospected_lead.py
──────────────────────────────
Outbound prospected lead record.

Populated by LeadProspectorAgent (PROSP) via Apollo API or CSV import.
Deduplication is enforced by the unique index on `domain`.

Status lifecycle:
  new → outreach_queued → approved → sent → replied
  new → disqualified
  new → outreach_queued → draft_failed
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Date, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProspectedLeadStatus:
    new = "new"
    outreach_queued = "outreach_queued"
    draft_failed = "draft_failed"
    approved = "approved"
    sent = "sent"
    bounced = "bounced"
    replied = "replied"
    disqualified = "disqualified"   # rejected from approval dashboard


class ProspectedLead(Base):
    __tablename__ = "prospected_leads"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── Company (dedup key) ───────────────────────────────────────────────────
    domain: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    company_name: Mapped[Optional[str]] = mapped_column(String(255))
    industry: Mapped[Optional[str]] = mapped_column(String(255))
    employee_count: Mapped[Optional[int]] = mapped_column(Integer())
    location: Mapped[Optional[str]] = mapped_column(String(255))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    country: Mapped[Optional[str]] = mapped_column(String(100))

    # ── Primary contact ───────────────────────────────────────────────────────
    contact_first_name: Mapped[Optional[str]] = mapped_column(String(100))
    contact_last_name: Mapped[Optional[str]] = mapped_column(String(100))
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    contact_title: Mapped[Optional[str]] = mapped_column(String(255))
    contact_linkedin: Mapped[Optional[str]] = mapped_column(String(500))

    # ── Prospecting signal (why this lead was selected) ───────────────────────
    signal: Mapped[Optional[str]] = mapped_column(Text)

    # ── Apollo metadata ───────────────────────────────────────────────────────
    apollo_person_id: Mapped[Optional[str]] = mapped_column(String(255))
    apollo_organization_id: Mapped[Optional[str]] = mapped_column(String(255))

    # ── Outreach draft metadata (stored for approval dashboard display) ───────
    outreach_subject: Mapped[Optional[str]] = mapped_column(String(500))
    outreach_draft: Mapped[Optional[str]] = mapped_column(Text)          # plain-text body
    approval_id: Mapped[Optional[str]] = mapped_column(String(255))      # FK to approval_requests.id
    outreach_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    # ── Rejection tracking ────────────────────────────────────────────────────
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)

    # ── Out-of-office reschedule (phase4-004) ─────────────────────────────────
    # Set when an OOO reply is classified by ReplyIntentAgent. While this
    # date is in the future, eligible_for_followup() suppresses sends and
    # the reschedule service pushes pending OutreachSequence rows past it.
    out_of_office_until: Mapped[Optional[date]] = mapped_column(Date)

    # ── Conversion link (phase4-003) ──────────────────────────────────────────
    # Set when phase4-003 promotes this prospect to a qualified Lead after
    # an INTERESTED reply with confidence >= 0.75. NULL means not converted.
    # Idempotency: convert_to_lead() refuses to re-convert when this is set.
    converted_lead_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False),
        index=True,
    )

    # ── Engagement tracking (phase3-002) ──────────────────────────────────────
    # Populated by app/api/tracking.py + app/api/webhooks_email.py via
    # app/services/engagement_tracker.py. NULL = no signal of that kind yet.
    tracking_token:   Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    opened_at:        Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_opened_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_clicked_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    replied_at:       Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    unsubscribed_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    engagement_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # ── Workflow state ────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(30),
        default=ProspectedLeadStatus.new,
        nullable=False,
        index=True,
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ── Computed helpers ──────────────────────────────────────────────────────

    @property
    def contact_name(self) -> str:
        """Full contact name — convenience for templates / admin views."""
        parts = [self.contact_first_name or "", self.contact_last_name or ""]
        return " ".join(p for p in parts if p).strip()
