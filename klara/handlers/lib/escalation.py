"""
Escalation dispatcher for Klaravex Klara AI backend.

Every time Klara AI cannot resolve a ticket, it calls ``escalate(...)`` which:
1. Marks the ticket as 'escalated'.
2. Writes a klaravex_escalations row.
3. Pushes a Telegram alert (if TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID set).
4. Sends an email alert via M365 SMTP (if SMTP_PASS set).

Both channels are best-effort. Per-channel errors are stored in
``delivered_via.errors`` so Anthony can see what failed.
"""

import json
import logging
import os
import uuid
from typing import Any, Optional

import asyncpg
import httpx

from .db import get_pool
from .email import send_email
from .tickets import update_status, append_event

log = logging.getLogger("klaravex.escalation")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")


async def _telegram_send(text: str) -> tuple[bool, Optional[str]]:
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return False, "missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID"
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                url,
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            )
        if r.status_code >= 400:
            return False, f"http {r.status_code}: {r.text[:200]}"
        return True, None
    except Exception as exc:
        return False, repr(exc)


async def _smtp_send(subject: str, body_text: str) -> tuple[bool, Optional[str]]:
    import os as _os
    if not _os.environ.get("SMTP_PASS", ""):
        return False, "missing SMTP_PASS"
    try:
        await send_email(to=ALERT_EMAIL, subject=subject, body=body_text)
        return True, None
    except Exception as exc:
        return False, repr(exc)


async def escalate(
    *,
    ticket_id: str,
    client_email: str,
    severity: str,
    summary: str,
    attempted: Optional[str] = None,
    recommended: Optional[str] = None,
) -> dict[str, Any]:
    """Mark ticket escalated, persist escalation row, dispatch alerts."""
    # 1. Update ticket status.
    try:
        await update_status(ticket_id, status="escalated")
        await append_event(ticket_id, "escalated", {"severity": severity, "summary": summary})
    except Exception as exc:
        log.exception("ticket status update failed during escalation: %s", exc)

    # 2. Dispatch.
    msg_md = (
        f"*Klaravex escalation* — {severity.upper()}\n"
        f"Client: `{client_email}`\n"
        f"Ticket: `{ticket_id}`\n\n"
        f"Summary: {summary}\n"
        + (f"\nAttempted: {attempted}" if attempted else "")
        + (f"\nRecommended: {recommended}" if recommended else "")
    )
    msg_txt = msg_md.replace("*", "").replace("`", "")

    tg_ok, tg_err = await _telegram_send(msg_md)
    email_ok, email_err = await _smtp_send(
        subject=f"[Klaravex/{severity}] Escalation — {client_email}",
        body_text=msg_txt,
    )

    delivered = {
        "telegram": tg_ok,
        "email": email_ok,
        "errors": [e for e in (tg_err, email_err) if e],
    }

    # 3. Persist escalation row. If the ticket_id has no matching klaravex_tickets
    # row (system escalations synthesise UUIDs), the FK will fail — retry with NULL
    # rather than lose the escalation record.
    pool = await get_pool()
    insert_sql = """
        INSERT INTO klaravex_escalations
            (ticket_id, client_email, severity, summary, attempted, recommended, delivered_via)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        RETURNING id
        """
    ticket_uuid: uuid.UUID | None = uuid.UUID(ticket_id)
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                insert_sql,
                ticket_uuid,
                client_email.lower(),
                severity,
                summary,
                attempted,
                recommended,
                json.dumps(delivered),
            )
        except asyncpg.exceptions.ForeignKeyViolationError:
            log.warning("escalation FK fallback: ticket %s not in klaravex_tickets, retrying with NULL", ticket_id)
            row = await conn.fetchrow(
                insert_sql,
                None,
                client_email.lower(),
                severity,
                summary,
                attempted,
                recommended,
                json.dumps(delivered),
            )
        esc_id = str(row["id"])
        log.warning("escalation %s dispatched: %s", esc_id, delivered)
        return {"escalation_id": esc_id, "delivered_via": delivered}


async def list_unacknowledged(limit: int = 50) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, ticket_id, client_email, severity, summary, recommended, created_at
              FROM klaravex_escalations
             WHERE acknowledged_at IS NULL
             ORDER BY created_at DESC
             LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]


async def acknowledge(escalation_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex_escalations SET acknowledged_at = now() WHERE id = $1",
            uuid.UUID(escalation_id),
        )
