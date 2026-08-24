"""
app/models/playbook.py
──────────────────────
Playbook — a pre-built workflow checklist for a recurring client-task pattern
(prod-006). Each playbook captures the steps that resolve a known scenario
("Reset user MFA", "New-hire onboarding", "New-tenant M365 cleanup") so the
agent system can suggest the right one when a matching ticket arrives.

Playbooks are INTERNAL knowledge, like KnownProblem entries — there is no
per-client scoping. The CRUD API is admin-only (X-API-Key).

Schema notes:
- `applies_to` is the same free-text product label used on KnownProblem.product
  ("Microsoft 365", "Meraki", "Intune"). NULL means the playbook is product-
  agnostic and matches any ticket regardless of declared product.
- `steps` is a JSONB array of {description, responsible_party, automation_script_ref}.
- `keywords` is a JSONB array of lowercase strings used by the suggest endpoint
  for keyword-overlap scoring. A future slice will replace this with a tsvector
  GIN index on (name, description, keywords) for true FTS without changing the
  request/response contract.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Playbook(Base):
    """A single entry in the Playbook library."""
    __tablename__ = "playbooks"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Product label this playbook applies to (e.g. "Microsoft 365"). NULL means
    # product-agnostic. Indexed for product-filtered list queries.
    applies_to: Mapped[str | None] = mapped_column(
        String(120), nullable=True, index=True
    )

    # Ordered list of {description, responsible_party, automation_script_ref}.
    # JSONB so the suggest endpoint can later pluck out automation refs without
    # parsing a string blob.
    steps: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    # Lowercase tokens used by the suggest endpoint for matching. Stored as
    # JSONB for forward compatibility with weights/synonyms in future slices.
    keywords: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Playbook id={self.id} name={self.name!r} applies_to={self.applies_to}>"
