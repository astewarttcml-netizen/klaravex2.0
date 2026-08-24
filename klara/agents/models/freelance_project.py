"""
app/models/freelance_project.py
────────────────────────────────
Represents a project discovered on a freelance platform (Upwork, Freelancer.com,
PeoplePerHour, Guru.com).

Status lifecycle:
  new → analyzed → bid_queued → bid_submitted → won | lost | withdrawn
  new → ignored   (score too low or not a fit)

The platform_id + platform combination is the natural dedup key.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FreelanceProjectStatus:
    new = "new"
    analyzed = "analyzed"
    bid_queued = "bid_queued"
    bid_submitted = "bid_submitted"
    won = "won"
    lost = "lost"
    withdrawn = "withdrawn"
    ignored = "ignored"


class FreelancePlatform:
    upwork = "upwork"
    freelancer = "freelancer"
    peopleperhour = "peopleperhour"
    guru = "guru"
    freelancermap = "freelancermap"


class FreelanceProject(Base):
    __tablename__ = "freelance_projects"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── Platform identity (dedup key: platform + platform_id) ─────────────────
    platform: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    platform_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )

    # ── Project details ───────────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    skills_required: Mapped[Optional[str]] = mapped_column(
        Text  # JSON array stored as text e.g. '["Azure", "M365", "PowerShell"]'
    )
    category: Mapped[Optional[str]] = mapped_column(String(255))

    # ── Budget ────────────────────────────────────────────────────────────────
    budget_min: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    budget_max: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    budget_type: Mapped[Optional[str]] = mapped_column(
        String(20)  # "fixed" | "hourly"
    )
    budget_currency: Mapped[str] = mapped_column(String(10), default="EUR")

    # ── Client info ───────────────────────────────────────────────────────────
    client_name: Mapped[Optional[str]] = mapped_column(String(255))
    client_location: Mapped[Optional[str]] = mapped_column(String(255))
    client_rating: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    client_reviews_count: Mapped[Optional[int]] = mapped_column(Integer())
    client_spend_total: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    client_email: Mapped[Optional[str]] = mapped_column(String(255))
    client_phone: Mapped[Optional[str]] = mapped_column(String(50))

    # ── Project metadata ──────────────────────────────────────────────────────
    url: Mapped[Optional[str]] = mapped_column(String(1000))
    posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    deadline_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    proposals_count: Mapped[Optional[int]] = mapped_column(Integer())
    is_verified_client: Mapped[Optional[bool]] = mapped_column(default=False)

    # ── Scoring + status ──────────────────────────────────────────────────────
    fit_score: Mapped[Optional[int]] = mapped_column(
        Integer()  # 0–100 — set by BidStrategyAgent
    )
    fit_rationale: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(50), default=FreelanceProjectStatus.new, index=True
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    bid_queued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    bid_submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    won_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    def __repr__(self) -> str:
        return (
            f"<FreelanceProject {self.platform}:{self.platform_id} "
            f"status={self.status} score={self.fit_score}>"
        )
