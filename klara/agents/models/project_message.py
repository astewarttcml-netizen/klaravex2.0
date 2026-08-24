"""
app/models/project_message.py
──────────────────────────────
ProjectMessage — a single message in the per-project client↔admin thread
(portal-231).

Design:
- `sender_type` is a plain string constrained to 'client' | 'admin' at the
  API layer (not a PG enum) so we avoid an ALTER TYPE if we ever add a third
  party type (e.g. 'system' for automated messages from Klara AI agents).
- `client_id` is denormalised on each row for cheap isolation queries that
  avoid a JOIN back to portal_projects.
- `read_by_client_at` / `read_by_admin_at` are nullable timestamps rather
  than booleans so the UI can show "read on <datetime>" if required later.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

SENDER_CLIENT = "client"
SENDER_ADMIN = "admin"


class ProjectMessage(Base):
    """One message in a project's communication thread."""
    __tablename__ = "project_messages"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("portal_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Denormalised for cheap isolation checks — same pattern as ProjectStatusEvent
    client_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("portal_clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 'client' or 'admin' — validated at API layer
    sender_type: Mapped[str] = mapped_column(String(10), nullable=False)

    # Stored at write time so the thread renders correctly if names change
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)

    body: Mapped[str] = mapped_column(Text, nullable=False)

    # NULL = unread; populated when the other party opens the thread
    read_by_client_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    read_by_admin_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectMessage id={self.id} project={self.project_id} "
            f"sender={self.sender_type}>"
        )
