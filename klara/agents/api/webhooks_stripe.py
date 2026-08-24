"""
app/api/webhooks_stripe.py
──────────────────────────
Stripe webhook handler.

Security policy (docs/policies.md §3.3 and §12):
  - Signature is verified with stripe.Webhook.construct_event before any processing.
  - Payment state is NEVER updated from frontend redirects — only from verified webhook events.
  - Every webhook is logged to payment_events (INSERT-only) for audit.
  - Duplicate stripe_event_id is silently skipped (idempotency via unique constraint).
"""
import json
import structlog
import stripe
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import get_settings, Settings
from klara.rarv.runtime import get_db
from klara.rarv.payment import Payment, PaymentEvent, PaymentStatus
from klara.rarv.portal import Client, Invoice, InvoiceStatus
from klara.rarv.runtime.notifications import on_payment_succeeded

logger = structlog.get_logger(__name__)

router = APIRouter()

# Map Stripe event types to internal payment statuses
STATUS_MAP: dict[str, PaymentStatus] = {
    "checkout.session.completed":   PaymentStatus.succeeded,
    "checkout.session.expired":     PaymentStatus.cancelled,
    "payment_intent.succeeded":     PaymentStatus.succeeded,
    "payment_intent.payment_failed": PaymentStatus.failed,
    "charge.refunded":              PaymentStatus.refunded,
    "charge.dispute.created":       PaymentStatus.disputed,
}


@router.post("/stripe", status_code=200)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Receive and process Stripe webhook events.

    Security:
      - Signature verified via stripe.Webhook.construct_event before any DB work.
      - Returns 400 on invalid signature.
      - Duplicate events (same stripe_event_id) are silently ignored.
      - Every event is written to payment_events for audit trail.
    """
    body = await request.body()
    sig = request.headers.get("stripe-signature", "")

    # Graceful no-op when Stripe is not configured (dev / test environments)
    if not settings.stripe_configured:
        logger.info("stripe_webhook.not_configured_skipping")
        return {"received": True}

    # ── 1. Verify signature ───────────────────────────────────────────────────
    try:
        event = stripe.Webhook.construct_event(
            body, sig, settings.stripe_webhook_secret
        )
    except stripe.SignatureVerificationError:
        logger.warning("stripe_webhook.invalid_signature")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as exc:
        logger.error("stripe_webhook.construct_event_error", error=str(exc))
        raise HTTPException(status_code=400, detail="Malformed webhook payload")

    # ── 2. Extract key fields ─────────────────────────────────────────────────
    event_id = event["id"]
    event_type = event["type"]
    data_object = event["data"]["object"]

    # ── 3. Idempotency check ──────────────────────────────────────────────────
    existing = await db.execute(
        select(PaymentEvent).where(PaymentEvent.stripe_event_id == event_id)
    )
    if existing.scalar_one_or_none():
        logger.info("stripe_webhook.duplicate_skipped", event_id=event_id)
        return {"received": True}

    # ── 4. Locate the Payment record (may be None for unknown events) ─────────
    payment = None
    session_id = data_object.get("id") if event_type.startswith("checkout") else None
    payment_intent_id = data_object.get("payment_intent") or (
        data_object.get("id") if not event_type.startswith("checkout") else None
    )

    if session_id:
        result = await db.execute(
            select(Payment).where(Payment.stripe_session_id == session_id)
        )
        payment = result.scalar_one_or_none()

    if not payment and payment_intent_id:
        result = await db.execute(
            select(Payment).where(Payment.stripe_payment_intent_id == payment_intent_id)
        )
        payment = result.scalar_one_or_none()

    # ── 5. Determine new status ───────────────────────────────────────────────
    new_status: PaymentStatus | None = STATUS_MAP.get(event_type)

    # ── 6. Update payment and invoice if applicable ───────────────────────────
    if payment and new_status:
        payment.status = new_status.value

        # Backfill payment_intent_id from checkout.session.completed event
        if event_type == "checkout.session.completed":
            pi_id = data_object.get("payment_intent")
            if pi_id and not payment.stripe_payment_intent_id:
                payment.stripe_payment_intent_id = pi_id

        payment.updated_at = datetime.now(timezone.utc)

        # Mark the linked invoice as paid on successful payment
        if new_status == PaymentStatus.succeeded:
            inv_result = await db.execute(
                select(Invoice).where(Invoice.id == payment.invoice_id)
            )
            invoice = inv_result.scalar_one_or_none()
            if invoice:
                invoice.status = InvoiceStatus.paid
                # Look up the client to get their email for the receipt
                _client_result = await db.execute(
                    select(Client).where(Client.id == invoice.client_id)
                )
                _client = _client_result.scalar_one_or_none()
                if _client:
                    # Store on payment for use in the notification call after commit
                    payment._notify_client_email = _client.email
                    payment._notify_client_name = _client.name
                    payment._notify_invoice_ref = invoice.reference or invoice.id
                    payment._notify_amount = invoice.amount
                    payment._notify_currency = getattr(invoice, "currency", "EUR")

    # ── 7. Insert PaymentEvent audit record (INSERT-only) ─────────────────────
    event_row = PaymentEvent(
        id=str(uuid4()),
        payment_id=payment.id if payment else None,
        stripe_event_id=event_id,
        event_type=event_type,
        stripe_payload=body.decode(),
        new_status=new_status.value if new_status else None,
    )
    db.add(event_row)

    # phase16-005: emit a critical AuditLog row on succeeded/failed events so
    # the phase11-005 webhook bridge forwards them. Never blocks the
    # webhook response — wrap in try/except.
    if new_status in (PaymentStatus.succeeded, PaymentStatus.failed):
        try:
            from klara.rarv.audit import AuditLog as _AuditLog
            critical_type = (
                "stripe.payment.succeeded" if new_status == PaymentStatus.succeeded
                else "stripe.payment.failed"
            )
            db.add(_AuditLog(
                id=str(uuid4()),
                event_type=critical_type,
                action_name="stripe_webhook",
                details=json.dumps({
                    "stripe_event_type": event_type,
                    "stripe_event_id": event_id,
                    "payment_id": payment.id if payment else None,
                }),
            ))
        except Exception as exc:
            logger.warning(
                "stripe_webhook.audit_emit_failed",
                error=str(exc),
                event_id=event_id,
            )

    await db.commit()

    # ── 8. Log ────────────────────────────────────────────────────────────────
    logger.info(
        "stripe_webhook.processed",
        event_id=event_id,
        event_type=event_type,
        payment_id=payment.id if payment else None,
        new_status=new_status.value if new_status else None,
    )

    # ── 9. Transactional notification (non-critical — after commit) ───────────
    if payment and new_status == PaymentStatus.succeeded:
        client_email = getattr(payment, "_notify_client_email", None)
        if client_email:
            await on_payment_succeeded(
                settings,
                client_email=client_email,
                client_name=getattr(payment, "_notify_client_name", None),
                invoice_reference=getattr(payment, "_notify_invoice_ref", "N/A"),
                amount=getattr(payment, "_notify_amount", 0.0),
                currency=getattr(payment, "_notify_currency", "EUR"),
            )

    # ── 10. Consumer callback — fire outbound Vapi call after payment ─────────
    # Only for checkout.session.completed events tagged source=consumer_pipeline
    # that include a phone number in Stripe metadata.
    if (
        event_type == "checkout.session.completed"
        and new_status == PaymentStatus.succeeded
        and data_object.get("metadata", {}).get("source") == "consumer_pipeline"
    ):
        meta = data_object.get("metadata", {})
        customer_phone = meta.get("customer_phone", "")
        if customer_phone:
            _vapi_key = getattr(settings, "vapi_api_key", "")
            _phone_id = getattr(settings, "vapi_phone_number_id", "")
            _assistant_id = getattr(settings, "vapi_troubleshoot_assistant_id", "")
            if _vapi_key and _phone_id and _assistant_id:
                try:
                    from klara.rarv.runtime.vapi_outbound import place_consumer_callback
                    await place_consumer_callback(
                        api_key=_vapi_key,
                        phone_number_id=_phone_id,
                        troubleshoot_assistant_id=_assistant_id,
                        customer_phone=customer_phone,
                        customer_name=meta.get("customer_name", ""),
                        device=meta.get("device", ""),
                        problem=meta.get("problem", ""),
                        ticket_number=meta.get("ticket_number", ""),
                    )
                except Exception as exc:
                    logger.warning(
                        "stripe_webhook.consumer_callback_failed",
                        error=str(exc),
                        ticket_number=meta.get("ticket_number"),
                    )
            else:
                logger.info(
                    "stripe_webhook.consumer_callback_skipped",
                    reason="vapi not configured",
                )
        else:
            logger.info(
                "stripe_webhook.consumer_callback_skipped",
                reason="no phone number in metadata",
                ticket_number=meta.get("ticket_number"),
            )

    return {"received": True}
