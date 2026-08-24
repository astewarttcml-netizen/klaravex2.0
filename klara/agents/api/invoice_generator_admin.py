"""
app/api/invoice_generator_admin.py
────────────────────────────────────
Admin endpoints for Klara AI-generated PDF invoices (generated_invoices table).

Registered at /api/v1/admin/generated-invoices in main.py.
All endpoints require X-API-Key via verify_api_key.

This is SEPARATE from /api/v1/admin/invoices (invoices_admin.py),
which manages externally-issued loki_invoices for payment reminders.

Endpoints
─────────
POST   /generate              — run InvoiceGeneratorAgent → queues P3 approval
GET    /                      — list generated invoices (filters: status, email)
GET    /{invoice_id}          — single invoice detail
PATCH  /{invoice_id}          — update notes (draft only)
POST   /{invoice_id}/mark-paid   — status → paid
POST   /{invoice_id}/cancel      — status → cancelled
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import AgentContext
from app.agents.registry import registry
from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.generated_invoice import GeneratedInvoice, GeneratedInvoiceStatus

logger = structlog.get_logger(__name__)
router = APIRouter(dependencies=[Depends(verify_api_key)])


# ──────────────────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────────────────

class GenerateInvoiceRequest(BaseModel):
    lead_id:             Optional[str]  = None
    client_name:         str            = Field(..., min_length=1, max_length=255)
    client_email:        str            = Field(..., min_length=5, max_length=255)
    client_address:      Optional[str]  = None
    client_company:      Optional[str]  = None
    service_description: str            = Field(..., min_length=1)
    amount_net:          float          = Field(..., gt=0)
    vat_rate:            float          = Field(default=0.0, ge=0, le=100)
    due_days:            int            = Field(default=14, ge=1, le=365)
    currency:            str            = Field(default="EUR", min_length=3, max_length=3)
    notes:               Optional[str]  = None

    @validator("client_email")
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v:
            raise ValueError("Invalid email address")
        return v

    @validator("currency")
    def validate_currency(cls, v: str) -> str:
        return v.upper()


class PatchInvoiceRequest(BaseModel):
    notes: Optional[str] = None


class InvoiceResponse(BaseModel):
    id:                  str
    lead_id:             Optional[str]
    invoice_number:      str
    client_name:         str
    client_email:        str
    client_address:      Optional[str]
    client_company:      Optional[str]
    service_description: str
    amount_net:          float
    vat_rate:            float
    vat_amount:          float
    amount_gross:        float
    currency:            str
    issued_date:         str
    due_date:            str
    pdf_path:            Optional[str]
    status:              str
    approval_id:         Optional[str]
    sent_at:             Optional[str]
    paid_at:             Optional[str]
    notes:               Optional[str]
    created_at:          str
    updated_at:          str

    class Config:
        from_attributes = True


def _to_response(inv: GeneratedInvoice) -> InvoiceResponse:
    return InvoiceResponse(
        id=inv.id,
        lead_id=inv.lead_id,
        invoice_number=inv.invoice_number,
        client_name=inv.client_name,
        client_email=inv.client_email,
        client_address=inv.client_address,
        client_company=inv.client_company,
        service_description=inv.service_description,
        amount_net=float(inv.amount_net),
        vat_rate=float(inv.vat_rate),
        vat_amount=float(inv.vat_amount),
        amount_gross=float(inv.amount_gross),
        currency=inv.currency,
        issued_date=str(inv.issued_date),
        due_date=str(inv.due_date),
        pdf_path=inv.pdf_path,
        status=inv.status,
        approval_id=inv.approval_id,
        sent_at=inv.sent_at.isoformat() if inv.sent_at else None,
        paid_at=inv.paid_at.isoformat() if inv.paid_at else None,
        notes=inv.notes,
        created_at=inv.created_at.isoformat(),
        updated_at=inv.updated_at.isoformat(),
    )


# ──────────────────────────────────────────────────────────────────────────────
# POST /generate
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_invoice(
    body: GenerateInvoiceRequest,
    db:   AsyncSession = Depends(get_db),
):
    """
    Run InvoiceGeneratorAgent to create a PDF invoice and queue it for
    P3 approval before sending to the client.

    Returns 202 Accepted with the approval_id.  The invoice is status=draft
    until Anthony approves the send action.
    """
    from klara.rarv.runtime import get_settings

    settings = get_settings()
    context  = AgentContext(
        db=db,
        settings=settings,
        lead_id=body.lead_id,
        conversation_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
    )

    agent  = registry.get("invoice_generator")
    result = await agent(context, body.dict())

    if result.approval_required:
        return {
            "status":      "pending_approval",
            "approval_id": result.approval_id,
            "message":     (
                f"Invoice queued for approval. "
                f"Approve at POST /api/v1/approvals/{result.approval_id}/approve"
            ),
        }

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error or "Invoice generation failed",
        )

    return result.output


# ──────────────────────────────────────────────────────────────────────────────
# GET /
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[InvoiceResponse])
async def list_generated_invoices(
    invoice_status: Optional[str]  = Query(None, alias="status"),
    client_email:   Optional[str]  = Query(None),
    limit:          int            = Query(50, ge=1, le=200),
    offset:         int            = Query(0, ge=0),
    db:             AsyncSession   = Depends(get_db),
):
    """List generated invoices with optional status and email filters."""
    q = select(GeneratedInvoice).order_by(GeneratedInvoice.created_at.desc())

    if invoice_status:
        q = q.where(GeneratedInvoice.status == invoice_status)
    if client_email:
        q = q.where(GeneratedInvoice.client_email == client_email.strip().lower())

    q = q.offset(offset).limit(limit)
    result = await db.execute(q)
    return [_to_response(inv) for inv in result.scalars().all()]


# ──────────────────────────────────────────────────────────────────────────────
# GET /{invoice_id}
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_generated_invoice(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(GeneratedInvoice).where(GeneratedInvoice.id == invoice_id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return _to_response(inv)


# ──────────────────────────────────────────────────────────────────────────────
# PATCH /{invoice_id}
# ──────────────────────────────────────────────────────────────────────────────

@router.patch("/{invoice_id}", response_model=InvoiceResponse)
async def patch_generated_invoice(
    invoice_id: str,
    body: PatchInvoiceRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update mutable fields (notes only) while invoice is in draft state."""
    result = await db.execute(
        select(GeneratedInvoice).where(GeneratedInvoice.id == invoice_id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if inv.status not in (
        GeneratedInvoiceStatus.draft, GeneratedInvoiceStatus.approved
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot edit invoice in status '{inv.status}'",
        )

    if body.notes is not None:
        inv.notes = body.notes

    await db.flush()
    return _to_response(inv)


# ──────────────────────────────────────────────────────────────────────────────
# POST /{invoice_id}/mark-paid
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/{invoice_id}/mark-paid", response_model=InvoiceResponse)
async def mark_paid(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Transition a sent invoice to paid status and stamp paid_at."""
    result = await db.execute(
        select(GeneratedInvoice).where(GeneratedInvoice.id == invoice_id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    allowed = (GeneratedInvoiceStatus.sent, GeneratedInvoiceStatus.approved)
    if inv.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot mark as paid from status '{inv.status}'",
        )

    inv.status  = GeneratedInvoiceStatus.paid
    inv.paid_at = datetime.now(tz=timezone.utc)
    await db.flush()

    logger.info("invoice_generator_admin.marked_paid", invoice_id=invoice_id,
                invoice_number=inv.invoice_number)
    return _to_response(inv)


# ──────────────────────────────────────────────────────────────────────────────
# POST /{invoice_id}/cancel
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/{invoice_id}/cancel", response_model=InvoiceResponse)
async def cancel_invoice(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Cancel (void) an invoice. Not reversible."""
    result = await db.execute(
        select(GeneratedInvoice).where(GeneratedInvoice.id == invoice_id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if inv.status == GeneratedInvoiceStatus.paid:
        raise HTTPException(
            status_code=409,
            detail="Cannot cancel a paid invoice. Create a credit note instead.",
        )
    if inv.status == GeneratedInvoiceStatus.cancelled:
        raise HTTPException(status_code=409, detail="Invoice is already cancelled")

    inv.status = GeneratedInvoiceStatus.cancelled
    await db.flush()

    logger.info("invoice_generator_admin.cancelled", invoice_id=invoice_id,
                invoice_number=inv.invoice_number)
    return _to_response(inv)
