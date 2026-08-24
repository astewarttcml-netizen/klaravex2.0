"""
B2B project workflow.

Lifecycle:
  intake → sow_draft → sow_sent (client reviews) → accepted → active
        → milestones tracked → final_signoff → invoiced → closed

Entry points:
  - create_project_from_intake(...)         called by b2b_project_webhook
  - generate_and_send_sow(project_id)       Claude-powered SOW draft
  - accept_sow(project_id)                  client clicks accept link
  - issue_milestone_signoff_link(...)       per-milestone signoff URL
  - sign_off_milestone(token)               client signs off → triggers Stripe invoice
  - close_project(project_id)               final state
  - send_weekly_progress(project_id)        scheduled progress email
"""

import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import stripe

from .db import get_pool
from .email import send_email

log = logging.getLogger("klaravex.projects")

PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")
PROJECT_SUPPORT_EMAIL = os.environ.get("PROJECT_SUPPORT_EMAIL", "support@klaravex.com")


SOW_PROMPT = """\
You are drafting a Statement of Work for Klaravex, a US-based managed IT/security MSP.

Client request summary:
  Title:   {title}
  Scope:   {scope_summary}
  Client:  {client_email}
  Budget:  ${budget:,.0f} USD (fixed-fee unless noted)
  SKU:     {sku}

Write a SOW with this structure (markdown, ~400-700 words total):

# Statement of Work — {title}

**Client:** {client_email}
**Provider:** Klaravex LLC (Wyoming)
**Effective date:** {today}
**Total fee:** ${budget:,.0f} USD

## 1. Background & objective
Briefly: why this project exists and what success looks like.

## 2. Scope of work
Bullet list of specific deliverables. Be concrete: "Configure Conditional Access policies for X, Y, Z" not "set up security".

## 3. Out of scope
At least 3 things this SOW does NOT include (manages client expectations).

## 4. Milestones
Break the project into 3-4 milestones. For each:
  - Title (one line)
  - Deliverable
  - Percentage of total fee (must sum to 100%)
  - Estimated duration (in business days from kickoff)

Format milestones as a markdown table or numbered list.

## 5. Client responsibilities
What the client must provide for the project to succeed (e.g., M365 Global Admin access, access to legacy systems, single point of contact).

## 6. Acceptance
Each milestone is invoiced upon written client sign-off via the Klaravex portal. Final milestone triggers project closure.

## 7. Change management
Any scope changes require a written change order. Klaravex will provide an estimate before any work is performed under a change order.

End with this acceptance line:
> By clicking "Accept SOW" in the Klaravex portal, the client agrees to the terms above.

CRITICAL — also include at the very end (after the markdown) a JSON block like this so we can parse milestones programmatically:

```json
{{
  "milestones": [
    {{"sequence": 1, "title": "...", "budget_percentage": 25, "estimated_business_days": 5}},
    {{"sequence": 2, "title": "...", "budget_percentage": 35, "estimated_business_days": 10}},
    {{"sequence": 3, "title": "...", "budget_percentage": 40, "estimated_business_days": 15}}
  ]
}}
```

The JSON percentages must sum to exactly 100.
"""


async def create_project_from_intake(
    *,
    client_email: str,
    title: str,
    scope_summary: str,
    budget_usd: float,
    sku: str,
    ticket_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        client_id = await conn.fetchval(
            "SELECT id FROM klaravex_clients WHERE email = $1",
            client_email.lower(),
        )
        project_id = await conn.fetchval(
            """
            INSERT INTO klaravex_projects
              (client_id, client_email, title, scope_summary, total_budget_usd,
               sku, status, ticket_id, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, 'intake', $7, $8::jsonb)
            RETURNING id::text
            """,
            client_id, client_email.lower(), title, scope_summary,
            budget_usd, sku, ticket_id, json.dumps(metadata or {}),
        )
    log.info("project created: %s for %s ($%s)", project_id, client_email, budget_usd)
    return project_id


async def generate_and_send_sow(project_id: str) -> dict[str, object]:
    """Claude generates the SOW. Stored in DB + emailed to client."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM klaravex_projects WHERE id = $1", project_id,
        )
    if not row:
        return {"ok": False, "error": "project_not_found"}

    litellm_url = os.environ.get("LITELLM_URL", "")
    litellm_key = os.environ.get("LITELLM_MASTER_KEY", "")
    if not (litellm_url and litellm_key):
        return {"ok": False, "error": "LITELLM_URL/KEY not set"}

    import httpx
    prompt = SOW_PROMPT.format(
        title=row["title"],
        scope_summary=row["scope_summary"] or "(no scope provided)",
        client_email=row["client_email"],
        budget=float(row["total_budget_usd"] or 0),
        sku=row["sku"] or "—",
        today=datetime.now(tz=timezone.utc).strftime("%B %-d, %Y"),
    )
    try:
        async with httpx.AsyncClient(timeout=90) as hc:
            r = await hc.post(
                f"{litellm_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {litellm_key}"},
                json={"model": "deepseek", "max_tokens": 2400, "messages": [{"role": "user", "content": prompt}]},
            )
            if r.status_code != 200:
                return {"ok": False, "error": f"llm_error: {r.status_code}"}
            sow_text = r.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        log.exception("SOW generation failed for %s: %s", project_id, exc)
        return {"ok": False, "error": f"llm_error: {exc}"}

    # Parse milestone JSON appendix
    import re
    milestones = []
    m = re.search(r"```json\s*(\{.*?\})\s*```", sow_text, re.S)
    if m:
        try:
            parsed = json.loads(m.group(1))
            milestones = parsed.get("milestones", [])
        except Exception as exc:
            log.warning("SOW milestone JSON parse failed for %s: %s", project_id, exc)

    sow_markdown = re.sub(r"```json.*?```", "", sow_text, flags=re.S).strip()

    # Persist SOW + milestones
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE klaravex_projects
               SET sow_markdown=$1, status='sow_sent', updated_at=now()
             WHERE id=$2
            """,
            sow_markdown, project_id,
        )
        # Delete any existing milestones (idempotency if regenerating)
        await conn.execute("DELETE FROM klaravex_project_milestones WHERE project_id=$1", project_id)
        for m_data in milestones:
            try:
                days = int(m_data.get("estimated_business_days", 7))
                due = datetime.now(tz=timezone.utc) + timedelta(days=days)
                await conn.execute(
                    """
                    INSERT INTO klaravex_project_milestones
                      (project_id, sequence, title, budget_percentage, estimated_due_at, signoff_token)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    project_id,
                    int(m_data.get("sequence", 0)),
                    str(m_data.get("title", "Milestone"))[:300],
                    float(m_data.get("budget_percentage", 0)),
                    due,
                    secrets.token_urlsafe(24),
                )
            except Exception as exc:
                log.warning("milestone insert failed: %s", exc)

    # Email the SOW to the client
    accept_token = secrets.token_urlsafe(24)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex_projects SET metadata = metadata || $1::jsonb WHERE id=$2",
            json.dumps({"accept_token": accept_token}), project_id,
        )
    accept_url = f"{PORTAL_BASE_URL.rstrip('/')}/portal/projects/{project_id}/accept?token={accept_token}"

    body = (
        f"Hi,\n\n"
        f"Your Klaravex Statement of Work for '{row['title']}' is ready for review.\n\n"
        f"View + accept in your portal:\n"
        f"  {PORTAL_BASE_URL}/portal/projects/{project_id}\n\n"
        f"Or accept directly here:\n"
        f"  {accept_url}\n\n"
        f"Total fee: ${float(row['total_budget_usd'] or 0):,.0f} USD, invoiced per milestone on sign-off.\n\n"
        f"Questions before you accept? Reply to this email or reach {PROJECT_SUPPORT_EMAIL}.\n\n"
        f"— The Klaravex Team\n"
    )
    try:
        await send_email(
            to=row["client_email"],
            subject=f"Klaravex SOW ready for review: {row['title']}",
            body=body,
        )
    except Exception as exc:
        log.exception("SOW email send failed for %s: %s", project_id, exc)
        return {"ok": False, "error": f"email_error: {exc}", "sow_persisted": True}

    return {
        "ok": True,
        "project_id": project_id,
        "milestone_count": len(milestones),
        "sow_chars": len(sow_markdown),
    }


async def accept_sow(project_id: str, token: str) -> dict[str, object]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT metadata, status, client_email, title FROM klaravex_projects WHERE id=$1",
            project_id,
        )
        if not row:
            return {"ok": False, "error": "project_not_found"}
        if (row["metadata"] or {}).get("accept_token") != token:
            return {"ok": False, "error": "invalid_token"}
        if row["status"] in ("accepted", "active", "final_signoff", "invoiced", "closed"):
            return {"ok": True, "already": True, "status": row["status"]}
        # Set first milestone to in_progress, schedule first weekly progress email
        await conn.execute(
            """
            UPDATE klaravex_projects
               SET status='active', sow_accepted_at=now(),
                   next_progress_at=now() + interval '7 days', updated_at=now()
             WHERE id=$1
            """,
            project_id,
        )
        await conn.execute(
            """
            UPDATE klaravex_project_milestones
               SET status='in_progress'
             WHERE project_id=$1 AND sequence=(
               SELECT MIN(sequence) FROM klaravex_project_milestones WHERE project_id=$1
             )
            """,
            project_id,
        )

    log.info("SOW accepted for %s by %s", project_id, row["client_email"])
    return {"ok": True, "status": "active"}


async def sign_off_milestone(token: str) -> dict[str, object]:
    """Client clicks signoff link for a milestone. Marks complete + issues Stripe invoice."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        m = await conn.fetchrow(
            """
            SELECT m.*, p.client_email, p.title AS project_title,
                   p.total_budget_usd, p.stripe_invoice_id AS project_invoice_id
              FROM klaravex_project_milestones m
              JOIN klaravex_projects p ON p.id = m.project_id
             WHERE m.signoff_token=$1
            """,
            token,
        )
    if not m:
        return {"ok": False, "error": "invalid_token"}
    if m["signed_off_at"]:
        return {"ok": True, "already": True}

    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

    # Find the Stripe customer for this client email
    invoice_id = None
    invoice_amount_cents = int(float(m["total_budget_usd"] or 0) * float(m["budget_percentage"] or 0) / 100.0 * 100)
    try:
        pool2 = await get_pool()
        async with pool2.acquire() as conn:
            stripe_cust_id = await conn.fetchval(
                "SELECT stripe_customer_id FROM klaravex_clients WHERE email=$1",
                m["client_email"].lower(),
            )
        if stripe_cust_id and invoice_amount_cents > 0:
            # Add invoice item, then finalize an invoice
            stripe.InvoiceItem.create(
                customer=stripe_cust_id,
                amount=invoice_amount_cents,
                currency="usd",
                description=f"{m['project_title']} — {m['title']}",
            )
            inv = stripe.Invoice.create(
                customer=stripe_cust_id,
                collection_method="send_invoice",
                days_until_due=14,
                description=f"Milestone {m['sequence']} sign-off: {m['title']}",
            )
            inv_finalized = stripe.Invoice.finalize_invoice(inv["id"])
            stripe.Invoice.send_invoice(inv_finalized["id"])
            invoice_id = inv_finalized["id"]
    except Exception as exc:
        log.exception("milestone invoice create failed: %s", exc)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE klaravex_project_milestones
               SET status='signed_off', signed_off_at=now(), invoice_id=$1, updated_at=now()
             WHERE id=$2
            """,
            invoice_id, m["id"],
        )
        # Advance next pending milestone to in_progress, or if all signed off, mark project final_signoff
        next_m = await conn.fetchrow(
            """
            SELECT id FROM klaravex_project_milestones
             WHERE project_id=$1 AND status='pending'
             ORDER BY sequence LIMIT 1
            """,
            m["project_id"],
        )
        if next_m:
            await conn.execute(
                "UPDATE klaravex_project_milestones SET status='in_progress' WHERE id=$1",
                next_m["id"],
            )
        else:
            await conn.execute(
                "UPDATE klaravex_projects SET status='final_signoff', updated_at=now() WHERE id=$1",
                m["project_id"],
            )

    return {"ok": True, "milestone_id": str(m["id"]), "invoice_id": invoice_id, "amount_cents": invoice_amount_cents}


async def send_weekly_progress_for_active_projects() -> dict[str, int]:
    """Cron entry point: send weekly progress emails for all 'active' projects past due."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, client_email, title FROM klaravex_projects
             WHERE status='active' AND (next_progress_at IS NULL OR next_progress_at <= now())
            """
        )

    sent = 0
    errors = 0
    for r in rows:
        try:
            await send_progress_email(str(r["id"]))
            sent += 1
        except Exception as exc:
            log.warning("progress email failed for %s: %s", r["id"], exc)
            errors += 1
    return {"sent": sent, "errors": errors, "candidates": len(rows)}


async def send_progress_email(project_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT * FROM klaravex_projects WHERE id=$1", project_id)
        if not p:
            return
        milestones = await conn.fetch(
            "SELECT * FROM klaravex_project_milestones WHERE project_id=$1 ORDER BY sequence",
            project_id,
        )

    lines = []
    for m in milestones:
        if m["status"] == "signed_off":
            mark = "✓"
        elif m["status"] == "in_progress":
            mark = "→"
        elif m["status"] == "blocked":
            mark = "!"
        else:
            mark = " "
        lines.append(f"  [{mark}] {m['sequence']}. {m['title']} ({float(m['budget_percentage']):.0f}%)")

    body = (
        f"Hi,\n\n"
        f"Weekly progress on '{p['title']}':\n\n"
        + "\n".join(lines) +
        f"\n\nFull details + sign off completed milestones:\n"
        f"  {PORTAL_BASE_URL.rstrip('/')}/portal/projects/{project_id}\n\n"
        f"Questions? Reply to this email.\n\n"
        f"— The Klaravex Team\n"
    )
    await send_email(
        to=p["client_email"],
        subject=f"Progress: {p['title']}",
        body=body,
    )

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex_projects SET next_progress_at=now() + interval '7 days', updated_at=now() WHERE id=$1",
            project_id,
        )
