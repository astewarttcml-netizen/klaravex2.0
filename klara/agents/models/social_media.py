"""
app/models/social_media.py
──────────────────────────
Social media post tracking and promotion management for Klara AI agents.

Lead routing integration:
- SocialMediaPost.is_qualified_lead = true triggers lead_qualification agent (P2)
- Qualified leads flow through standard pipeline: qualification → scoring → routing
"""
import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func, Index
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from klara.rarv.runtime import Base


class SocialMediaPlatform(str, enum.Enum):
    """Supported social media platforms."""
    twitter = "twitter"
    linkedin = "linkedin"
    facebook = "facebook"
    instagram = "instagram"
    youtube = "youtube"
    reddit = "reddit"
    tiktok = "tiktok"
    custom = "custom"


class PromotionStatus(str, enum.Enum):
    """Promotion campaign lifecycle states."""
    draft = "draft"
    scheduled = "scheduled"
    active = "active"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"


class SocialMediaPost(Base):
    """
    Social media post tracking.

    LEAD ROUTING: is_qualified_lead=true → triggers lead_qualification agent
    """
    __tablename__ = "social_media_posts"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── Foreign Keys ──────────────────────────────────────────────────────────
    conversation_id: Mapped[str | None] = mapped_column(
        String(36), index=True
    )  # Nullable for external posts

    # ── Content ───────────────────────────────────────────────────────────────
    platform: Mapped[str] = mapped_column(
        String(30), default=SocialMediaPlatform.custom, nullable=False, index=True
    )
    platform_post_id: Mapped[str | None] = mapped_column(
        String(255), index=True
    )  # Twitter ID, Instagram ID, etc.
    content: Mapped[str | None] = mapped_column(Text)  # Full post text
    author: Mapped[str | None] = mapped_column(String(255), index=True)
    url: Mapped[str | None] = mapped_column(String(2048))  # Full post URL

    # ── Timestamps ────────────────────────────────────────────────────────────
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Engagement Metrics ────────────────────────────────────────────────────
    impressions: Mapped[int | None] = mapped_column(Integer)
    clicks: Mapped[int | None] = mapped_column(Integer)
    likes: Mapped[int | None] = mapped_column(Integer)
    comments: Mapped[int | None] = mapped_column(Integer)
    shares: Mapped[int | None] = mapped_column(Integer)
    engagement_score: Mapped[float | None] = mapped_column(Float)

    # ── LEAD ROUTING ──────────────────────────────────────────────────────────
    is_qualified_lead: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    qualified_lead_reason: Mapped[str | None] = mapped_column(Text)
    qualified_lead_confidence: Mapped[float | None] = mapped_column(
        Float
    )  # 0.0–1.0

    # ── Extra data ────────────────────────────────────────────────────────────
    extra_data: Mapped[dict | None] = mapped_column(JSONB)  # Platform-specific fields (metadata is reserved by SQLAlchemy)

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

    __table_args__ = (
        Index(
            "ix_social_media_posts_qualified_lead",
            "is_qualified_lead",
            "platform",
            "created_at",
        ),
        Index("ix_social_media_posts_conversation_platform", "conversation_id", "platform"),
    )

    def __repr__(self) -> str:
        return f"<SocialMediaPost id={self.id} platform={self.platform} qualified={self.is_qualified_lead}>"


class SocialMediaAnalytics(Base):
    """
    Time-series analytics for social media posts.

    Stores snapshots at regular intervals for trend analysis and reporting.
    """
    __tablename__ = "social_media_analytics"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── Foreign Keys ──────────────────────────────────────────────────────────
    post_id: Mapped[str] = mapped_column(
        String(36), index=True, nullable=False
    )  # Links to SocialMediaPost

    # ── Dimension ─────────────────────────────────────────────────────────────
    platform: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    period: Mapped[str] = mapped_column(
        String(20), default="daily", nullable=False
    )  # daily, hourly, weekly

    # ── Metrics ───────────────────────────────────────────────────────────────
    impressions: Mapped[int | None] = mapped_column(Integer)
    clicks: Mapped[int | None] = mapped_column(Integer)
    likes: Mapped[int | None] = mapped_column(Integer)
    comments: Mapped[int | None] = mapped_column(Integer)
    shares: Mapped[int | None] = mapped_column(Integer)
    reach: Mapped[int | None] = mapped_column(Integer)
    engagement_rate: Mapped[float | None] = mapped_column(Float)

    # ── Timestamps ────────────────────────────────────────────────────────────
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_social_media_analytics_post_period", "post_id", "period", "snapshot_at"),
        Index("ix_social_media_analytics_platform_time", "platform", "snapshot_at"),
    )

    def __repr__(self) -> str:
        return f"<SocialMediaAnalytics post_id={self.post_id} period={self.period} impressions={self.impressions}>"


class SocialMediaPromotion(Base):
    """
    Promotion campaign scheduling and management.

    Manages multi-platform promotion scheduling, budget tracking, and status.
    """
    __tablename__ = "social_media_promotions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── Campaign ──────────────────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    target_url: Mapped[str | None] = mapped_column(String(2048))

    # ── Targeting ─────────────────────────────────────────────────────────────
    platforms: Mapped[list[str]] = mapped_column(
        ARRAY(String(30)), default=list, nullable=False
    )  # ['twitter', 'linkedin', ...]
    target_audience_json: Mapped[dict | None] = mapped_column(
        JSONB
    )  # {'keywords': [...], 'interests': [...]}

    # ── Status ────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(30), default=PromotionStatus.draft, nullable=False, index=True
    )

    # ── Budget & Schedule ─────────────────────────────────────────────────────
    budget_usd: Mapped[float | None] = mapped_column(Float)
    spent_usd: Mapped[float | None] = mapped_column(Float, default=0.0)

    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Results ───────────────────────────────────────────────────────────────
    impressions_delivered: Mapped[int | None] = mapped_column(Integer)
    clicks_delivered: Mapped[int | None] = mapped_column(Integer)
    conversions: Mapped[int | None] = mapped_column(Integer)

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

    __table_args__ = (
        Index("ix_social_media_promotions_status_schedule", "status", "scheduled_start"),
        Index("ix_social_media_promotions_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<SocialMediaPromotion id={self.id} title={self.title} status={self.status}>"
