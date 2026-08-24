"""A1 archetype — consumer subscription lifecycle handlers.

Three Stripe events drive A1 subscription workflows for all three consumer SKUs:

  customer.subscription.created  → welcome email + intake form link (Day-0)
  invoice.paid                   → monthly status-update email (per WORKFLOWS §A1.3)
  customer.subscription.deleted  → offboarding: Anthony alert with tenure + exit survey

SKU-specific behaviour layered on top of the common path:

  essentials      — standard single-household intake + monthly report
  family-senior   — family intake (household members, per-member devices, primary contact)
                    + per-member monthly report + quarterly proactive check-in scheduled
                    + scam/fraud keyword escalation (WORKFLOWS §A1.4)
  home-membership — same as essentials but IoT device inventory field included in intake
                    + monthly proactive check-in scheduled
                    + IoT-specific escalation flag (WORKFLOWS §A1.4)

Called from stripe_webhook._dispatch_event() after the generic alert/ticket
path has already run, so this module focuses on A1-specific business logic only.

All functions are idempotent: re-running on a duplicate event is safe.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import stripe

from .db import get_pool
from .email import send_email
from .client_monthly_report import send_client_monthly_report

log = logging.getLogger("klaravex.a1_consumer_sub")

PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "support@klaravex.com")
ANTHONY_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

# SKUs handled by A1 workflow.
A1_SKUS = {"essentials", "family-senior", "home-membership"}

# Env var holding the intake form URL; defaults to portal path.
INTAKE_FORM_URL = os.environ.get(
    "A1_INTAKE_FORM_URL",
    f"{PORTAL_BASE_URL}/portal/intake/consumer-sub",
)

# Per-SKU intake form paths so each SKU gets a tailored form.
_INTAKE_PATHS: dict[str, str] = {
    "essentials": "consumer-sub",
    "family-senior": "family-senior",
    "home-membership": "home-membership",
}

# Proactive check-in cadences (days between check-ins, per WORKFLOWS §A1.3 + §A1.4).
# These are stored as metadata on the client profile so the scheduler cron can
# pick them up — this module only records the preference at subscription time.
_CHECKIN_INTERVAL_DAYS: dict[str, int] = {
    "family-senior": 90,   # quarterly
    "home-membership": 30, # monthly
    "essentials": 0,       # weekly wellness chat handled by generic cron; no dedicated slot
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _sku_from_subscription(sub_obj: dict) -> Optional[str]:
    """Extract SKU from a Stripe subscription object (metadata or product name)."""
    meta = sub_obj.get("metadata") or {}
    if meta.get("sku"):
        return meta["sku"]
    items = (sub_obj.get("items") or {}).get("data") or []
    for item in items:
        price = item.get("price") or {}
        # product may be expanded or just an id string
        prod = price.get("product")
        if isinstance(prod, dict):
            return prod.get("name") or prod.get("id")
        elif isinstance(prod, str):
            return prod
    return None


def _is_a1_sku(sku: Optional[str]) -> bool:
    if not sku:
        return False
    s = sku.lower()
    return any(s.startswith(prefix) for prefix in A1_SKUS)


async def _resolve_customer(obj: dict) -> tuple[Optional[str], Optional[str]]:
    """Return (email, name) from a Stripe object, fetching the Customer if needed."""
    email = (
        (obj.get("customer_details") or {}).get("email")
        or obj.get("customer_email")
        or obj.get("receipt_email")
    )
    name = (obj.get("customer_details") or {}).get("name")
    if not email and obj.get("customer"):
        try:
            cust = stripe.Customer.retrieve(obj["customer"])
            email = cust.get("email")
            name = cust.get("name")
        except Exception as exc:
            log.warning("customer retrieve failed: %s", exc)
    return email, name


async def _intake_already_sent(email: str) -> bool:
    """True if we already sent the A1 intake form email for this address."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT a1_intake_sent_at FROM klaravex_clients WHERE email=$1",
            email.lower(),
        )
    # Column may not exist on older DB versions — treat as unsent in that case.
    if row is None:
        return False
    return bool(row.get("a1_intake_sent_at"))


async def _mark_intake_sent(email: str) -> None:
    """Stamp a1_intake_sent_at on the client row (idempotency guard)."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE klaravex_clients
                   SET a1_intake_sent_at = COALESCE(a1_intake_sent_at, now())
                 WHERE email = $1
                """,
                email.lower(),
            )
    except Exception as exc:
        log.warning("mark intake sent failed for %s: %s", email, exc)


async def _client_tenure_days(stripe_customer_id: str) -> Optional[int]:
    """Return approximate subscription tenure in days from the earliest sub start."""
    try:
        subs = stripe.Subscription.list(
            customer=stripe_customer_id, status="all", limit=10
        )
        earliest: Optional[int] = None
        for sub in (subs.data if hasattr(subs, "data") else list(subs)):
            sd = sub.to_dict() if hasattr(sub, "to_dict") else dict(sub)
            created = sd.get("start_date") or sd.get("created")
            if created and (earliest is None or created < earliest):
                earliest = created
        if earliest is None:
            return None
        started = datetime.fromtimestamp(earliest, tz=timezone.utc)
        return (datetime.now(tz=timezone.utc) - started).days
    except Exception as exc:
        log.warning("tenure calculation failed for %s: %s", stripe_customer_id, exc)
        return None


async def _send_telegram(text: str) -> None:
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT):
        return
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT, "text": text},
            )
    except Exception as exc:
        log.warning("Telegram send failed: %s", exc)


# ── SKU-specific helpers ──────────────────────────────────────────────────────

def _intake_url_for_sku(email: str, sku: str) -> str:
    """Return the full intake form URL for the given SKU."""
    base = os.environ.get("A1_INTAKE_FORM_URL", INTAKE_FORM_URL)
    # Honour an explicit override first; otherwise build from per-SKU path.
    if base == INTAKE_FORM_URL:
        path = _INTAKE_PATHS.get(sku, "consumer-sub")
        base = f"{PORTAL_BASE_URL}/portal/intake/{path}"
    return f"{base}?email={email}"


def _build_welcome_body(greeting: str, intake_url: str, sku: str, email: str) -> tuple[str, str]:
    """Return (subject, body) for the Day-0 welcome email, tailored by SKU."""
    support = SUPPORT_EMAIL

    if sku == "family-senior":
        subject = "Welcome to Klaravex Family & Senior Support — complete your 5-minute setup"
        body = (
            f"{greeting}\n\n"
            f"Your Klaravex Family & Senior Support membership is active. Welcome.\n\n"
            f"To make sure every household member gets the right help from day one,\n"
            f"please take 5 minutes to complete your household setup:\n\n"
            f"  {intake_url}\n\n"
            f"The form covers:\n"
            f"  • Names and roles of each household member we support\n"
            f"  • Devices each person uses (phone, laptop, tablet, etc.)\n"
            f"  • Primary contact person for the household\n"
            f"  • Each member's top IT or security concern\n"
            f"  • Preferred contact method (chat / email / phone)\n\n"
            f"We run a dedicated monthly check-in for each household member, and a\n"
            f"quarterly family review. We will always escalate scam, fraud, or financial-\n"
            f"security concerns immediately — no waiting.\n\n"
            f"Once submitted, we send a direct link to our AI support chat — available 24/7.\n\n"
            f"Anything urgent right now? Reply here or reach {support}.\n\n"
            f"— The Klaravex Team\n"
        )

    elif sku == "home-membership":
        subject = "Welcome to Klaravex Home Membership — complete your 5-minute setup"
        body = (
            f"{greeting}\n\n"
            f"Your Klaravex Home Membership is active. Welcome.\n\n"
            f"To get your household — and all its connected devices — set up correctly,\n"
            f"please take 5 minutes to complete your home setup:\n\n"
            f"  {intake_url}\n\n"
            f"The form covers:\n"
            f"  • Household size and primary devices (Win / macOS / iOS / Android)\n"
            f"  • Smart-home and IoT devices (routers, cameras, thermostats, etc.)\n"
            f"  • Primary contact person\n"
            f"  • Top 3 current pain points\n"
            f"  • Preferred contact method (chat / email / phone)\n\n"
            f"We run a monthly proactive check-in for all Home Membership accounts.\n"
            f"Smart-home and IoT questions are escalated to our senior engineer when\n"
            f"our knowledge base doesn't have a definitive answer.\n\n"
            f"Once submitted, we send a direct link to our AI support chat — available 24/7.\n\n"
            f"Anything urgent right now? Reply here or reach {support}.\n\n"
            f"— The Klaravex Team\n"
        )

    else:  # essentials (and any unrecognised A1 SKU — safe default)
        subject = "Welcome to Klaravex — complete your 5-minute setup (takes care of everything)"
        body = (
            f"{greeting}\n\n"
            f"Your Klaravex Essentials membership is active. Welcome.\n\n"
            f"To get you the most useful support from day one, please take 5 minutes\n"
            f"to complete your setup form:\n\n"
            f"  {intake_url}\n\n"
            f"The form covers:\n"
            f"  • Your household and devices\n"
            f"  • Your top 3 IT pain points right now\n"
            f"  • How you prefer us to reach you\n\n"
            f"Once you submit, we confirm you're all set and send a direct link to our AI\n"
            f"support chat — available 24/7.\n\n"
            f"If you have something urgent right now, reply to this email or reach\n"
            f"{support} — we respond the same day.\n\n"
            f"— The Klaravex Team\n"
        )

    return subject, body


async def _set_checkin_schedule(email: str, sku: str) -> None:
    """Record the proactive check-in interval on the client profile.

    The scheduler cron (infra/cron/proactive_checkins.py) reads
    `a1_checkin_interval_days` to decide when to fire the next check-in.
    A value of 0 means no dedicated slot (essentials uses the generic weekly chat).
    """
    interval = _CHECKIN_INTERVAL_DAYS.get(sku, 0)
    if interval == 0:
        return
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE klaravex_clients
                   SET a1_checkin_interval_days = $2,
                       a1_next_checkin_at       = now() + ($2 || ' days')::interval
                 WHERE email = $1
                """,
                email.lower(),
                str(interval),
            )
        log.info(
            "A1 check-in schedule set for %s (sku=%s interval=%d days)",
            email, sku, interval,
        )
    except Exception as exc:
        log.warning("set_checkin_schedule failed for %s: %s", email, exc)


async def _send_family_monthly_report(email: str, sku: str) -> dict:
    """For family-senior SKUs: send one report per household member.

    Fetches the members list from klaravex_clients.a1_household_members (JSON),
    then calls send_client_monthly_report for each member's sub-email where
    available, falling back to the primary email with a per-member section.

    Returns a summary dict.
    """
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT a1_household_members FROM klaravex_clients WHERE email=$1",
                email.lower(),
            )
    except Exception as exc:
        log.warning("household members fetch failed for %s: %s", email, exc)
        row = None

    members: list[dict] = []
    if row and row.get("a1_household_members"):
        import json as _json
        try:
            members = _json.loads(row["a1_household_members"])
        except Exception:
            pass

    if not members:
        # No member data yet — fall back to standard single-account report.
        result = await send_client_monthly_report(email)
        return {"action": "monthly_report_sent_fallback", "email": email, **result}

    sent_count = 0
    errors: list[str] = []
    for member in members:
        member_email = member.get("email") or email
        try:
            result = await send_client_monthly_report(member_email, member_context=member)
            if result.get("sent"):
                sent_count += 1
        except Exception as exc:
            log.warning(
                "A1 family monthly report failed for member %s (primary=%s): %s",
                member_email, email, exc,
            )
            errors.append(str(exc))

    return {
        "action": "family_monthly_report",
        "primary_email": email,
        "members_total": len(members),
        "members_sent": sent_count,
        "errors": errors,
    }


# ── public event handlers ─────────────────────────────────────────────────────

async def handle_subscription_created(event: dict) -> dict:
    """Day-0: send welcome + intake form within 60 seconds of subscription creation.

    Idempotent: no-op if intake already sent for this email.
    """
    obj = event.get("data", {}).get("object") or {}
    sku = _sku_from_subscription(obj)
    if not _is_a1_sku(sku):
        return {"action": "skip", "reason": "not_a1_sku", "sku": sku}

    email, name = await _resolve_customer(obj)
    if not email:
        return {"action": "skip", "reason": "no_email"}

    if await _intake_already_sent(email):
        return {"action": "skip", "reason": "intake_already_sent", "email": email}

    greeting = f"Hi {name}," if name else "Hi there,"
    intake_url = _intake_url_for_sku(email, sku)
    subject, body = _build_welcome_body(greeting, intake_url, sku, email)

    try:
        await send_email(to=email, subject=subject, body=body)
        await _mark_intake_sent(email)
        await _set_checkin_schedule(email, sku)
        log.info("A1 welcome+intake sent to %s (sku=%s)", email, sku)
        return {"action": "sent", "email": email, "sku": sku}
    except Exception as exc:
        log.exception("A1 welcome+intake email failed for %s: %s", email, exc)
        return {"action": "error", "email": email, "error": str(exc)}


async def handle_invoice_paid(event: dict) -> dict:
    """Monthly billing cycle: send the consumer their monthly status-update email.

    Only fires for A1 SKUs. Delegates to client_monthly_report.send_client_monthly_report
    which already builds a consumer-segment stat email from klaravex_tickets data.

    Skips gracefully if no client record exists (e.g., new customer whose profile
    hasn't been created yet — they'll get the cron-based monthly report next cycle).
    """
    obj = event.get("data", {}).get("object") or {}
    # invoice.paid objects don't carry subscription items directly; fetch the
    # subscription to check the SKU when it's attached.
    sub_id = obj.get("subscription")
    sku: Optional[str] = (obj.get("metadata") or {}).get("sku")

    if not sku and sub_id:
        try:
            sub = stripe.Subscription.retrieve(sub_id)
            sku = _sku_from_subscription(sub.to_dict() if hasattr(sub, "to_dict") else dict(sub))
        except Exception as exc:
            log.warning("subscription retrieve failed for invoice %s: %s", obj.get("id"), exc)

    if not _is_a1_sku(sku):
        return {"action": "skip", "reason": "not_a1_sku", "sku": sku}

    email, _name = await _resolve_customer(obj)
    if not email:
        return {"action": "skip", "reason": "no_email"}

    try:
        if sku == "family-senior":
            # Per-member report for family/senior accounts (WORKFLOWS §A1.3 + task 6.5).
            result = await _send_family_monthly_report(email, sku)
            log.info(
                "A1 family monthly report for %s: members_sent=%s",
                email, result.get("members_sent"),
            )
        else:
            result = await send_client_monthly_report(email)
            log.info("A1 monthly report for %s: sent=%s", email, result.get("sent"))
            result = {
                "action": "monthly_report_sent" if result.get("sent") else "monthly_report_skipped",
                **result,
            }
        return {"email": email, **result}
    except Exception as exc:
        log.exception("A1 monthly report failed for %s: %s", email, exc)
        return {"action": "error", "email": email, "error": str(exc)}


async def handle_subscription_deleted(event: dict) -> dict:
    """Offboarding: alert Anthony with tenure + plan; exit survey already sent by generic handler.

    The generic stripe_webhook handler already fires send_exit_survey() for all deletions.
    This handler adds the Anthony alert enriched with tenure_days per WORKFLOWS §A1.6.
    """
    obj = event.get("data", {}).get("object") or {}
    sku = _sku_from_subscription(obj)
    if not _is_a1_sku(sku):
        return {"action": "skip", "reason": "not_a1_sku", "sku": sku}

    email, name = await _resolve_customer(obj)
    if not email:
        return {"action": "skip", "reason": "no_email"}

    customer_id = obj.get("customer")
    tenure_days = await _client_tenure_days(customer_id) if customer_id else None
    sub_id = obj.get("id") or "—"
    tenure_str = f"{tenure_days} days" if tenure_days is not None else "unknown"

    subject = f"[Klaravex A1] Cancellation — {email} ({sku}) — {tenure_str}"
    alert_body = (
        f"A1 consumer subscription cancelled.\n\n"
        f"Customer:   {name or '—'} <{email}>\n"
        f"Plan:       {sku}\n"
        f"Tenure:     {tenure_str}\n"
        f"Sub ID:     {sub_id}\n"
        f"Stripe:     https://dashboard.stripe.com/customers/{customer_id}\n\n"
        f"Exit survey has been sent to the customer automatically.\n\n"
        f"Consider a manual win-back if tenure > 60 days.\n"
    )

    try:
        await send_email(to=ANTHONY_EMAIL, subject=subject, body=alert_body)
        await _send_telegram(f"{subject}\nTenure: {tenure_str}\nEmail: {email}")
        log.info("A1 cancellation alert sent for %s (tenure=%s sku=%s)", email, tenure_str, sku)
        return {"action": "alert_sent", "email": email, "tenure_days": tenure_days, "sku": sku}
    except Exception as exc:
        log.exception("A1 cancellation alert failed for %s: %s", email, exc)
        return {"action": "error", "email": email, "error": str(exc)}
