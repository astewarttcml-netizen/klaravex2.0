"""
Public-safe view of the marketing AI competition.

Everything in this module is designed to be served on the public internet.
NOTHING here exposes:
  - Customer emails or names
  - Mercury card numbers, last4, or transaction IDs
  - Agent system prompts (only short personality summaries)
  - Action payloads (only action type counts)
  - Pending approval contents
  - Internal env vars or API tokens
  - klaravex_clients PII (only aggregate counts)

Action type → public-friendly label mapping centralized so a new action type
doesn't accidentally leak verbatim.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import get_pool

log = logging.getLogger("klaravex.marketing_public")


# Friendly public names for each action type. Anything not in this map is
# rendered as the generic "Strategic move" — secrets stay opaque.
PUBLIC_ACTION_LABELS = {
    "apollo.search":                  "Researching potential clients",
    "apollo.search_contacts":         "Researching potential clients",
    "resend.send":                    "Reaching out to a prospect",
    "resend.send_email":              "Reaching out to a prospect",
    "organic.post_draft":             "Drafting a social post",
    "meta_ads.create_campaign":       "Launching a Meta ad campaign",
    "google_ads.create_campaign":     "Launching a Google ad campaign",
    "linkedin_ads.create_campaign":   "Launching a LinkedIn ad campaign",
    "human.approval_request":         "Asking the operator a strategic question",
    "human.request_approval":         "Asking the operator a strategic question",
    "observation":                    "Analyzing performance",
    "guardrail.organic.post_draft":   "Brand-voice guardrail kicked in",
}


# Personality summaries safe for public display (one line each)
PUBLIC_PERSONALITY = {
    "alpha": "Aggressive growth. Move fast, accept higher risk for volume.",
    "beta":  "Patient + ROI-focused. Build compounding loops over flashy wins.",
}


def label_action(action_type: str) -> str:
    return PUBLIC_ACTION_LABELS.get(action_type, "Strategic move")


async def public_snapshot() -> dict:
    """Return a sanitized leaderboard payload suitable for public display."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        teams = await conn.fetch("""
            SELECT
              t.team_code, t.display_name, t.status,
              t.budget_usd, t.spend_usd, t.activated_at,
              t.attribution_tag,
              (SELECT COUNT(*) FROM klaravex_clients
                 WHERE attribution_team = t.attribution_tag) AS clients,
              (SELECT COUNT(*) FROM klaravex_marketing_actions
                 WHERE team_id = t.id AND status='executed') AS actions_taken,
              (SELECT COUNT(*) FROM klaravex_marketing_runs
                 WHERE team_id = t.id AND status='completed') AS ticks_completed
            FROM klaravex_marketing_teams t
            WHERE t.status IN ('soft_launch', 'live', 'paused', 'winner', 'retired')
            ORDER BY t.team_code
        """)

        # Recent action feed (last 24h, sanitized)
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
        recent_actions = await conn.fetch("""
            SELECT a.action_type, a.status, a.created_at, t.team_code
              FROM klaravex_marketing_actions a
              JOIN klaravex_marketing_teams t ON t.id = a.team_id
             WHERE a.created_at >= $1 AND a.status NOT IN ('pending','failed','blocked')
             ORDER BY a.created_at DESC LIMIT 12
        """, cutoff)

        # Spend over last 24h for the sparkline
        spend_24h = await conn.fetch("""
            SELECT t.team_code,
                   DATE_TRUNC('hour', s.txn_at) AS hour,
                   SUM(s.amount_usd) AS amount
              FROM klaravex_marketing_spend s
              JOIN klaravex_marketing_teams t ON t.id = s.team_id
             WHERE s.txn_at >= $1 AND s.status IN ('settled','authorized')
             GROUP BY t.team_code, hour
             ORDER BY hour
        """, cutoff)

    snapshot_teams = []
    for t in teams:
        spend = float(t["spend_usd"] or 0)
        budget = float(t["budget_usd"] or 0)
        clients = int(t["clients"] or 0)
        cac = round(spend / clients, 2) if clients else None
        snapshot_teams.append({
            "team_code": t["team_code"],
            "display_name": t["display_name"],
            "status": t["status"],
            "personality": PUBLIC_PERSONALITY.get(t["team_code"], ""),
            "budget_usd": budget,
            "spend_usd": round(spend, 2),
            "budget_remaining_usd": round(max(0, budget - spend), 2),
            "spend_percent": round(min(100, (spend / budget * 100) if budget else 0), 1),
            "clients_acquired": clients,
            "cac_usd": cac,
            "actions_taken": int(t["actions_taken"] or 0),
            "ticks_completed": int(t["ticks_completed"] or 0),
            "activated_at": t["activated_at"].isoformat() if t["activated_at"] else None,
        })

    feed = [
        {
            "team_code": r["team_code"],
            "label": label_action(r["action_type"]),
            "at": r["created_at"].isoformat(),
        }
        for r in recent_actions
    ]

    spend_series = {}
    for r in spend_24h:
        spend_series.setdefault(r["team_code"], []).append({
            "hour": r["hour"].isoformat(),
            "amount_usd": float(r["amount"] or 0),
        })

    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "competition_overview": {
            "premise": "Two AI agent teams. $1,000 each. 30 days. Whoever generates more billed revenue from new clients wins.",
            "metric": "Billed revenue per dollar spent (ROI).",
            "started_at": min(
                (t["activated_at"] for t in snapshot_teams if t.get("activated_at")),
                default=None,
            ),
        },
        "teams": snapshot_teams,
        "live_feed": feed,
        "spend_24h_series": spend_series,
    }
