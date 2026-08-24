"""
Master daily operator digest.

One email at 8am ET combining the state of every Klaravex workflow that needs
Anthony's attention or visibility. Replaces hunting across 5 portal tabs.

Sections:
  - Race status   — Alpha vs Beta in one line
  - Pending       — total items waiting on approval (link to /portal/admin/approvals)
  - Money in      — new paying clients in last 24h, attribution tag if any
  - Money out     — renewal reminders sent, dunning events, total Mercury spend
  - Freelance     — new bids queued + bids submitted in last 24h
  - Projects      — active projects, milestones due in next 7 days
  - Marketing AI  — actions taken, tool errors
  - Anomalies     — anything outside normal envelope (defined per metric)
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from .db import get_pool
from .email import send_email

log = logging.getLogger("klaravex.operator_digest")

ANTHONY_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")


async def build_digest() -> dict:
    """Build the digest payload AND format the email body in one pass."""
    pool = await get_pool()
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)

    async with pool.acquire() as conn:
        # 1. Marketing race
        teams = await conn.fetch("""
            SELECT t.team_code, t.status, t.budget_usd, t.spend_usd, t.attribution_tag,
                   (SELECT COUNT(*) FROM klaravex_clients
                      WHERE attribution_team = t.attribution_tag) AS clients,
                   (SELECT COUNT(*) FROM klaravex_marketing_actions
                      WHERE team_id = t.id AND created_at >= $1) AS actions_24h,
                   (SELECT COALESCE(SUM(amount_usd),0) FROM klaravex_marketing_spend
                      WHERE team_id = t.id AND txn_at >= $1
                            AND status IN ('settled','authorized')) AS spend_24h
            FROM klaravex_marketing_teams t ORDER BY t.team_code
        """, cutoff)

        # 2. Approvals waiting
        social_pending = await conn.fetchval(
            "SELECT COUNT(*) FROM klaravex_social_drafts WHERE status='pending'"
        )
        action_pending = await conn.fetchval(
            "SELECT COUNT(*) FROM klaravex_marketing_actions WHERE status='pending' AND approval_required"
        )
        bid_pending = await conn.fetchval(
            "SELECT COUNT(*) FROM klaravex_platform_bids WHERE status='queued'"
        )
        outreach_pending = await conn.fetchval(
            "SELECT COUNT(*) FROM klaravex_outreach_approvals "
            "WHERE status='pending' OR (status='approved' AND sent_at IS NULL)"
        )
        kb_pending = await conn.fetchval(
            "SELECT COUNT(*) FROM klaravex_kb_drafts WHERE status='pending'"
        )

        # 3. New clients in last 24h
        new_clients = await conn.fetch("""
            SELECT email, segment, attribution_team, created_at, name
              FROM klaravex_clients
             WHERE created_at >= $1
             ORDER BY created_at DESC LIMIT 20
        """, cutoff)

        # 4. Renewal reminders sent
        reminders_24h = await conn.fetch("""
            SELECT reminder_kind, COUNT(*) AS n FROM klaravex_renewal_reminders
             WHERE sent_at >= $1 GROUP BY reminder_kind
        """, cutoff)
        reminders_breakdown = {r["reminder_kind"]: int(r["n"] or 0) for r in reminders_24h}

        # 5. Freelance bids — submitted in last 24h + queued
        bids_submitted = await conn.fetchval("""
            SELECT COUNT(*) FROM klaravex_platform_bids
             WHERE submitted_at >= $1 AND status='submitted'
        """, cutoff)
        bids_queued = await conn.fetchval(
            "SELECT COUNT(*) FROM klaravex_platform_bids WHERE status='queued'"
        )

        # 6. Active projects + milestones due in next 7 days
        active_projects = await conn.fetchval("""
            SELECT COUNT(*) FROM klaravex_projects WHERE status IN ('active','final_signoff')
        """)
        due_soon = await conn.fetch("""
            SELECT m.title, m.estimated_due_at, p.client_email, p.title AS project_title
              FROM klaravex_project_milestones m
              JOIN klaravex_projects p ON p.id = m.project_id
             WHERE m.status='in_progress'
               AND m.estimated_due_at <= now() + interval '7 days'
             ORDER BY m.estimated_due_at ASC LIMIT 8
        """)

        # 7. Recent dunning events
        dunning_24h = await conn.fetchval("""
            SELECT COUNT(*) FROM klaravex_tickets
             WHERE source='stripe' AND severity='high'
               AND created_at >= $1
        """, cutoff)

        # 8. Onboarding completion
        onb = await conn.fetchrow("""
            SELECT
              COUNT(*) FILTER (WHERE status='active')    AS active,
              COUNT(*) FILTER (WHERE status='completed') AS completed
            FROM klaravex_onboarding_checklists
        """)

    # ── Format ────────────────────────────────────────────────────────────────
    today_str = datetime.now(tz=timezone.utc).strftime("%A, %B %-d, %Y · %H:%M UTC")
    lines = []
    lines.append("=" * 72)
    lines.append("  KLARAVEX · DAILY OPERATOR DIGEST")
    lines.append(f"  {today_str}")
    lines.append("=" * 72)
    lines.append("")

    # Pending approvals — surface first since it's the action-needed section
    total_pending = (social_pending or 0) + (action_pending or 0) + (bid_pending or 0)
    if total_pending:
        lines.append(f"  ⚠ {total_pending} item(s) waiting on you")
        lines.append(f"  →  {PORTAL_BASE_URL}/portal/admin/approvals")
        if social_pending:    lines.append(f"     · {social_pending} social draft(s)")
        if action_pending:    lines.append(f"     · {action_pending} marketing AI action(s)")
        if bid_pending:       lines.append(f"     · {bid_pending} freelance bid(s)")
        lines.append("")

    lines.append("MARKETING RACE")
    lines.append("-" * 72)
    by_team = {t["team_code"]: t for t in teams}
    for code in ("alpha", "beta"):
        t = by_team.get(code)
        if not t:
            continue
        spend = float(t["spend_usd"] or 0)
        budget = float(t["budget_usd"] or 0)
        spend_24 = float(t["spend_24h"] or 0)
        clients = int(t["clients"] or 0)
        actions = int(t["actions_24h"] or 0)
        cac = (spend / clients) if clients else None
        lines.append(f"  {code.upper():<8} [{t['status']:<13}] ${spend:6.0f} / ${budget:.0f}   "
                     f"clients={clients}   CAC={'$' + format(cac,',.0f') if cac else '—'}")
        lines.append(f"           last 24h: ${spend_24:.2f} spent, {actions} action(s)")
    lines.append("")
    lines.append(f"  Public race page: {PORTAL_BASE_URL}/race")
    lines.append("")

    lines.append("NEW CLIENTS (last 24h)")
    lines.append("-" * 72)
    if not new_clients:
        lines.append("  No new clients in the last 24h.")
    else:
        for c in new_clients:
            tag = f" [{c['attribution_team'].upper()}]" if c['attribution_team'] else ""
            lines.append(f"  + {c['email']:<35} segment={c['segment']:<8} {c['name'] or '':<25}{tag}")
    lines.append("")

    lines.append("RENEWAL REMINDERS SENT (last 24h)")
    lines.append("-" * 72)
    if not reminders_breakdown:
        lines.append("  None.")
    else:
        for kind, n in reminders_breakdown.items():
            lines.append(f"  {kind:<15} {n}")
    lines.append("")

    lines.append("FREELANCE PIPELINE")
    lines.append("-" * 72)
    lines.append(f"  Bids submitted last 24h: {bids_submitted or 0}")
    lines.append(f"  Bids queued (awaiting):  {bids_queued or 0}")
    lines.append("")

    lines.append("PROJECTS")
    lines.append("-" * 72)
    lines.append(f"  Active projects: {active_projects or 0}")
    if due_soon:
        lines.append(f"  Milestones due in next 7 days:")
        for m in due_soon:
            due = m["estimated_due_at"].strftime("%m-%d") if m["estimated_due_at"] else "—"
            lines.append(f"     {due}  {m['project_title']} — {m['title']}  ({m['client_email']})")
    lines.append("")

    lines.append("DUNNING + ONBOARDING")
    lines.append("-" * 72)
    lines.append(f"  Payment failures / past-due tickets last 24h: {dunning_24h or 0}")
    if onb:
        lines.append(f"  Onboarding checklists: {int(onb['active'] or 0)} active, "
                     f"{int(onb['completed'] or 0)} completed")
    lines.append("")

    lines.append("-" * 72)
    lines.append(f"All systems: {PORTAL_BASE_URL}/portal/")
    lines.append(f"Approvals:   {PORTAL_BASE_URL}/portal/admin/approvals")
    lines.append(f"Race:        {PORTAL_BASE_URL}/race")
    lines.append("=" * 72)

    return {"body": "\n".join(lines), "total_pending": total_pending}


async def send_operator_digest() -> dict:
    try:
        digest = await build_digest()
    except Exception as exc:
        log.exception("operator digest build failed: %s", exc)
        return {"sent": False, "error": str(exc)}
    try:
        await send_email(
            to=ANTHONY_EMAIL,
            subject=f"[Klaravex] Daily Operator Digest · {digest['total_pending']} pending",
            body=digest["body"],
        )
        return {"sent": True, "total_pending": digest["total_pending"]}
    except Exception as exc:
        log.exception("operator digest send failed: %s", exc)
        return {"sent": False, "error": str(exc)}
