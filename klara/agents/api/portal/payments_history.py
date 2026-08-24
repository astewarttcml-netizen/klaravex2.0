"""
app/api/portal/payments_history.py
──────────────────────────────────
Recent payments listing for the client portal (portal-223).

Route:  GET /api/v1/portal/payments/recent
Auth:   portal JWT (get_current_portal_client)

Returns the authenticated client's most recent successful payments joined
with their parent invoice for display context. Only Payment rows whose
status was set to `succeeded` by a verified Stripe webhook event are
returned (per docs/policies.md §3.3 — payment truth derives only from
verified webhook events).

Ordering: most recently updated payment first (Payment.updated_at desc).
The frontend renders this as a "Recent Payments" section on the portal
dashboard / invoices page.
"""
from __future__ import annotations

from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.portal_auth import get_current_portal_client
from app.database import get_db
from app.models.payment import Payment, PaymentStatus
from app.models.portal import Client, Invoice

logger = structlog.get_logger(__name__)
router = APIRouter()


class RecentPaymentItem(BaseModel):
    """One row in the recent payments listing."""
    id: str
    invoice_id: str
    invoice_reference: str
    project_id: Optional[str]
    amount: str            # serialised Decimal as string to preserve precision
    currency: str
    status: str            # always "succeeded" for this endpoint
    paid_at: str           # Payment.updated_at ISO-8601


@router.get(
    "/recent",
    response_model=List[RecentPaymentItem],
    summary="List recent successful payments for the authenticated client",
)
async def list_recent_payments(
    limit: int = Query(10, ge=1, le=50),
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
) -> List[RecentPaymentItem]:
    """
    Return the authenticated client's recent successful payments.

    - Scoped by client_id (no cross-client access).
    - Filters strictly to status=succeeded; pending / failed / refunded /
      disputed / cancelled payments are excluded so the section only shows
      what the client has actually paid.
    - Joined with Invoice for reference + project_id.
    - Ordered newest-paid first (Payment.updated_at desc).
    - `limit` clamped to [1, 50]; default 10.
    """
    rows = await db.execute(
        select(Payment, Invoice)
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .where(
            Payment.client_id == client.id,
            Payment.status == PaymentStatus.succeeded.value,
        )
        .order_by(Payment.updated_at.desc())
        .limit(limit)
    )

    items: List[RecentPaymentItem] = []
    for payment, invoice in rows.all():
        items.append(
            RecentPaymentItem(
                id=payment.id,
                invoice_id=payment.invoice_id,
                invoice_reference=invoice.reference,
                project_id=invoice.project_id,
                amount=str(payment.amount),
                currency=payment.currency,
                status=payment.status,
                paid_at=payment.updated_at.isoformat(),
            )
        )

    logger.info(
        "portal.recent_payments_listed",
        client_id=client.id,
        count=len(items),
        limit=limit,
    )
    return items
