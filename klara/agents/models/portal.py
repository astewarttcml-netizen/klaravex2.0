"""
app/models/portal.py
────────────────────
ORM models for the client portal: Client, Project, ClientFile, Invoice.

GDPR notes:
- Client.email / Client.name are personal data under Art. 4 GDPR.
- Purpose: authenticated portal access and project communication only.
- Clients can request deletion; admin must remove or anonymise.
- portal_clients are NOT leads — separate table, separate lifecycle.
- Files are stored at server paths; paths are never exposed directly.
"""
import enum
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class ProjectStatus(str, enum.Enum):
    new_request      = "new_request"
    in_assessment    = "in_assessment"
    draft_ready      = "draft_ready"
    awaiting_approval = "awaiting_approval"
    in_progress      = "in_progress"
    waiting_on_client = "waiting_on_client"
    complete         = "complete"


# Human-readable labels and descriptions shown to clients
PROJECT_STATUS_LABELS: dict[ProjectStatus, dict[str, str]] = {
    ProjectStatus.new_request: {
        "label": "New Request",
        "description": "We've received your request and it's in the queue.",
    },
    ProjectStatus.in_assessment: {
        "label": "In Assessment",
        "description": "We're reviewing your environment and requirements.",
    },
    ProjectStatus.draft_ready: {
        "label": "Draft Ready",
        "description": "A draft or proposal is ready for your review.",
    },
    ProjectStatus.awaiting_approval: {
        "label": "Awaiting Your Approval",
        "description": "We're waiting for your sign-off before proceeding.",
    },
    ProjectStatus.in_progress: {
        "label": "In Progress",
        "description": "Work is actively under way.",
    },
    ProjectStatus.waiting_on_client: {
        "label": "Waiting on You",
        "description": "We need something from you to continue — check the next action.",
    },
    ProjectStatus.complete: {
        "label": "Complete",
        "description": "This project has been delivered and closed.",
    },
}


class InvoiceStatus(str, enum.Enum):
    draft     = "draft"
    sent      = "sent"
    unpaid    = "unpaid"
    paid      = "paid"
    overdue   = "overdue"
    cancelled = "cancelled"


class FileLabel(str, enum.Enum):
    """
    Lifecycle stage of a ClientFile (portal-241).

    Workflow: draft → approved → delivered.
      - draft:     internal working copy; HIDDEN from the client portal.
      - approved:  vetted by IT Experts; visible to the owning client.
      - delivered: handed over and acknowledged; visible to the owning client.

    Only `approved` and `delivered` are exposed via the portal files API;
    `draft` files are filtered out at the listing and download layer so a
    client cannot guess an id and pull a draft.
    """
    draft     = "draft"
    approved  = "approved"
    delivered = "delivered"


# Labels that may be returned by the client portal. `draft` is admin-only.
CLIENT_VISIBLE_FILE_LABELS: frozenset[str] = frozenset(
    {FileLabel.approved.value, FileLabel.delivered.value}
)


# ─────────────────────────────────────────────────────────────────────────────
# Client
# ─────────────────────────────────────────────────────────────────────────────

class Client(Base):
    """
    A portal client account — distinct from a Lead.

    Leads are pre-sale prospects.  Clients are paying / active engagements
    with portal access.  A lead may be converted to a client, but the records
    are kept separate for clarity and GDPR scope limitation.
    """
    __tablename__ = "portal_clients"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── PII (GDPR Art. 4) ─────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    company: Mapped[str | None] = mapped_column(String(255))

    # ── Auth ──────────────────────────────────────────────────────────────────
    # nullable=True: passwordless accounts (magic link only) have no password hash.
    # Existing accounts retain their bcrypt hash for backward compat.
    # Migration 0047 sets this column nullable in the DB.
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Preferred language for portal UI and outbound communication ("en" or "de")
    language_preference: Mapped[str] = mapped_column(
        String(5), nullable=False, default="en", server_default="en"
    )

    # ── Internal notes (never exposed to client) ──────────────────────────────
    internal_notes: Mapped[str | None] = mapped_column(Text)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<Client id={self.id} email={self.email} active={self.is_active}>"


# ─────────────────────────────────────────────────────────────────────────────
# Project
# ─────────────────────────────────────────────────────────────────────────────

class Project(Base):
    """
    A client-facing project record.

    - status uses ProjectStatus enum values.
    - next_action and latest_update are plain-English client-facing text.
    - Internal technical details should NOT appear here.
    """
    __tablename__ = "portal_projects"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    client_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True
        # No FK constraint here to keep migrations independent;
        # application layer enforces client ownership.
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=ProjectStatus.new_request,
        index=True,
    )

    # Client-facing plain-English summary of what happens next
    next_action: Mapped[str | None] = mapped_column(Text)

    # Client-facing summary of the most recent work done
    latest_update: Mapped[str | None] = mapped_column(Text)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} client={self.client_id} status={self.status}>"


# ─────────────────────────────────────────────────────────────────────────────
# ClientFile
# ─────────────────────────────────────────────────────────────────────────────

class ClientFile(Base):
    """
    A file or document accessible to a specific client.

    Security rules:
    - file_path is a server-side path and is NEVER returned in API responses.
    - Downloads are served through the portal files API only.
    - client_id ownership is checked on every download request.
    """
    __tablename__ = "portal_files"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    client_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # ── Storage ───────────────────────────────────────────────────────────────
    # Server-side path — NEVER exposed in API responses
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column()
    mime_type: Mapped[str | None] = mapped_column(String(128))
    original_filename: Mapped[str | None] = mapped_column(String(255))

    # ── Lifecycle label (portal-241) ──────────────────────────────────────────
    # See FileLabel. `draft` rows are never returned through the portal API;
    # the listing and download endpoints filter on CLIENT_VISIBLE_FILE_LABELS.
    label: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=FileLabel.draft.value,
        server_default=FileLabel.draft.value,
        index=True,
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<ClientFile id={self.id} client={self.client_id} title={self.title!r}>"


# ─────────────────────────────────────────────────────────────────────────────
# Invoice
# ─────────────────────────────────────────────────────────────────────────────

class Invoice(Base):
    """
    An invoice shown to a client in the portal.

    Phase 1: payment_link is a manually set URL (e.g. Stripe payment link).
    Phase 2: wire Stripe API to generate and update payment_link automatically.

    Currency stored as ISO 4217 code (default EUR).
    Amount stored as NUMERIC(10,2) — exact decimal, no floating-point errors.
    """
    __tablename__ = "portal_invoices"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    client_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), index=True
    )

    reference: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=InvoiceStatus.unpaid, index=True
    )

    # Manually set for Phase 1; will be generated by Stripe in Phase 2
    payment_link: Mapped[str | None] = mapped_column(String(2048))
    due_date: Mapped[date | None] = mapped_column(Date)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Invoice id={self.id} ref={self.reference} status={self.status}>"


# ─────────────────────────────────────────────────────────────────────────────
# InvoiceLineItem (portal-221 slice 2)
# ─────────────────────────────────────────────────────────────────────────────

class InvoiceLineItem(Base):
    """
    A single billable line on an invoice.

    Each line carries its own VAT rate so a single invoice can mix standard,
    reduced, and zero-rated items (common for German consultancy work).

    Subtotal / VAT amount / total for the invoice are computed by summing
    over its line items (see app/api/portal/invoices.py). Invoice.amount
    remains the canonical GROSS total — when line items exist their
    sum-with-VAT must equal Invoice.amount, but we do not enforce this in
    the schema so existing invoices without line items continue to work.

    `position` controls display order; ties broken by id for stability.
    """
    __tablename__ = "portal_invoice_line_items"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    invoice_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True
        # No FK constraint here to keep migrations independent;
        # application layer enforces invoice ownership.
    )

    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # VAT rate as a decimal fraction: 0.19 for 19% German standard, 0.07 reduced,
    # 0.00 for non-taxable (e.g. reverse-charge EU B2B). Stored at line level
    # because a single invoice can mix rates.
    vat_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=Decimal("0.0000")
    )

    # Display order on the invoice. Lower = earlier.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<InvoiceLineItem id={self.id} invoice={self.invoice_id} "
            f"qty={self.quantity} price={self.unit_price} vat={self.vat_rate}>"
        )

    # ── Helpers (no DB I/O — safe to call on detached instances) ──────────────

    @property
    def line_subtotal(self) -> Decimal:
        """Net amount for this line: quantity × unit_price."""
        return (self.quantity or Decimal(0)) * (self.unit_price or Decimal(0))

    @property
    def line_vat(self) -> Decimal:
        """VAT amount for this line: line_subtotal × vat_rate."""
        return self.line_subtotal * (self.vat_rate or Decimal(0))

    @property
    def line_total(self) -> Decimal:
        """Gross amount for this line: line_subtotal + line_vat."""
        return self.line_subtotal + self.line_vat
