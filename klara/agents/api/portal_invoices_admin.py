"""
app/api/portal_invoices_admin.py
─────────────────────────────────
Admin-only endpoints for portal invoices and their line items (portal-313).

These endpoints manage portal_invoices and portal_invoice_line_items — the
client-facing billing records.  They are SEPARATE from /admin/invoices which
manages loki_invoices (lead-linked pre-sale estimates).

Invoices
  GET    /api/v1/admin/portal/invoices                   — list invoices (filterable)
  POST   /api/v1/admin/portal/invoices                   — create invoice (+ optional line items)
  GET    /api/v1/admin/portal/invoices/{id}              — get full invoice with line items
  PATCH  /api/v1/admin/portal/invoices/{id}              — update reference/amount/currency/due_date/payment_link
  POST   /api/v1/admin/portal/invoices/{id}/mark-paid    — transition to paid status
  POST   /api/v1/admin/portal/invoices/{id}/cancel       — transition to cancelled status

Line items
  POST   /api/v1/admin/portal/invoices/{id}/line-items          — add a line item
  PATCH  /api/v1/admin/portal/invoices/{id}/line-items/{item_id} — update a line item
  DELETE /api/v1/admin/portal/invoices/{id}/line-items/{item_id} — remove a line item

Design notes:
- vat_rate is stored as a decimal fraction (0.19 = 19%); the API accepts this
  same format. Validation rejects values > 1.0 (catches the common 19.0 mistake).
- amount is the authoritative gross total on the Invoice row; line items are
  for display only. If line items are supplied on creation, amount is auto-computed
  as sum(qty * unit_price * (1 + vat_rate)) across lines if amount is omitted.
- Line-item edits on paid/cancelled invoices are blocked.
- Status transitions: unpaid/sent/overdue → paid (mark-paid);
  draft/unpaid/sent/overdue → cancelled (cancel).
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.portal import Client, Invoice, InvoiceLineItem, InvoiceStatus, Project

logger = structlog.get_logger(__name__).bind(agent="portal_invoices_admin")

router = APIRouter()


# ── Payable/cancellable status sets ──────────────────────────────────────────

_PAYABLE_STATUSES   = {InvoiceStatus.unpaid, InvoiceStatus.sent, InvoiceStatus.overdue}
_CANCELLABLE_STATUSES = {InvoiceStatus.draft, InvoiceStatus.unpaid, InvoiceStatus.sent, InvoiceStatus.overdue}
_MUTABLE_STATUSES   = {InvoiceStatus.draft, InvoiceStatus.unpaid, InvoiceStatus.sent, InvoiceStatus.overdue}


# ── Schemas ───────────────────────────────────────────────────────────────────

class LineItemRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=500)
    quantity: Decimal = Field(..., gt=0, description="Number of units (positive decimal).")
    unit_price: Decimal = Field(..., description="Price per unit (may be negative for discounts).")
    vat_rate: Decimal = Field(
        Decimal("0.0000"),
        description="VAT rate as a decimal fraction: 0.19 = 19%, 0.07 = 7%, 0.00 = exempt.",
    )
    position: int = Field(0, description="Display order (lower = earlier).")

    @field_validator("vat_rate")
    @classmethod
    def vat_rate_in_range(cls, v: Decimal) -> Decimal:
        if v < 0 or v > 1:
            raise ValueError(
                "vat_rate must be a decimal fraction between 0.0000 and 1.0000. "
                "Example: use 0.19 for 19%, not 19."
            )
        return v


class InvoiceCreateRequest(BaseModel):
    client_id: str = Field(..., description="UUID of the portal client.")
    project_id: Optional[str] = Field(None, description="UUID of the associated project (optional).")
    reference: str = Field(..., min_length=1, max_length=100, description="Invoice reference number (e.g. INV-2026-001).")
    amount: Optional[Decimal] = Field(
        None,
        description=(
            "Gross total amount. If omitted and line_items are supplied, "
            "computed automatically as sum of line totals."
        ),
    )
    currency: str = Field("EUR", min_length=3, max_length=3, description="ISO 4217 currency code.")
    status: str = Field(InvoiceStatus.unpaid.value, description="Initial invoice status.")
    due_date: Optional[str] = Field(None, description="Due date in YYYY-MM-DD format.")
    payment_link: Optional[str] = Field(None, max_length=2048, description="Manual payment URL (Stripe link or similar).")
    line_items: Optional[List[LineItemRequest]] = Field(None, description="Optional line items to create with the invoice.")

    @field_validator("status")
    @classmethod
    def status_valid(cls, v: str) -> str:
        valid = {s.value for s in InvoiceStatus}
        if v not in valid:
            raise ValueError(f"Invalid status '{v}'. Allowed: {sorted(valid)}")
        return v

    @field_validator("due_date")
    @classmethod
    def due_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        from datetime import date
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError("due_date must be in YYYY-MM-DD format.")
        return v


class InvoicePatchRequest(BaseModel):
    reference: Optional[str] = Field(None, min_length=1, max_length=100)
    amount: Optional[Decimal] = None
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    due_date: Optional[str] = None
    payment_link: Optional[str] = Field(None, max_length=2048)
    # Status is intentionally excluded here — use mark-paid / cancel endpoints.

    @field_validator("due_date")
    @classmethod
    def due_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        from datetime import date
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError("due_date must be in YYYY-MM-DD format.")
        return v


class LineItemResponse(BaseModel):
    id: str
    invoice_id: str
    description: str
    quantity: str       # serialized as string to preserve decimal precision
    unit_price: str
    vat_rate: str
    position: int
    line_subtotal: str
    line_vat: str
    line_total: str
    created_at: str


class InvoiceAdminResponse(BaseModel):
    id: str
    client_id: str
    project_id: Optional[str]
    reference: str
    amount: str
    currency: str
    status: str
    payment_link: Optional[str]
    due_date: Optional[str]
    line_items: List[LineItemResponse]
    created_at: str
    updated_at: str


class InvoiceListItem(BaseModel):
    """Lighter summary for list endpoints (no line items)."""
    id: str
    client_id: str
    project_id: Optional[str]
    reference: str
    amount: str
    currency: str
    status: str
    due_date: Optional[str]
    created_at: str


def _line_to_response(li: InvoiceLineItem) -> LineItemResponse:
    return LineItemResponse(
        id=li.id,
        invoice_id=li.invoice_id,
        description=li.description,
        quantity=str(li.quantity),
        unit_price=str(li.unit_price),
        vat_rate=str(li.vat_rate),
        position=li.position,
        line_subtotal=str(li.line_subtotal),
        line_vat=str(li.line_vat),
        line_total=str(li.line_total),
        created_at=li.created_at.isoformat(),
    )


async def _get_invoice_with_lines(
    invoice_id: str, db: AsyncSession
) -> tuple[Invoice, list[InvoiceLineItem]]:
    """Fetch invoice + ordered line items. Raises 404 if not found."""
    inv_result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice: Invoice | None = inv_result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")

    li_result = await db.execute(
        select(InvoiceLineItem)
        .where(InvoiceLineItem.invoice_id == invoice_id)
        .order_by(InvoiceLineItem.position, InvoiceLineItem.id)
    )
    line_items = list(li_result.scalars().all())
    return invoice, line_items


def _invoice_full_response(inv: Invoice, lines: list[InvoiceLineItem]) -> InvoiceAdminResponse:
    return InvoiceAdminResponse(
        id=inv.id,
        client_id=inv.client_id,
        project_id=inv.project_id,
        reference=inv.reference,
        amount=str(inv.amount),
        currency=inv.currency,
        status=inv.status,
        payment_link=inv.payment_link,
        due_date=inv.due_date.isoformat() if inv.due_date else None,
        line_items=[_line_to_response(li) for li in lines],
        created_at=inv.created_at.isoformat(),
        updated_at=inv.updated_at.isoformat(),
    )


def _compute_gross_total(items: List[LineItemRequest]) -> Decimal:
    total = Decimal("0.00")
    for li in items:
        subtotal = li.quantity * li.unit_price
        total += subtotal + (subtotal * li.vat_rate)
    return total.quantize(Decimal("0.01"))


# ── Invoice endpoints ─────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=List[InvoiceListItem],
    dependencies=[Depends(verify_api_key)],
    summary="List portal invoices (admin, filterable)",
)
async def list_invoices(
    client_id: Optional[str] = Query(None),
    invoice_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    if invoice_status:
        valid = {s.value for s in InvoiceStatus}
        if invoice_status not in valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid status '{invoice_status}'. Allowed: {sorted(valid)}",
            )

    query = select(Invoice).order_by(Invoice.created_at.desc())
    if client_id:
        query = query.where(Invoice.client_id == client_id)
    if invoice_status:
        query = query.where(Invoice.status == invoice_status)
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    rows = result.scalars().all()

    logger.info("admin.invoices.listed", count=len(rows))
    return [
        InvoiceListItem(
            id=inv.id,
            client_id=inv.client_id,
            project_id=inv.project_id,
            reference=inv.reference,
            amount=str(inv.amount),
            currency=inv.currency,
            status=inv.status,
            due_date=inv.due_date.isoformat() if inv.due_date else None,
            created_at=inv.created_at.isoformat(),
        )
        for inv in rows
    ]


@router.post(
    "",
    response_model=InvoiceAdminResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key)],
    summary="Create a portal invoice (optionally with line items)",
)
async def create_invoice(
    req: InvoiceCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a portal invoice.

    If `line_items` are provided and `amount` is omitted, the gross total is
    auto-computed from the line items (qty × unit_price × (1 + vat_rate)).

    If `amount` is also supplied with `line_items`, the supplied amount is used
    as the authoritative total — caller is responsible for consistency.
    """
    # Validate client exists
    client_check = await db.execute(select(Client).where(Client.id == req.client_id))
    if client_check.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Client '{req.client_id}' not found.")

    # Validate project belongs to client if supplied
    if req.project_id:
        proj_check = await db.execute(
            select(Project).where(Project.id == req.project_id, Project.client_id == req.client_id)
        )
        if proj_check.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project '{req.project_id}' not found for this client.",
            )

    # Resolve amount
    if req.amount is None:
        if not req.line_items:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Either `amount` or at least one `line_items` entry must be provided.",
            )
        gross = _compute_gross_total(req.line_items)
    else:
        gross = req.amount

    # Parse due_date
    due_date = None
    if req.due_date:
        from datetime import date
        due_date = date.fromisoformat(req.due_date)

    invoice = Invoice(
        client_id=req.client_id,
        project_id=req.project_id,
        reference=req.reference,
        amount=gross,
        currency=req.currency.upper(),
        status=req.status,
        due_date=due_date,
        payment_link=req.payment_link,
    )
    db.add(invoice)
    await db.flush()  # get invoice.id

    line_items_created: list[InvoiceLineItem] = []
    if req.line_items:
        for li_req in req.line_items:
            li = InvoiceLineItem(
                invoice_id=invoice.id,
                description=li_req.description,
                quantity=li_req.quantity,
                unit_price=li_req.unit_price,
                vat_rate=li_req.vat_rate,
                position=li_req.position,
            )
            db.add(li)
            line_items_created.append(li)

    await db.commit()
    await db.refresh(invoice)
    for li in line_items_created:
        await db.refresh(li)

    logger.info(
        "admin.invoice.created",
        invoice_id=invoice.id,
        client_id=req.client_id,
        reference=req.reference,
        amount=str(gross),
        line_items=len(line_items_created),
    )
    return _invoice_full_response(invoice, line_items_created)


@router.get(
    "/{invoice_id}",
    response_model=InvoiceAdminResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Get a portal invoice with its line items",
)
async def get_invoice(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
):
    invoice, lines = await _get_invoice_with_lines(invoice_id, db)
    return _invoice_full_response(invoice, lines)


@router.patch(
    "/{invoice_id}",
    response_model=InvoiceAdminResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Update portal invoice fields (reference, amount, currency, due_date, payment_link)",
)
async def patch_invoice(
    invoice_id: str,
    req: InvoicePatchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Partial update of invoice metadata.

    To change status use the mark-paid or cancel endpoints — those enforce
    valid status transitions and produce cleaner audit trails.
    """
    invoice, lines = await _get_invoice_with_lines(invoice_id, db)

    updates = req.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No fields provided for update.",
        )

    for field, value in updates.items():
        if field == "due_date" and value:
            from datetime import date
            value = date.fromisoformat(value)
        if field == "currency" and value:
            value = value.upper()
        setattr(invoice, field, value)

    await db.commit()
    await db.refresh(invoice)

    logger.info("admin.invoice.updated", invoice_id=invoice_id, fields=list(updates.keys()))
    return _invoice_full_response(invoice, lines)


@router.post(
    "/{invoice_id}/mark-paid",
    response_model=InvoiceAdminResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Mark a portal invoice as paid",
)
async def mark_invoice_paid(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Transition the invoice to `paid` status.
    Valid from: unpaid, sent, overdue.
    """
    invoice, lines = await _get_invoice_with_lines(invoice_id, db)

    if invoice.status == InvoiceStatus.paid.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invoice is already marked as paid.",
        )
    if invoice.status not in {s.value for s in _PAYABLE_STATUSES}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot mark invoice as paid from status '{invoice.status}'. "
                f"Valid from: {sorted(s.value for s in _PAYABLE_STATUSES)}."
            ),
        )

    invoice.status = InvoiceStatus.paid.value
    await db.commit()
    await db.refresh(invoice)

    logger.info("admin.invoice.marked_paid", invoice_id=invoice_id)
    return _invoice_full_response(invoice, lines)


@router.post(
    "/{invoice_id}/cancel",
    response_model=InvoiceAdminResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Cancel a portal invoice",
)
async def cancel_invoice(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Transition the invoice to `cancelled` status.
    Valid from: draft, unpaid, sent, overdue.
    Already-paid invoices cannot be cancelled here — raise a credit note instead.
    """
    invoice, lines = await _get_invoice_with_lines(invoice_id, db)

    if invoice.status == InvoiceStatus.cancelled.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invoice is already cancelled.",
        )
    if invoice.status not in {s.value for s in _CANCELLABLE_STATUSES}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot cancel invoice with status '{invoice.status}'. "
                f"Valid from: {sorted(s.value for s in _CANCELLABLE_STATUSES)}."
            ),
        )

    invoice.status = InvoiceStatus.cancelled.value
    await db.commit()
    await db.refresh(invoice)

    logger.info("admin.invoice.cancelled", invoice_id=invoice_id)
    return _invoice_full_response(invoice, lines)


# ── Line item endpoints ───────────────────────────────────────────────────────

@router.post(
    "/{invoice_id}/line-items",
    response_model=LineItemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key)],
    summary="Add a line item to a portal invoice",
)
async def add_line_item(
    invoice_id: str,
    req: LineItemRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Append a line item to an invoice.
    Blocked on paid or cancelled invoices.
    """
    inv_result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice: Invoice | None = inv_result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")

    if invoice.status not in {s.value for s in _MUTABLE_STATUSES}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot add line items to an invoice with status '{invoice.status}'.",
        )

    li = InvoiceLineItem(
        invoice_id=invoice_id,
        description=req.description,
        quantity=req.quantity,
        unit_price=req.unit_price,
        vat_rate=req.vat_rate,
        position=req.position,
    )
    db.add(li)
    await db.commit()
    await db.refresh(li)

    logger.info("admin.invoice.line_item_added", invoice_id=invoice_id, line_item_id=li.id)
    return _line_to_response(li)


@router.patch(
    "/{invoice_id}/line-items/{item_id}",
    response_model=LineItemResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Update a line item on a portal invoice",
)
async def patch_line_item(
    invoice_id: str,
    item_id: str,
    req: LineItemRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Replace all fields on a line item (full replacement, not sparse patch).
    Blocked on paid or cancelled invoices.
    """
    inv_result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice: Invoice | None = inv_result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")

    if invoice.status not in {s.value for s in _MUTABLE_STATUSES}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot modify line items on an invoice with status '{invoice.status}'.",
        )

    li_result = await db.execute(
        select(InvoiceLineItem).where(
            InvoiceLineItem.id == item_id,
            InvoiceLineItem.invoice_id == invoice_id,
        )
    )
    li: InvoiceLineItem | None = li_result.scalar_one_or_none()
    if li is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line item not found.")

    li.description = req.description
    li.quantity = req.quantity
    li.unit_price = req.unit_price
    li.vat_rate = req.vat_rate
    li.position = req.position

    await db.commit()
    await db.refresh(li)

    logger.info("admin.invoice.line_item_updated", invoice_id=invoice_id, line_item_id=item_id)
    return _line_to_response(li)


@router.delete(
    "/{invoice_id}/line-items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_api_key)],
    summary="Delete a line item from a portal invoice",
)
async def delete_line_item(
    invoice_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Remove a line item.  Blocked on paid or cancelled invoices.
    Returns 204 No Content on success.
    """
    inv_result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    invoice: Invoice | None = inv_result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")

    if invoice.status not in {s.value for s in _MUTABLE_STATUSES}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete line items from an invoice with status '{invoice.status}'.",
        )

    li_result = await db.execute(
        select(InvoiceLineItem).where(
            InvoiceLineItem.id == item_id,
            InvoiceLineItem.invoice_id == invoice_id,
        )
    )
    li: InvoiceLineItem | None = li_result.scalar_one_or_none()
    if li is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line item not found.")

    await db.delete(li)
    await db.commit()

    logger.info("admin.invoice.line_item_deleted", invoice_id=invoice_id, line_item_id=item_id)
