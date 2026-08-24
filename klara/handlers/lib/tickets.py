"""
Ticket writer for Klaravex Klara AI backend.

Single source of truth for creating and updating klaravex_tickets rows.
Every handler (intake, stripe webhook, smartlead webhook, calendly, chat) calls
into this module so the ticket table is the audit log of all client touches.

Public surface:
    create_ticket(...)          -> ticket_id (uuid str)
    append_event(ticket_id, …)  -> None
    update_status(ticket_id, …) -> None
    get_or_create_client(...)   -> client_id (uuid str)
    list_tickets_for_email(...) -> list of dicts
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .db import get_pool

log = logging.getLogger("klaravex.tickets")

VALID_SEVERITY = {"low", "standard", "high", "emergency"}
VALID_STATUS = {"open", "in_progress", "waiting_client", "resolved", "closed", "escalated"}
VALID_SOURCE = {"chat", "intake_consumer", "intake_b2b", "stripe", "smartlead", "calendly", "workflow", "portal"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_or_create_client(
    email: str,
    *,
    segment: str,
    name: Optional[str] = None,
    stripe_customer_id: Optional[str] = None,
    company: Optional[str] = None,
    phone: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    """Return client UUID, upserting by email."""
    if segment not in ("consumer", "b2b"):
        raise ValueError(f"invalid segment: {segment!r}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO klaravex_clients
                (email, name, segment, stripe_customer_id, company, phone, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
            ON CONFLICT (email) DO UPDATE
              SET name = COALESCE(EXCLUDED.name, klaravex_clients.name),
                  stripe_customer_id = COALESCE(EXCLUDED.stripe_customer_id, klaravex_clients.stripe_customer_id),
                  company = COALESCE(EXCLUDED.company, klaravex_clients.company),
                  phone   = COALESCE(EXCLUDED.phone, klaravex_clients.phone),
                  metadata = klaravex_clients.metadata || EXCLUDED.metadata,
                  updated_at = now()
            RETURNING id
            """,
            email.lower(),
            name,
            segment,
            stripe_customer_id,
            company,
            phone,
            json.dumps(metadata or {}),
        )
        return str(row["id"])


async def create_ticket(
    *,
    client_email: str,
    subject: str,
    severity: str = "standard",
    status: str = "open",
    source: str,
    summary: Optional[str] = None,
    archetype: Optional[str] = None,
    sku: Optional[str] = None,
    workflow_state: Optional[str] = None,
    assignee: str = "loki",
    metadata: Optional[dict[str, Any]] = None,
    initial_event: Optional[dict[str, Any]] = None,
    segment_hint: str = "consumer",
) -> str:
    """Create a ticket. Returns the ticket UUID."""
    if severity not in VALID_SEVERITY:
        raise ValueError(f"invalid severity: {severity!r}")
    if status not in VALID_STATUS:
        raise ValueError(f"invalid status: {status!r}")
    if source not in VALID_SOURCE:
        raise ValueError(f"invalid source: {source!r}")

    client_id = await get_or_create_client(client_email, segment=segment_hint)
    history = [initial_event] if initial_event else [{"at": _now_iso(), "type": "created", "source": source}]

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO klaravex_tickets
                (client_id, client_email, severity, status, assignee, source,
                 archetype, sku, workflow_state, subject, summary, history, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13::jsonb)
            RETURNING id
            """,
            uuid.UUID(client_id),
            client_email.lower(),
            severity,
            status,
            assignee,
            source,
            archetype,
            sku,
            workflow_state,
            subject,
            summary,
            json.dumps(history),
            json.dumps(metadata or {}),
        )
        ticket_id = str(row["id"])
        log.info("ticket created id=%s source=%s severity=%s", ticket_id, source, severity)
        return ticket_id


async def append_event(ticket_id: str, event_type: str, payload: Optional[dict[str, Any]] = None) -> None:
    """Append an event to a ticket history."""
    event = {"at": _now_iso(), "type": event_type, **(payload or {})}
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE klaravex_tickets
               SET history = history || $2::jsonb,
                   updated_at = now()
             WHERE id = $1
            """,
            uuid.UUID(ticket_id),
            json.dumps([event]),
        )


async def update_status(
    ticket_id: str,
    *,
    status: str,
    resolution: Optional[str] = None,
    assignee: Optional[str] = None,
    workflow_state: Optional[str] = None,
) -> None:
    if status not in VALID_STATUS:
        raise ValueError(f"invalid status: {status!r}")
    resolved_at = "now()" if status in ("resolved", "closed") else "NULL"
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE klaravex_tickets
               SET status = $2,
                   resolution = COALESCE($3, resolution),
                   assignee = COALESCE($4, assignee),
                   workflow_state = COALESCE($5, workflow_state),
                   resolved_at = {resolved_at},
                   updated_at = now()
             WHERE id = $1
            RETURNING client_email, subject, status, assignee
            """,
            uuid.UUID(ticket_id),
            status,
            resolution,
            assignee,
            workflow_state,
        )
    if row is not None:
        await _notify_status_change(ticket_id, row)


async def _notify_status_change(ticket_id: str, row: Any) -> None:
    """Best-effort internal email on status change. One email per real,
    human/engineer-driven status transition -- not a high-frequency loop, so
    no cooldown/dedup needed here (unlike the marketing autopilot's
    request_human_approval, which fires from an LLM re-deciding every tick)."""
    import os

    from .email import send_email

    alert_email = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
    subject = f"[Ticket] {row['status']} — {row['subject'] or ticket_id}"
    body = (
        f"Ticket:   {ticket_id}\n"
        f"Client:   {row['client_email']}\n"
        f"Status:   {row['status']}\n"
        f"Assignee: {row['assignee'] or '—'}\n"
    )
    try:
        await send_email(alert_email, subject, body)
    except Exception as e:  # noqa: BLE001
        log.warning("ticket status-change email failed ticket_id=%s: %s", ticket_id, e)


async def list_tickets_for_email(email: str, *, limit: int = 50) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, severity, status, source, subject, summary,
                   archetype, sku, workflow_state, created_at, updated_at, resolved_at
              FROM klaravex_tickets
             WHERE client_email = $1
             ORDER BY created_at DESC
             LIMIT $2
            """,
            email.lower(),
            limit,
        )
        return [dict(r) for r in rows]


async def stats_for_email(email: str) -> dict[str, int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
              COUNT(*)                                 AS total,
              COUNT(*) FILTER (WHERE status = 'open')        AS open,
              COUNT(*) FILTER (WHERE status = 'escalated')   AS escalated,
              COUNT(*) FILTER (WHERE status IN ('resolved','closed')) AS resolved
              FROM klaravex_tickets
             WHERE client_email = $1
            """,
            email.lower(),
        )
        return {k: int(v or 0) for k, v in dict(row).items()}
