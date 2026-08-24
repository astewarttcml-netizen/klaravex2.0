"""
Daily digest email for the marketing AI competition.

Sent to Anthony each morning at 9am via cron (set the schedule outside the app).
Includes:
  - 24h leaderboard summary (both teams, side by side)
  - Spend rollup
  - New clients acquired and which team they're attributed to
  - Pending approvals queue
  - Last 5 actions from each team
  - Quick links to the leaderboard + public race page
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from .db import get_pool
from .email import send_email

log = logging.getLogger("klaravex.marketing_digest")

DIGEST_RECIPIENT = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")
PUBLIC_RACE_URL = os.environ.get("PUBLIC_RACE_URL", "https://api.klaravex.com/race")


async def send_daily_digest() -> dict:
    pool = await get_pool()
    since = datetime.now(tz=timezone.utc) - timedelta(hours=24)

    async with pool.acquire() as conn:
        teams = await conn.fetch("""
            SELECT
              t.id, t.team_code, t.display_name, t.status, t.budget_usd, t.spend_usd,
              t.daily_spend_cap_usd, t.attribution_tag,
              (SELECT COUNT(*) FROM klaravex_clients
                 WHERE attribution_team = t.attribution_tag) AS total_clients,
              (SELECT COUNT(*) FROM klaravex_clients
                 WHERE attribution_team = t.attribution_tag AND created_at >= $1) AS new_clients_24h,
              (SELECT COALESCE(SUM(amount_usd),0) FROM klaravex_marketing_spend
                 WHERE team_id = t.id AND txn_at >= $1 AND status IN ('settled','authorized')) AS spend_24h,
              (SELECT COUNT(*) FROM klaravex_marketing_actions
                 WHERE team_id = t.id AND status='pending' AND approval_required) AS pending_approvals
            FROM klaravex_marketing_teams t
            ORDER BY t.team_code
        """, since)

        recent_actions = await conn.fetch("""
            SELECT a.action_type, a.status, a.action_target, a.created_at, t.team_code
              FROM klaravex_marketing_actions a
              JOIN klaravex_marketing_teams t ON t.id = a.team_id
             WHERE a.created_at >= $1
             ORDER BY a.created_at DESC LIMIT 30
        """, since)

        pending_actions = await conn.fetch("""
            SELECT a.action_type, a.action_target, a.created_at, t.team_code
              FROM klaravex_marketing_actions a
              JOIN klaravex_marketing_teams t ON t.id = a.team_id
             WHERE a.status='pending' AND a.approval_required
             ORDER BY a.created_at ASC LIMIT 10
        """)

    # Format ASCII tables for the email
    lines = []
    lines.append("=" * 70)
    lines.append("  KLARAVEX MARKETING AI · DAILY DIGEST")
    lines.append("  " + datetime.now(tz=timezone.utc).strftime("%A, %B %-d, %Y · %H:%M UTC"))
    lines.append("=" * 70)
    lines.append("")
    lines.append("LEADERBOARD")
    lines.append("-" * 70)

    by_team = {t["team_code"]: dict(t) for t in teams}
    for code in ("alpha", "beta"):
        t = by_team.get(code)
        if not t:
            continue
        spend = float(t["spend_usd"] or 0)
        budget = float(t["budget_usd"] or 0)
        spend_24 = float(t["spend_24h"] or 0)
        clients = int(t["total_clients"] or 0)
        new_clients = int(t["new_clients_24h"] or 0)
        cac = (spend / clients) if clients else None
        lines.append(f"  {t['display_name']}  [{t['status']}]")
        lines.append(f"    Spend:           ${spend:,.2f} of ${budget:,.0f}  (last 24h: ${spend_24:.2f})")
        lines.append(f"    Clients:         {clients} total  ({'+' if new_clients else ''}{new_clients} last 24h)")
        lines.append(f"    CAC:             {('$' + format(cac, ',.0f')) if cac is not None else '—'}")
        lines.append(f"    Pending approval: {t['pending_approvals']}")
        lines.append("")

    if pending_actions:
        lines.append("PENDING YOUR APPROVAL")
        lines.append("-" * 70)
        for p in pending_actions:
            lines.append(f"  [{p['team_code'].upper()}] {p['action_type']:<30} {p['action_target'] or ''}")
            lines.append(f"        ({p['created_at'].strftime('%m-%d %H:%M')} UTC)")
        lines.append("")

    lines.append("RECENT ACTIVITY (last 24h)")
    lines.append("-" * 70)
    if not recent_actions:
        lines.append("  No actions in the last 24 hours.")
    else:
        for a in recent_actions[:15]:
            label = f"[{a['team_code'].upper()}]"
            ts = a["created_at"].strftime("%m-%d %H:%M")
            lines.append(f"  {ts}  {label:<6} {a['status']:<10} {a['action_type']}")
    lines.append("")

    lines.append("-" * 70)
    lines.append(f"Full leaderboard (private):  {PORTAL_BASE_URL}/portal/admin/marketing-leaderboard")
    lines.append(f"Public spectator page:       {PUBLIC_RACE_URL}")
    lines.append("=" * 70)

    body = "\n".join(lines)
    try:
        await send_email(
            to=DIGEST_RECIPIENT,
            subject="[Klaravex Marketing AI] Daily Digest",
            body=body,
        )
        return {"sent": True, "teams": len(teams), "actions_24h": len(recent_actions)}
    except Exception as exc:
        log.exception("digest send failed: %s", exc)
        return {"sent": False, "error": str(exc)}
