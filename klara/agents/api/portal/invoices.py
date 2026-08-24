"""
app/api/portal/invoices.py
───────────────────────────
Client invoice and payment endpoints.

GET /api/v1/portal/invoices           — list all client invoices
GET /api/v1/portal/invoices/{id}      — get one invoice detail (Phase 2.2.1)

Phase 1: payment_link is a static URL (manual Stripe payment link or similar).
Phase 2: Replace with Stripe API integration — generate/poll payment intent.

Authorization: client_id ownership enforced on every query.

Phase 2.2.1 detail endpoint contract (portal-221):
The detail response includes client name, project title, and a `payment_status`
field derived ONLY from the Payment table (which is itself only mutated by
verified Stripe webhook events — see app/api/webhooks_stripe.py). The frontend
must NOT trust URL params (?payment=success) when rendering the invoice — the
backend-truth `payment_status` and `payment_verified` fields are authoritative.
"""
from decimal import Decimal
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.portal_auth import get_current_portal_client
from app.database import get_db
from app.models.payment import Payment, PaymentStatus
from app.models.portal import (
    Client,
    Invoice,
    InvoiceLineItem,
    InvoiceStatus,
    Project,
)


# Cents-precision rounding for VAT/subtotal/total. Use ROUND_HALF_UP for the
# user-facing values so totals never differ by a cent due to banker's rounding.
from decimal import ROUND_HALF_UP


def _money(value: Decimal) -> Decimal:
    """Quantize a Decimal to two places with ROUND_HALF_UP (display rounding)."""
    return (value or Decimal(0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Response schemas ──────────────────────────────────────────────────────────

class InvoiceResponse(BaseModel):
    id: str
    reference: str
    amount: Decimal
    currency: str
    status: str
    status_label: str
    due_date: Optional[str]
    payment_link: Optional[str]   # only returned when status is unpaid/overdue
    project_id: Optional[str]
    created_at: str


class LineItemResponse(BaseModel):
    """A single billable line on an invoice (portal-221 slice 2)."""
    id: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    vat_rate: Decimal           # decimal fraction; 0.19 == 19%
    line_subtotal: Decimal      # net = quantity × unit_price
    line_vat: Decimal           # VAT amount on this line
    line_total: Decimal         # gross = subtotal + VAT
    position: int


class InvoiceDetailResponse(InvoiceResponse):
    """
    Extended response for the GET /{invoice_id} detail endpoint (portal-221).

    Adds joined relations (client name, project title), itemised line items
    with VAT breakdown, and the authoritative payment status from the
    Payment table. `payment_verified` is True iff a matching Payment row
    exists with a status set by a verified Stripe webhook event (succeeded
    or refunded). Frontends MUST use these fields rather than inferring
    payment state from query-string parameters.

    Money totals (subtotal, vat_amount, total) are computed from line_items
    when present. When no line items exist the invoice is treated as a
    single un-itemised charge: subtotal = total = invoice.amount, vat = 0.
    """
    client_name: str
    project_title: Optional[str]
    payment_status: Optional[str]   # from Payment.status; None if no checkout yet
    payment_verified: bool          # True only when Payment row reflects a verified event
    pdf_url: Optional[str]          # link to download invoice PDF; None until storage wired

    # ── Itemised totals ───────────────────────────────────────────────────────
    line_items: List[LineItemResponse]
    subtotal: Decimal               # sum of line subtotals (net)
    vat_amount: Decimal             # sum of line VAT amounts
    total: Decimal                  # gross total — equals invoice.amount


_STATUS_LABELS: dict[str, str] = {
    InvoiceStatus.draft:     "Draft",
    InvoiceStatus.sent:      "Sent",
    InvoiceStatus.unpaid:    "Payment Due",
    InvoiceStatus.paid:      "Paid",
    InvoiceStatus.overdue:   "Overdue",
    InvoiceStatus.cancelled: "Cancelled",
}

_PAYABLE_STATUSES = {InvoiceStatus.unpaid, InvoiceStatus.overdue, InvoiceStatus.sent}

# Payment.status values that reflect a Stripe webhook-verified terminal event.
# Per docs/policies.md §3.3, only these statuses are produced from a verified
# stripe_signature on an event row in payment_events.
_VERIFIED_PAYMENT_STATUSES = {
    PaymentStatus.succeeded.value,
    PaymentStatus.refunded.value,
}


def _to_response(inv: Invoice) -> InvoiceResponse:
    is_payable = inv.status in {s.value for s in _PAYABLE_STATUSES}
    return InvoiceResponse(
        id=inv.id,
        reference=inv.reference,
        amount=inv.amount,
        currency=inv.currency,
        status=inv.status,
        status_label=_STATUS_LABELS.get(inv.status, inv.status),
        due_date=inv.due_date.isoformat() if inv.due_date else None,
        # Only expose payment_link when payment is actually required
        payment_link=inv.payment_link if is_payable else None,
        project_id=inv.project_id,
        created_at=inv.created_at.isoformat(),
    )


def _line_item_to_response(item: InvoiceLineItem) -> LineItemResponse:
    return LineItemResponse(
        id=item.id,
        description=item.description,
        quantity=item.quantity,
        unit_price=item.unit_price,
        vat_rate=item.vat_rate,
        line_subtotal=_money(item.line_subtotal),
        line_vat=_money(item.line_vat),
        line_total=_money(item.line_total),
        position=item.position,
    )


def _compute_totals(
    inv: Invoice, line_items: List[InvoiceLineItem]
) -> tuple[Decimal, Decimal, Decimal]:
    """
    Return (subtotal, vat_amount, total).

    With line items: sum each line's net + VAT; total = subtotal + vat_amount.
    Without line items: treat invoice as a single un-itemised gross charge —
    subtotal = total = invoice.amount, vat = 0. This preserves backward
    compatibility for invoices created before line items existed.
    """
    if not line_items:
        return _money(inv.amount), _money(Decimal(0)), _money(inv.amount)
    subtotal = sum((it.line_subtotal for it in line_items), Decimal(0))
    vat_amount = sum((it.line_vat for it in line_items), Decimal(0))
    total = subtotal + vat_amount
    return _money(subtotal), _money(vat_amount), _money(total)


def _to_detail_response(
    inv: Invoice,
    client: Client,
    project: Optional[Project],
    payment: Optional[Payment],
    line_items: Optional[List[InvoiceLineItem]] = None,
) -> InvoiceDetailResponse:
    base = _to_response(inv)
    payment_status = payment.status if payment is not None else None
    payment_verified = (
        payment_status is not None and payment_status in _VERIFIED_PAYMENT_STATUSES
    )
    items = line_items or []
    subtotal, vat_amount, total = _compute_totals(inv, items)
    return InvoiceDetailResponse(
        **base.model_dump(),
        client_name=client.name,
        project_title=project.title if project is not None else None,
        payment_status=payment_status,
        payment_verified=payment_verified,
        # PDF storage is not yet wired (tracked separately). Return None so the
        # frontend can hide the View PDF button instead of linking to a 404.
        pdf_url=None,
        line_items=[_line_item_to_response(it) for it in items],
        subtotal=subtotal,
        vat_amount=vat_amount,
        total=total,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[InvoiceResponse], summary="List client invoices")
async def list_invoices(
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Return all invoices for the authenticated client.

    Excludes 'draft' invoices — only sent/unpaid/paid/overdue/cancelled shown.
    Ordered newest first.
    """
    result = await db.execute(
        select(Invoice)
        .where(
            Invoice.client_id == client.id,
            Invoice.status != InvoiceStatus.draft,
        )
        .order_by(Invoice.created_at.desc())
    )
    invoices = result.scalars().all()
    return [_to_response(inv) for inv in invoices]


@router.get(
    "/{invoice_id}",
    response_model=InvoiceDetailResponse,
    summary="Get invoice detail",
)
async def get_invoice(
    invoice_id: str,
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Return a single invoice with joined client/project context and an
    authoritative payment status (portal-221).

    Returns 404 if not found or belongs to a different client.
    Draft invoices are not accessible.

    `payment_status` is sourced from the Payment table — which is itself
    only mutated by verified Stripe webhook events — never from frontend
    redirect query parameters.
    """
    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.client_id == client.id,  # ← ownership check
            Invoice.status != InvoiceStatus.draft,
        )
    )
    invoice: Invoice | None = result.scalar_one_or_none()

    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found.",
        )

    # Look up the linked project (if any) — title is shown to the client.
    project: Project | None = None
    if invoice.project_id is not None:
        proj_result = await db.execute(
            select(Project).where(
                Project.id == invoice.project_id,
                Project.client_id == client.id,  # defence-in-depth ownership
            )
        )
        project = proj_result.scalar_one_or_none()

    # Look up the most-recent Payment for this invoice. The frontend uses this
    # status to render Pending / Paid / Failed without trusting URL params.
    payment_result = await db.execute(
        select(Payment)
        .where(Payment.invoice_id == invoice_id)
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    payment: Payment | None = payment_result.scalar_one_or_none()

    # Load itemised line items, ordered by position (then id for stability).
    items_result = await db.execute(
        select(InvoiceLineItem)
        .where(InvoiceLineItem.invoice_id == invoice_id)
        .order_by(InvoiceLineItem.position.asc(), InvoiceLineItem.id.asc())
    )
    line_items: List[InvoiceLineItem] = list(items_result.scalars().all())

    logger.info("portal.invoice_viewed", client_id=client.id, invoice_id=invoice_id)
    return _to_detail_response(invoice, client, project, payment, line_items)
