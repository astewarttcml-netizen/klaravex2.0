"""
app/api/invoices_admin.py
──────────────────────────
Admin CRUD endpoints for loki_invoices.

All endpoints require X-API-Key (managed via verify_api_key).
Registered at /api/v1/admin/invoices in main.py.

Endpoints
─────────
GET    /                          — list invoices (filter: status, lead_id, overdue)
GET    /{invoice_id}              — single invoice detail
POST   /                          — create invoice
PATCH  /{invoice_id}              — update editable fields
POST   /{invoice_id}/mark-paid    — convenience: status → paid
POST   /{invoice_id}/cancel       — soft-delete: status → cancelled

Design notes:
  - amount_eur, due_date, invoice_ref are editable only while status is
    draft or sent (not after reminder has been queued or payment received)
  - status transitions are enforced: only valid forward moves are accepted
  - lead_id is immutable after creation
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, condecimal
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.database import get_db
from app.models.invoice import Invoice, InvoiceStatus
from app.models.lead import Lead

logger = structlog.get_logger(__name__)

router = APIRouter()

# ── Valid forward status transitions ─────────────────────────────────────────
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    InvoiceStatus.draft:     {InvoiceStatus.sent, InvoiceStatus.cancelled},
    InvoiceStatus.sent:      {InvoiceStatus.unpaid, InvoiceStatus.paid, InvoiceStatus.cancelled},
    InvoiceStatus.unpaid:    {InvoiceStatus.reminded, InvoiceStatus.paid, InvoiceStatus.cancelled},
    InvoiceStatus.reminded:  {InvoiceStatus.paid, InvoiceStatus.cancelled},
    InvoiceStatus.paid:      set(),   # terminal
    InvoiceStatus.cancelled: set(),   # terminal
}

# Statuses that are still editable (can change amount/date/ref)
_EDITABLE_STATUSES = {InvoiceStatus.draft, InvoiceStatus.sent}


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class InvoiceCreate(BaseModel):
    lead_id: str = Field(..., description="UUID of the associated lead")
    invoice_ref: str = Field(..., min_length=1, max_length=100, description="e.g. INV-2026-001")
    amount_eur: Decimal = Field(..., gt=0, description="Invoice amount in EUR")
    description: Optional[str] = Field(None, max_length=500)
    issue_date: Optional[date] = None
    due_date: date = Field(..., description="Payment due date (ISO)")
    status: InvoiceStatus = Field(InvoiceStatus.sent, description="Initial status (default: sent)")
    notes: Optional[str] = Field(None, description="Internal notes (not sent to client)")


class InvoiceUpdate(BaseModel):
    invoice_ref: Optional[str] = Field(None, min_length=1, max_length=100)
    amount_eur: Optional[Decimal] = Field(None, gt=0)
    description: Optional[str] = Field(None, max_length=500)
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    status: Optional[InvoiceStatus] = None
    notes: Optional[str] = None


class InvoiceOut(BaseModel):
    id: str
    lead_id: str
    lead_name: Optional[str]
    lead_email: Optional[str]
    invoice_ref: str
    amount_eur: Decimal
    description: Optional[str]
    issue_date: Optional[date]
    due_date: date
    status: str
    reminder_sent_at: Optional[datetime]
    reminder_count: int
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    days_overdue: Optional[int]

    class Config:
        from_attributes = True


def _to_out(inv: Invoice, lead: Optional[Lead]) -> InvoiceOut:
    today = date.today()
    overdue = None
    if inv.due_date < today and inv.status not in (
        InvoiceStatus.paid, InvoiceStatus.cancelled
    ):
        overdue = (today - inv.due_date).days

    return InvoiceOut(
        id=inv.id,
        lead_id=inv.lead_id,
        lead_name=lead.name if lead else None,
        lead_email=lead.email if lead else None,
        invoice_ref=inv.invoice_ref,
        amount_eur=inv.amount_eur,
        description=inv.description,
        issue_date=inv.issue_date,
        due_date=inv.due_date,
        status=inv.status,
        reminder_sent_at=inv.reminder_sent_at,
        reminder_count=inv.reminder_count,
        notes=inv.notes,
        created_at=inv.created_at,
        updated_at=inv.updated_at,
        days_overdue=overdue,
    )


# ── Helper: load invoice or 404 ───────────────────────────────────────────────

async def _get_invoice(invoice_id: str, db: AsyncSession) -> Invoice:
    row = (await db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return row


async def _get_lead(lead_id: str, db: AsyncSession) -> Optional[Lead]:
    return (await db.execute(
        select(Lead).where(Lead.id == lead_id)
    )).scalar_one_or_none()


# ── 1. List invoices ──────────────────────────────────────────────────────────

@router.get(
    "/",
    dependencies=[Depends(verify_api_key)],
    response_model=List[InvoiceOut],
    summary="List invoices",
)
async def list_invoices(
    lead_id: Optional[str] = Query(None, description="Filter by lead UUID"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    overdue_only: bool = Query(False, description="Only show overdue, unpaid invoices"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    List all invoices, newest first.

    Filters:
      lead_id      — restrict to one lead
      status       — draft | sent | unpaid | reminded | paid | cancelled
      overdue_only — due_date < today AND status NOT IN (paid, cancelled)
    """
    q = select(Invoice)
    conditions = []

    if lead_id:
        conditions.append(Invoice.lead_id == lead_id)

    if status_filter:
        try:
            s = InvoiceStatus(status_filter)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status '{status_filter}'. "
                       f"Valid: {[e.value for e in InvoiceStatus]}",
            )
        conditions.append(Invoice.status == s)

    if overdue_only:
        today = date.today()
        conditions.append(Invoice.due_date < today)
        conditions.append(Invoice.status.notin_([InvoiceStatus.paid, InvoiceStatus.cancelled]))

    if conditions:
        q = q.where(and_(*conditions))

    q = q.order_by(Invoice.due_date.desc()).limit(limit).offset(offset)
    invoices = (await db.execute(q)).scalars().all()

    # Batch-load leads for display
    lead_ids = list({inv.lead_id for inv in invoices})
    leads_map: dict[str, Lead] = {}
    if lead_ids:
        leads_result = await db.execute(select(Lead).where(Lead.id.in_(lead_ids)))
        for lead in leads_result.scalars().all():
            leads_map[lead.id] = lead

    return [_to_out(inv, leads_map.get(inv.lead_id)) for inv in invoices]


# ── 2. Get single invoice ─────────────────────────────────────────────────────

@router.get(
    "/{invoice_id}",
    dependencies=[Depends(verify_api_key)],
    response_model=InvoiceOut,
    summary="Get invoice detail",
)
async def get_invoice(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
):
    inv = await _get_invoice(invoice_id, db)
    lead = await _get_lead(inv.lead_id, db)
    return _to_out(inv, lead)


# ── 3. Create invoice ─────────────────────────────────────────────────────────

@router.post(
    "/",
    dependencies=[Depends(verify_api_key)],
    response_model=InvoiceOut,
    status_code=201,
    summary="Create a new invoice",
)
async def create_invoice(
    body: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new invoice linked to a lead.

    The lead must exist and must not be anonymised.
    invoice_ref must be unique per lead (enforced at DB level via index;
    duplicates will surface as a 409 here).
    """
    # Verify lead
    lead = await _get_lead(body.lead_id, db)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")
    if lead.status == "anonymised":
        raise HTTPException(
            status_code=422,
            detail="Cannot create invoice for anonymised lead.",
        )

    # Check for duplicate invoice_ref on this lead
    existing = (await db.execute(
        select(Invoice).where(
            Invoice.lead_id == body.lead_id,
            Invoice.invoice_ref == body.invoice_ref,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Invoice ref '{body.invoice_ref}' already exists for this lead.",
        )

    inv = Invoice(
        id=str(uuid.uuid4()),
        lead_id=body.lead_id,
        invoice_ref=body.invoice_ref,
        amount_eur=body.amount_eur,
        description=body.description,
        issue_date=body.issue_date,
        due_date=body.due_date,
        status=body.status,
        notes=body.notes,
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)

    logger.info(
        "invoice.created",
        invoice_id=inv.id,
        invoice_ref=inv.invoice_ref,
        lead_id=inv.lead_id,
        amount_eur=str(inv.amount_eur),
    )
    return _to_out(inv, lead)


# ── 4. Update invoice ─────────────────────────────────────────────────────────

@router.patch(
    "/{invoice_id}",
    dependencies=[Depends(verify_api_key)],
    response_model=InvoiceOut,
    summary="Update invoice fields",
)
async def update_invoice(
    invoice_id: str,
    body: InvoiceUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update editable invoice fields.

    Rules:
    - invoice_ref, amount_eur, due_date, issue_date are only editable
      while status is 'draft' or 'sent'.
    - Status transitions are validated (only forward moves allowed).
    - notes is always editable.
    - lead_id is immutable.
    """
    inv = await _get_invoice(invoice_id, db)
    lead = await _get_lead(inv.lead_id, db)

    # -- Status transition validation
    if body.status is not None and body.status != inv.status:
        allowed = _ALLOWED_TRANSITIONS.get(inv.status, set())
        if body.status not in allowed:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Cannot transition from '{inv.status}' to '{body.status}'. "
                    f"Allowed: {sorted(allowed) or 'none (terminal state)'}."
                ),
            )
        inv.status = body.status

    # -- Fields gated on editable status
    current_status = inv.status  # already updated above if changed
    is_editable = current_status in _EDITABLE_STATUSES

    if body.invoice_ref is not None:
        if not is_editable:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot change invoice_ref when status is '{current_status}'.",
            )
        inv.invoice_ref = body.invoice_ref

    if body.amount_eur is not None:
        if not is_editable:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot change amount_eur when status is '{current_status}'.",
            )
        inv.amount_eur = body.amount_eur

    if body.due_date is not None:
        if not is_editable:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot change due_date when status is '{current_status}'.",
            )
        inv.due_date = body.due_date

    if body.issue_date is not None:
        if not is_editable:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot change issue_date when status is '{current_status}'.",
            )
        inv.issue_date = body.issue_date

    if body.description is not None:
        inv.description = body.description

    # notes: always editable
    if body.notes is not None:
        inv.notes = body.notes

    inv.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(inv)

    logger.info(
        "invoice.updated",
        invoice_id=inv.id,
        invoice_ref=inv.invoice_ref,
        status=inv.status,
    )
    return _to_out(inv, lead)


# ── 5. Mark paid ──────────────────────────────────────────────────────────────

@router.post(
    "/{invoice_id}/mark-paid",
    dependencies=[Depends(verify_api_key)],
    response_model=InvoiceOut,
    summary="Mark invoice as paid",
)
async def mark_paid(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Convenience endpoint — transitions invoice to 'paid'.
    Valid from: sent, unpaid, reminded.
    Idempotent if already paid.
    """
    inv = await _get_invoice(invoice_id, db)
    lead = await _get_lead(inv.lead_id, db)

    if inv.status == InvoiceStatus.paid:
        return _to_out(inv, lead)  # idempotent

    if inv.status == InvoiceStatus.cancelled:
        raise HTTPException(
            status_code=422,
            detail="Cannot mark a cancelled invoice as paid.",
        )

    inv.status = InvoiceStatus.paid
    inv.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(inv)

    logger.info(
        "invoice.marked_paid",
        invoice_id=inv.id,
        invoice_ref=inv.invoice_ref,
        lead_id=inv.lead_id,
    )
    return _to_out(inv, lead)


# ── 6. Cancel invoice ─────────────────────────────────────────────────────────

@router.post(
    "/{invoice_id}/cancel",
    dependencies=[Depends(verify_api_key)],
    response_model=InvoiceOut,
    summary="Cancel (void) an invoice",
)
async def cancel_invoice(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Mark invoice as cancelled (soft delete / void).
    Valid from any non-terminal status.
    Idempotent if already cancelled.
    Cannot cancel a paid invoice.
    """
    inv = await _get_invoice(invoice_id, db)
    lead = await _get_lead(inv.lead_id, db)

    if inv.status == InvoiceStatus.cancelled:
        return _to_out(inv, lead)  # idempotent

    if inv.status == InvoiceStatus.paid:
        raise HTTPException(
            status_code=422,
            detail="Cannot cancel a paid invoice. Create a credit note instead.",
        )

    inv.status = InvoiceStatus.cancelled
    inv.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(inv)

    logger.info(
        "invoice.cancelled",
        invoice_id=inv.id,
        invoice_ref=inv.invoice_ref,
        lead_id=inv.lead_id,
    )
    return _to_out(inv, lead)
