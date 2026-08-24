"""
Klaravex Stripe webhook handler — drop-in FastAPI router.

Mount in your Klara AI backend with:

    from fastapi import FastAPI
    from infra.klara.handlers.stripe_webhook import router as stripe_router
    app = FastAPI()
    app.include_router(stripe_router, prefix="/api/v1/stripe")

Required env vars (already declared in infra/.env.klaravex.template):
    STRIPE_SECRET_KEY
    STRIPE_WEBHOOK_SECRET
    SMTP_PASS                    (M365 SMTP password; email skipped if absent)
    SMTP_USER                    default: support@klaravex.com
    ANTHONY_ALERT_EMAIL          default: astewart@klaravex.com
    TELEGRAM_BOT_TOKEN           (optional)
    TELEGRAM_CHAT_ID             (optional)
"""

import json
import os
import logging
from typing import Any, Optional

import httpx
import stripe
from fastapi import APIRouter, Header, HTTPException, Request

from .lib import tickets as tickets_lib
from .lib.db import get_pool
from .lib.email import send_email
from .lib.welcome import send_post_signup_welcome
from .lib import renewals as renewals_lib
from .lib import cancellation as cancellation_lib
from .lib import onboarding as onboarding_lib
from .lib.marketing_attribution import stamp_attribution_on_client
from .lib.lifecycle_extras import handle_invoice_paid_recovery
from .lib import a1_consumer_sub as a1_lib
from .lib import b2b_foundation as foundation_lib
from .lib import b2b_assurance as assurance_lib
from .lib import b2b_directive as directive_lib
from .lib import b2b_addons as addons_lib
from .lib import project_workflows as pw_lib
from . import dunning as dunning_agent

_PW_SKUS = {*pw_lib.A6_SKUS, *pw_lib.A7_SKUS, *pw_lib.A8_SKUS}

log = logging.getLogger("klaravex.stripe_webhook")
router = APIRouter()

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

ALERT_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_failed",
}

# Renewal-reminder events — handled by renewals_lib in addition to alert flow.
RENEWAL_EVENTS = {
    "invoice.upcoming",
}

# Dunning events — handled by dunning_agent in addition to normal alert flow.
DUNNING_EVENTS = {
    "invoice.payment_failed",
    "customer.subscription.past_due",
    "customer.subscription.unpaid",
}

_DUNNING_DISPATCH = {
    "invoice.payment_failed":          dunning_agent.handle_invoice_payment_failed,
    "customer.subscription.past_due":  dunning_agent.handle_subscription_past_due,
    "customer.subscription.unpaid":    dunning_agent.handle_subscription_unpaid,
}


def _format_alert(event: dict[str, Any]) -> tuple[str, str]:
    et = event["type"]
    obj = event["data"]["object"]
    sku = (obj.get("metadata") or {}).get("sku") or "—"
    customer_email = obj.get("customer_details", {}).get("email") or obj.get("customer_email") or obj.get("receipt_email") or "—"
    amount = obj.get("amount_total") or obj.get("amount_paid") or obj.get("amount_due") or 0
    amount_str = f"${amount/100:.2f}" if isinstance(amount, int) and amount else "—"
    currency = (obj.get("currency") or "usd").upper()
    subject = f"[Klaravex] {et} — {sku} — {amount_str} {currency}"
    body = (
        f"Stripe event: {et}\n"
        f"SKU: {sku}\n"
        f"Customer: {customer_email}\n"
        f"Amount: {amount_str} {currency}\n"
        f"Object id: {obj.get('id')}\n"
        f"Dashboard: https://dashboard.stripe.com/{'test/' if event.get('livemode') is False else ''}events/{event['id']}\n"
    )
    return subject, body


async def _send_telegram(text: str) -> None:
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT):
        return
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": text},
        )


async def _claim_event(event: dict[str, Any]) -> tuple[str, Optional[str]]:
    """Idempotency gate.

    Atomically tries to claim ownership of ``event['id']`` by inserting into
    klaravex_stripe_events with ON CONFLICT DO NOTHING.

    Returns one of:
      ('claimed', None)              → new event, caller must dispatch
      ('duplicate_skipped', status)  → event already done | skipped
      ('in_flight', status)          → event currently processing
      ('duplicate_failed_skipped', status) → prior attempt failed; do not auto-retry

    On unexpected DB failure we log + return ('claimed', None) so the handler
    proceeds (failing closed here would block ALL webhooks on a DB outage).
    """
    event_id = event.get("id")
    event_type = event.get("type") or "unknown"
    if not event_id:
        return "claimed", None
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Try to claim. Status starts as 'processing' so a concurrent
            # retry sees in_flight (the row is committed by the INSERT).
            inserted = await conn.fetchval(
                """
                INSERT INTO klaravex_stripe_events
                    (event_id, event_type, status, payload)
                VALUES ($1, $2, 'processing', $3::jsonb)
                ON CONFLICT (event_id) DO NOTHING
                RETURNING event_id
                """,
                event_id,
                event_type,
                json.dumps(event),
            )
            if inserted:
                return "claimed", None
            # Already exists — look up current status.
            status = await conn.fetchval(
                "SELECT status FROM klaravex_stripe_events WHERE event_id = $1",
                event_id,
            )
        if status in ("done", "skipped"):
            return "duplicate_skipped", status
        if status == "failed":
            return "duplicate_failed_skipped", status
        # received | processing | anything else → treat as in flight
        return "in_flight", status
    except Exception as exc:  # noqa: BLE001
        log.exception("dedup gate failed for event %s — failing open: %s", event_id, exc)
        return "claimed", None


async def _mark_event(event_id: str, *, status: str, error: Optional[str] = None) -> None:
    """Best-effort status update. Never raises."""
    if not event_id:
        return
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE klaravex_stripe_events
                   SET status = $2,
                       error = $3,
                       processed_at = NOW()
                 WHERE event_id = $1
                """,
                event_id,
                status,
                error,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("failed to mark event %s as %s: %s", event_id, status, exc)


@router.post("/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(default="")) -> dict[str, str]:
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        log.warning("Invalid Stripe signature: %s", e)
        raise HTTPException(status_code=400, detail="invalid signature")

    # Idempotency gate — MUST run before any side effects.
    claim, _prior_status = await _claim_event(event)
    event_id = event.get("id") or ""
    if claim == "duplicate_skipped":
        log.info("stripe webhook dedup: %s already processed (skip)", event_id)
        return {"status": "duplicate_skipped", "event_id": event_id}
    if claim == "in_flight":
        log.info("stripe webhook dedup: %s currently processing (in_flight)", event_id)
        return {"status": "in_flight", "event_id": event_id}
    if claim == "duplicate_failed_skipped":
        log.warning(
            "stripe webhook dedup: %s previously failed — NOT auto-retrying; "
            "Anthony must reprocess manually from klaravex_stripe_events",
            event_id,
        )
        return {"status": "duplicate_failed_skipped", "event_id": event_id}

    # claim == 'claimed' → first-time event, run dispatch.
    try:
        await _dispatch_event(event)
    except Exception as exc:  # noqa: BLE001
        await _mark_event(event_id, status="failed", error=repr(exc)[:1000])
        # Re-raise so Stripe sees a 500 and retries. The dedup gate will catch
        # the retry as duplicate_failed_skipped (no double-processing); Anthony
        # gets a chance to fix the underlying issue and manually reprocess.
        raise

    await _mark_event(event_id, status="done")
    return {"status": "ok", "event_id": event_id}


async def _dispatch_event(event: dict[str, Any]) -> None:
    """Run every side-effect for a Stripe event. Raises on hard failure.

    Note: many inner blocks already catch + log so they don't tear down the
    whole dispatch. The outer try/except in the route promotes any escapee
    into a 'failed' status row so Stripe retries pass through the dedup gate.
    """
    if event["type"] in ALERT_EVENTS:
        subject, body = _format_alert(event)
        try:
            await send_email(ALERT_EMAIL, subject, body)
            await _send_telegram(f"{subject}\n\n{body}")
        except Exception as e:  # noqa: BLE001
            log.exception("alert dispatch failed: %s", e)

        # Persist as ticket so the portal reflects billing events.
        try:
            await _persist_stripe_ticket(event)
        except Exception as e:  # noqa: BLE001
            log.warning("ticket persistence failed (continuing): %s", e)

        # First-time client onboarding: send welcome email with portal magic link.
        # Idempotent (klaravex_clients.welcome_sent_at), so safe to call on every event.
        if event["type"] in ("customer.subscription.created", "checkout.session.completed", "invoice.paid"):
            try:
                obj = event["data"]["object"]
                email = (
                    obj.get("customer_details", {}).get("email")
                    or obj.get("customer_email")
                    or obj.get("receipt_email")
                )
                if not email and obj.get("customer"):
                    try:
                        cust = stripe.Customer.retrieve(obj["customer"])
                        email = cust.get("email")
                        cust_name = cust.get("name")
                    except Exception:
                        cust_name = None
                else:
                    cust_name = obj.get("customer_details", {}).get("name") if obj.get("customer_details") else None
                if email:
                    sku = (obj.get("metadata") or {}).get("sku")
                    consumer_prefixes = (
                        "essentials", "family-", "home-", "per-incident",
                        "resume-", "tech-", "solo-", "ai-", "identity-",
                    )
                    segment = "consumer" if (sku and sku.lower().startswith(consumer_prefixes)) else "b2b"
                    result = await send_post_signup_welcome(
                        email=email,
                        name=cust_name,
                        sku=sku,
                        segment=segment,
                    )
                    log.info("welcome dispatch for %s: %s", email, result.get("reason"))
                    # Day-0 onboarding checklist (idempotent — only creates once per client)
                    try:
                        onb = await onboarding_lib.ensure_checklist(email, segment)
                        log.info("onboarding checklist for %s: %s", email, onb)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("onboarding checklist creation failed (continuing): %s", exc)
                    # Marketing attribution: if Stripe Checkout was created with
                    # metadata.marketing_team=alpha|beta, stamp it on the client.
                    try:
                        team = (obj.get("metadata") or {}).get("marketing_team")
                        if team:
                            await stamp_attribution_on_client(email, team)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("attribution stamp failed (continuing): %s", exc)
            except Exception as e:  # noqa: BLE001
                log.exception("welcome dispatch failed (continuing): %s", e)

        # A2 one-time session kickoff — covers per-incident, ai-coaching,
        # identity-privacy, tech-kit, solo-launch (and their checkout aliases).
        # Sends intake form email, creates ticket, schedules follow-ups.
        # Idempotent (dedup by stripe_session_id + SKU inside a2_kickoff).
        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            session_sku = (session.get("metadata") or {}).get("sku", "")
            # Normalise variant SKU names sent from Stripe checkout flow
            _SKU_ALIASES: dict[str, str] = {
                "tech-kit-basic":         "tech-kit",
                "tech-kit-pro":           "tech-kit",
                "solo-launch-starter":    "solo-launch",
                "solo-launch-pro":        "solo-launch",
                "ai-coaching-session":    "ai-coaching",
                "identity-privacy-basic": "identity-privacy",
                "identity-privacy-pro":   "identity-privacy",
            }
            normalised_sku = _SKU_ALIASES.get(session_sku, session_sku)
            from .lib.per_incident_session import SKU_CONFIG, a2_kickoff
            # If SKU is blank, attempt line-item lookup for per-incident (voice flow)
            if not normalised_sku:
                try:
                    line_items = stripe.checkout.Session.list_line_items(session["id"], limit=5)
                    for li in (line_items.get("data") or []):
                        price_id = (li.get("price") or {}).get("id", "")
                        if price_id == "price_1TvQqI14iRJDip4yBEGW2tUb":  # per-incident price ID
                            normalised_sku = "per-incident"
                            break
                except Exception:
                    pass
            if normalised_sku in SKU_CONFIG:
                try:
                    kickoff_result = await a2_kickoff(normalised_sku, session)
                    log.info(
                        "a2_kickoff[%s]: ticket=%s triage=%s followups=%s",
                        normalised_sku,
                        kickoff_result.get("ticket_id"),
                        kickoff_result.get("triage"),
                        kickoff_result.get("followups_scheduled"),
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning("a2_kickoff[%s] failed (continuing): %s", normalised_sku, e)

        # A2 resume session kickoff — runs for resume-basic, resume-premium, resume-executive.
        # Sends intake email, creates ticket with SKU-specific session count, schedules follow-ups.
        # Idempotent (dedup by stripe_session_id inside kickoff).
        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            _session_sku = (session.get("metadata") or {}).get("sku", "").lower()
            _is_resume = _session_sku.startswith("resume-")
            if not _is_resume:
                # Best-effort: check line items if sku metadata not set
                try:
                    _li = stripe.checkout.Session.list_line_items(session["id"], limit=5)
                    for _item in (_li.get("data") or []):
                        _price_meta = ((_item.get("price") or {}).get("metadata") or {})
                        if (_price_meta.get("sku", "").lower().startswith("resume-")
                                or "resume" in ((_item.get("price") or {}).get("nickname") or "").lower()):
                            _is_resume = True
                            break
                except Exception:
                    pass
            if _is_resume:
                try:
                    from .lib.resume_session import kickoff as resume_kickoff
                    resume_result = await resume_kickoff(session)
                    log.info(
                        "resume kickoff: ticket=%s sku=%s sessions=%s triage=%s followups=%s",
                        resume_result.get("ticket_id"),
                        resume_result.get("sku"),
                        resume_result.get("sessions_total"),
                        resume_result.get("triage"),
                        resume_result.get("followups_scheduled"),
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning("resume kickoff failed (continuing): %s", e)

        # Trigger outbound Vapi troubleshoot call for voice-originated payments.
        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            if (session.get("metadata") or {}).get("source") == "vapi":
                caller_phone = (session.get("metadata") or {}).get("caller_phone", "")
                call_sid = (session.get("metadata") or {}).get("call_sid", "")
                intent = (session.get("metadata") or {}).get("intent", "per-incident")
                if caller_phone:
                    try:
                        from .vapi.outbound_call import trigger_troubleshoot_call
                        call_result = await trigger_troubleshoot_call(caller_phone, call_sid, intent)
                        log.info(
                            "outbound call result: %s",
                            call_result.get("id") or call_result.get("error"),
                        )
                    except Exception as e:  # noqa: BLE001
                        log.warning("outbound call dispatch failed (continuing): %s", e)

    # Exit survey: subscription.deleted → ask the customer why they left.
    if event["type"] == "customer.subscription.deleted":
        try:
            obj = event["data"]["object"]
            customer_id = obj.get("customer")
            cust_email = None
            cust_name = None
            if customer_id:
                try:
                    cust = stripe.Customer.retrieve(customer_id)
                    cust_email = cust.get("email")
                    cust_name = cust.get("name")
                except Exception as exc:
                    log.warning("customer retrieve for exit survey failed: %s", exc)
            plan_name = None
            items = (obj.get("items") or {}).get("data") or []
            if items:
                price = items[0].get("price") or {}
                prod = price.get("product")
                if isinstance(prod, dict):
                    plan_name = prod.get("name")
                elif isinstance(prod, str):
                    try:
                        prod_obj = stripe.Product.retrieve(prod)
                        plan_name = (prod_obj.to_dict() if hasattr(prod_obj, "to_dict") else dict(prod_obj)).get("name")
                    except Exception:
                        pass
            if cust_email:
                await cancellation_lib.send_exit_survey(cust_email, cust_name, plan_name)
                log.info("exit survey sent to %s (plan=%s)", cust_email, plan_name)
        except Exception as e:  # noqa: BLE001
            log.exception("exit survey dispatch failed: %s", e)

    # Dunning auto-resume: invoice.paid → clear payment_failed_count, recovery email.
    if event["type"] == "invoice.paid":
        try:
            result = await handle_invoice_paid_recovery(event)
            log.info("dunning recovery check: %s", result.get("action"))
        except Exception as e:  # noqa: BLE001
            log.warning("dunning recovery failed (continuing): %s", e)

    # Renewal reminder: invoice.upcoming → send 7-day pre-renewal email.
    # Cron handles 30-day and 1-day reminders for windows Stripe doesn't fire.
    if event["type"] in RENEWAL_EVENTS:
        try:
            result = await renewals_lib.handle_invoice_upcoming(event)
            log.info("renewal reminder dispatch: %s", result.get("reason"))
        except Exception as e:  # noqa: BLE001
            log.exception("renewal reminder failed: %s", e)

    # Dunning agent — runs for payment/subscription failure events regardless of
    # whether they also fired the alert block above (invoice.payment_failed fires
    # both; past_due and unpaid are dunning-only).
    if event["type"] in DUNNING_EVENTS:
        handler = _DUNNING_DISPATCH.get(event["type"])
        if handler:
            try:
                dunning_result = await handler(event)
                log.info(
                    "dunning handler %s completed: ticket=%s escalation=%s",
                    event["type"],
                    dunning_result.get("ticket_id"),
                    dunning_result.get("escalation_id"),
                )
            except Exception as e:  # noqa: BLE001
                log.exception("dunning handler failed for %s: %s", event["type"], e)

    # A1 archetype — consumer subscription lifecycle (essentials, family-senior, home-membership).
    # Runs after the generic alert/ticket/welcome blocks so A1-specific logic only adds
    # what those blocks don't cover (intake form link, monthly stat email, Anthony alert with tenure).
    _A1_DISPATCH = {
        "customer.subscription.created": a1_lib.handle_subscription_created,
        "invoice.paid":                  a1_lib.handle_invoice_paid,
        "customer.subscription.deleted": a1_lib.handle_subscription_deleted,
    }
    a1_handler = _A1_DISPATCH.get(event["type"])
    if a1_handler:
        try:
            a1_result = await a1_handler(event)
            log.info("A1 handler %s: action=%s", event["type"], a1_result.get("action"))
        except Exception as e:  # noqa: BLE001
            log.exception("A1 handler failed for %s: %s", event["type"], e)

    # A3 archetype — Foundation tier lifecycle (foundation, foundation-annual, foundation-comanaged).
    # Each handler guards on the SKU internally; non-Foundation events return action='skipped' cheaply.
    _A3_FOUNDATION_DISPATCH = {
        "customer.subscription.created": foundation_lib.handle_subscription_created,
        "invoice.paid":                  foundation_lib.handle_invoice_paid,
        "customer.subscription.deleted": foundation_lib.handle_subscription_deleted,
    }
    a3_handler = _A3_FOUNDATION_DISPATCH.get(event["type"])
    if a3_handler:
        try:
            a3_result = await a3_handler(event)
            log.info("A3 Foundation handler %s: action=%s", event["type"], a3_result.get("action"))
        except Exception as e:  # noqa: BLE001
            log.exception("A3 Foundation handler failed for %s: %s", event["type"], e)

    # A3 archetype — Assurance tier lifecycle (assurance, assurance-annual, assurance-comanaged).
    # Extends Foundation with MDR, SAT, email-security tuning, and vCISO-lite advisory.
    _A3_ASSURANCE_DISPATCH = {
        "customer.subscription.created": assurance_lib.handle_subscription_created,
        "invoice.paid":                  assurance_lib.handle_invoice_paid,
        "customer.subscription.deleted": assurance_lib.handle_subscription_deleted,
    }
    a3_assurance_handler = _A3_ASSURANCE_DISPATCH.get(event["type"])
    if a3_assurance_handler:
        try:
            a3_assurance_result = await a3_assurance_handler(event)
            log.info("A3 Assurance handler %s: action=%s", event["type"], a3_assurance_result.get("action"))
        except Exception as e:  # noqa: BLE001
            log.exception("A3 Assurance handler failed for %s: %s", event["type"], e)

    # A3 archetype — Directive tier lifecycle (directive, directive-annual, directive-comanaged).
    # Top-tier: full vCISO, compliance program management, risk register, board reporting.
    _A3_DIRECTIVE_DISPATCH = {
        "customer.subscription.created": directive_lib.handle_subscription_created,
        "invoice.paid":                  directive_lib.handle_invoice_paid,
        "customer.subscription.deleted": directive_lib.handle_subscription_deleted,
    }
    a3_directive_handler = _A3_DIRECTIVE_DISPATCH.get(event["type"])
    if a3_directive_handler:
        try:
            a3_directive_result = await a3_directive_handler(event)
            log.info("A3 Directive handler %s: action=%s", event["type"], a3_directive_result.get("action"))
        except Exception as e:  # noqa: BLE001
            log.exception("A3 Directive handler failed for %s: %s", event["type"], e)

    # A4 archetype — B2B add-on recurring services (sat, email-security, managed-edr,
    # loki-concierge, vcio-standalone, vciso-standalone, ir-retainer).
    # Activates on subscription.created (add-on purchased standalone or alongside tier),
    # subscription.updated (add-on added to existing subscription), and
    # subscription.deleted (all add-ons on the subscription are deactivated).
    # Each handler inspects line-item SKUs internally; non-addon events return skipped cheaply.
    _A4_DISPATCH = {
        "customer.subscription.created": addons_lib.handle_subscription_created,
        "customer.subscription.updated": addons_lib.handle_subscription_updated,
        "customer.subscription.deleted": addons_lib.handle_subscription_deleted,
    }
    a4_handler = _A4_DISPATCH.get(event["type"])
    if a4_handler:
        try:
            a4_results = await a4_handler(event)
            for r in a4_results:
                log.info(
                    "A4 addon handler %s: action=%s sku=%s",
                    event["type"],
                    r.get("action"),
                    r.get("sku", "—"),
                )
        except Exception as e:  # noqa: BLE001
            log.exception("A4 addon handler failed for %s: %s", event["type"], e)

    # A5 archetype — B2B fixed-fee assessment (cir-small/medium/large, it-audit,
    # hipaa-gap, iso27001-readiness, soc2-readiness, attestation-prep).
    # Cyber-Insurance Readiness is the lead magnet; all A5 SKUs funnel through here.
    # Idempotent (dedup by stripe_session_id + SKU inside a5_kickoff).
    if event["type"] == "checkout.session.completed":
        _a5_session = event["data"]["object"]
        _a5_session_sku = (_a5_session.get("metadata") or {}).get("sku", "")
        from .lib.assessment_workflow import A5_SKU_CONFIG, _A5_SKU_ALIASES, a5_kickoff
        _a5_canonical = _A5_SKU_ALIASES.get(_a5_session_sku, _a5_session_sku)
        if _a5_canonical in A5_SKU_CONFIG:
            try:
                a5_result = await a5_kickoff(_a5_canonical, _a5_session)
                log.info(
                    "a5_kickoff[%s]: ticket=%s triage=%s followups=%s",
                    _a5_canonical,
                    a5_result.get("ticket_id"),
                    a5_result.get("triage"),
                    a5_result.get("followups_scheduled"),
                )
            except Exception as e:  # noqa: BLE001
                log.warning("a5_kickoff[%s] failed (continuing): %s", _a5_canonical, e)

    # A6/A7/A8 archetypes — fixed-fee projects, block-hour support, procurement.
    # Routes by SKU: A6_SKUS → project kickoff, A7_SKUS → hour block, A8_SKUS → procurement fee.
    # Each inner handler is idempotent (dedup via stripe session_id).
    if event["type"] == "checkout.session.completed":
        _pw_session = event["data"]["object"]
        _pw_sku = ((_pw_session.get("metadata") or {}).get("sku") or "").lower()
        if _pw_sku in _PW_SKUS:
            try:
                pw_result = await pw_lib.handle_checkout_completed(_pw_session)
                log.info(
                    "A6/A7/A8 checkout[%s]: action=%s project=%s block=%s ticket=%s",
                    _pw_sku,
                    pw_result.get("action"),
                    pw_result.get("project_id"),
                    pw_result.get("block_id"),
                    pw_result.get("ticket_id"),
                )
            except Exception as e:  # noqa: BLE001
                log.exception("A6/A7/A8 checkout handler failed for sku=%s: %s", _pw_sku, e)


async def _persist_stripe_ticket(event: dict[str, Any]) -> None:
    et = event["type"]
    obj = event["data"]["object"]
    customer_email = (
        obj.get("customer_details", {}).get("email")
        or obj.get("customer_email")
        or obj.get("receipt_email")
    )
    if not customer_email and obj.get("customer"):
        try:
            cust = stripe.Customer.retrieve(obj["customer"])
            customer_email = cust.get("email")
        except Exception as exc:
            log.warning("customer lookup failed for %s: %s", obj["customer"], exc)
    if not customer_email:
        return
    sku = (obj.get("metadata") or {}).get("sku")
    stripe_customer_id = obj.get("customer") or None
    # Best-effort segment hint: SKUs prefixed with consumer products start with
    # 'essentials', 'family-', 'home-', 'per-incident', 'resume-', 'tech-',
    # 'solo-', 'ai-', 'identity-'. Everything else (foundation, assurance, etc.)
    # is B2B.
    consumer_prefixes = (
        "essentials", "family-", "home-", "per-incident",
        "resume-", "tech-", "solo-", "ai-", "identity-",
    )
    segment = "consumer" if (sku and sku.startswith(consumer_prefixes)) else "b2b"

    # Severity: payment_failed = high; subscription deleted = high; others standard.
    severity = "high" if et in ("invoice.payment_failed", "customer.subscription.deleted") else "standard"
    status = "open" if severity == "high" else "resolved"
    resolution = None if status == "open" else f"Stripe event {et} acknowledged"

    if stripe_customer_id:
        try:
            await tickets_lib.get_or_create_client(
                customer_email,
                segment=segment,
                stripe_customer_id=stripe_customer_id,
            )
        except Exception:
            pass

    await tickets_lib.create_ticket(
        client_email=customer_email,
        subject=f"Stripe {et}",
        severity=severity,
        status=status,
        source="stripe",
        archetype="A1" if "subscription" in et else "A2",
        sku=sku,
        summary=f"{et} for {sku or 'unknown SKU'}",
        segment_hint=segment,
        metadata={
            "stripe_event_id": event.get("id"),
            "stripe_object_id": obj.get("id"),
            "livemode": event.get("livemode"),
        },
        initial_event={
            "at": event.get("created"),
            "type": et,
            "source": "stripe",
            "stripe_event_id": event.get("id"),
        },
    )
