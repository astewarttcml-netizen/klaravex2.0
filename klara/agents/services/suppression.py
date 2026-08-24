"""
app/services/suppression.py
───────────────────────────
phase4-005 — email suppression service.

Two public functions:
  is_suppressed(db, email)         — O(1) pre-send check
  add_to_suppression(db, email, ...) — idempotent insert (ON CONFLICT DO NOTHING)

Email is stored and matched lowercased. Both functions accept any case at
the call site and normalise internally.

An exception type is exported (SuppressedRecipient) for callers that want
to fail-fast at send time instead of silently skipping.
"""
from __future__ import annotations

from typing import Optional
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_suppression import EmailSuppression, SuppressionSource

logger = structlog.get_logger(__name__)


class SuppressedRecipient(Exception):
    """Raised by pre-send checks when the recipient is on the suppression list."""

    def __init__(self, email: str, source: Optional[str] = None):
        self.email = email
        self.source = source
        super().__init__(
            f"Recipient {email!r} is on the suppression list"
            + (f" (source={source})" if source else "")
        )


def _norm(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    return email.strip().lower()


async def is_suppressed(db: AsyncSession, email: Optional[str]) -> bool:
    """True iff the (case-normalised) email is on the suppression list."""
    norm = _norm(email)
    if not norm:
        return False
    result = await db.execute(
        select(EmailSuppression.id).where(EmailSuppression.email == norm)
    )
    return result.scalar_one_or_none() is not None


async def get_suppression(
    db: AsyncSession, email: Optional[str]
) -> Optional[EmailSuppression]:
    """Return the suppression row or None. Useful when callers need source/reason."""
    norm = _norm(email)
    if not norm:
        return None
    result = await db.execute(
        select(EmailSuppression).where(EmailSuppression.email == norm)
    )
    return result.scalar_one_or_none()


async def add_to_suppression(
    db: AsyncSession,
    email: Optional[str],
    *,
    source: str = SuppressionSource.manual,
    reason: Optional[str] = None,
) -> bool:
    """
    Add an email to the suppression list. Returns True if a new row was
    inserted, False if it was already suppressed (idempotent).

    Uses Postgres ON CONFLICT DO NOTHING so concurrent inserts from
    different agents/webhook handlers can't race-create duplicates.
    """
    norm = _norm(email)
    if not norm:
        return False

    stmt = (
        pg_insert(EmailSuppression)
        .values(
            id=str(uuid4()),
            email=norm,
            source=source,
            reason=reason,
        )
        .on_conflict_do_nothing(index_elements=["email"])
        .returning(EmailSuppression.id)
    )
    result = await db.execute(stmt)
    inserted = result.scalar_one_or_none()
    if inserted is not None:
        logger.info(
            "suppression.added",
            email=norm,
            source=source,
            id=inserted,
        )
        return True
    logger.info("suppression.already_present", email=norm)
    return False


async def assert_not_suppressed(db: AsyncSession, email: Optional[str]) -> None:
    """Convenience for pre-send checks: raises SuppressedRecipient if listed."""
    row = await get_suppression(db, email)
    if row is not None:
        raise SuppressedRecipient(email or "", source=row.source)
