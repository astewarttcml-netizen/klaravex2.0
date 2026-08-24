"""
app/models/invoice.py
─────────────────────
Standalone invoice model for Klara AI's outbound billing flow.

This is DISTINCT from portal.Invoice (portal_clients → invoices).
Klara AI invoices are linked to the sales-cycle Lead, not the portal client.

Use case:
  Anthony issues invoices externally (DATEV, email, PDF).
  When an invoice goes overdue, InvoiceReminderAgent queues a reminder.
  This model tracks the invoice lifecycle so the daily sweep can find
  overdue items without requiring explicit payload.

GDPR: amount, due_date, invoice_ref are billing data associated with a lead.
  Stored for the purpose of automated payment reminders only.
  Tied to the lead lifecycle — anonymised when the lead is anonymised.
"""
import enum
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InvoiceStatus(str, enum.Enum):
    draft     = "draft"       # created, not yet sent to client
    sent      = "sent"        # sent to client, within due date
    unpaid    = "unpaid"      # sent, past due date (not yet reminded)
    reminded  = "reminded"    # reminder sent, awaiting payment
    paid      = "paid"        # payment received
    cancelled = "cancelled"   # invoice voided / written off


class Invoice(Base):
    """
    Klara AI invoice — linked to a Lead (pre-portal, sales-cycle lifecycle).

    Uniquely identified by (lead_id, invoice_ref) — one ref per lead.
    """
    __tablename__ = "loki_invoices"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── Ownership ─────────────────────────────────────────────────────────────
    lead_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )

    # ── Invoice details ────────────────────────────────────────────────────────
    invoice_ref: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))

    # ── Dates ─────────────────────────────────────────────────────────────────
    issue_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # ── Status ────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=InvoiceStatus.sent, index=True
    )

    # ── Reminder tracking ─────────────────────────────────────────────────────
    # Stamped by InvoiceReminderAgent when a reminder is queued for approval.
    # Prevents duplicate reminders on each daily sweep run.
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    # How many reminders have been queued/sent for this invoice.
    reminder_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # ── Internal notes ────────────────────────────────────────────────────────
    notes: Mapped[str | None] = mapped_column(Text)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<Invoice id={self.id} ref={self.invoice_ref} "
            f"lead={self.lead_id} status={self.status}>"
        )
