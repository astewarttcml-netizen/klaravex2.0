#!/usr/bin/env python3
"""
Klaravex resolution regression detector — T8.13.

Standalone script (not FastAPI). Run from cron or systemd timer:

    python -m klara.cron.loki_resolution_regression

Checks for the last 7 days of resolved tickets. A ticket is flagged as a
regression if its status was changed BACK to 'open' within 24 hours of
resolution (i.e., resolved_at is set, but updated_at > resolved_at and
status = 'open' OR the ticket history JSON log shows a reopen event).

Alert is sent to APPROVAL_NOTIFY_EMAIL if:
    regressions / total_resolved_last_7d > 10%

Required env vars:
    DATABASE_URL
    SMTP_PASS                  (M365 SMTP password)
    SMTP_USER                  (default: support@klaravex.com)
    APPROVAL_NOTIFY_EMAIL      (default: ANTHONY_ALERT_EMAIL → astewart@klaravex.com)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from klara.handlers.lib.db import get_pool, close_pool
    from klara.handlers.lib.email import send_email
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from klara.handlers.lib.db import get_pool, close_pool  # type: ignore[no-redef]
    from klara.handlers.lib.email import send_email  # type: ignore[no-redef]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("klaravex.cron.loki_resolution_regression")

APPROVAL_NOTIFY_EMAIL = os.environ.get(
    "APPROVAL_NOTIFY_EMAIL",
    os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com"),
)
REGRESSION_THRESHOLD = float(os.environ.get("REGRESSION_THRESHOLD", "0.10"))  # 10 %
REOPEN_WINDOW_HOURS = int(os.environ.get("REOPEN_WINDOW_HOURS", "24"))


async def _fetch_resolved_tickets(since: datetime) -> list[dict[str, Any]]:
    """Return tickets resolved in the last 7 days."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id,
                client_email,
                subject,
                status,
                resolved_at,
                updated_at,
                history
            FROM klaravex_tickets
            WHERE resolved_at >= $1
              AND resolved_at IS NOT NULL
            ORDER BY resolved_at DESC
            """,
            since,
        )
    return [dict(r) for r in rows]


def _is_regression(ticket: dict[str, Any], reopen_window: timedelta) -> bool:
    """Return True if the ticket was reopened within *reopen_window* of resolution.

    Two detection strategies:
    1. Direct: current status is 'open' and updated_at is within reopen_window
       of resolved_at.
    2. History log: scan the JSONB history array for an event where
       action/status == 'open' that occurred within reopen_window after resolved_at.
    """
    resolved_at = ticket.get("resolved_at")
    updated_at = ticket.get("updated_at")
    status = ticket.get("status")

    if not resolved_at:
        return False

    # Strategy 1: current status is open and the update happened soon after resolution.
    if status == "open" and updated_at and (updated_at - resolved_at) <= reopen_window:
        return True

    # Strategy 2: scan history log for a reopen event.
    history = ticket.get("history") or []
    if isinstance(history, str):
        import json as _json
        try:
            history = _json.loads(history)
        except Exception:
            history = []

    reopen_deadline = resolved_at + reopen_window
    for event in history:
        if not isinstance(event, dict):
            continue
        event_status = event.get("status") or event.get("action", "")
        event_ts_raw = event.get("timestamp") or event.get("at") or event.get("created_at")
        if event_status == "open" and event_ts_raw:
            try:
                if isinstance(event_ts_raw, str):
                    from datetime import datetime as _dt
                    event_ts = _dt.fromisoformat(event_ts_raw.replace("Z", "+00:00"))
                else:
                    event_ts = event_ts_raw
                if resolved_at <= event_ts <= reopen_deadline:
                    return True
            except Exception:
                continue

    return False


async def _send_alert(total: int, regressions: list[dict[str, Any]], rate: float) -> None:
    if not RESEND_API_KEY:
        log.warning("RESEND_API_KEY missing — regression alert email skipped")
        return

    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pct = f"{rate * 100:.1f}%"
    subject = (
        f"[Klaravex] Resolution Regression Alert — {pct} reopen rate "
        f"({len(regressions)}/{total} tickets) {run_date}"
    )

    lines = [
        f"Resolution regression check: {run_date}",
        f"Window: last 7 days of resolved tickets",
        f"Reopen threshold: {REOPEN_WINDOW_HOURS} hours post-resolution",
        f"Regression rate: {pct} ({len(regressions)} of {total} resolved tickets reopened)",
        f"Alert threshold: {REGRESSION_THRESHOLD * 100:.0f}%",
        "",
        "--- Regressed tickets ---",
    ]
    for t in regressions:
        resolved_str = t["resolved_at"].strftime("%Y-%m-%d %H:%M UTC") if t.get("resolved_at") else "?"
        lines.append(
            f"  [{t['id']}] {t.get('subject', '(no subject)')!r} "
            f"| client: {t.get('client_email', '?')} "
            f"| resolved: {resolved_str}"
        )

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": RESEND_FROM,
                "to": [APPROVAL_NOTIFY_EMAIL],
                "subject": subject,
                "text": "\n".join(lines),
            },
        )
    if r.status_code >= 300:
        log.error("Resend regression alert failed: %s %s", r.status_code, r.text)
    else:
        log.info(
            "Regression alert sent to %s (%d/%d regressions, %s)",
            APPROVAL_NOTIFY_EMAIL,
            len(regressions),
            total,
            pct,
        )


async def main() -> None:
    since = datetime.now(timezone.utc) - timedelta(days=7)
    reopen_window = timedelta(hours=REOPEN_WINDOW_HOURS)

    log.info(
        "loki_resolution_regression: checking tickets resolved since %s (reopen window=%dh)",
        since.strftime("%Y-%m-%d"),
        REOPEN_WINDOW_HOURS,
    )

    tickets = await _fetch_resolved_tickets(since)
    log.info("Found %d resolved tickets in the last 7 days", len(tickets))

    if not tickets:
        log.info("No resolved tickets — nothing to check")
        await close_pool()
        return

    regressions = [t for t in tickets if _is_regression(t, reopen_window)]
    rate = len(regressions) / len(tickets)

    log.info(
        "Regression rate: %.1f%% (%d/%d) — threshold: %.0f%%",
        rate * 100,
        len(regressions),
        len(tickets),
        REGRESSION_THRESHOLD * 100,
    )

    if rate > REGRESSION_THRESHOLD:
        log.warning("Regression rate exceeds threshold — sending alert")
        await _send_alert(len(tickets), regressions, rate)
    else:
        log.info("Regression rate within threshold — no alert")

    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
