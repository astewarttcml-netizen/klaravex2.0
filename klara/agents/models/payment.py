"""
app/models/payment.py
─────────────────────
Payment and PaymentEvent models for Stripe webhook-driven payment state.

Policy rules (from docs/policies.md §3.3, §12):
- Payment truth derives ONLY from verified Stripe webhook events.
- No frontend redirect or unverified signal may change payment state.
- Every state change must log payment_intent_id and event_id.
- Manual overrides require explicit human approval and a rollback plan.
"""
import enum
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import DateTime, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from klara.rarv.runtime import Base


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class PaymentStatus(str, enum.Enum):
    pending   = "pending"    # checkout session created, no webhook yet
    succeeded = "succeeded"  # payment_intent.succeeded webhook received + verified
    failed    = "failed"     # payment_intent.payment_failed webhook received
    refunded  = "refunded"   # charge.refunded webhook received
    disputed  = "disputed"   # charge.dispute.created webhook received
    cancelled = "cancelled"  # checkout.session.expired or manual void (requires approval)


class PaymentEventType(str, enum.Enum):
    checkout_session_created    = "checkout.session.created"
    checkout_session_completed  = "checkout.session.completed"
    checkout_session_expired    = "checkout.session.expired"
    payment_intent_succeeded    = "payment_intent.succeeded"
    payment_intent_failed       = "payment_intent.payment_failed"
    charge_refunded             = "charge.refunded"
    dispute_created             = "charge.dispute.created"
    other                       = "other"


# ─────────────────────────────────────────────────────────────────────────────
# Payment
# ─────────────────────────────────────────────────────────────────────────────

class Payment(Base):
    """
    Canonical payment record tied to a portal invoice.

    State is SET ONLY by verified Stripe webhook events processed in
    PaymentEvent rows. No application code may update `status` directly
    without a corresponding PaymentEvent record.

    Columns:
    - invoice_id:          links to portal_invoices.id
    - client_id:           denormalized for fast ownership checks
    - stripe_session_id:   Stripe Checkout Session ID (cs_...)
    - stripe_payment_intent_id: Stripe PaymentIntent ID (pi_...)
    - amount / currency:   duplicated from invoice at checkout creation time
    - status:              current state derived from the latest webhook event
    """
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    invoice_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True
    )
    client_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, index=True
    )

    # ── Stripe identifiers ────────────────────────────────────────────────────
    stripe_session_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True
    )

    # ── Amount (snapshot at checkout creation time) ───────────────────────────
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")

    # ── State — only updated by verified webhook events ───────────────────────
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=PaymentStatus.pending,
        index=True,
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<Payment id={self.id} invoice={self.invoice_id} "
            f"status={self.status} amount={self.amount}{self.currency}>"
        )


# ─────────────────────────────────────────────────────────────────────────────
# PaymentEvent
# ─────────────────────────────────────────────────────────────────────────────

class PaymentEvent(Base):
    """
    Immutable audit record of every Stripe webhook event that touched a payment.

    Rules:
    - INSERT-only: rows are never updated or deleted.
    - Every status change on Payment must produce a PaymentEvent row first.
    - stripe_event_id has a unique index to enforce idempotency —
      duplicate webhook deliveries are silently ignored at the DB level.

    Columns:
    - payment_id:      FK to payments.id (nullable: event may arrive before
                       payment row in edge cases — store and reconcile)
    - stripe_event_id: Stripe event ID (evt_...) — unique constraint
    - event_type:      PaymentEventType enum value
    - stripe_payload:  raw Stripe event JSON for audit and replay
    - new_status:      the payment status set as a result of this event
    - processed_at:    server timestamp when the webhook was processed
    """
    __tablename__ = "payment_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    payment_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), index=True
    )

    # ── Stripe event identity ─────────────────────────────────────────────────
    stripe_event_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # ── Payload and state snapshot ────────────────────────────────────────────
    stripe_payload: Mapped[str | None] = mapped_column(Text)   # JSON string
    new_status: Mapped[str | None] = mapped_column(String(30)) # status set by this event

    # ── Timestamps ────────────────────────────────────────────────────────────
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<PaymentEvent id={self.id} event={self.stripe_event_id} "
            f"type={self.event_type} status={self.new_status}>"
        )
