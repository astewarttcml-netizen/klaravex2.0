"""
GDPR / CCPA data export — self-service.

A logged-in client clicks "Export my data" in the portal.
We assemble all data we hold about them as a JSON bundle,
store it inline in the DB (under 1MB for typical clients),
and email a one-time signed download URL (24-hour TTL).
"""

import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import get_pool
from .email import send_email

log = logging.getLogger("klaravex.data_export")

PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")
EXPORT_TTL_HOURS = int(os.environ.get("DATA_EXPORT_TTL_HOURS", "24"))


def _hash_token(plaintext: str) -> bytes:
    return hashlib.sha256(plaintext.encode("utf-8")).digest()


async def _assemble_bundle(email: str) -> dict:
    """Pull every klaravex_* table row that references this email."""
    email_lc = email.lower()
    pool = await get_pool()
    bundle: dict[str, object] = {
        "schema_version": "1.0",
        "subject_email": email_lc,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "exported_by": "Klaravex automated data-export pipeline",
        "data": {},
    }

    async with pool.acquire() as conn:
        # Identity
        client = await conn.fetchrow(
            "SELECT * FROM klaravex_clients WHERE email=$1", email_lc,
        )
        bundle["data"]["client_profile"] = dict(client) if client else None

        # Tickets
        tickets = await conn.fetch(
            "SELECT * FROM klaravex_tickets WHERE client_email=$1 ORDER BY created_at",
            email_lc,
        )
        bundle["data"]["tickets"] = [dict(r) for r in tickets]

        # Hours ledger
        try:
            ledger = await conn.fetch(
                "SELECT * FROM klaravex_hours_ledger WHERE client_email=$1 ORDER BY created_at",
                email_lc,
            )
            bundle["data"]["hours_ledger"] = [dict(r) for r in ledger]
        except Exception:
            bundle["data"]["hours_ledger"] = []

        # Renewal reminders sent
        try:
            renewals = await conn.fetch(
                "SELECT * FROM klaravex_renewal_reminders WHERE email=$1 ORDER BY sent_at",
                email_lc,
            )
            bundle["data"]["renewal_reminders"] = [dict(r) for r in renewals]
        except Exception:
            bundle["data"]["renewal_reminders"] = []

        # Cancellation attempts
        try:
            cancels = await conn.fetch(
                "SELECT * FROM klaravex_cancellation_attempts WHERE email=$1 ORDER BY created_at",
                email_lc,
            )
            bundle["data"]["cancellation_attempts"] = [dict(r) for r in cancels]
        except Exception:
            bundle["data"]["cancellation_attempts"] = []

        # SMS sessions
        try:
            sms = await conn.fetch(
                """
                SELECT s.* FROM klaravex_sms_sessions s
                JOIN klaravex_clients c ON c.id = s.client_id
                WHERE c.email=$1 ORDER BY s.created_at
                """,
                email_lc,
            )
            bundle["data"]["sms_sessions"] = [dict(r) for r in sms]
        except Exception:
            bundle["data"]["sms_sessions"] = []

        # Portal session/login token history (count only; sensitive content excluded)
        try:
            token_count = await conn.fetchval(
                "SELECT COUNT(*) FROM klaravex_portal_tokens WHERE email=$1",
                email_lc,
            )
            bundle["data"]["portal_token_history_count"] = int(token_count or 0)
        except Exception:
            bundle["data"]["portal_token_history_count"] = 0

        # Welcome email metadata
        try:
            welcome_sent_at = await conn.fetchval(
                "SELECT welcome_sent_at FROM klaravex_clients WHERE email=$1",
                email_lc,
            )
            bundle["data"]["welcome_email_sent_at"] = welcome_sent_at.isoformat() if welcome_sent_at else None
        except Exception:
            pass

    # Convert datetimes / UUIDs / bytes to JSON-safe primitives
    import uuid
    from decimal import Decimal

    def _scrub(o):
        if isinstance(o, dict):
            return {k: _scrub(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_scrub(v) for v in o]
        if isinstance(o, (datetime,)):
            return o.isoformat()
        if isinstance(o, uuid.UUID):
            return str(o)
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, bytes):
            return f"<bytes:{len(o)}>"
        return o

    bundle["data"] = _scrub(bundle["data"])
    return bundle


async def request_export(email: str) -> dict:
    """Trigger a fresh export. Returns metadata about the export request."""
    pool = await get_pool()
    plaintext_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(plaintext_token)
    expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=EXPORT_TTL_HOURS)

    # Insert pending row
    async with pool.acquire() as conn:
        request_id = await conn.fetchval(
            """
            INSERT INTO klaravex_data_export_requests
                (email, status, token_hash, expires_at)
            VALUES ($1, 'building', $2, $3)
            RETURNING id::text
            """,
            email.lower(), token_hash, expires_at,
        )

    # Assemble synchronously (v1; data sets are small)
    try:
        bundle = await _assemble_bundle(email)
        json_bytes = json.dumps(bundle, indent=2, ensure_ascii=False).encode("utf-8")
        ticket_count = len((bundle.get("data") or {}).get("tickets") or [])

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE klaravex_data_export_requests
                   SET status='ready', file_bytes=$1, byte_count=$2, ticket_count=$3, completed_at=now()
                 WHERE id=$4
                """,
                json_bytes, len(json_bytes), ticket_count, request_id,
            )

        download_url = f"{PORTAL_BASE_URL.rstrip('/')}/portal/data-export/download?token={plaintext_token}"

        # Email the user
        body = (
            f"Hi,\n\n"
            f"Your Klaravex data export is ready.\n\n"
            f"  Records: {ticket_count} tickets + your profile and history\n"
            f"  Size:    {len(json_bytes):,} bytes\n"
            f"  Format:  JSON (machine-readable, suitable for transfer to another provider)\n\n"
            f"Download (single use, expires in {EXPORT_TTL_HOURS} hours):\n\n"
            f"  {download_url}\n\n"
            f"This link is tied to your account. After {EXPORT_TTL_HOURS} hours or one download,\n"
            f"it expires. Request a fresh one anytime from {PORTAL_BASE_URL}/portal/data-export.\n\n"
            f"Questions about what's included? Reply to this email.\n\n"
            f"— The Klaravex Team\n"
        )
        await send_email(to=email, subject="Your Klaravex data export is ready", body=body)
        log.info("data export ready for %s (bytes=%d, tickets=%d)", email, len(json_bytes), ticket_count)
        return {
            "request_id": request_id,
            "status": "ready",
            "byte_count": len(json_bytes),
            "ticket_count": ticket_count,
            "expires_at": expires_at.isoformat(),
        }
    except Exception as exc:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE klaravex_data_export_requests SET status='failed', error=$1 WHERE id=$2",
                str(exc)[:500], request_id,
            )
        log.exception("data export build failed for %s: %s", email, exc)
        return {"request_id": request_id, "status": "failed", "error": str(exc)}


async def resolve_download_token(plaintext_token: str) -> Optional[tuple[str, bytes]]:
    """Return (email, file_bytes) if the token is valid and not yet downloaded/expired."""
    token_hash = _hash_token(plaintext_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, email, file_bytes, expires_at, downloaded_at, status
              FROM klaravex_data_export_requests
             WHERE token_hash = $1
            """,
            token_hash,
        )
        if not row:
            return None
        if row["status"] != "ready":
            return None
        if row["downloaded_at"] is not None:
            return None
        if row["expires_at"] < datetime.now(tz=timezone.utc):
            return None
        # Mark downloaded
        await conn.execute(
            "UPDATE klaravex_data_export_requests SET downloaded_at=now() WHERE id=$1",
            row["id"],
        )
        return row["email"], bytes(row["file_bytes"])


async def list_export_requests(email: str) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, status, byte_count, ticket_count, created_at, completed_at,
                   expires_at, downloaded_at
              FROM klaravex_data_export_requests
             WHERE email=$1 ORDER BY created_at DESC LIMIT 10
            """,
            email.lower(),
        )
    return [
        {
            "id": str(r["id"]),
            "status": r["status"],
            "byte_count": r["byte_count"],
            "ticket_count": r["ticket_count"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
            "downloaded_at": r["downloaded_at"].isoformat() if r["downloaded_at"] else None,
        }
        for r in rows
    ]
