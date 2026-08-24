"""Repository seam for `klaravex.customer_helper_tokens`.

Architecture-review finding (review-20260621T123417Z-1 High [1][2][6][7])
called out four overlapping debts in iter-1's handler:
  - SQL embedded in HTTP handler (no repository seam)
  - DIP violation: handler imports `get_pool()` directly
  - TOCTOU two-round-trip on the failure path (`_atomic_redeem` then
    `_explain_failure`) with an unreachable 500 branch
  - `get_pool()` invoked 3x per request

This module collapses them:

  - `RedeemOutcome` — discriminated union of every terminal state
    (`Redeemed | Unknown | Expired | AlreadyRedeemed | PaymentMissing`).
    Handlers translate outcome → HTTP status; no SQL knowledge required.
  - `TokenStore` Protocol — call shape the handler depends on.
  - `PgTokenStore` — default Postgres implementation. ONE round-trip per
    redeem via a CTE that wraps `SELECT … FOR UPDATE` + conditional
    `UPDATE … RETURNING` in a single statement. The row returned tells
    the caller both whether the redeem won the race AND why it lost.
  - `AuditLog` Protocol + `PgAuditLog` — symmetric DI seam for the
    `note_submissions` row the handler emits. Added in iter-3 to close
    the half-inverted persistence boundary flagged in
    review-20260621T124700Z-2 High [1].

Per CLAUDE.md Pattern 32 routing: this store talks to Azure klaravex-db
ONLY (klaravex_api / klaravex.com surface). Never use this against the
Cloud86 dediviac_db0 (decommissioned).
"""

import datetime as dt
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path as FsPath
from typing import Optional, Protocol, Union

from .customer_helper_schemas import Session
from .lib.db import get_pool

log = logging.getLogger("klaravex.customer_helper.store")


# ---------------------------------------------------------------------------
# Outcome ADT
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Redeemed:
    session: Session


@dataclass(frozen=True)
class Unknown:
    """No row matched the token_sha — 404."""


@dataclass(frozen=True)
class AlreadyRedeemed:
    """Row exists, redeemed_at IS NOT NULL — 410."""


@dataclass(frozen=True)
class Expired:
    """Row exists, expires_at <= now() — 410."""


@dataclass(frozen=True)
class PaymentMissing:
    """Row exists, payment_confirmed IS FALSE — 402."""


RedeemOutcome = Union[Redeemed, Unknown, AlreadyRedeemed, Expired, PaymentMissing]


# Peek-only ADT for the /download eligibility check. Subset of
# RedeemOutcome that drops the `Redeemed` success variant — peek MUST
# NOT mutate the row, so a successful peek returns `Available` (no
# session payload, just permission to download). Keeping this as a
# distinct sum type rather than reusing `Redeemed` means the type
# checker rejects accidental misuse like `await store.peek(t)` then
# `session = outcome.session` on the assumption that peek hands back
# the post-redeem credentials.
@dataclass(frozen=True)
class Available:
    """Row exists, payment_confirmed=TRUE, redeemed_at IS NULL, not
    expired — token is eligible to download the helper binary."""


PeekOutcome = Union[Available, Unknown, AlreadyRedeemed, Expired, PaymentMissing]


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class TokenStore(Protocol):
    """Contract the redeem handler depends on.

    Implementations MUST:
      - Be atomic w.r.t. the redeemed_at flip (concurrent redeems on the
        same token produce at most one `Redeemed`).
      - Translate every infrastructure error into an exception (this
        contract does not include a "transport failed" outcome; let
        FastAPI surface a 5xx).
    """

    async def try_redeem(self, token_sha: bytes) -> RedeemOutcome: ...

    async def peek(self, token_sha: bytes) -> PeekOutcome:
        """Read-only eligibility check for /download.

        Implementations MUST NOT mutate the row. Returns `Available`
        when the same eligibility predicates the redeem CTE enforces
        all hold; otherwise the matching failure variant. Concurrent
        peeks on the same token are race-free because no SELECT FOR
        UPDATE is required — token_sha256 is the table's primary key
        so this is a single index lookup + heap fetch per peek.

        Performance follow-up (iter-58 next-iteration-intent): the
        peek-only SELECT could become index-only with a covering
        index on (token_sha256, redeemed_at, expires_at,
        payment_confirmed). Schema today has only the PK
        (idx_cht_expires_at is a separate index used for expiry
        sweeps). Do NOT claim the covering index exists until the
        migration is applied to Azure klaravex-db.
        """
        ...


# ---------------------------------------------------------------------------
# Default Postgres implementation
# ---------------------------------------------------------------------------


# Single-statement redeem.
#
#   `locked` SELECTs the row FOR UPDATE so concurrent redeems serialize.
#   `upd` UPDATEs redeemed_at, returning session columns ONLY if all
#   eligibility predicates hold. The outer SELECT joins both so a single
#   row carries either the success payload OR the failure-classification
#   columns (payment_confirmed, prev_redeemed_at, expired) from `locked`.
#
# Returns:
#   0 rows  → unknown token (locked produced nothing)
#   1 row, customer_session_id IS NOT NULL → success
#   1 row, customer_session_id IS NULL     → eligibility check failed;
#       classify via payment_confirmed / prev_redeemed_at / expired
# Read-only eligibility check for /download. No FOR UPDATE — concurrent
# peeks are safe because no row state is changing. token_sha256 is the
# table PK so this is one index lookup + one heap fetch per peek; the
# covering-index variant called for by review-20260621T131000Z [P4] is
# still a queued migration (manifest iter-57 next_iteration_intent),
# NOT a fact about today's schema. Do not let a future reader trust an
# index-only-scan claim that isn't there.
_PEEK_SQL = """
SELECT payment_confirmed,
       redeemed_at,
       (expires_at <= now()) AS expired
  FROM klaravex.customer_helper_tokens
 WHERE token_sha256 = $1;
"""


_REDEEM_SQL = """
WITH locked AS (
  SELECT token_sha256,
         payment_confirmed,
         redeemed_at,
         expires_at
    FROM klaravex.customer_helper_tokens
   WHERE token_sha256 = $1
   FOR UPDATE
),
upd AS (
  UPDATE klaravex.customer_helper_tokens t
     SET redeemed_at = now()
    FROM locked l
   WHERE t.token_sha256 = l.token_sha256
     AND l.payment_confirmed = TRUE
     AND l.redeemed_at IS NULL
     AND l.expires_at > now()
  RETURNING t.customer_session_id,
           t.session_password,
           t.expires_at AS sess_expires_at,
           t.display_topic,
           t.operator_label
)
SELECT l.payment_confirmed,
       l.redeemed_at  AS prev_redeemed_at,
       (l.expires_at <= now()) AS expired,
       u.customer_session_id,
       u.session_password,
       u.sess_expires_at,
       u.display_topic,
       u.operator_label
  FROM locked l
  LEFT JOIN upd u ON TRUE;
"""


class PgTokenStore:
    """Default `TokenStore` backed by the shared klaravex-db asyncpg pool."""

    async def try_redeem(self, token_sha: bytes) -> RedeemOutcome:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(_REDEEM_SQL, token_sha)

        if row is None:
            return Unknown()

        if row["customer_session_id"] is not None:
            return Redeemed(
                session=_row_to_session(row),
            )

        if row["prev_redeemed_at"] is not None:
            return AlreadyRedeemed()
        if row["expired"]:
            return Expired()
        if not row["payment_confirmed"]:
            return PaymentMissing()

        # All eligibility flags green but UPDATE matched 0 rows. Genuinely
        # unreachable under Postgres MVCC + SELECT FOR UPDATE within one
        # transaction — but if it ever fires (driver bug, future schema
        # drift, deferred constraints), the dashboard must not see a
        # legitimate-looking 410. Log a WARNING that the watchdog can
        # alert on, then map to AlreadyRedeemed so the customer retries
        # cleanly. (review-20260621T124700Z-2 Low [5])
        log.warning(
            "customer_helper.redeem race_loss eligibility_all_green_but_update_matched_zero "
            "token_h16=%s",
            token_sha[:8].hex(),
        )
        return AlreadyRedeemed()

    async def peek(self, token_sha: bytes) -> PeekOutcome:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(_PEEK_SQL, token_sha)

        if row is None:
            return Unknown()
        if row["redeemed_at"] is not None:
            return AlreadyRedeemed()
        if row["expired"]:
            return Expired()
        if not row["payment_confirmed"]:
            return PaymentMissing()
        return Available()


def _row_to_session(row: dict) -> Session:
    exp: dt.datetime = row["sess_expires_at"]
    return Session(
        customer_session_id=row["customer_session_id"],
        session_password=row["session_password"],
        expires_at=exp.isoformat(),
        display_topic=row["display_topic"],
        operator_label=row["operator_label"] or "Klara (AI)",
    )


# ---------------------------------------------------------------------------
# Audit-log seam
# ---------------------------------------------------------------------------


class AuditLog(Protocol):
    """Contract for the best-effort `note_submissions` row.

    Implementations MUST NOT raise — the customer has already paid and is
    waiting for a session. A persistence failure here is logged but never
    propagated. Tests inject a spy implementation to lock the call shape.
    """

    async def record_redeem(
        self, token_h16: str, customer_session_id: str
    ) -> None: ...


class PgAuditLog:
    """Default `AuditLog` backed by the shared klaravex-db asyncpg pool.

    Symmetric DI seam with `PgTokenStore`: every persistence dependency
    in this handler module crosses the same Protocol boundary, so a future
    "reuse one connection per request" optimization can span both halves
    (review-20260621T124700Z-2 High [1]).
    """

    async def record_redeem(
        self, token_h16: str, customer_session_id: str
    ) -> None:
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO note_submissions
                        (agent_id, topic, surface, action_summary, created_at)
                    VALUES ($1, $2, $3, $4, now())
                    """,
                    "klaravex-api/customer-helper",
                    "api-integration",
                    "klaravex.com",
                    f"customer_helper.redeem token_h16={token_h16} "
                    f"session_id={customer_session_id}",
                )
        except Exception as exc:  # noqa: BLE001 — surface to logs, never raise
            log.warning(
                "note_submissions write failed for token_h16=%s err=%s",
                token_h16,
                exc,
            )


# ---------------------------------------------------------------------------
# Binary-store seam
# ---------------------------------------------------------------------------
#
# Third persistence boundary in this handler module, alongside
# `TokenStore` (Postgres) and `AuditLog` (Postgres). Iter-57 shipped
# the /download handler with the filesystem read hardcoded into
# `customer_helper._resolve_binary`; review-20260622T215846Z-1 High
# flagged the asymmetric DI as a regression of pattern-40 (every
# persistence dependency in this module crosses the same Protocol
# shape). Iter-58 lifts the filesystem read behind `BinaryStore` so
# tests can inject a one-line fake and the production handler depends
# only on the abstract shape.


@dataclass(frozen=True)
class BinaryArtifact:
    """Resolved signed-binary artifact for one platform.

    `path` is the on-disk file FileResponse will stream via sendfile(2).
    `sha256` is the strong ETag value the handler emits — pre-computed
    by scripts/build_customer_helpers at sign time so the request hot
    path never hashes the 80MB payload (iter-55/56 [P1] fix).
    """

    path: FsPath
    sha256: str


class BinaryStore(Protocol):
    """Contract the /download handler depends on for binary lookup.

    Implementations resolve `platform` → `BinaryArtifact` or return
    None when the platform is not yet served (pre-procurement: e.g.
    mac notarization still pending). Returning None — never raising
    — is load-bearing: the handler maps None → HTTP 503 with parity
    to the stub. Raising would mask the pre-procurement state as a
    5xx and surface in dashboards as an outage.
    """

    def resolve(self, platform: str) -> Optional[BinaryArtifact]: ...


class FsBinaryStore:
    """Default `BinaryStore` — reads a manifest from `KLX_HELPER_BINARIES_DIR`.

    Manifest schema (manifest.json colocated with the binaries):
        {"mac-arm64": {"file": "Klaravex-Helper-arm64.dmg",
                       "sha256": "abcd..."}, ...}

    Resolution is "all-or-None": any missing piece (env unset, dir
    absent, manifest unreadable, entry missing, sha missing, file
    missing, OR file escapes the binaries dir via the manifest's
    `file` field) returns None. The last check (containment) closes
    the path-traversal vector security-sentinel S2988 flagged on
    iter-57: a manifest authored or tampered with by a non-trusted
    process could otherwise name `../../etc/passwd` and have the
    handler stream that file.
    """

    def resolve(self, platform: str) -> Optional[BinaryArtifact]:
        raw = os.environ.get("KLX_HELPER_BINARIES_DIR")
        if not raw:
            return None
        base = FsPath(raw)

        manifest_path = base / "manifest.json"
        if not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("customer_helper.download manifest_unreadable err=%s", exc)
            return None

        entry = manifest.get(platform)
        if not isinstance(entry, dict):
            return None
        fname = entry.get("file")
        sha = entry.get("sha256")
        if not isinstance(fname, str) or not isinstance(sha, str):
            return None

        file_path = base / fname
        # Path-traversal guard: resolve both sides and require the
        # candidate to live inside `base`. `is_relative_to` was added
        # in Python 3.9. If the file does not exist its `.resolve()`
        # still produces a normalized absolute path we can compare.
        try:
            base_resolved = base.resolve()
            file_resolved = file_path.resolve()
        except OSError as exc:
            log.warning(
                "customer_helper.download path_resolve_failed platform=%s err=%s",
                platform,
                exc,
            )
            return None
        if not file_resolved.is_relative_to(base_resolved):
            log.warning(
                "customer_helper.download manifest_path_escape platform=%s name=%r",
                platform,
                fname,
            )
            return None

        if not file_resolved.is_file():
            return None
        return BinaryArtifact(path=file_resolved, sha256=sha)


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


_default_store: TokenStore = PgTokenStore()
_default_audit: AuditLog = PgAuditLog()
_default_binaries: BinaryStore = FsBinaryStore()


def get_token_store() -> TokenStore:
    """FastAPI dependency. Tests override via `app.dependency_overrides`."""
    return _default_store


def get_audit_log() -> AuditLog:
    """FastAPI dependency. Tests override via `app.dependency_overrides`."""
    return _default_audit


def get_binary_store() -> BinaryStore:
    """FastAPI dependency. Tests override via `app.dependency_overrides`."""
    return _default_binaries
