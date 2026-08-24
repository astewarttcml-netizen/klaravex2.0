"""
app/api/portal/payments.py
──────────────────────────
Stripe checkout-session endpoint for the client portal.

Route:  POST /api/v1/portal/invoices/{invoice_id}/checkout
Auth:   portal JWT (get_current_portal_client)
"""
from __future__ import annotations

import structlog
import stripe

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.portal_auth import get_current_portal_client
from app.database import get_db
from app.models.payment import Payment
from app.models.portal import Client, Invoice, InvoiceStatus

logger = structlog.get_logger(__name__)

router = APIRouter()

# Statuses that allow a new checkout session to be created
PAYABLE_STATUSES = {InvoiceStatus.sent, InvoiceStatus.unpaid, InvoiceStatus.overdue}


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str
    invoice_id: str


@router.post(
    "/{invoice_id}/checkout",
    response_model=CheckoutResponse,
    summary="Create Stripe checkout session for an invoice",
)
async def create_checkout_session(
    invoice_id: str,
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CheckoutResponse:
    """
    Create (or re-use) a Stripe Checkout Session for the given invoice.

    - 404 if invoice not found or belongs to another client
    - 400 if invoice status is not payable (draft / paid / cancelled)
    - 503 if Stripe is not configured in settings
    - 502 on Stripe API errors
    """
    # ── 1. Load invoice and verify ownership ──────────────────────────────
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.client_id == client.id)
    )
    invoice: Invoice | None = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")

    # ── 2. Payability check ───────────────────────────────────────────────
    if invoice.status not in {s.value for s in PAYABLE_STATUSES}:
        raise HTTPException(
            status_code=400,
            detail=f"Invoice cannot be paid (current status: {invoice.status}).",
        )

    # ── 3. Stripe configured check ────────────────────────────────────────
    if not settings.stripe_configured:
        raise HTTPException(
            status_code=503,
            detail="Payment processing is not configured. Please contact support.",
        )

    # ── 4. Create Stripe Checkout Session ─────────────────────────────────
    # Inject the real invoice_id into the success/cancel URL templates so the
    # portal can re-fetch the authoritative payment status on return.
    success_url = settings.stripe_success_url.replace("{INVOICE_ID}", str(invoice.id))
    cancel_url = settings.stripe_cancel_url.replace("{INVOICE_ID}", str(invoice.id))

    try:
        sc = stripe.StripeClient(settings.stripe_secret_key)
        session = sc.checkout.sessions.create(
            params={
                "mode": "payment",
                "line_items": [
                    {
                        "price_data": {
                            "currency": invoice.currency.lower(),
                            "unit_amount": int(invoice.amount * 100),
                            "product_data": {"name": f"Invoice {invoice.reference}"},
                        },
                        "quantity": 1,
                    }
                ],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "customer_email": client.email,
                "metadata": {
                    "invoice_id": str(invoice.id),
                    "client_id": str(client.id),
                    "reference": invoice.reference,
                },
            }
        )
    except stripe.StripeError as exc:
        logger.error(
            "portal.checkout_stripe_error",
            invoice_id=invoice_id,
            client_id=client.id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Payment provider error: {exc.user_message}",
        )

    # ── 5. Upsert Payment row ─────────────────────────────────────────────
    # Retries are allowed: a fresh Checkout Session may be created after a
    # cancelled/failed/expired prior attempt. We update the existing pending
    # row in-place so its Payment.id is reused by the upcoming webhook;
    # otherwise we always create a fresh pending row to track the new session.
    existing_result = await db.execute(
        select(Payment)
        .where(Payment.invoice_id == invoice_id)
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    existing: Payment | None = existing_result.scalar_one_or_none()
    if existing is not None and existing.status == "pending":
        existing.stripe_session_id = session.id
    else:
        payment = Payment(
            invoice_id=invoice_id,
            client_id=client.id,
            stripe_session_id=session.id,
            amount=invoice.amount,
            currency=invoice.currency,
            status="pending",
        )
        db.add(payment)
    await db.commit()

    # ── 6. Log & return ───────────────────────────────────────────────────
    logger.info(
        "portal.checkout_created",
        invoice_id=invoice_id,
        client_id=client.id,
        session_id=session.id,
    )
    return CheckoutResponse(
        checkout_url=session.url,
        session_id=session.id,
        invoice_id=invoice_id,
    )


@router.get("/{invoice_id}/status", summary="Get payment status for invoice")
async def get_payment_status(
    invoice_id: str,
    client: Client = Depends(get_current_portal_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the current payment status for an invoice.

    Called by the portal frontend after returning from Stripe to get
    the authoritative backend state. The frontend MUST NOT trust URL
    params (?payment=success) — it must call this endpoint.

    Returns 404 if no payment record exists yet for this invoice
    (checkout session not yet created or webhook not yet processed).
    """
    # Ownership check — ensure invoice belongs to this client
    invoice_result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.client_id == client.id,
        )
    )
    invoice = invoice_result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")

    # Get most recent payment for this invoice
    payment_result = await db.execute(
        select(Payment)
        .where(Payment.invoice_id == invoice_id)
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    payment = payment_result.scalar_one_or_none()

    if payment is None:
        return {
            "invoice_id": invoice_id,
            "invoice_status": invoice.status,
            "payment_status": None,
            "message": "No payment initiated yet.",
        }

    return {
        "invoice_id": invoice_id,
        "invoice_status": invoice.status,
        "payment_status": payment.status,
        "stripe_session_id": payment.stripe_session_id,
        "updated_at": payment.updated_at.isoformat(),
    }
