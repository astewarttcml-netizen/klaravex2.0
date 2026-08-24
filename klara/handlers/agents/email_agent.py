"""Inbound email agent — polls support@, hello@, and info@klaravex.com and routes to AI resolver."""

import logging
import os
import re
from typing import Any

import asyncpg
import httpx

from .resolver import _generate_steps, _query_kb
from ..lib.email import send_email
from ..lib.db import normalize_dsn
from ..classifier import classify_intent, ESCALATE_INTENTS

log = logging.getLogger("klaravex.agents.email_agent")

GRAPH_TENANT_ID = os.environ.get("MS_GRAPH_TENANT_ID", "")
GRAPH_CLIENT_ID = os.environ.get("MS_GRAPH_CLIENT_ID", "")
GRAPH_CLIENT_SECRET = os.environ.get("MS_GRAPH_CLIENT_SECRET", "")
SUPPORT_EMAIL = os.environ.get("MS_GRAPH_SENDER_EMAIL", "support@klaravex.com")
MONITORED_INBOXES = [
    SUPPORT_EMAIL,
    os.environ.get("MS_GRAPH_HELLO_EMAIL", "hello@klaravex.com"),
    os.environ.get("MS_GRAPH_INFO_EMAIL", "info@klaravex.com"),
]
DATABASE_URL = os.environ.get("DATABASE_URL", "")
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")

# Keyword sets retained for reference but classification is now delegated to
# classifier.classify_intent(). Kept here so any external code that imported
# them directly does not break (backward compatibility).
BREACH_KEYWORDS = {"hacked", "breach", "ransomware", "locked out", "stolen", "compromised"}
LEGAL_KEYWORDS = {"lawyer", "attorney", "lawsuit", "legal action", "sue", "court"}
REFUND_KEYWORDS = {"refund", "money back", "charge back", "chargeback", "dispute"}


async def _get_token() -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}/oauth2/v2.0/token",
            data={
                "client_id": GRAPH_CLIENT_ID,
                "client_secret": GRAPH_CLIENT_SECRET,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )
        r.raise_for_status()
        return r.json()["access_token"]


async def _get_unread_messages_for(token: str, mailbox: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{GRAPH_BASE}/users/{mailbox}/messages"
            "?$filter=isRead eq false&$top=20"
            "&$select=id,subject,from,body,receivedDateTime",
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code == 200:
            return r.json().get("value", [])
        log.warning("graph messages failed for %s: %s", mailbox, r.status_code)
        return []


async def _mark_read(token: str, message_id: str, mailbox: str = "") -> None:
    target = mailbox or SUPPORT_EMAIL
    async with httpx.AsyncClient(timeout=10) as client:
        await client.patch(
            f"{GRAPH_BASE}/users/{target}/messages/{message_id}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"isRead": True},
        )


async def _lookup_client(email: str) -> dict | None:
    if not DATABASE_URL:
        return None
    try:
        db = await asyncpg.connect(normalize_dsn(DATABASE_URL))
        try:
            row = await db.fetchrow(
                "SELECT id, name, skip_payment FROM klaravex_clients WHERE email = $1", email
            )
            return dict(row) if row else None
        finally:
            await db.close()
    except Exception as e:
        log.warning("client lookup failed: %s", e)
        return None


def _classify_email(subject: str, body: str) -> str:
    """
    Classify email intent using the shared classifier.

    Guard against single-keyword false positives: 'breach' / 'legal' require at
    least TWO matching keywords from their respective sets. One keyword in the
    body is too easy to trip ('hacked off about my printer' → not a breach).

    Maps classifier intents to the legacy labels used by process_inbox():
      legal_threat      -> "legal"
      security_incident -> "breach"
      refund_request    -> "refund"
      everything else   -> "tech_support"
    """
    text_lower = f"{subject} {body}".lower()
    result = classify_intent(f"{subject} {body}")
    intent = result["intent"]
    matched_keywords = result.get("keywords") or []

    if intent == "legal_threat":
        if len(matched_keywords) >= 2:
            return "legal"
        # Single weak hit — downgrade to tech_support and let Anthony catch it manually
        log.info("legal intent downgraded — only 1 keyword matched: %s", matched_keywords)
        return "tech_support"

    if intent == "security_incident":
        if len(matched_keywords) >= 2:
            return "breach"
        log.info("breach intent downgraded — only 1 keyword matched: %s", matched_keywords)
        return "tech_support"

    if intent == "refund_request":
        return "refund"
    return "tech_support"


# ── Loop / self-reply guards ────────────────────────────────────────────────

# Don't auto-reply to addresses ending in these — they are us.
INTERNAL_DOMAINS = (
    "klaravex.com", "klaravex.eu", "klaravex.io",
)

# Don't auto-reply to common no-reply/bounce/notification senders.
# `microsoftexchange` catches the hex-suffixed NDR sender pattern Exchange
# uses for delivery-failure replies (e.g. MicrosoftExchange329e71ec88…@…)
# — auto-replying to those triggers an infinite Undeliverable: Re:
# Undeliverable: … chain.
NO_REPLY_PATTERNS = (
    "noreply", "no-reply", "do-not-reply", "mailer-daemon",
    "postmaster", "bounce", "notification", "notifications@",
    "microsoftexchange",
)

# Banks, card issuers, payment processors, fintech business banking.
# Emails from these institutions are operational notifications (statements,
# fraud alerts, merchant-services updates) — never a real support request.
# Auto-replying to them creates compliance noise and abuse complaints.
FINANCIAL_DOMAINS = (
    # US card issuers
    "chase.com", "jpmorgan.com", "jpmchase.com",
    "amex.com", "americanexpress.com", "aexp.com",
    "discover.com", "discovercard.com",
    "capitalone.com", "citi.com", "citibank.com", "citicards.com",
    "wellsfargo.com", "bankofamerica.com", "bofa.com",
    "usbank.com", "navyfederal.com", "pnc.com", "ally.com",
    "schwab.com", "fidelity.com", "synchrony.com", "barclaycardus.com",
    # US fintech / business banking
    "mercury.com", "mercurybank.com", "brex.com", "ramp.com",
    "novo.co", "bluevine.com", "relayfi.com", "lili.co",
    # Payment processors / merchant services
    "stripe.com", "square.com", "squareup.com",
    "paypal.com", "venmo.com",
    "merchantservices.com", "firstdata.com", "fiserv.com",
    "worldpay.com", "paymentcloud.com", "authorize.net",
    "shopify.com", "shopify-billing.com",
    # EU banking
    "n26.com", "revolut.com", "wise.com", "transferwise.com",
    "deutsche-bank.de", "db.com", "sparkasse.de", "commerzbank.de",
    "ing.de", "ing-diba.de", "comdirect.de", "dkb.de", "postbank.de",
    "klarna.com",
)

# Local-parts (the part before @) that signal an automated/transactional
# sender from ANY domain — banks, vendors, SaaS billing, etc. Matches
# exact local-part or local-part-with-suffix (e.g. "billing.no-reply@").
TRANSACTIONAL_LOCAL_PARTS = (
    "billing", "statements", "statement", "alerts", "alert",
    "customerservice", "customer.service", "customer-service",
    "merchantservices", "merchant-services", "merchant_services",
    "fraudalerts", "fraud", "fraud-alerts", "disputes", "dispute",
    "cardservices", "card-services", "cards",
    "payments", "payment", "transactions", "transaction",
    "accountservices", "account-services", "accountalerts",
    "receipt", "receipts", "invoice", "invoices",
    "no_reply", "donotreply", "do_not_reply",
    "automated", "automatic", "auto",
    "system", "sysadmin", "admin",
)

# Subject-line patterns that signal an automated transactional email.
# Used as a fallback when sender domain isn't on the FINANCIAL_DOMAINS list
# (e.g., a smaller credit union, a payroll vendor, a SaaS billing system).
TRANSACTIONAL_SUBJECT_PATTERNS = (
    "statement", "your bill", "your balance", "your account",
    "transaction notification", "transaction alert",
    "fraud alert", "card alert", "account alert", "account update",
    "payment received", "payment posted", "payment due", "payment confirmation",
    "verify your", "verification code", "two-factor", "2fa",
    "security code", "account verification",
    "wire transfer", "ach transfer", "deposit notification",
    "withdrawal", "balance update", "credit card statement",
    "your invoice", "invoice from", "receipt for", "receipt from",
    "auto-renewal", "subscription renewed",
)


def _domain_of(addr: str) -> str:
    if not addr or "@" not in addr:
        return ""
    return addr.split("@", 1)[1].lower().strip().rstrip(".")


def _local_of(addr: str) -> str:
    if not addr or "@" not in addr:
        return ""
    return addr.split("@", 1)[0].lower().strip()


def _is_internal_sender(from_addr: str) -> bool:
    """True when the sender is one of our own mailboxes — never auto-reply to self."""
    if not from_addr or "@" not in from_addr:
        return True  # treat malformed as internal to be safe
    lower = from_addr.lower().strip()
    if any(lower.endswith("@" + d) for d in INTERNAL_DOMAINS):
        return True
    if any(p in lower for p in NO_REPLY_PATTERNS):
        return True
    return False


def _is_financial_sender(from_addr: str) -> bool:
    """True when the sender's domain is a known bank, card issuer, fintech, or payment processor.

    Matches the full domain AND any subdomain (e.g., 'alerts.chase.com' → chase.com).
    """
    domain = _domain_of(from_addr)
    if not domain:
        return False
    for known in FINANCIAL_DOMAINS:
        if domain == known or domain.endswith("." + known):
            return True
    return False


def _is_transactional_sender(from_addr: str) -> bool:
    """True when the sender's local-part looks like an automated/transactional address.

    Matches exact local-part, or local-part starting with the keyword followed
    by '.', '-', '_', or '@' (e.g., 'billing.alerts@', 'statements-no-reply@').
    """
    local = _local_of(from_addr)
    if not local:
        return False
    for p in TRANSACTIONAL_LOCAL_PARTS:
        if local == p:
            return True
        if local.startswith(p + ".") or local.startswith(p + "-") or local.startswith(p + "_"):
            return True
    return False


def _is_transactional_subject(subject: str) -> bool:
    """True when the subject line matches a known automated-notification pattern."""
    if not subject:
        return False
    lower = subject.lower()
    return any(p in lower for p in TRANSACTIONAL_SUBJECT_PATTERNS)


def _should_skip_autoreply(from_addr: str, subject: str) -> tuple[bool, str]:
    """Compose all skip rules. Returns (skip, reason)."""
    if _is_internal_sender(from_addr):
        return True, "internal_or_noreply"
    if _is_financial_sender(from_addr):
        return True, "financial_institution"
    if _is_transactional_sender(from_addr):
        return True, "transactional_local_part"
    if _is_transactional_subject(subject):
        return True, "transactional_subject"
    return False, ""


async def _was_auto_replied_recently(from_addr: str, hours: int = 24) -> bool:
    """True if we auto-replied to this address in the last `hours`.

    Backed by klaravex_clients.metadata.last_autoreply_at. No new schema —
    just rides on the existing client row's metadata jsonb.
    """
    if not from_addr or "@" not in from_addr:
        return True
    import asyncpg as _asyncpg
    from datetime import datetime, timedelta, timezone
    try:
        conn = await _asyncpg.connect(normalize_dsn(DATABASE_URL))
        try:
            row = await conn.fetchrow(
                "SELECT metadata FROM klaravex_clients WHERE email = $1",
                from_addr.lower(),
            )
            if not row:
                return False
            meta = row["metadata"] or {}
            if isinstance(meta, str):
                meta = json.loads(meta)
            last_iso = meta.get("last_autoreply_at")
            if not last_iso:
                return False
            try:
                last = datetime.fromisoformat(str(last_iso).replace("Z", "+00:00"))
            except Exception:
                return False
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            return last >= cutoff
        finally:
            await conn.close()
    except Exception as exc:
        log.warning("autoreply lookup failed for %s: %s", from_addr, exc)
        return False


async def _mark_auto_replied(from_addr: str) -> None:
    """Stamp klaravex_clients.metadata.last_autoreply_at = now() for this email.

    Creates the row if it doesn't exist (best-effort).
    """
    if not from_addr or "@" not in from_addr:
        return
    import asyncpg as _asyncpg
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        conn = await _asyncpg.connect(normalize_dsn(DATABASE_URL))
        try:
            existing = await conn.fetchval(
                "SELECT 1 FROM klaravex_clients WHERE email = $1",
                from_addr.lower(),
            )
            if not existing:
                await conn.execute(
                    """
                    INSERT INTO klaravex_clients (email, segment, metadata)
                    VALUES ($1, 'consumer', $2::jsonb)
                    ON CONFLICT (email) DO NOTHING
                    """,
                    from_addr.lower(),
                    json.dumps({"source": "email_agent_autoreply", "last_autoreply_at": now_iso}),
                )
            else:
                await conn.execute(
                    """
                    UPDATE klaravex_clients
                       SET metadata = metadata || $2::jsonb,
                           updated_at = now()
                     WHERE email = $1
                    """,
                    from_addr.lower(),
                    json.dumps({"last_autoreply_at": now_iso}),
                )
        finally:
            await conn.close()
    except Exception as exc:
        log.warning("autoreply stamp failed for %s: %s", from_addr, exc)


async def _send_payment_link_email(to: str, issue: str) -> str:
    """Build a Stripe checkout session and return the URL, or '' on failure."""
    if not STRIPE_SECRET_KEY:
        return ""
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{"price": "price_1TfPfR14iRJDip4yJkg8GPBs", "quantity": 1}],
            customer_email=to,
            success_url="https://klaravex.com/personal/thanks/?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="https://klaravex.com/personal/pricing/",
            metadata={"intent": "per-incident", "source": "email", "issue": issue[:200]},
        )
        return session.url or ""
    except Exception as e:
        log.warning("stripe session create failed: %s", e)
        return ""


def _signature(inbox: str) -> str:
    """Return the appropriate sign-off block for the given inbox address."""
    if "hello" in inbox:
        return "Klaravex\nhello@klaravex.com"
    if "info" in inbox:
        return "Klaravex\ninfo@klaravex.com"
    return "Klaravex Support\nsupport@klaravex.com"


async def process_inbox() -> dict[str, Any]:
    """Poll all monitored inboxes and process unread messages. Called by cron or webhook."""
    if not (GRAPH_TENANT_ID and GRAPH_CLIENT_ID and GRAPH_CLIENT_SECRET):
        log.warning("MS Graph credentials not set; email agent skipped")
        return {"processed": 0}

    token = await _get_token()
    total_processed = 0
    results_by_inbox: dict[str, int] = {}

    for inbox in MONITORED_INBOXES:
        messages = await _get_unread_messages_for(token, inbox)
        processed = 0

        for msg in messages:
            msg_id = msg.get("id", "")
            subject = msg.get("subject", "") or ""
            from_addr = msg.get("from", {}).get("emailAddress", {}).get("address", "")
            body_content = msg.get("body", {}).get("content", "") or ""
            # Strip HTML tags for classification and AI context
            body_text = re.sub(r"<[^>]+>", " ", body_content).strip()[:1000]

            log.info("processing email inbox=%s from=%s subject=%r", inbox, from_addr, subject[:60])

            # GUARD 1: Skip internal Klaravex senders + no-reply addresses +
            # banks / card issuers / payment processors + transactional senders
            # (billing@, statements@, alerts@, …) + transactional-subject patterns
            # ("Your statement is ready", "Fraud alert", …).
            #
            # WHY: this agent's `else` branch sends a Stripe payment link asking
            # for $79 — auto-replying to a credit card company asking THEM to pay
            # us looks like a scam, gets us flagged, and burns merchant trust.
            # See: 2026-06-10 Anthony bug report.
            skip, skip_reason = _should_skip_autoreply(from_addr, subject)
            if skip:
                log.info("skipping %s (reason=%s)", from_addr, skip_reason)
                await _mark_read(token, msg_id, mailbox=inbox)
                processed += 1
                continue

            # GUARD 2: Don't auto-reply twice to the same person inside 24h.
            # Prevents thread loops (someone replies to our reply with a
            # keyword) and prevents reply-storms after a backlog drain.
            if await _was_auto_replied_recently(from_addr, hours=24):
                log.info("skipping %s — already auto-replied within 24h", from_addr)
                await _mark_read(token, msg_id, mailbox=inbox)
                processed += 1
                continue

            intent = _classify_email(subject, body_text)
            client = await _lookup_client(from_addr)
            is_vip = client and client.get("skip_payment")
            sig = _signature(inbox)

            # Mark read immediately to avoid reprocessing on next poll
            await _mark_read(token, msg_id, mailbox=inbox)

            if intent == "legal":
                # GUARD 3: ESCALATE-ONLY. Never auto-reply to legal threats —
                # Anthony reviews and crafts the response personally. The old
                # canned acknowledgement was scary for both sides.
                await send_email(
                    to=os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com"),
                    subject=f"[LEGAL ESCALATION — ANTHONY REPLY NEEDED] {from_addr}: {subject[:60]}",
                    body=(
                        f"Inbox: {inbox}\nSender: {from_addr}\nSubject: {subject}\n\n"
                        f"Message:\n{body_text}\n\n"
                        f"--- The AI agent did NOT auto-reply. You must reply manually. ---"
                    ),
                )

            elif intent == "breach":
                # GUARD 3: ESCALATE-ONLY. Never auto-reply to suspected breaches.
                # The canned "sign out of everything" template was firing on
                # false positives. Anthony reviews and replies if real.
                await send_email(
                    to=os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com"),
                    subject=f"[BREACH ESCALATION — ANTHONY REPLY NEEDED] {from_addr}: {subject[:60]}",
                    body=(
                        f"Inbox: {inbox}\nSender: {from_addr}\nSubject: {subject}\n\n"
                        f"Message:\n{body_text}\n\n"
                        f"--- The AI agent did NOT auto-reply. Triage manually. ---"
                    ),
                )

            elif intent == "refund":
                # AI never issues refunds — escalate to team and send hold acknowledgement
                await send_email(
                    to=os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com"),
                    subject=f"[REFUND REQUEST] Email from {from_addr}: {subject[:60]}",
                    body=f"Inbox: {inbox}\nSender: {from_addr}\nSubject: {subject}\n\nMessage:\n{body_text}",
                )
                await send_email(
                    to=from_addr,
                    subject=f"Re: {subject}",
                    body=(
                        "Thank you for reaching out. We have received your request and a member of our team "
                        "will review it and get back to you within 24 hours.\n\n"
                        f"{sig}"
                    ),
                )

            else:
                # Tech support — generate AI fix steps and deliver them (or gate on payment)
                issue = f"{subject}: {body_text[:300]}"
                kb_context = await _query_kb(issue)
                steps = await _generate_steps(issue, kb_context, attempt=0)
                steps_text = "\n".join(steps)

                if is_vip:
                    # VIP client (skip_payment=True) — deliver steps immediately, no payment gate
                    first_name = ""
                    if client and client.get("name"):
                        first_name = " " + client["name"].split()[0]
                    await send_email(
                        to=from_addr,
                        subject=f"Re: {subject} — Your fix steps",
                        body=(
                            f"Hi{first_name},\n\n"
                            "Here are the steps to resolve your issue:\n\n"
                            f"{steps_text}\n\n"
                            "Reply to this email if any step doesn't work and we'll send a different approach.\n\n"
                            f"{sig}"
                        ),
                    )
                else:
                    # Unknown / unpaid client — send payment link first
                    payment_url = await _send_payment_link_email(from_addr, issue)
                    if payment_url:
                        await send_email(
                            to=from_addr,
                            subject=f"Re: {subject} — Get help now",
                            body=(
                                "Thanks for reaching out to Klaravex.\n\n"
                                "Our AI support system can resolve this for you. "
                                "A complete fix session is $79 — once payment is confirmed, "
                                "we will send you step-by-step instructions immediately.\n\n"
                                f"Pay here: {payment_url}\n\n"
                                "The link is valid for 24 hours. "
                                "Questions? Call +1 (424) 348-6010.\n\n"
                                f"{sig}"
                            ),
                        )
                    else:
                        # Stripe not configured — fall back to a generic hold reply
                        await send_email(
                            to=from_addr,
                            subject=f"Re: {subject}",
                            body=(
                                "Thanks for reaching out to Klaravex. "
                                "Our team will get back to you within 24 hours.\n\n"
                                f"{sig}"
                            ),
                        )

            processed += 1

        results_by_inbox[inbox] = processed
        total_processed += processed

    return {
        "processed": total_processed,
        "by_inbox": results_by_inbox,
    }
