"""
app/services/stripe_consumer.py
────────────────────────────────
Stripe helpers for the consumer IT support pipeline.

Creates a Checkout Session (one-time, dynamic price) tied to an Atera
ticket so the user has a payment link ready after their remote session.

Pricing tiers (EUR — adjustable at call site):
  Quick Fix   ≤ 30 min  → €25
  Standard    ≤ 60 min  → €50  (default when duration unknown)
  Extended    > 60 min  → €75 / hr billed to nearest 30 min

The session is created for the Standard tier by default because we don't
know the actual duration at intake time.  Anthony can issue a partial
refund via the Stripe dashboard if the session runs short, or create a
second session for extended billing.

All Stripe API calls are blocking — we run them in a thread pool via
asyncio.to_thread to avoid blocking the event loop.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import stripe
import structlog

logger = structlog.get_logger(__name__)

# Tier definitions — amounts in EUR cents
TIER_QUICK    = ("Quick Fix (under 30 min)",   2_500)   # €25
TIER_STANDARD = ("Standard session (1 hr)",    5_000)   # €50   ← default
TIER_EXTENDED = ("Extended session (1+ hrs)",  7_500)   # €75 first hour


def _sync_create_checkout_session(
    api_key: str,
    amount_cents: int,
    description: str,
    customer_email: str,
    success_url: str,
    cancel_url: str,
    metadata: dict[str, Any],
) -> dict:
    stripe.api_key = api_key

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "eur",
                "unit_amount": amount_cents,
                "product_data": {"name": description},
            },
            "quantity": 1,
        }],
        customer_email=customer_email or None,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata,
        payment_method_types=["card"],
        # Maximum allowed by Stripe: 24 hours from creation
        expires_at=int(time.time()) + 86_400,
    )

    return {"url": session.url, "session_id": session.id}


async def create_consumer_checkout_session(
    api_key: str,
    amount_cents: int,
    description: str,
    customer_email: str,
    success_url: str,
    cancel_url: str,
    metadata: dict[str, Any] | None = None,
) -> dict:
    """
    Async wrapper around Stripe Checkout Session creation.

    Returns {"url": str, "session_id": str} on success.
    Raises StripeConsumerError on failure.
    """
    try:
        result = await asyncio.to_thread(
            _sync_create_checkout_session,
            api_key,
            amount_cents,
            description,
            customer_email,
            success_url,
            cancel_url,
            metadata or {},
        )
        logger.info(
            "stripe_consumer.session_created",
            session_id=result["session_id"],
            amount_cents=amount_cents,
            customer_email=customer_email,
        )
        return result
    except stripe.StripeError as exc:
        logger.error("stripe_consumer.stripe_error", error=str(exc))
        raise StripeConsumerError(str(exc)) from exc
    except Exception as exc:
        logger.error("stripe_consumer.unexpected_error", error=str(exc))
        raise StripeConsumerError(str(exc)) from exc


class StripeConsumerError(Exception):
    pass
