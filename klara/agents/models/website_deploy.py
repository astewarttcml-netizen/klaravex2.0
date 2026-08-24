"""
app/models/website_deploy.py
─────────────────────────────
ORM model for website_deploy_jobs table.

Tracks page content update jobs pushed to WordPress via the WP REST API.
All jobs go through a mandatory P3 human approval gate before execution.
The agent ONLY creates drafts — it never sets status: publish on any WP page.
"""
from __future__ import annotations

import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from klara.rarv.runtime import Base


class DeployJobStatus(str, enum.Enum):
    PENDING   = "PENDING"    # Queued, awaiting human approval
    APPROVED  = "APPROVED"   # Approved, not yet executing
    EXECUTING = "EXECUTING"  # WP REST API call in flight
    COMPLETED = "COMPLETED"  # Successfully written to WP as draft
    FAILED    = "FAILED"     # WP API returned an error


class WebsiteDeployJob(Base):
    """
    Represents a single WordPress page content update job.

    Lifecycle:
      queue endpoint  → status=PENDING, returns job_id
      approve endpoint → status=APPROVED → EXECUTING → COMPLETED | FAILED

    Immutability contract: new_content and old_content_hash are never
    mutated after INSERT.  Only status, approved_at, executed_at, and
    error_message are updated post-creation.
    """
    __tablename__ = "website_deploy_jobs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── Target ────────────────────────────────────────────────────────────────
    page_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    page_title: Mapped[str] = mapped_column(String(500), nullable=False)

    # ── Content ───────────────────────────────────────────────────────────────
    new_content: Mapped[str] = mapped_column(Text, nullable=False)
    # SHA-256 hex digest of the existing WP page content at queue time.
    # Nullable because fetching the current content is best-effort.
    old_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── Status ────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20),
        default=DeployJobStatus.PENDING,
        nullable=False,
        index=True,
    )

    # ── Provenance ────────────────────────────────────────────────────────────
    queued_by: Mapped[str] = mapped_column(String(255), nullable=False)

    # ── Timestamps ────────────────────────────────────────────────────────────
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Error capture ─────────────────────────────────────────────────────────
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<WebsiteDeployJob id={self.id} page_id={self.page_id} "
            f"status={self.status} queued_by={self.queued_by}>"
        )
