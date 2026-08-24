"""
app/models/lead.py
──────────────────
Lead ORM model.

GDPR note: name/email/phone are personal data under Art. 4 GDPR.
- Stored with purpose limitation (IT consulting qualification only).
- Anonymised after gdpr_anonymize_after_days via Celery task.
- Full deletion on Subject Access Request / right to erasure.
"""
import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from klara.rarv.runtime import Base


class LeadStatus(str, enum.Enum):
    new = "new"
    qualified = "qualified"
    disqualified = "disqualified"
    discovery_done = "discovery_done"   # discovery call completed, post_call_processor done
    proposal_sent = "proposal_sent"
    won = "won"
    lost = "lost"
    anonymised = "anonymised"   # GDPR anonymisation applied


class LeadSource(str, enum.Enum):
    chat = "chat"
    contact_form = "contact_form"
    wp_webhook = "wp_webhook"
    callback_request = "callback_request"   # Rückruf anfordern (phone callback form)
    manual = "manual"


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── PII fields (GDPR Art. 4) ──────────────────────────────────────────────
    name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(50))
    company: Mapped[str | None] = mapped_column(String(255))

    # ── Business fields ───────────────────────────────────────────────────────
    source: Mapped[str] = mapped_column(
        String(30), default=LeadSource.chat, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30), default=LeadStatus.new, nullable=False, index=True
    )
    score: Mapped[float | None] = mapped_column(Float)          # 0–100
    score_reason: Mapped[str | None] = mapped_column(Text)
    services_interest: Mapped[str | None] = mapped_column(Text)  # JSON array stored as text
    budget_range: Mapped[str | None] = mapped_column(String(100))
    timeline: Mapped[str | None] = mapped_column(String(100))
    message: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    # ── GDPR consent ─────────────────────────────────────────────────────────
    gdpr_consent: Mapped[bool] = mapped_column(default=False, nullable=False)
    gdpr_consent_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gdpr_consent_ip: Mapped[str | None] = mapped_column(String(45))  # IPv6 max length

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    anonymised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Engagement tracking ───────────────────────────────────────────────────
    # Set by CalendarIntegrationAgent after booking invite is sent (idempotency).
    booking_email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set by FollowupNurtureAgent after 3-day follow-up is sent (idempotency).
    followup_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set by ColdNurtureAgent: which step (0=none, 1, 2, 3) has been queued.
    cold_nurture_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Timestamp of last cold nurture email queued (used to enforce step gaps).
    cold_nurture_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Discovery call & onboarding ───────────────────────────────────────────
    # Raw / structured notes captured from discovery call (migration 0023).
    call_notes: Mapped[str | None] = mapped_column(Text)
    # Set when the discovery call is marked completed (idempotency + reporting).
    call_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set by ClientOnboardingAgent when the onboarding email is sent (idempotency).
    onboarding_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── NPS / client satisfaction ─────────────────────────────────────────────
    # Set by ClientSatisfactionAgent when the survey email is sent (idempotency).
    satisfaction_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Written by GET /api/v1/survey/nps when the client clicks a score link.
    satisfaction_score: Mapped[float | None] = mapped_column(Float)

    # ── Testimonial / referral ────────────────────────────────────────────────
    # Set by TestimonialRequesterAgent when the review request is queued (idempotency).
    testimonial_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set by ReferralCampaignAgent when the referral ask is queued (idempotency).
    referral_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Lead enrichment ───────────────────────────────────────────────────────
    # Set by LeadEnrichmentAgent after enrichment inference completes (idempotency).
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Inferred company size string e.g. "11-50 employees (inferred)".
    company_size: Mapped[str | None] = mapped_column(String(150))
    # JSON array of inferred current technologies e.g. '["Google Workspace", "on-prem Exchange"]'.
    tech_stack: Mapped[str | None] = mapped_column(Text)
    # Set by DiscoveryCallPrepAgent when call prep doc is generated (triggers enrichment sweep).
    call_prep_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Callback request (Rückruf anfordern) ─────────────────────────────────
    # Set by CallbackIntakeAgent when a phone callback form is submitted (idempotency).
    callback_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Free-text preferred callback window from the form e.g. "Vormittags", "14:00–16:00".
    preferred_callback_time: Mapped[str | None] = mapped_column(String(100))

    # ── Calendly booking (Phase 8) ────────────────────────────────────────────
    # Set by CalendlyWebhookAgent on invitee.created; cleared on invitee.canceled.
    meeting_booked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # UTC start time of the booked event (from Calendly scheduled_event.start_time).
    meeting_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Calendly scheduled_event URI — used for cancellation matching.
    calendly_event_uri: Mapped[str | None] = mapped_column(Text)


    def __repr__(self) -> str:
        return f"<Lead id={self.id} status={self.status} score={self.score}>"
