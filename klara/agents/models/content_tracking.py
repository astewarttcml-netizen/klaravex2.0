"""
app/models/content_tracking.py
───────────────────────────────
ORM models for tracking public content pages and their revision history.

Design notes:
- Rows in content_revisions are INSERT-only for audit purposes.  Never UPDATE
  or DELETE a revision row; create a new one instead.
- published_at is only set when status transitions to "published".  All other
  status changes leave published_at as NULL.
- rollback_target_revision_id lets admins undo a publish instantly by pointing
  at the last known-good revision.  The service layer reads that ID and creates
  a new revision with status="rolled_back" whose content matches the target.
"""
import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class ContentLanguage(str, enum.Enum):
    en = "en"
    de = "de"


class RevisionStatus(str, enum.Enum):
    draft             = "draft"
    pending_approval  = "pending_approval"
    approved          = "approved"
    published         = "published"
    rejected          = "rejected"
    rolled_back       = "rolled_back"


# ─────────────────────────────────────────────────────────────────────────────
# ContentPage
# ─────────────────────────────────────────────────────────────────────────────

class ContentPage(Base):
    """
    A public-facing page tracked by the content agent system.

    - slug is the URL path, e.g. /about or /de/uber-uns.
    - language is the ISO 639-1 code for the page's primary language.
    - wp_post_id links to the WordPress post for two-way sync.
    - current_revision_id is updated after each successful publish.
    """
    __tablename__ = "content_pages"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── Identity ──────────────────────────────────────────────────────────────
    slug: Mapped[str] = mapped_column(
        String(500), nullable=False, unique=True, index=True
    )
    language: Mapped[str] = mapped_column(
        String(5), nullable=False, default=ContentLanguage.en, index=True
    )
    title: Mapped[str | None] = mapped_column(String(500))

    # ── WordPress sync ────────────────────────────────────────────────────────
    wp_post_id: Mapped[int | None] = mapped_column(
        Integer, unique=True, index=True
    )

    # ── Current state ─────────────────────────────────────────────────────────
    # Set to NULL until the first revision is published.
    current_revision_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False)
        # Intentionally no FK constraint here; application layer enforces it.
        # Avoids circular dependency between content_pages and content_revisions.
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<ContentPage id={self.id} slug={self.slug!r} lang={self.language}>"


# ─────────────────────────────────────────────────────────────────────────────
# ContentRevision
# ─────────────────────────────────────────────────────────────────────────────

class ContentRevision(Base):
    """
    An individual edit/revision of a ContentPage.

    Rows are INSERT-only — never update or delete a revision.
    published_at is set only when status transitions to "published".
    rollback_target_revision_id points at the revision to restore if this
    revision is rejected or needs to be undone.
    """
    __tablename__ = "content_revisions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── Links ─────────────────────────────────────────────────────────────────
    page_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True
    )
    approval_request_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), index=True
    )

    # ── Status ────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=RevisionStatus.draft, index=True
    )

    # ── Authorship ────────────────────────────────────────────────────────────
    proposed_by: Mapped[str | None] = mapped_column(String(100))

    # ── Content ───────────────────────────────────────────────────────────────
    diff_summary: Mapped[str | None] = mapped_column(Text)
    content_snapshot: Mapped[str | None] = mapped_column(Text)

    # ── Rollback ──────────────────────────────────────────────────────────────
    rollback_target_revision_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False)
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ContentRevision id={self.id} page={self.page_id} status={self.status}>"
        )
