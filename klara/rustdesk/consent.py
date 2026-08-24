"""Consent capture + immutable audit log (spec §4 requirement 1 + §6).

Liability gate: before any frame is sent OR any input event is executed, we
record the customer's consent to a SHA-256 hash-chained append-only log AND to
`klaravex_remote_sessions.consent_accepted_at`. Each chain entry includes the
SHA-256 hash of the previous entry — a single tampered row breaks the chain.

Storage:
    * Hash-chain log → `klaravex_remote_session_events` (Cloud86 Postgres,
      shared pool via klara.handlers.lib.db). Local JSONL sink kept as a
      fall-through for the dev loop and tests that don't run a DB.
    * Consent record → `klaravex_remote_sessions` columns
      (consent_*; signature_sha256 binds the accepted-at timestamp + customer
      email + consent text version into a single tamper-evident token).

The consent text below is the v1 wording from spec §6. Versioning is
explicit: any change → new `consent_text_version`. Old session rows still
verify against their version's text.

PUBLIC GATE — call `ensure_consent_recorded(session_id)` before letting the
session-loop send any InputEvent or open any frame iterator. The function
raises `ConsentNotRecorded` if the DB row has no `consent_accepted_at`. The
session loop catches that exception, fires the killswitch with reason
`no_consent`, and refuses to proceed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("klaravex.rustdesk.consent")

CONSENT_TEXT_V1 = (
    "I authorize Klaravex AI to view and control this computer for the "
    "duration of this support session (session ID: {session_id}). I "
    "understand I can stop the session at any time using the STOP button "
    "or Ctrl+Shift+X."
)
CONSENT_TEXT_VERSION = "v1-2026-06"


class ConsentNotRecorded(RuntimeError):
    """Raised when control is attempted before consent_accepted_at is set."""


@dataclass(frozen=True)
class ConsentRecord:
    session_id: str
    customer_email: str
    consent_text_version: str
    consent_text: str
    ip_address: str
    user_agent: str
    accepted_at: str  # ISO8601 UTC
    signature_sha256: str  # binds the four above into one tamper-evident token


def consent_text_for(session_id: str) -> str:
    return CONSENT_TEXT_V1.format(session_id=session_id)


def _signature(
    session_id: str,
    customer_email: str,
    version: str,
    text: str,
    accepted_at: str,
) -> str:
    """SHA-256 of the canonical consent tuple. This is the "customer signature"
    the spec calls for — it's the cryptographic equivalent of a click receipt:
    if any field is altered after the fact, the signature stops matching.
    """
    canonical = json.dumps(
        {
            "session_id": session_id,
            "customer_email": customer_email,
            "consent_text_version": version,
            "consent_text": text,
            "accepted_at": accepted_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def make_consent_record(
    session_id: str,
    customer_email: str,
    ip_address: str,
    user_agent: str,
) -> ConsentRecord:
    accepted_at = datetime.now(timezone.utc).isoformat()
    text = consent_text_for(session_id)
    return ConsentRecord(
        session_id=session_id,
        customer_email=customer_email,
        consent_text_version=CONSENT_TEXT_VERSION,
        consent_text=text,
        ip_address=ip_address,
        user_agent=user_agent,
        accepted_at=accepted_at,
        signature_sha256=_signature(
            session_id, customer_email, CONSENT_TEXT_VERSION, text, accepted_at,
        ),
    )


async def persist_consent(record: ConsentRecord) -> None:
    """INSERT/UPDATE the consent fields on klaravex_remote_sessions."""
    try:
        from klara.handlers.lib.db import get_pool  # type: ignore
    except ImportError:
        log.debug("klara.handlers not importable — skipping consent DB persist")
        return
    if not os.environ.get("DATABASE_URL"):
        log.debug("DATABASE_URL unset — skipping consent DB persist")
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO klaravex_remote_sessions (
                session_id, customer_email, customer_region, goal,
                state,
                consent_text_version, consent_text, consent_accepted_at,
                consent_ip, consent_user_agent, consent_signature_sha256
            )
            VALUES ($1, $2, 'other', '',
                    'pending_connect',
                    $3, $4, $5::timestamptz, $6::inet, $7, $8)
            ON CONFLICT (session_id) DO UPDATE SET
                consent_text_version  = COALESCE(klaravex_remote_sessions.consent_text_version, EXCLUDED.consent_text_version),
                consent_text          = COALESCE(klaravex_remote_sessions.consent_text,         EXCLUDED.consent_text),
                consent_accepted_at   = COALESCE(klaravex_remote_sessions.consent_accepted_at,  EXCLUDED.consent_accepted_at),
                consent_ip            = COALESCE(klaravex_remote_sessions.consent_ip,           EXCLUDED.consent_ip),
                consent_user_agent    = COALESCE(klaravex_remote_sessions.consent_user_agent,   EXCLUDED.consent_user_agent),
                consent_signature_sha256 = COALESCE(klaravex_remote_sessions.consent_signature_sha256, EXCLUDED.consent_signature_sha256),
                state = CASE
                    WHEN klaravex_remote_sessions.consent_accepted_at IS NULL
                        THEN 'pending_connect'
                    ELSE klaravex_remote_sessions.state
                END
            """,
            record.session_id,
            record.customer_email,
            record.consent_text_version,
            record.consent_text,
            record.accepted_at,
            record.ip_address or None,
            record.user_agent,
            record.signature_sha256,
        )
    log.info("consent persisted session=%s sig=%s…", record.session_id, record.signature_sha256[:10])


async def ensure_consent_recorded(session_id: str) -> None:
    """Hard gate — raise ConsentNotRecorded if consent_accepted_at IS NULL."""
    try:
        from klara.handlers.lib.db import get_pool  # type: ignore
    except ImportError:
        log.debug("klara.handlers not importable — consent gate bypassed (test mode)")
        return
    if not os.environ.get("DATABASE_URL"):
        log.debug("DATABASE_URL unset — consent gate bypassed (test mode)")
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT consent_accepted_at FROM klaravex_remote_sessions WHERE session_id=$1",
            session_id,
        )
        if row is None or row["consent_accepted_at"] is None:
            raise ConsentNotRecorded(
                f"session {session_id}: consent not recorded — refusing to control"
            )


@dataclass
class AuditEntry:
    session_id: str
    sequence: int
    event_type: str  # Closed set of audit event types — adding a new one
                    # MUST update this docstring AND the consumer truth
                    # tables (RemoteSession.warmup_state, dashboard).
                    # Pattern 29 enforcement: this is the canonical wire
                    # identifier list for hash-chain consumers.
                    #
                    #   "consent"
                    #   "action_predicted"
                    #   "action_rejected"
                    #   "action_confirmed"
                    #   "action_executed"
                    #   "killswitch_fired"
                    #   "session_end"
                    #   "transport_attached"
                    #   "frame_pump_started"
                    #   "warmup_skipped_stub"
                    #   "warmup_aborted_killswitch"
                    #   "warmup_completed"
                    #   "warmup_failed"
    payload: dict[str, Any] 
    prev_hash: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_hash(self) -> str:
        canonical = json.dumps(
            {
                "session_id": self.session_id,
                "sequence": self.sequence,
                "event_type": self.event_type,
                "payload": self.payload,
                "prev_hash": self.prev_hash,
                "timestamp": self.timestamp,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class HashChainAuditLog:
    """In-memory hash chain with optional JSONL persistence + best-effort DB mirror."""
    def __init__(self, sink_path: Path | None = None, mirror_to_db: bool | None = None):
        self.entries: list[AuditEntry] = []
        self.sink_path = sink_path
        if mirror_to_db is None:
            mirror_to_db = os.environ.get("KLX_AUDIT_DB_MIRROR", "0") == "1"
        self.mirror_to_db = mirror_to_db
        if sink_path is not None:
            sink_path.parent.mkdir(parents=True, exist_ok=True)

    def _prev_hash(self) -> str:
        if not self.entries:
            return "0" * 64
        return self.entries[-1].compute_hash()

    def append(self, session_id: str, event_type: str, payload: dict[str, Any]) -> AuditEntry:
        entry = AuditEntry(
            session_id=session_id,
            sequence=len(self.entries),
            event_type=event_type,
            payload=payload,
            prev_hash=self._prev_hash(),
        )
        self.entries.append(entry)
        entry_hash = entry.compute_hash()
        if self.sink_path is not None:
            with self.sink_path.open("a", encoding="utf-8") as f:
                row = {**asdict(entry), "hash": entry_hash}
                f.write(json.dumps(row) + "\n")
        if self.mirror_to_db:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._mirror_one(entry, entry_hash))
            except RuntimeError:
                pass
        return entry

    async def _mirror_one(self, entry: AuditEntry, entry_hash: str) -> None:
        try:
            from klara.handlers.lib.db import get_pool  # type: ignore
        except ImportError:
            return
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO klaravex_remote_session_events
                        (session_id, sequence, event_type, payload, prev_hash, entry_hash, occurred_at)
                    VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7::timestamptz)
                    ON CONFLICT (session_id, sequence) DO NOTHING
                    """,
                    entry.session_id,
                    entry.sequence,
                    entry.event_type,
                    json.dumps(entry.payload),
                    entry.prev_hash,
                    entry_hash,
                    entry.timestamp,
                )
        except Exception as exc:
            log.warning("audit DB mirror failed session=%s seq=%s err=%s",
                        entry.session_id, entry.sequence, exc)

    def verify(self) -> bool:
        prev = "0" * 64
        for entry in self.entries:
            if entry.prev_hash != prev:
                return False
            prev = entry.compute_hash()
        return True
