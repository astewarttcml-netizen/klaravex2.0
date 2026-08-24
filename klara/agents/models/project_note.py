"""
app/models/project_note.py
───────────────────────────
Internal admin notes attached to a project (portal-232).

These notes are NEVER visible to the client portal.  They exist only in
admin-facing API endpoints protected by verify_api_key.

Design:
- `updated_at` is refreshed automatically on every UPDATE by the DB
  (server_default + onupdate via func.now()) so no application code needs
  to touch it.
- Optional `invoice_id` lets Anthony link a note to a specific invoice for
  quick context.  NULL = note applies to the project in general.
- No `task_id` FK — no task table exists in this schema yet.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from klara.rarv.runtime import Base


class ProjectNote(Base):
    __tablename__ = "project_notes"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("portal_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional — link the note to a specific invoice for context
    invoice_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("portal_invoices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
