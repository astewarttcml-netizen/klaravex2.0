"""
app/models/known_problem.py
───────────────────────────
KnownProblem — knowledge-base entry that maps a recurring product symptom
to its diagnosis, fix, and any related ticket templates (prod-004).

Used by the agent system to suggest a likely root cause and a known good
fix when a new ticket comes in. The match flow (slice 2) will:
  1. read the incoming ticket text
  2. score it against known symptoms (initially ILIKE, later FTS)
  3. surface the top match in the agent's reasoning context
  4. propose a ticket template from related_ticket_templates if one applies

This table holds INTERNAL knowledge — there is no per-client scoping.
The CRUD API is locked behind X-API-Key (admin only).
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Computed, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from klara.rarv.runtime import Base


class KnownProblem(Base):
    """A single entry in the Know-How Library."""
    __tablename__ = "known_problems"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # Product / system the symptom belongs to (free-text for now: 'Microsoft 365',
    # 'Meraki', 'Intune'…). Indexed for filter queries.
    product: Mapped[str] = mapped_column(String(120), nullable=False, index=True)

    # The observable client-reported symptom. Long-form so it can be matched
    # against ticket descriptions. Indexed via FTS GIN in a follow-up migration.
    symptom: Mapped[str] = mapped_column(Text, nullable=False)

    # The internal diagnosis: why the symptom happens.
    diagnosis: Mapped[str] = mapped_column(Text, nullable=False)

    # The known good fix or remediation steps.
    fix: Mapped[str] = mapped_column(Text, nullable=False)

    # Free-form list of ticket-template references to suggest when this problem
    # matches. Stored as JSONB so we can later filter by template id natively.
    related_ticket_templates: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    # Cross-cutting categorisation tags ('auth', 'licensing', 'networking', …).
    # Orthogonal to `product`: an Intune row and a Microsoft 365 row can share
    # the 'auth' tag so the admin filter surfaces both in one view. Stored as
    # JSONB and indexed with GIN (jsonb_path_ops) for cheap `tags @> '["x"]'`
    # containment queries; case is normalised at the API layer.
    tags: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    # PostgreSQL STORED GENERATED column maintained by the database from
    # (product, symptom, diagnosis). The Python attribute is read-only —
    # writes happen at the DB level whenever a source column changes.
    # Declared so SQLAlchemy can reference it in FTS queries
    # (KnownProblem.search_vector.op("@@")(plainto_tsquery(...))).
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(product, '')),   'A') || "
            "setweight(to_tsvector('english', coalesce(symptom, '')),   'B') || "
            "setweight(to_tsvector('english', coalesce(diagnosis, '')), 'C')",
            persisted=True,
        ),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<KnownProblem id={self.id} product={self.product!r}>"
