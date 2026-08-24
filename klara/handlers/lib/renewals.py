"""
Renewal reminder dispatch.

Sends 30/7/1-day pre-renewal email reminders. Idempotent via
klaravex_renewal_reminders unique constraint on (subscription, kind, renewal_at).

Trigger sources:
  - Stripe webhook `invoice.upcoming` (fires 7 days before by default) → dispatches the 7-day reminder
  - Daily cron scan_renewals() → finds 30-day-out and 1-day-out subscriptions
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import stripe

from .db import get_pool
from .email import send_email

log = logging.getLogger("klaravex.renewals")

PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")
BILLING_SUPPORT_EMAIL = os.environ.get("BILLING_SUPPORT_EMAIL", "support@klaravex.com")


REMINDER_COPY = {
    "renewal_30d": {
        "subject_tpl": "Your Klaravex {plan} renews in 30 days",
        "intro": "Just a heads-up: your subscription renews in about 30 days.",
        "cta": "Plenty of time to review or make changes.",
    },
    "renewal_7d": {
        "subject_tpl": "Reminder: Klaravex {plan} renews in a week",
        "intro": "Your subscription is set to renew next week.",
        "cta": "If you want to switch tiers, pause, or update your payment method, do it before then.",
    },
    "renewal_1d": {
        "subject_tpl": "Heads-up: Klaravex {plan} renews tomorrow",
        "intro": "Your subscription renews tomorrow.",
        "cta": "Your card on file will be charged automatically. Reach out if you need anything to change.",
    },
}


async def _already_sent(subscription_id: str, kind: str, renewal_at: datetime) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchval(
            """
            SELECT 1 FROM klaravex_renewal_reminders
             WHERE stripe_subscription_id = $1 AND reminder_kind = $2 AND renewal_at = $3
            """,
            subscription_id, kind, renewal_at,
        )
    return bool(row)


async def _record_sent(
    *,
    subscription_id: str,
    customer_id: str,
    email: str,
    kind: str,
    renewal_at: datetime,
    metadata: Optional[dict] = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO klaravex_renewal_reminders
                (stripe_subscription_id, stripe_customer_id, email, reminder_kind, renewal_at, metadata)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            ON CONFLICT (stripe_subscription_id, reminder_kind, renewal_at) DO NOTHING
            """,
            subscription_id, customer_id, email.lower(), kind, renewal_at,
            __import__("json").dumps(metadata or {}),
        )


async def send_renewal_reminder(
    *,
    subscription_id: str,
    customer_id: str,
    email: str,
    name: Optional[str],
    plan_name: str,
    amount_display: str,
    interval_display: str,
    kind: str,
    renewal_at: datetime,
) -> dict[str, object]:
    """Send a single reminder; idempotent across calls."""
    if kind not in REMINDER_COPY:
        return {"sent": False, "reason": f"unknown_kind:{kind}"}
    if not email or "@" not in email:
        return {"sent": False, "reason": "invalid_email"}
    if await _already_sent(subscription_id, kind, renewal_at):
        return {"sent": False, "reason": "already_sent"}

    copy = REMINDER_COPY[kind]
    greeting = f"Hi {name}," if name else "Hi there,"
    renewal_str = renewal_at.strftime("%B %-d, %Y")
    subject = copy["subject_tpl"].format(plan=plan_name)
    body = (
        f"{greeting}\n\n"
        f"{copy['intro']}\n\n"
        f"  Plan:          {plan_name}\n"
        f"  Renewal date:  {renewal_str}\n"
        f"  Amount:        {amount_display} / {interval_display}\n\n"
        f"{copy['cta']}\n\n"
        f"Manage your subscription (cancel, change plan, update card):\n"
        f"  {PORTAL_BASE_URL}/portal/subscription\n\n"
        f"Questions? Reply to this email or reach {BILLING_SUPPORT_EMAIL}.\n\n"
        f"— The Klaravex Team\n"
    )
    try:
        await send_email(to=email, subject=subject, body=body)
    except Exception as exc:
        log.exception("renewal reminder send failed for %s: %s", email, exc)
        return {"sent": False, "reason": f"email_error: {exc}"}

    await _record_sent(
        subscription_id=subscription_id,
        customer_id=customer_id,
        email=email,
        kind=kind,
        renewal_at=renewal_at,
        metadata={"plan": plan_name, "amount": amount_display, "interval": interval_display},
    )
    log.info("renewal reminder sent: %s | %s | %s", email, kind, plan_name)
    return {"sent": True, "reason": "delivered"}


# In-process product cache to avoid hitting Stripe for the same product
# every scan-loop iteration. TTL'd implicitly by container lifespan.
_PRODUCT_CACHE: dict[str, str] = {}


def _resolve_product_name(price: dict) -> str:
    """Return product display name. Handles both expanded dicts and bare IDs."""
    product = price.get("product")
    if isinstance(product, dict):
        return product.get("name") or "Klaravex"
    if isinstance(product, str):
        cached = _PRODUCT_CACHE.get(product)
        if cached:
            return cached
        try:
            prod_obj = stripe.Product.retrieve(product)
            prod = prod_obj.to_dict() if hasattr(prod_obj, "to_dict") else dict(prod_obj)
            name = prod.get("name") or "Klaravex"
            _PRODUCT_CACHE[product] = name
            return name
        except Exception as exc:
            log.warning("product retrieve failed for %s: %s", product, exc)
            return "Klaravex"
    return "Klaravex"


def _format_subscription_for_reminder(sub: dict, customer_email: Optional[str]) -> dict:
    """Extract reminder-relevant fields from a Stripe subscription object.

    Stripe's 2024-09-30 API moved current_period_end/start from the subscription
    level to the per-item level (to support multi-item subs with different cadences).
    We read it from items[0] as a single-item subscription proxy.
    """
    items = sub.get("items", {}).get("data", [])
    plan_name = "Klaravex"
    amount = 0
    currency = "USD"
    interval = "month"
    interval_count = 1
    item_period_end = sub.get("current_period_end")  # legacy fallback
    if items:
        first = items[0]
        price = first.get("price") or {}
        plan_name = _resolve_product_name(price)
        amount = int(price.get("unit_amount") or 0) / 100.0
        currency = (price.get("currency") or "usd").upper()
        recur = price.get("recurring") or {}
        interval = recur.get("interval", "month")
        interval_count = int(recur.get("interval_count", 1))
        # Item-level period_end takes precedence (modern Stripe API)
        item_period_end = first.get("current_period_end") or item_period_end
    return {
        "subscription_id": sub.get("id"),
        "customer_id": sub.get("customer"),
        "email": customer_email,
        "plan_name": plan_name,
        "amount_display": (
            f"${amount:,.2f} USD" if currency == "USD" else
            f"€{amount:,.2f} EUR" if currency == "EUR" else
            f"{amount:,.2f} {currency}"
        ),
        "interval_display": (
            f"{interval}" if interval_count == 1 else f"{interval_count} {interval}s"
        ),
        "current_period_end": item_period_end,
    }


async def handle_invoice_upcoming(event: dict) -> dict[str, object]:
    """Stripe webhook: invoice.upcoming fires ~7 days before renewal by default.

    We dispatch the renewal_7d reminder.
    """
    invoice = event["data"]["object"]
    subscription_id = invoice.get("subscription")
    customer_id = invoice.get("customer")
    if not (subscription_id and customer_id):
        return {"sent": False, "reason": "missing_subscription_or_customer"}

    try:
        sub_obj = stripe.Subscription.retrieve(subscription_id, expand=["items.data.price"])
        customer_obj = stripe.Customer.retrieve(customer_id)
    except Exception as exc:
        log.exception("stripe retrieve failed: %s", exc)
        return {"sent": False, "reason": f"stripe_error: {exc}"}

    sub = sub_obj.to_dict() if hasattr(sub_obj, "to_dict") else dict(sub_obj)
    customer = customer_obj.to_dict() if hasattr(customer_obj, "to_dict") else dict(customer_obj)

    info = _format_subscription_for_reminder(sub, customer.get("email"))
    if not info.get("email"):
        return {"sent": False, "reason": "no_customer_email"}
    if not info.get("current_period_end"):
        return {"sent": False, "reason": "no_renewal_date"}

    renewal_at = datetime.fromtimestamp(info["current_period_end"], tz=timezone.utc)
    return await send_renewal_reminder(
        subscription_id=info["subscription_id"],
        customer_id=info["customer_id"],
        email=info["email"],
        name=customer.get("name"),
        plan_name=info["plan_name"],
        amount_display=info["amount_display"],
        interval_display=info["interval_display"],
        kind="renewal_7d",
        renewal_at=renewal_at,
    )


async def scan_renewals_due(window_kind: str) -> dict[str, object]:
    """Cron entry point. Scans all active subscriptions and sends the chosen reminder
    for any whose current_period_end falls in the matching window.

    window_kind: 'renewal_30d' → 27–33 days out
                 'renewal_1d'  → 0.5–1.5 days out
    """
    if window_kind == "renewal_30d":
        lower, upper = timedelta(days=27), timedelta(days=33)
    elif window_kind == "renewal_7d":
        # Belt-and-suspenders for Stripe `invoice.upcoming` — covers the case
        # where Stripe's auto-fire was missed/disabled. Idempotency on the
        # unique (subscription, kind, renewal_at) constraint prevents dupes.
        lower, upper = timedelta(days=6), timedelta(days=8)
    elif window_kind == "renewal_1d":
        lower, upper = timedelta(hours=12), timedelta(hours=36)
    else:
        return {"error": f"unknown window_kind:{window_kind}"}

    now = datetime.now(tz=timezone.utc)
    sent = 0
    skipped = 0
    errors = 0

    # Scan via Stripe auto-pagination. Cheap at our scale (<10K subs).
    try:
        subs_iter = stripe.Subscription.list(
            status="active",
            limit=100,
            expand=["data.items.data.price"],
        ).auto_paging_iter()
    except Exception as exc:
        log.exception("stripe list failed during renewal scan: %s", exc)
        return {"window": window_kind, "sent": 0, "skipped": 0, "errors": 1}

    for sub in subs_iter:
        sub_dict = sub.to_dict() if hasattr(sub, "to_dict") else dict(sub)
        # Item-level period_end (Stripe 2024-09-30+) falls back to legacy field.
        items_data = (sub_dict.get("items") or {}).get("data") or []
        cpe = None
        if items_data:
            cpe = items_data[0].get("current_period_end")
        cpe = cpe or sub_dict.get("current_period_end")
        if not cpe:
            continue
        renewal_at = datetime.fromtimestamp(cpe, tz=timezone.utc)
        delta = renewal_at - now
        if not (lower <= delta <= upper):
            continue
        try:
            customer = stripe.Customer.retrieve(sub_dict["customer"])
            cust_dict = customer.to_dict() if hasattr(customer, "to_dict") else dict(customer)
            info = _format_subscription_for_reminder(sub_dict, cust_dict.get("email"))
            if not info.get("email"):
                skipped += 1
                continue
            result = await send_renewal_reminder(
                subscription_id=info["subscription_id"],
                customer_id=info["customer_id"],
                email=info["email"],
                name=cust_dict.get("name"),
                plan_name=info["plan_name"],
                amount_display=info["amount_display"],
                interval_display=info["interval_display"],
                kind=window_kind,
                renewal_at=renewal_at,
            )
            if result.get("sent"):
                sent += 1
            else:
                skipped += 1
        except Exception as exc:
            log.warning("scan reminder error on %s: %s", sub_dict.get("id"), exc)
            errors += 1

    log.info("renewal scan %s complete: sent=%d skipped=%d errors=%d", window_kind, sent, skipped, errors)
    return {"window": window_kind, "sent": sent, "skipped": skipped, "errors": errors}
