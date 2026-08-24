#!/usr/bin/env python3
"""Klaravex pipeline staleness watchdog.

Daily cron. For each pipeline below, queries the DB for most recent row.
If staleness > threshold, fires escalate_to_anthony (Telegram + email).

Pipelines: social_drafts (4d), freelance_projects (2d), prospected_leads (2d),
outreach_approvals (2d), marketing_actions (2d), tickets (14d).

Designed to run from cron. Reads creds from /opt/klaravex-watchdog/env.
Exit 0 always; errors self-report via the same channel.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

DB_HOST = os.environ["KLX_DB_HOST"]
DB_USER = os.environ["KLX_DB_USER"]
DB_PASS = os.environ["KLX_DB_PASS"]
DB_NAME = os.environ.get("KLX_DB_NAME", "klaravex")
API_BASE = os.environ.get("KLX_API_BASE", "https://api.klaravex.com")
VAPI_SECRET = os.environ["KLX_VAPI_SHARED_SECRET"]

PIPELINES = [
    ("social_drafts",      "klaravex_social_drafts",      timedelta(days=4)),
    ("freelance_projects", "klaravex_freelance_projects", timedelta(days=2)),
    ("prospected_leads",   "klaravex_prospected_leads",   timedelta(days=2)),
    ("outreach_approvals", "klaravex_outreach_approvals", timedelta(days=2)),
    ("marketing_actions",  "klaravex_marketing_actions",  timedelta(days=2)),
    ("tickets",            "klaravex_tickets",            timedelta(days=14)),
]


def escalate(severity: str, reason: str, summary: str) -> None:
    payload = json.dumps({
        "call_sid": "watchdog",
        "reason": reason,
        "severity": severity,
        "summary": summary,
    }).encode()
    req = urllib.request.Request(
        f"{API_BASE}/api/v1/vapi/escalate_to_anthony",
        data=payload,
        headers={"x-vapi-secret": VAPI_SECRET, "content-type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as exc:
        print(f"[watchdog] escalate failed: {exc}", file=sys.stderr)


def main() -> int:
    try:
        import psycopg2
    except ImportError:
        print("[watchdog] psycopg2 not installed", file=sys.stderr)
        return 0

    try:
        conn = psycopg2.connect(
            host=DB_HOST, user=DB_USER, password=DB_PASS, dbname=DB_NAME,
            port=5432, sslmode="require", connect_timeout=10,
        )
    except Exception as exc:
        escalate("high", "watchdog DB connect failed", f"Could not connect to {DB_HOST}: {exc}")
        return 0

    now = datetime.now(timezone.utc)
    stale = []
    fresh = []

    with conn.cursor() as cur:
        for name, table, threshold in PIPELINES:
            try:
                cur.execute(f"SELECT MAX(created_at) FROM {table}")
                row = cur.fetchone()
                last_at = row[0] if row else None
            except Exception as exc:
                stale.append((name, "DB_ERROR", str(exc)[:200]))
                conn.rollback()
                continue
            if last_at is None:
                stale.append((name, "NEVER", "0 rows ever"))
                continue
            age = now - last_at
            if age > threshold:
                stale.append((name, age, last_at.strftime("%Y-%m-%d %H:%M UTC")))
            else:
                fresh.append((name, age))

    conn.close()

    if not stale:
        # Weekly OK on Mondays so Anthony knows it ran
        if now.weekday() == 0 and now.hour < 12:
            lines = ["Klaravex watchdog OK — weekly heartbeat.\n"]
            for name, age in fresh:
                hrs = int(age.total_seconds() // 3600)
                lines.append(f"  - {name}: last {hrs}h ago")
            escalate("normal", "Klaravex pipelines all healthy", "\n".join(lines))
        return 0

    lines = ["STALE pipelines detected:\n"]
    for name, age, when in stale:
        if isinstance(age, timedelta):
            d = age.days
            h = int(age.total_seconds() // 3600) - d * 24
            lines.append(f"  - {name}: {d}d {h}h since {when}")
        else:
            lines.append(f"  - {name}: {age} ({when})")
    if fresh:
        lines.append("\nHealthy:")
        for name, age in fresh:
            h = int(age.total_seconds() // 3600)
            lines.append(f"  - {name} ({h}h)")
    lines.append("\nFix: ssh anthony-klaravex (rig via Tailscale) OR ssh root@hetzner-usa-watchdog; docker logs klaravex-worker --since 24h | grep error; verify celery beat schedule. See runbooks/rig-usa-ha-stack-2026-07-01.md §9.")

    escalate("high", f"Klaravex pipelines stale: {len(stale)} affected",
             "\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
