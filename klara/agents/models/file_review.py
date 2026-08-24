"""
app/models/file_review.py
─────────────────────────
FileReview — a client's thumbs-up/down + optional comment on one of their
delivered or approved files (portal-242).

One review per (file_id, client_id) pair — re-submitting from the portal
upserts the existing row so the client always sees their latest opinion.

Reviews are only allowed on files whose label is in CLIENT_VISIBLE_FILE_LABELS;
the portal endpoint enforces this. Storing a row never grants access to a
draft file — the visibility rules in app/api/portal/files.py are the source
of truth.

GDPR: comment is free-text supplied by the client and may include opinion or
context. It is treated as personal data tied to the Client.
"""
from __future__ import annotations

import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FileRating(str, enum.Enum):
    """Two-state rating — matches the portal's thumbs-up/thumbs-down UI."""
    up   = "up"
    down = "down"


class FileReview(Base):
    """
    A single client's feedback on one ClientFile.

    Uniqueness on (file_id, client_id) is enforced at the DB level so the
    upsert path can rely on it instead of racing with a SELECT-then-INSERT.
    """
    __tablename__ = "portal_file_reviews"
    __table_args__ = (
        UniqueConstraint(
            "file_id", "client_id", name="uq_portal_file_reviews_file_client"
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # No FK — same convention as ClientFile / Project; ownership is enforced
    # in the application layer to keep migrations independent.
    file_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True
    )
    client_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True
    )

    # "up" or "down". Stored as String for forward compat (e.g. a future
    # neutral state) without needing a migration to alter an enum type.
    rating: Mapped[str] = mapped_column(String(10), nullable=False)

    comment: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<FileReview id={self.id} file={self.file_id} "
            f"client={self.client_id} rating={self.rating}>"
        )
