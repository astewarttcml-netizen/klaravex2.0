"""A6/A7/A8 archetype workflows — projects, block hours, procurement.

Three archetypes implemented here:

  A6 — Fixed-Fee Project (M365 migration, network overhaul, etc.)
       Phases: scoping → SOW → execution → handoff → warranty
       Milestone billing: each sign-off triggers a Stripe invoice
       Entry points:
         handle_checkout_completed(event)  → Stripe checkout.session.completed
         request_project(...)              → called from chat / portal
         record_work_log(...)              → Anthony logs hours against a phase
         close_project(project_id)         → finalize + schedule warranty check

  A7 — Block-Hour Support (10 h and 25 h pre-purchased blocks)
       Usage tracking, burn-rate alerts (75/50/25/0%), auto top-up link
       Entry points:
         handle_checkout_completed(event)  → Stripe checkout.session.completed
         log_hours(...)                    → deduct hours from a block
         get_balance(client_email)         → current balance in hours
         send_topup_link(client_email)     → manual top-up trigger

  A8 — Procurement / Resale
       Quote → approval → order → delivery tracking
       Margin is tracked per line item; purchases > $5 000 require Anthony approval
       Entry points:
         request_procurement(...)          → client or Klara AI initiates a request
         approve_procurement(token)        → client approves the quote
         mark_ordered(proc_id, po_ref)     → Anthony logs the purchase
         mark_delivered(proc_id)           → item delivered, invoice issued

All public coroutines are idempotent where possible.  Errors are caught
and returned in result dicts rather than raised, so callers do not tear
down the webhook dispatch loop.

Wiring in stripe_webhook._dispatch_event():

    from .lib import project_workflows as pw_lib

    # A6 + A7: checkout.session.completed
    _A6_A7_A8_SKUS = {*pw_lib.A6_SKUS, *pw_lib.A7_SKUS, *pw_lib.A8_SKUS}
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        sku = (session.get("metadata") or {}).get("sku", "").lower()
        if sku in _A6_A7_A8_SKUS:
            result = await pw_lib.handle_checkout_completed(session)
            log.info("A6/A7/A8 checkout: action=%s", result.get("action"))
"""

import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import stripe

from .db import get_pool
from .email import send_email
from .escalation import escalate
from . import tickets as tickets_lib

log = logging.getLogger("klaravex.project_workflows")

# ── environment ────────────────────────────────────────────────────────────────

PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "support@klaravex.com")
ANTHONY_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
CALENDLY_KICKOFF_URL = os.environ.get("CALENDLY_KICKOFF_URL", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ── SKU registries ─────────────────────────────────────────────────────────────

A6_SKUS: frozenset[str] = frozenset({
    "m365-migration",
    "m365-setup",
    "azure-project",
    "azure-review",
    "intune-rollout",
    "windows-server-project",
    "backup-dr-setup",
    "powershell-project",
    "monitoring-setup",
    "firewall-deploy",
    "ai-automation-project",
    "office-it-relocation",
})

A7_SKUS: frozenset[str] = frozenset({
    "remote-block-10hr",
    "remote-block-25hr",
})

A8_SKUS: frozenset[str] = frozenset({
    "procurement-flat",
})

# Hours per SKU block
_A7_HOURS: dict[str, int] = {
    "remote-block-10hr": 10,
    "remote-block-25hr": 25,
}

# Procurement approval threshold (purchases above this require Anthony's OK)
_PROCUREMENT_ANTHONY_THRESHOLD_USD = 5_000.0

# Burn-rate alert thresholds (fraction of original block remaining)
_A7_ALERT_THRESHOLDS = [0.75, 0.50, 0.25, 0.0]


# ══════════════════════════════════════════════════════════════════════════════
# ── shared helpers ────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def _portal(path: str) -> str:
    return f"{PORTAL_BASE_URL.rstrip('/')}{path}"


async def _alert_anthony(subject: str, body: str) -> None:
    """Best-effort email + Telegram alert to Anthony. Never raises."""
    try:
        await send_email(to=ANTHONY_EMAIL, subject=subject, body=body)
    except Exception as exc:
        log.warning("alert email to Anthony failed: %s", exc)
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    telegram_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if telegram_token and telegram_chat:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as http:
                await http.post(
                    f"https://api.telegram.org/bot{telegram_token}/sendMessage",
                    json={"chat_id": telegram_chat, "text": f"{subject}\n\n{body}"},
                )
        except Exception as exc:
            log.warning("Telegram alert to Anthony failed: %s", exc)


async def _resolve_customer(obj: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract (email, name, stripe_customer_id) from a Stripe object."""
    customer_id = obj.get("customer")
    email = (
        (obj.get("customer_details") or {}).get("email")
        or obj.get("customer_email")
        or obj.get("receipt_email")
    )
    name = (obj.get("customer_details") or {}).get("name")
    if not email and customer_id:
        try:
            cust = stripe.Customer.retrieve(customer_id)
            email = cust.get("email")
            name = cust.get("name")
        except Exception as exc:
            log.warning("customer retrieve failed (%s): %s", customer_id, exc)
    return email, name, customer_id


def _sku_from_checkout(session: dict) -> str:
    """Return lowercase SKU from a checkout session's metadata or line items."""
    sku = ((session.get("metadata") or {}).get("sku") or "").lower()
    return sku


# ══════════════════════════════════════════════════════════════════════════════
# ── A6 — Fixed-Fee Project ────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

# Default milestone structure by SKU family.  Klara AI uses these when no bespoke
# scope is provided so a basic project plan can be sent immediately.
_A6_DEFAULT_MILESTONES: dict[str, list[dict[str, Any]]] = {
    "m365-migration": [
        {"sequence": 1, "title": "Discovery & pre-flight assessment",     "budget_pct": 20, "days": 5},
        {"sequence": 2, "title": "Pilot migration (5 users)",             "budget_pct": 30, "days": 10},
        {"sequence": 3, "title": "Full tenant cutover & validation",      "budget_pct": 35, "days": 20},
        {"sequence": 4, "title": "Handoff documentation & training",      "budget_pct": 15, "days": 25},
    ],
    "firewall-deploy": [
        {"sequence": 1, "title": "Site survey & design approval",         "budget_pct": 25, "days": 3},
        {"sequence": 2, "title": "Hardware deployment & baseline config", "budget_pct": 40, "days": 8},
        {"sequence": 3, "title": "Policy tuning & client sign-off",       "budget_pct": 35, "days": 12},
    ],
    "_default": [
        {"sequence": 1, "title": "Scoping & planning",   "budget_pct": 25, "days": 5},
        {"sequence": 2, "title": "Execution phase 1",    "budget_pct": 35, "days": 15},
        {"sequence": 3, "title": "Execution phase 2",    "budget_pct": 25, "days": 25},
        {"sequence": 4, "title": "Handoff & closeout",   "budget_pct": 15, "days": 30},
    ],
}


def _default_milestones(sku: str) -> list[dict[str, Any]]:
    return _A6_DEFAULT_MILESTONES.get(sku, _A6_DEFAULT_MILESTONES["_default"])


async def _create_a6_project(
    *,
    client_email: str,
    name: Optional[str],
    sku: str,
    stripe_customer_id: Optional[str],
    stripe_session_id: Optional[str],
    budget_usd: float,
    scope_summary: str,
    company: Optional[str],
) -> dict[str, Any]:
    """Insert project + default milestones. Returns project_id and milestone count."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        client_id = await conn.fetchval(
            "SELECT id FROM klaravex_clients WHERE email = $1",
            client_email.lower(),
        )

        # Idempotency: one project per stripe session
        if stripe_session_id:
            existing = await conn.fetchval(
                "SELECT id::text FROM klaravex_projects WHERE metadata->>'stripe_session_id' = $1",
                stripe_session_id,
            )
            if existing:
                log.info("A6 project already exists for session %s — skipping", stripe_session_id)
                return {"project_id": existing, "created": False}

        project_id = await conn.fetchval(
            """
            INSERT INTO klaravex_projects
              (client_id, client_email, title, scope_summary, total_budget_usd,
               sku, status, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, 'scoping', $7::jsonb)
            RETURNING id::text
            """,
            client_id,
            client_email.lower(),
            _sku_title(sku),
            scope_summary,
            budget_usd,
            sku,
            json.dumps({
                "stripe_session_id": stripe_session_id,
                "stripe_customer_id": stripe_customer_id,
                "company": company,
                "client_name": name,
            }),
        )

        milestones = _default_milestones(sku)
        for m in milestones:
            due = datetime.now(tz=timezone.utc) + timedelta(days=m["days"])
            await conn.execute(
                """
                INSERT INTO klaravex_project_milestones
                  (project_id, sequence, title, budget_percentage, estimated_due_at, signoff_token, status)
                VALUES ($1, $2, $3, $4, $5, $6, 'pending')
                """,
                project_id,
                m["sequence"],
                m["title"],
                float(m["budget_pct"]),
                due,
                secrets.token_urlsafe(24),
            )

    log.info("A6 project created: %s sku=%s client=%s $%.0f", project_id, sku, client_email, budget_usd)
    return {"project_id": project_id, "created": True, "milestone_count": len(milestones)}


def _sku_title(sku: str) -> str:
    titles = {
        "m365-migration":         "Microsoft 365 Migration",
        "m365-setup":             "Microsoft 365 Setup",
        "azure-project":          "Azure Infrastructure Project",
        "azure-review":           "Azure Environment Review",
        "intune-rollout":         "Intune Endpoint Rollout",
        "windows-server-project": "Windows Server Project",
        "backup-dr-setup":        "Backup & Disaster Recovery Setup",
        "powershell-project":     "PowerShell Automation Project",
        "monitoring-setup":       "Monitoring & Alerting Setup",
        "firewall-deploy":        "Firewall Deployment",
        "ai-automation-project":  "AI Automation Project",
        "office-it-relocation":   "Office IT Relocation",
    }
    return titles.get(sku, sku.replace("-", " ").title())


async def _send_a6_kickoff_email(
    *,
    to: str,
    name: Optional[str],
    project_id: str,
    sku: str,
    company: Optional[str],
    budget_usd: float,
) -> None:
    greeting = f"Hi {name}," if name else "Hi,"
    org_line = f" for {company}" if company else ""
    title = _sku_title(sku)
    portal_url = _portal(f"/portal/projects/{project_id}")
    kickoff_url = CALENDLY_KICKOFF_URL or _portal("/portal/schedule")
    body = (
        f"{greeting}\n\n"
        f"Thank you for booking your {title} project{org_line} with Klaravex.\n\n"
        f"Here is what happens next:\n"
        f"  1. Review your project plan (milestones + timeline) in your portal:\n"
        f"     {portal_url}\n\n"
        f"  2. Schedule your kickoff call so we can align on scope, access requirements,\n"
        f"     and your preferred cutover window:\n"
        f"     {kickoff_url}\n\n"
        f"  3. We will send your Statement of Work within one business day of the kickoff call.\n"
        f"     Each milestone is invoiced upon written sign-off — total project fee:\n"
        f"     ${budget_usd:,.0f} USD.\n\n"
        f"If you have urgent questions before the kickoff call, reply to this email or\n"
        f"start a chat at klaravex.com — our AI coordinator responds immediately.\n\n"
        f"— The Klaravex Team\n"
        f"support@klaravex.com\n"
    )
    await send_email(
        to=to,
        subject=f"Your Klaravex {title} project — next steps",
        body=body,
    )


async def handle_a6_checkout(session: dict[str, Any]) -> dict[str, Any]:
    """Kick off an A6 project when checkout.session.completed fires.

    Called from handle_checkout_completed() when the SKU is in A6_SKUS.
    Returns a result dict; never raises.
    """
    sku = _sku_from_checkout(session)
    email, name, stripe_customer_id = await _resolve_customer(session)
    if not email:
        return {"action": "error", "reason": "no_email", "archetype": "A6"}

    meta = session.get("metadata") or {}
    company = meta.get("company")
    scope_summary = meta.get("scope_summary") or f"Client-submitted {_sku_title(sku)} project."
    budget_usd = float((session.get("amount_total") or 0)) / 100.0

    # 1. Upsert client record.
    try:
        await tickets_lib.get_or_create_client(
            email,
            segment="b2b",
            name=name,
            stripe_customer_id=stripe_customer_id,
            company=company,
            metadata={"sku": sku, "source": "stripe_a6_checkout"},
        )
    except Exception as exc:
        log.warning("A6 client upsert failed: %s", exc)

    # 2. Create project + milestones (idempotent via session_id).
    project_result: dict[str, Any] = {}
    try:
        project_result = await _create_a6_project(
            client_email=email,
            name=name,
            sku=sku,
            stripe_customer_id=stripe_customer_id,
            stripe_session_id=session.get("id"),
            budget_usd=budget_usd,
            scope_summary=scope_summary,
            company=company,
        )
    except Exception as exc:
        log.warning("A6 project creation failed: %s", exc)
        return {"action": "error", "reason": str(exc), "archetype": "A6"}

    project_id = project_result.get("project_id")

    # 3. Open a scoping ticket.
    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=email,
            subject=f"A6 project scoping — {_sku_title(sku)} ({company or email})",
            severity="standard",
            status="open",
            source="stripe",
            archetype="A6",
            sku=sku,
            summary=f"New project purchased. Kickoff email sent. Scope: {scope_summary[:200]}",
            segment_hint="b2b",
            metadata={"project_id": project_id, "stripe_session_id": session.get("id")},
        )
    except Exception as exc:
        log.warning("A6 scoping ticket failed: %s", exc)

    # 4. Email client.
    if project_result.get("created", True):
        try:
            await _send_a6_kickoff_email(
                to=email,
                name=name,
                project_id=project_id,
                sku=sku,
                company=company,
                budget_usd=budget_usd,
            )
        except Exception as exc:
            log.warning("A6 kickoff email failed for %s: %s", email, exc)

    # 5. Alert Anthony — new project in scope.
    alert_subject = f"[Klaravex A6] New project — {_sku_title(sku)} ({company or email})"
    alert_body = (
        f"A new fixed-fee project has been purchased.\n\n"
        f"SKU:       {sku}\n"
        f"Client:    {name or '(not provided)'} <{email}>\n"
        f"Company:   {company or '(not provided)'}\n"
        f"Budget:    ${budget_usd:,.0f} USD\n"
        f"Project:   {_portal(f'/portal/projects/{project_id}')}\n"
        f"Ticket:    {ticket_id or '—'}\n\n"
        f"Action: schedule kickoff call, review scope, send SOW within 1 business day.\n"
        f"Kickoff URL: {CALENDLY_KICKOFF_URL or '(set CALENDLY_KICKOFF_URL)'}\n"
    )
    await _alert_anthony(alert_subject, alert_body)

    return {
        "action": "a6_project_initiated",
        "archetype": "A6",
        "sku": sku,
        "email": email,
        "project_id": project_id,
        "ticket_id": ticket_id,
        "milestone_count": project_result.get("milestone_count"),
    }


async def request_project(
    *,
    client_email: str,
    sku: str,
    scope_summary: str,
    budget_usd: float,
    company: Optional[str] = None,
    name: Optional[str] = None,
) -> dict[str, Any]:
    """Create an A6 project from a portal / chat request (no Stripe event).

    Use when Anthony or Klara AI initiates a project outside the checkout flow
    (e.g., upsell from a managed plan, SOW-first engagement).
    """
    try:
        await tickets_lib.get_or_create_client(
            client_email,
            segment="b2b",
            name=name,
            company=company,
            metadata={"sku": sku, "source": "manual_project_request"},
        )
    except Exception as exc:
        log.warning("A6 client upsert (manual) failed: %s", exc)

    project_result = await _create_a6_project(
        client_email=client_email,
        name=name,
        sku=sku,
        stripe_customer_id=None,
        stripe_session_id=None,
        budget_usd=budget_usd,
        scope_summary=scope_summary,
        company=company,
    )

    await _alert_anthony(
        subject=f"[Klaravex A6] Manual project request — {_sku_title(sku)} ({company or client_email})",
        body=(
            f"Project requested outside of Stripe checkout.\n\n"
            f"SKU:    {sku}\n"
            f"Client: {client_email}\n"
            f"Budget: ${budget_usd:,.0f} USD\n"
            f"Scope:  {scope_summary[:300]}\n"
            f"Portal: {_portal('/portal/projects/' + str(project_result.get('project_id', '')))}\n"
        ),
    )
    return project_result


async def record_work_log(
    *,
    project_id: str,
    milestone_sequence: int,
    hours_logged: float,
    notes: str,
    logged_by: str = "anthony",
) -> dict[str, Any]:
    """Log hours Anthony worked on a project milestone.

    Stores the entry in klaravex_project_work_logs and updates the milestone
    status to 'in_progress' if it was still 'pending'.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        milestone = await conn.fetchrow(
            """
            SELECT id, status, title FROM klaravex_project_milestones
             WHERE project_id = $1 AND sequence = $2
            """,
            project_id,
            milestone_sequence,
        )
        if not milestone:
            return {"ok": False, "error": "milestone_not_found"}

        log_id = await conn.fetchval(
            """
            INSERT INTO klaravex_project_work_logs
              (project_id, milestone_id, hours_logged, notes, logged_by)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id::text
            """,
            project_id,
            milestone["id"],
            hours_logged,
            notes,
            logged_by,
        )
        if milestone["status"] == "pending":
            await conn.execute(
                "UPDATE klaravex_project_milestones SET status='in_progress', updated_at=now() WHERE id=$1",
                milestone["id"],
            )

    log.info(
        "work log: project=%s milestone=%d %.1fh by %s",
        project_id, milestone_sequence, hours_logged, logged_by,
    )
    return {"ok": True, "log_id": log_id, "milestone_id": str(milestone["id"])}


async def close_project(project_id: str) -> dict[str, Any]:
    """Mark project closed and schedule 30-day warranty check email."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT client_email, title, sku FROM klaravex_projects WHERE id=$1",
            project_id,
        )
        if not row:
            return {"ok": False, "error": "project_not_found"}
        await conn.execute(
            """
            UPDATE klaravex_projects
               SET status='closed',
                   warranty_check_at=now() + interval '30 days',
                   updated_at=now()
             WHERE id=$1
            """,
            project_id,
        )

    try:
        await send_email(
            to=row["client_email"],
            subject=f"Your Klaravex {row['title']} project is complete",
            body=(
                f"Hi,\n\n"
                f"Your {row['title']} project has been completed and closed.\n\n"
                f"Project documentation and the full change log are available in your portal:\n"
                f"  {_portal(f'/portal/projects/{project_id}')}\n\n"
                f"We will check in 30 days to confirm everything is running smoothly.\n"
                f"If you have any questions before then, reply to this email or start a chat\n"
                f"at klaravex.com.\n\n"
                f"— The Klaravex Team\n"
                f"support@klaravex.com\n"
            ),
        )
    except Exception as exc:
        log.warning("A6 close email failed for %s: %s", row["client_email"], exc)

    log.info("A6 project closed: %s", project_id)
    return {"ok": True, "project_id": project_id, "warranty_check_in_days": 30}


async def send_warranty_checks() -> dict[str, int]:
    """Cron entry point: send 30-day stability checks for recently closed projects."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, client_email, title
              FROM klaravex_projects
             WHERE status = 'closed'
               AND warranty_check_at IS NOT NULL
               AND warranty_check_at <= now()
               AND warranty_email_sent_at IS NULL
            """
        )

    sent = 0
    errors = 0
    for r in rows:
        try:
            await send_email(
                to=r["client_email"],
                subject=f"30-day check-in: {r['title']}",
                body=(
                    f"Hi,\n\n"
                    f"It has been 30 days since your {r['title']} project was completed.\n\n"
                    f"Is everything running as expected? If you have noticed any issues or have\n"
                    f"questions about what was delivered, reply to this email — we will help\n"
                    f"you promptly.\n\n"
                    f"If you would like ongoing managed IT support, we would be happy to discuss\n"
                    f"our managed plans:\n"
                    f"  {_portal('/portal/plans')}\n\n"
                    f"— The Klaravex Team\n"
                    f"support@klaravex.com\n"
                ),
            )
            pool2 = await get_pool()
            async with pool2.acquire() as conn2:
                await conn2.execute(
                    "UPDATE klaravex_projects SET warranty_email_sent_at=now() WHERE id=$1",
                    r["id"],
                )
            sent += 1
        except Exception as exc:
            log.warning("warranty check email failed for project %s: %s", r["id"], exc)
            errors += 1

    return {"sent": sent, "errors": errors, "candidates": len(rows)}


# ══════════════════════════════════════════════════════════════════════════════
# ── A7 — Block-Hour Support ───────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

async def _create_or_top_up_block(
    *,
    client_email: str,
    sku: str,
    stripe_customer_id: Optional[str],
    stripe_session_id: Optional[str],
    paid_amount_usd: float,
) -> dict[str, Any]:
    """Create a new hour block or top up an existing open one.

    Returns {"block_id": ..., "hours_total": ..., "hours_remaining": ..., "created": bool}
    """
    hours = _A7_HOURS.get(sku, 10)
    pool = await get_pool()
    async with pool.acquire() as conn:
        client_id = await conn.fetchval(
            "SELECT id FROM klaravex_clients WHERE email=$1",
            client_email.lower(),
        )

        # Idempotency: one block per stripe session
        if stripe_session_id:
            existing_id = await conn.fetchval(
                "SELECT id::text FROM klaravex_hour_blocks WHERE metadata->>'stripe_session_id' = $1",
                stripe_session_id,
            )
            if existing_id:
                bal = await conn.fetchrow(
                    "SELECT hours_total, hours_remaining FROM klaravex_hour_blocks WHERE id=$1",
                    existing_id,
                )
                return {
                    "block_id": existing_id,
                    "hours_total": bal["hours_total"],
                    "hours_remaining": bal["hours_remaining"],
                    "created": False,
                }

        block_id = await conn.fetchval(
            """
            INSERT INTO klaravex_hour_blocks
              (client_id, client_email, sku, hours_total, hours_remaining,
               paid_amount_usd, status, metadata)
            VALUES ($1, $2, $3, $4, $4, $5, 'active', $6::jsonb)
            RETURNING id::text
            """,
            client_id,
            client_email.lower(),
            sku,
            hours,
            paid_amount_usd,
            json.dumps({
                "stripe_session_id": stripe_session_id,
                "stripe_customer_id": stripe_customer_id,
            }),
        )

    log.info("A7 block created: %s %dh client=%s", block_id, hours, client_email)
    return {"block_id": block_id, "hours_total": hours, "hours_remaining": hours, "created": True}


async def handle_a7_checkout(session: dict[str, Any]) -> dict[str, Any]:
    """Kick off an A7 block-hour subscription when checkout.session.completed fires."""
    sku = _sku_from_checkout(session)
    email, name, stripe_customer_id = await _resolve_customer(session)
    if not email:
        return {"action": "error", "reason": "no_email", "archetype": "A7"}

    hours = _A7_HOURS.get(sku, 10)
    paid_amount_usd = float((session.get("amount_total") or 0)) / 100.0

    # 1. Upsert client.
    try:
        await tickets_lib.get_or_create_client(
            email,
            segment="b2b",
            name=name,
            stripe_customer_id=stripe_customer_id,
            metadata={"sku": sku, "source": "stripe_a7_checkout"},
        )
    except Exception as exc:
        log.warning("A7 client upsert failed: %s", exc)

    # 2. Create hour block (idempotent).
    block_result: dict[str, Any] = {}
    try:
        block_result = await _create_or_top_up_block(
            client_email=email,
            sku=sku,
            stripe_customer_id=stripe_customer_id,
            stripe_session_id=session.get("id"),
            paid_amount_usd=paid_amount_usd,
        )
    except Exception as exc:
        log.warning("A7 block creation failed: %s", exc)
        return {"action": "error", "reason": str(exc), "archetype": "A7"}

    block_id = block_result.get("block_id")

    # 3. Open a ticket.
    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=email,
            subject=f"A7 block-hours purchased — {sku} ({hours}h)",
            severity="low",
            status="resolved",
            source="stripe",
            archetype="A7",
            sku=sku,
            summary=f"{hours}h block purchased. Block ID: {block_id}. Balance: {hours}h remaining.",
            segment_hint="b2b",
            metadata={"block_id": block_id, "stripe_session_id": session.get("id")},
        )
    except Exception as exc:
        log.warning("A7 ticket creation failed: %s", exc)

    # 4. Welcome email.
    if block_result.get("created", True):
        portal_url = _portal(f"/portal/hours/{block_id}")
        try:
            await send_email(
                to=email,
                subject=f"Your Klaravex {hours}-hour support block is ready",
                body=(
                    f"Hi{' ' + name if name else ''},\n\n"
                    f"Your {hours}-hour remote support block has been activated.\n\n"
                    f"Track your usage and submit requests in your portal:\n"
                    f"  {portal_url}\n\n"
                    f"How it works:\n"
                    f"  • Submit a support request via the portal or by replying to this email\n"
                    f"  • Klara AI handles simple issues at no charge\n"
                    f"  • Hands-on engineer time is deducted from your block\n"
                    f"  • You will be notified at 75%, 50%, 25%, and 0% remaining\n"
                    f"  • At 25%, a top-up link is sent automatically\n\n"
                    f"Current balance: {hours}h\n\n"
                    f"— The Klaravex Team\n"
                    f"support@klaravex.com\n"
                ),
            )
        except Exception as exc:
            log.warning("A7 welcome email failed for %s: %s", email, exc)

    # 5. Alert Anthony.
    await _alert_anthony(
        subject=f"[Klaravex A7] Block hours purchased — {sku} ({email})",
        body=(
            f"A new hour block has been purchased.\n\n"
            f"SKU:     {sku}\n"
            f"Hours:   {hours}\n"
            f"Client:  {name or '(not provided)'} <{email}>\n"
            f"Amount:  ${paid_amount_usd:,.2f} USD\n"
            f"Block:   {_portal(f'/portal/hours/{block_id}')}\n"
        ),
    )

    return {
        "action": "a7_block_activated",
        "archetype": "A7",
        "sku": sku,
        "email": email,
        "block_id": block_id,
        "hours_total": hours,
        "ticket_id": ticket_id,
    }


async def log_hours(
    *,
    block_id: str,
    hours_used: float,
    description: str,
    logged_by: str = "anthony",
) -> dict[str, Any]:
    """Deduct hours from a block and fire burn-rate alerts as thresholds are crossed.

    Returns the updated block balance and any alert that was sent.
    """
    if hours_used <= 0:
        return {"ok": False, "error": "hours_used must be positive"}

    pool = await get_pool()
    async with pool.acquire() as conn:
        block = await conn.fetchrow(
            "SELECT * FROM klaravex_hour_blocks WHERE id=$1 FOR UPDATE",
            block_id,
        )
        if not block:
            return {"ok": False, "error": "block_not_found"}
        if block["status"] != "active":
            return {"ok": False, "error": f"block_status={block['status']}"}

        new_remaining = float(block["hours_remaining"]) - hours_used
        if new_remaining < 0:
            new_remaining = 0.0

        prev_fraction = float(block["hours_remaining"]) / float(block["hours_total"])
        new_fraction = new_remaining / float(block["hours_total"])

        new_status = "depleted" if new_remaining <= 0 else "active"

        await conn.execute(
            """
            UPDATE klaravex_hour_blocks
               SET hours_remaining=$1, status=$2, updated_at=now()
             WHERE id=$3
            """,
            new_remaining,
            new_status,
            block_id,
        )

        # Persist the usage log entry.
        await conn.execute(
            """
            INSERT INTO klaravex_hour_logs
              (block_id, hours_used, description, logged_by)
            VALUES ($1, $2, $3, $4)
            """,
            block_id,
            hours_used,
            description,
            logged_by,
        )

    # Check which alert thresholds were crossed.
    alerts_fired: list[float] = []
    for threshold in _A7_ALERT_THRESHOLDS:
        if prev_fraction > threshold >= new_fraction:
            alerts_fired.append(threshold)
            try:
                await _send_a7_alert(
                    block_id=block_id,
                    client_email=block["client_email"],
                    hours_remaining=new_remaining,
                    hours_total=float(block["hours_total"]),
                    threshold=threshold,
                    sku=block["sku"],
                )
            except Exception as exc:
                log.warning("A7 alert send failed (threshold %.0f%%): %s", threshold * 100, exc)

    log.info(
        "A7 log_hours: block=%s used=%.2f remaining=%.2f status=%s alerts=%s",
        block_id, hours_used, new_remaining, new_status, alerts_fired,
    )
    return {
        "ok": True,
        "block_id": block_id,
        "hours_remaining": new_remaining,
        "hours_used": hours_used,
        "status": new_status,
        "alerts_fired": alerts_fired,
    }


async def _send_a7_alert(
    *,
    block_id: str,
    client_email: str,
    hours_remaining: float,
    hours_total: float,
    threshold: float,
    sku: str,
) -> None:
    """Send a burn-rate alert to the client at 75/50/25/0% remaining."""
    pct = int(threshold * 100)
    portal_url = _portal(f"/portal/hours/{block_id}")

    if threshold == 0.0:
        subject = "Your Klaravex support block is depleted — top up to continue"
        body = (
            f"Hi,\n\n"
            f"Your {int(hours_total)}-hour support block has been fully used.\n\n"
            f"To continue receiving hands-on support, top up your block:\n"
            f"  {portal_url}\n\n"
            f"Your Klara AI AI coordinator continues to handle questions 24/7 at no charge.\n\n"
            f"— The Klaravex Team\n"
            f"support@klaravex.com\n"
        )
    elif threshold == 0.25:
        # At 25%: include payment link
        topup_url = await _generate_topup_link(client_email, sku)
        subject = f"25% of your Klaravex support hours remain — replenish now"
        body = (
            f"Hi,\n\n"
            f"You have {hours_remaining:.1f} hours remaining ({pct}% of your block).\n\n"
            f"To avoid any interruption, top up your support block now:\n"
            f"  {topup_url or portal_url}\n\n"
            f"View your full usage history:\n"
            f"  {portal_url}\n\n"
            f"— The Klaravex Team\n"
            f"support@klaravex.com\n"
        )
    else:
        subject = f"{pct}% of your Klaravex support hours remain"
        body = (
            f"Hi,\n\n"
            f"A quick balance notice: you have {hours_remaining:.1f} hours remaining "
            f"({pct}% of your {int(hours_total)}-hour block).\n\n"
            f"View usage and request history:\n"
            f"  {portal_url}\n\n"
            f"When you are ready to top up, reply to this email or visit the portal.\n\n"
            f"— The Klaravex Team\n"
            f"support@klaravex.com\n"
        )

    await send_email(to=client_email, subject=subject, body=body)

    # Also alert Anthony at depletion so no client is left hanging.
    if threshold == 0.0:
        await _alert_anthony(
            subject=f"[Klaravex A7] Block depleted — {client_email} ({sku})",
            body=(
                f"A {int(hours_total)}-hour block is now depleted.\n\n"
                f"Client: {client_email}\n"
                f"SKU:    {sku}\n"
                f"Block:  {_portal(f'/portal/hours/{block_id}')}\n\n"
                f"Top-up link sent to client. Monitor for renewal within 48 hours.\n"
            ),
        )


async def _generate_topup_link(client_email: str, sku: str) -> Optional[str]:
    """Create a Stripe Checkout Session for a block top-up and return the URL."""
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not stripe_key:
        return None
    try:
        stripe.api_key = stripe_key
        pool = await get_pool()
        async with pool.acquire() as conn:
            stripe_cust_id = await conn.fetchval(
                "SELECT stripe_customer_id FROM klaravex_clients WHERE email=$1",
                client_email.lower(),
            )
        price_id_env = f"STRIPE_PRICE_{sku.upper().replace('-', '_')}"
        price_id = os.environ.get(price_id_env, "")
        if not price_id:
            return None
        session_params: dict[str, Any] = {
            "mode": "payment",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": _portal("/portal/hours?topup=success"),
            "cancel_url": _portal("/portal/hours"),
            "metadata": {"sku": sku, "source": "a7_topup_auto"},
        }
        if stripe_cust_id:
            session_params["customer"] = stripe_cust_id
        else:
            session_params["customer_email"] = client_email
        cs = stripe.checkout.Session.create(**session_params)
        return cs.get("url")
    except Exception as exc:
        log.warning("A7 topup link generation failed: %s", exc)
        return None


async def get_balance(client_email: str) -> dict[str, Any]:
    """Return the active hour-block balance for a client."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id::text, sku, hours_total, hours_remaining, status, created_at
              FROM klaravex_hour_blocks
             WHERE client_email=$1 AND status='active'
             ORDER BY created_at DESC
            """,
            client_email.lower(),
        )
    blocks = [dict(r) for r in rows]
    total_remaining = sum(float(b["hours_remaining"]) for b in blocks)
    return {
        "client_email": client_email,
        "active_blocks": len(blocks),
        "total_hours_remaining": total_remaining,
        "blocks": blocks,
    }


async def send_topup_link(client_email: str) -> dict[str, Any]:
    """Manually trigger a top-up payment link for a client (e.g., from Klara AI chat)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        block = await conn.fetchrow(
            """
            SELECT id::text, sku, hours_total, hours_remaining
              FROM klaravex_hour_blocks
             WHERE client_email=$1
             ORDER BY created_at DESC
             LIMIT 1
            """,
            client_email.lower(),
        )
    sku = block["sku"] if block else "remote-block-10hr"
    url = await _generate_topup_link(client_email, sku)
    if url:
        portal_url = _portal(f"/portal/hours/{block['id']}" if block else "/portal/hours")
        try:
            await send_email(
                to=client_email,
                subject="Top up your Klaravex support hours",
                body=(
                    f"Hi,\n\n"
                    f"Here is your one-click link to top up your support hours:\n\n"
                    f"  {url}\n\n"
                    f"View your current usage:\n"
                    f"  {portal_url}\n\n"
                    f"— The Klaravex Team\n"
                    f"support@klaravex.com\n"
                ),
            )
        except Exception as exc:
            log.warning("A7 manual topup email failed: %s", exc)
    return {"ok": bool(url), "url": url, "sku": sku}


# ══════════════════════════════════════════════════════════════════════════════
# ── A8 — Procurement / Resale ─────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

async def request_procurement(
    *,
    client_email: str,
    description: str,
    requirements: str,
    estimated_cost_usd: float,
    quantity: int = 1,
    company: Optional[str] = None,
    name: Optional[str] = None,
    margin_pct: float = 12.0,
    source: str = "chat",
) -> dict[str, Any]:
    """Create a procurement request from a client chat or portal submission.

    Klara AI researches options and presents a quote; this function creates the
    record and triggers Anthony review if the estimated cost is over the threshold.

    margin_pct: default markup Klaravex adds to the cost price (12%).
    """
    pool = await get_pool()

    # Upsert client.
    try:
        await tickets_lib.get_or_create_client(
            client_email,
            segment="b2b",
            name=name,
            company=company,
            metadata={"source": "procurement_request"},
        )
    except Exception as exc:
        log.warning("A8 client upsert failed: %s", exc)

    approval_token = secrets.token_urlsafe(24)
    sell_price_usd = round(estimated_cost_usd * quantity * (1.0 + margin_pct / 100.0), 2)

    async with pool.acquire() as conn:
        proc_id = await conn.fetchval(
            """
            INSERT INTO klaravex_procurement_requests
              (client_email, description, requirements, quantity,
               estimated_cost_usd, margin_pct, sell_price_usd,
               status, approval_token, source, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending_quote', $8, $9, $10::jsonb)
            RETURNING id::text
            """,
            client_email.lower(),
            description,
            requirements,
            quantity,
            estimated_cost_usd,
            margin_pct,
            sell_price_usd,
            approval_token,
            source,
            json.dumps({"company": company, "client_name": name}),
        )

    # Open a ticket.
    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=client_email,
            subject=f"Procurement request — {description[:80]}",
            severity="standard",
            status="open",
            source=source,
            archetype="A8",
            sku="procurement-flat",
            summary=(
                f"Client requested: {description}. "
                f"Est. cost: ${estimated_cost_usd:,.2f} × {quantity}. "
                f"Sell price (incl. margin): ${sell_price_usd:,.2f}."
            ),
            segment_hint="b2b",
            metadata={"proc_id": proc_id},
        )
    except Exception as exc:
        log.warning("A8 ticket creation failed: %s", exc)

    # High-value: always escalate to Anthony for approval before quoting.
    total_estimated = estimated_cost_usd * quantity
    requires_anthony = total_estimated > _PROCUREMENT_ANTHONY_THRESHOLD_USD
    if requires_anthony:
        try:
            await escalate(
                ticket_id=ticket_id or "",
                client_email=client_email,
                severity="standard",
                summary=(
                    f"Procurement request requires approval (>${_PROCUREMENT_ANTHONY_THRESHOLD_USD:,.0f}): "
                    f"{description[:150]}. Est. total cost: ${total_estimated:,.2f}."
                ),
                attempted="Procurement request received; quote pending Anthony approval",
                recommended=(
                    f"Review the request and approve or decline in the portal: "
                    f"{_portal(f'/portal/procurement/{proc_id}')}"
                ),
            )
        except Exception as exc:
            log.warning("A8 high-value escalation failed: %s", exc)

    await _alert_anthony(
        subject=f"[Klaravex A8] Procurement request — {description[:60]} ({company or client_email})",
        body=(
            f"A procurement request has been submitted.\n\n"
            f"Client:       {name or '(not provided)'} <{client_email}>\n"
            f"Company:      {company or '(not provided)'}\n"
            f"Description:  {description}\n"
            f"Requirements: {requirements}\n"
            f"Qty:          {quantity}\n"
            f"Est. cost:    ${estimated_cost_usd:,.2f} each (${total_estimated:,.2f} total)\n"
            f"Sell price:   ${sell_price_usd:,.2f} (margin: {margin_pct:.1f}%)\n"
            f"Needs approval: {'YES — over threshold' if requires_anthony else 'No'}\n\n"
            f"Portal: {_portal(f'/portal/procurement/{proc_id}')}\n"
        ),
    )

    return {
        "ok": True,
        "proc_id": proc_id,
        "ticket_id": ticket_id,
        "sell_price_usd": sell_price_usd,
        "requires_anthony_approval": requires_anthony,
        "status": "pending_quote",
    }


async def approve_procurement(token: str) -> dict[str, Any]:
    """Client approves a procurement quote by clicking the approval link.

    Marks the request as approved and alerts Anthony to place the order.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM klaravex_procurement_requests WHERE approval_token=$1",
            token,
        )
        if not row:
            return {"ok": False, "error": "invalid_token"}
        if row["status"] not in ("pending_quote", "quote_sent"):
            return {"ok": True, "already": True, "status": row["status"]}
        await conn.execute(
            """
            UPDATE klaravex_procurement_requests
               SET status='approved', client_approved_at=now(), updated_at=now()
             WHERE id=$1
            """,
            row["id"],
        )

    log.info("A8 procurement approved: %s by %s", row["id"], row["client_email"])

    await _alert_anthony(
        subject=f"[Klaravex A8] Client approved procurement — {row['description'][:60]}",
        body=(
            f"A client has approved a procurement quote and is ready for you to order.\n\n"
            f"Client:    {row['client_email']}\n"
            f"Item:      {row['description']}\n"
            f"Qty:       {row['quantity']}\n"
            f"Sell:      ${float(row['sell_price_usd']):,.2f}\n"
            f"Cost est:  ${float(row['estimated_cost_usd']):,.2f} each\n"
            f"Portal:    {_portal('/portal/procurement/' + str(row['id']))}\n\n"
            f"Next step: place the order, then call mark_ordered(proc_id, po_ref) to log it.\n"
        ),
    )

    return {"ok": True, "proc_id": str(row["id"]), "status": "approved"}


async def mark_ordered(proc_id: str, po_reference: str, actual_cost_usd: float) -> dict[str, Any]:
    """Anthony marks a procurement as ordered and records the actual cost (for margin tracking)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM klaravex_procurement_requests WHERE id=$1",
            proc_id,
        )
        if not row:
            return {"ok": False, "error": "proc_not_found"}
        actual_sell = float(row["sell_price_usd"])
        actual_margin_usd = actual_sell - (actual_cost_usd * int(row["quantity"]))
        actual_margin_pct = (actual_margin_usd / actual_sell * 100.0) if actual_sell else 0.0
        await conn.execute(
            """
            UPDATE klaravex_procurement_requests
               SET status='ordered',
                   actual_cost_usd=$1,
                   actual_margin_usd=$2,
                   actual_margin_pct=$3,
                   po_reference=$4,
                   ordered_at=now(),
                   updated_at=now()
             WHERE id=$5
            """,
            actual_cost_usd,
            actual_margin_usd,
            actual_margin_pct,
            po_reference,
            proc_id,
        )

    # Notify the client that their order is placed.
    try:
        await send_email(
            to=row["client_email"],
            subject=f"Your order is placed — {row['description'][:60]}",
            body=(
                f"Hi,\n\n"
                f"Great news — your order for {row['description']} (qty: {row['quantity']}) "
                f"has been placed.\n\n"
                f"Reference: {po_reference}\n\n"
                f"We will notify you as soon as delivery is confirmed. "
                f"You can track the status in your portal:\n"
                f"  {_portal(f'/portal/procurement/{proc_id}')}\n\n"
                f"— The Klaravex Team\n"
                f"support@klaravex.com\n"
            ),
        )
    except Exception as exc:
        log.warning("A8 order confirmation email failed for %s: %s", row["client_email"], exc)

    log.info(
        "A8 ordered: proc=%s po=%s cost=%.2f margin=%.2f (%.1f%%)",
        proc_id, po_reference, actual_cost_usd, actual_margin_usd, actual_margin_pct,
    )
    return {
        "ok": True,
        "proc_id": proc_id,
        "po_reference": po_reference,
        "actual_margin_usd": actual_margin_usd,
        "actual_margin_pct": actual_margin_pct,
    }


async def mark_delivered(proc_id: str) -> dict[str, Any]:
    """Mark a procurement as delivered and issue the Stripe invoice."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM klaravex_procurement_requests WHERE id=$1",
            proc_id,
        )
        if not row:
            return {"ok": False, "error": "proc_not_found"}
        if row["status"] == "invoiced":
            return {"ok": True, "already": True, "status": "invoiced"}
        await conn.execute(
            """
            UPDATE klaravex_procurement_requests
               SET status='delivered', delivered_at=now(), updated_at=now()
             WHERE id=$1
            """,
            proc_id,
        )

    # Issue Stripe invoice.
    invoice_id: Optional[str] = None
    sell_amount_cents = int(float(row["sell_price_usd"]) * 100)
    try:
        stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
        async with pool.acquire() as conn:
            stripe_cust_id = await conn.fetchval(
                "SELECT stripe_customer_id FROM klaravex_clients WHERE email=$1",
                row["client_email"].lower(),
            )
        if stripe_cust_id and sell_amount_cents > 0:
            stripe.InvoiceItem.create(
                customer=stripe_cust_id,
                amount=sell_amount_cents,
                currency="usd",
                description=f"Procurement: {row['description']} (qty: {row['quantity']})",
            )
            inv = stripe.Invoice.create(
                customer=stripe_cust_id,
                collection_method="send_invoice",
                days_until_due=14,
                description=f"Klaravex procurement — {row['description'][:80]}",
            )
            inv_finalized = stripe.Invoice.finalize_invoice(inv["id"])
            stripe.Invoice.send_invoice(inv_finalized["id"])
            invoice_id = inv_finalized["id"]
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE klaravex_procurement_requests
                       SET status='invoiced', invoice_id=$1, invoiced_at=now(), updated_at=now()
                     WHERE id=$2
                    """,
                    invoice_id,
                    proc_id,
                )
    except Exception as exc:
        log.exception("A8 invoice creation failed for proc %s: %s", proc_id, exc)

    # Delivery confirmation email.
    try:
        await send_email(
            to=row["client_email"],
            subject=f"Delivery confirmed — {row['description'][:60]}",
            body=(
                f"Hi,\n\n"
                f"Your order for {row['description']} (qty: {row['quantity']}) "
                f"has been delivered.\n\n"
                f"An invoice for ${float(row['sell_price_usd']):,.2f} USD has been sent "
                f"{'(Stripe invoice ID: ' + invoice_id + ')' if invoice_id else 'to your email'}.\n\n"
                f"If you have any questions about the delivery, reply to this email.\n\n"
                f"— The Klaravex Team\n"
                f"support@klaravex.com\n"
            ),
        )
    except Exception as exc:
        log.warning("A8 delivery email failed for %s: %s", row["client_email"], exc)

    log.info("A8 delivered + invoiced: proc=%s invoice=%s", proc_id, invoice_id)
    return {
        "ok": True,
        "proc_id": proc_id,
        "invoice_id": invoice_id,
        "sell_amount_usd": float(row["sell_price_usd"]),
    }


async def handle_a8_checkout(session: dict[str, Any]) -> dict[str, Any]:
    """Handle checkout.session.completed for procurement-flat SKU.

    procurement-flat is billed as a flat service fee.  The actual hardware/
    software quote is handled separately via request_procurement().
    This handler just creates the client record and opens a ticket.
    """
    sku = _sku_from_checkout(session)
    email, name, stripe_customer_id = await _resolve_customer(session)
    if not email:
        return {"action": "error", "reason": "no_email", "archetype": "A8"}

    meta = session.get("metadata") or {}
    company = meta.get("company")

    try:
        await tickets_lib.get_or_create_client(
            email,
            segment="b2b",
            name=name,
            stripe_customer_id=stripe_customer_id,
            company=company,
            metadata={"sku": sku, "source": "stripe_a8_checkout"},
        )
    except Exception as exc:
        log.warning("A8 client upsert failed: %s", exc)

    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=email,
            subject=f"A8 procurement service fee — {company or email}",
            severity="standard",
            status="open",
            source="stripe",
            archetype="A8",
            sku=sku,
            summary="Procurement flat fee paid. Awaiting procurement request from client.",
            segment_hint="b2b",
            metadata={"stripe_session_id": session.get("id")},
        )
    except Exception as exc:
        log.warning("A8 ticket creation failed: %s", exc)

    await _alert_anthony(
        subject=f"[Klaravex A8] Procurement fee paid — {company or email}",
        body=(
            f"A client has paid the procurement flat fee.\n\n"
            f"Client:  {name or '(not provided)'} <{email}>\n"
            f"Company: {company or '(not provided)'}\n"
            f"Ticket:  {ticket_id or '—'}\n\n"
            f"Next: wait for the client's hardware/software requirements, "
            f"then use request_procurement() to initiate a quote.\n"
        ),
    )

    return {
        "action": "a8_procurement_fee_received",
        "archetype": "A8",
        "sku": sku,
        "email": email,
        "ticket_id": ticket_id,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ── Unified checkout entry point ──────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

async def handle_checkout_completed(session: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a checkout.session.completed event to the right A6/A7/A8 handler.

    Called from stripe_webhook._dispatch_event():

        from .lib import project_workflows as pw_lib
        if event["type"] == "checkout.session.completed":
            sku = (session.get("metadata") or {}).get("sku", "").lower()
            if sku in {*pw_lib.A6_SKUS, *pw_lib.A7_SKUS, *pw_lib.A8_SKUS}:
                result = await pw_lib.handle_checkout_completed(session)
                log.info("A6/A7/A8 checkout: action=%s", result.get("action"))

    Returns a result dict; never raises.
    """
    sku = _sku_from_checkout(session)
    if sku in A6_SKUS:
        return await handle_a6_checkout(session)
    if sku in A7_SKUS:
        return await handle_a7_checkout(session)
    if sku in A8_SKUS:
        return await handle_a8_checkout(session)
    return {"action": "skipped", "reason": f"sku {sku!r} not in A6/A7/A8", "archetype": None}
