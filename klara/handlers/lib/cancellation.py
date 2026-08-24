"""
Cancellation intercept + save-flow library.

Customer-facing flow:
  1. From /portal/subscription, "Cancel my plan" button → /portal/cancel/{sub_id}
  2. Customer picks exit reason → save offer presented based on reason
  3. Three offers possible:
       - PAUSE 30 days  (stripe.Subscription.modify with pause_collection)
       - DISCOUNT 25% for 3 months (coupon applied)
       - CONFIRM CANCEL (sets cancel_at_period_end=True; access continues until renewal)
  4. Every interaction logged to klaravex_cancellation_attempts for analytics.

Webhook side:
  - customer.subscription.deleted → send exit survey email (in stripe_webhook.py).
"""

import logging
import os
from typing import Optional

import stripe

from .db import get_pool
from .email import send_email

log = logging.getLogger("klaravex.cancellation")

PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")
SUPPORT_EMAIL = os.environ.get("BILLING_SUPPORT_EMAIL", "support@klaravex.com")

# Map exit reason → recommended save offer
SAVE_OFFER_MAP = {
    "too_expensive": "discount_25pct",
    "not_using":     "pause_30d",
    "switching":     "discount_25pct",
    "quality":       "none",  # No discount can fix quality complaints — escalate to human
    "other":         "pause_30d",
}

REASON_LABELS = {
    "too_expensive": "It's too expensive",
    "not_using":     "I'm not using it enough",
    "switching":     "I'm switching to another provider",
    "quality":       "It didn't meet my expectations",
    "other":         "Other / something else",
}


async def log_attempt(
    *,
    subscription_id: str,
    customer_id: str,
    email: str,
    plan_name: Optional[str],
    reason_category: Optional[str] = None,
    reason_detail: Optional[str] = None,
    save_offer_shown: Optional[str] = None,
    save_offer_outcome: Optional[str] = None,
    final_outcome: str = "abandoned",
) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO klaravex_cancellation_attempts
                (stripe_subscription_id, stripe_customer_id, email, plan_name,
                 reason_category, reason_detail, save_offer_shown, save_offer_outcome,
                 final_outcome, resolved_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                    CASE WHEN $9 IN ('saved','cancelled') THEN now() ELSE NULL END)
            RETURNING id::text
            """,
            subscription_id, customer_id, email.lower(), plan_name,
            reason_category, reason_detail, save_offer_shown, save_offer_outcome,
            final_outcome,
        )


def offer_for_reason(reason_category: str) -> str:
    return SAVE_OFFER_MAP.get(reason_category, "pause_30d")


async def apply_pause_30d(subscription_id: str) -> dict[str, object]:
    """Pause subscription collection for 30 days. Access continues; no charge."""
    import time
    resumes_at = int(time.time()) + (30 * 86400)
    try:
        stripe.Subscription.modify(
            subscription_id,
            pause_collection={"behavior": "void", "resumes_at": resumes_at},
        )
        return {"ok": True, "resumes_at": resumes_at}
    except Exception as exc:
        log.exception("pause failed for %s: %s", subscription_id, exc)
        return {"ok": False, "error": str(exc)}


async def apply_discount_25pct(subscription_id: str, customer_id: str) -> dict[str, object]:
    """Apply a 25% off coupon for 3 months. Creates the coupon on first use, idempotent."""
    coupon_id = "klaravex-save-25-3mo"
    try:
        try:
            stripe.Coupon.retrieve(coupon_id)
        except Exception:
            stripe.Coupon.create(
                id=coupon_id,
                percent_off=25,
                duration="repeating",
                duration_in_months=3,
                name="Klaravex Stay Bonus: 25% off for 3 months",
            )
        stripe.Customer.modify(customer_id, coupon=coupon_id)
        return {"ok": True, "coupon": coupon_id}
    except Exception as exc:
        log.exception("discount apply failed for %s: %s", subscription_id, exc)
        return {"ok": False, "error": str(exc)}


async def confirm_cancel(subscription_id: str) -> dict[str, object]:
    """Mark subscription to cancel at period end. Access continues until renewal date."""
    try:
        sub = stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)
        return {"ok": True, "cancels_at": sub.get("cancel_at") or sub.get("current_period_end")}
    except Exception as exc:
        log.exception("cancel failed for %s: %s", subscription_id, exc)
        return {"ok": False, "error": str(exc)}


async def send_exit_survey(email: str, name: Optional[str], plan_name: Optional[str]) -> None:
    """Sent on customer.subscription.deleted from stripe_webhook."""
    greeting = f"Hi {name}," if name else "Hi there,"
    body = (
        f"{greeting}\n\n"
        f"Your Klaravex {plan_name or 'subscription'} has ended. We're sorry to see you go.\n\n"
        f"Would you mind taking 30 seconds to tell us why? Reply to this email with one word:\n\n"
        f"  • PRICE   — too expensive\n"
        f"  • USAGE   — didn't use it enough\n"
        f"  • SWITCH  — moved to another provider\n"
        f"  • QUALITY — didn't meet expectations\n"
        f"  • OTHER   — and a sentence on what happened\n\n"
        f"Your feedback directly shapes what we build next.\n\n"
        f"If something changes, we'd love to have you back at any time:\n"
        f"  {PORTAL_BASE_URL.rstrip('/')}/portal/subscription\n\n"
        f"— The Klaravex Team\n"
    )
    await send_email(to=email, subject="One quick question about your Klaravex experience", body=body)
