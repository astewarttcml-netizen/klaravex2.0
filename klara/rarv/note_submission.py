"""
app/models/note_submission.py
──────────────────────────────
RARV journal queue — single write path into the klaravex-vault.

Any Klara AI agent that discovers something worth recording inserts a row
here. The RARV journal team's heartbeat picks up `pending` rows every
30 min, runs them through the 4-agent pipeline (Reasoner → Writer →
Reflector → Verifier), and commits the resulting markdown to the
git-backed vault at github.com/astewarttcml-netizen/klaravex-vault.

Single write path: only the RARV journal team writes to the vault.
Every other agent's path to memory goes through THIS table.

Schema mirrors the live Hetzner table (see migration 0070 on the
Hetzner clone). Migration file alignment between repo and Hetzner is
tracked separately — repo's 0070 is autonomy_promotion_approval_id,
Hetzner's 0070 is note_submissions. The schema below is the source of
truth for ORM access; reconciliation of the migration chain itself is
deliberately out of scope for this commit.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from klara.rarv.runtime import Base


class SubmissionStatus:
    """Stable string constants for the submission_status PG enum."""
    pending = "pending"        # waiting for the journal team to claim
    claimed = "claimed"        # picked up by a worker, lock in place
    processing = "processing"  # actively running through the 4-agent pipeline
    written = "written"        # committed to the vault (terminal)
    rejected = "rejected"      # governance rejected (terminal)
    failed = "failed"          # exhausted max_attempts (terminal)

    TERMINAL = frozenset({written, rejected, failed})
    ALL = frozenset({pending, claimed, processing, written, rejected, failed})


# Tied to the existing Postgres enum type. `create_type=False` so SQLAlchemy
# never tries to create/drop it — Hetzner already has it, and tests use
# Base.metadata.create_all() against a different dialect (or skip DDL).
submission_status_enum = PG_ENUM(
    SubmissionStatus.pending,
    SubmissionStatus.claimed,
    SubmissionStatus.processing,
    SubmissionStatus.written,
    SubmissionStatus.rejected,
    SubmissionStatus.failed,
    name="submission_status",
    schema="public",
    create_type=False,
)


class NoteKind:
    """Convention for note_kind — not enforced at DB level (text column)."""
    decision = "decision"         # locked-in choice
    finding = "finding"           # discovered fact / observation
    incident = "incident"         # outage / failure event
    learning = "learning"         # lesson extracted from incident/win
    blocker = "blocker"           # something blocking progress
    artifact_pointer = "artifact_pointer"  # link to code/file/screenshot
    backstory_update = "backstory_update"  # agent persona refresh


class NoteSubmission(Base):
    __tablename__ = "klaravex_note_submissions"

    # ── Identity ─────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    submission_uuid: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        unique=True,
        nullable=False,
        server_default=text("gen_random_uuid()"),
    )

    # ── Provenance ───────────────────────────────────────────────────────
    agent_id: Mapped[str] = mapped_column(Text, nullable=False)
    agent_run_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False))
    conversation_id: Mapped[Optional[int]] = mapped_column(BigInteger)

    # ── Content ──────────────────────────────────────────────────────────
    topic_slug: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    note_kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_refs: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    proposed_frontmatter: Mapped[Optional[dict]] = mapped_column(JSONB)

    # ── Workflow ─────────────────────────────────────────────────────────
    priority: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("5")
    )
    status: Mapped[str] = mapped_column(
        submission_status_enum,
        nullable=False,
        server_default=text("'pending'::submission_status"),
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)
    reject_code: Mapped[Optional[str]] = mapped_column(Text)
    journal_team_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("3")
    )

    # ── Lock / claim ─────────────────────────────────────────────────────
    claimed_by: Mapped[Optional[str]] = mapped_column(Text)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # ── Commit result ────────────────────────────────────────────────────
    commit_sha: Mapped[Optional[str]] = mapped_column(String(40))
    vault_path: Mapped[Optional[str]] = mapped_column(Text)

    # ── Audit ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def is_terminal(self) -> bool:
        """True when the submission has reached a terminal status."""
        return self.status in SubmissionStatus.TERMINAL

    def can_retry(self) -> bool:
        """True when a failed attempt can be re-queued."""
        return (
            self.status != SubmissionStatus.written
            and self.journal_team_attempts < self.max_attempts
        )

    def __repr__(self) -> str:
        return (
            f"<NoteSubmission id={self.id} agent={self.agent_id} "
            f"topic={self.topic_slug} status={self.status} "
            f"attempts={self.journal_team_attempts}/{self.max_attempts}>"
        )
