"""
app/models/translation_audit.py
─────────────────────────────────
ORM model for translation_audit_log table.

Records every HTML block inspected during a /de/ page scan, with a flag
indicating whether the block appears to be untranslated English.

Each scan run is grouped by audit_run_id (a UUID generated at scan start).
Records are never deleted — resolved_at is set when Anthony marks a block
as fixed, preserving the audit trail.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from klara.rarv.runtime import Base


class TranslationAuditEntry(Base):
    """
    One inspected HTML block from a /de/ page scan.

    Lifecycle:
      scan run       → row inserted, flagged=True if block looks English
      Anthony fixes  → resolved_at stamped via PATCH endpoint (future)

    Immutability contract: all detection columns (page_url, block_tag,
    block_text_snippet, english_word_count, german_indicator_count, flagged,
    audit_run_id, detected_at) are never mutated after INSERT.
    Only resolved_at is written post-creation.
    """

    __tablename__ = "translation_audit_log"

    # ── Identity ──────────────────────────────────────────────────────────────
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── Source ────────────────────────────────────────────────────────────────
    page_url: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    block_tag: Mapped[str] = mapped_column(String(16), nullable=False)   # e.g. "h2", "p", "li"

    # ── Extracted content (capped at 500 chars to keep rows lean) ─────────────
    block_text_snippet: Mapped[str] = mapped_column(String(500), nullable=False)

    # ── Detection scores ──────────────────────────────────────────────────────
    english_word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    german_indicator_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # ── Result ────────────────────────────────────────────────────────────────
    flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    # ── Run grouping ──────────────────────────────────────────────────────────
    audit_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<TranslationAuditEntry id={self.id} page={self.page_url} "
            f"tag={self.block_tag} flagged={self.flagged}>"
        )
