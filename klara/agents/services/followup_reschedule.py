"""
app/services/followup_reschedule.py
────────────────────────────────────
phase4-004 — push pending follow-ups out past an OOO window.

When a cold-outreach prospect returns an auto-reply with intent
OUT_OF_OFFICE and a parsed return_date, this service:
  1. Stamps prospect.out_of_office_until = return_date
  2. Re-times any non-terminal OutreachSequence rows whose scheduled_at
     falls on or before return_date — pushing them to (return_date + 1 day)
     at the same time of day they were already scheduled.
  3. Returns the count of rows that were pushed.

The companion check in app/services/outreach_followup.eligible_for_followup
treats a future out_of_office_until as a blocker so even un-rescheduled
sends are suppressed inside the OOO window.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outreach_sequence import OutreachSequence, OutreachSequenceStatus
from app.models.prospected_lead import ProspectedLead

logger = structlog.get_logger(__name__)


# OutreachSequence statuses that should NOT be touched — they're already
# delivered, suppressed, or cancelled and rescheduling them would be wrong.
_TERMINAL_STATUSES = frozenset({
    OutreachSequenceStatus.sent,
    OutreachSequenceStatus.suppressed,
    OutreachSequenceStatus.cancelled,
})


async def reschedule_after_ooo(
    db: AsyncSession,
    prospect: ProspectedLead,
    return_date: date,
) -> int:
    """
    Push pending OutreachSequence rows past return_date and stamp the
    prospect's OOO window. Returns the number of sequence rows pushed.

    Behaviour:
      • If return_date is None or in the past, this is a no-op (returns 0).
      • prospect.out_of_office_until is set unconditionally so the
        eligibility check stays correct even if there are no pending rows.
      • Each non-terminal sequence row whose scheduled_at date falls at
        or before return_date is moved to (return_date + 1 day) preserving
        the original time-of-day (UTC).
      • Rows already scheduled after return_date are left alone.
    """
    if return_date is None:
        logger.info(
            "followup_reschedule.no_return_date",
            prospect_id=prospect.id,
        )
        return 0

    today_utc = datetime.now(timezone.utc).date()
    if return_date < today_utc:
        logger.info(
            "followup_reschedule.return_date_in_past",
            prospect_id=prospect.id,
            return_date=return_date.isoformat(),
        )
        return 0

    # Always stamp the window — eligible_for_followup uses this even if there
    # are no sequence rows yet (e.g. step-2 hasn't been scheduled).
    prospect.out_of_office_until = return_date

    # Fetch all non-terminal pending rows for this prospect.
    result = await db.execute(
        select(OutreachSequence).where(
            OutreachSequence.prospect_id == prospect.id,
            OutreachSequence.status.not_in(list(_TERMINAL_STATUSES)),
        )
    )
    sequences = list(result.scalars().all())

    target_date = return_date + timedelta(days=1)
    pushed_count = 0
    for seq in sequences:
        current = seq.scheduled_at
        # If the existing schedule is already past return_date, skip.
        if current.date() > return_date:
            continue
        # Preserve time-of-day in UTC, just shift the date.
        new_at = datetime.combine(
            target_date,
            current.timetz() if current.tzinfo else time(current.hour, current.minute, tzinfo=timezone.utc),
        )
        # datetime.combine with a non-naive time yields tzinfo on Python 3.12
        if new_at.tzinfo is None:
            new_at = new_at.replace(tzinfo=timezone.utc)
        seq.scheduled_at = new_at
        pushed_count += 1
        logger.info(
            "followup_reschedule.pushed",
            prospect_id=prospect.id,
            sequence_id=seq.id,
            step=seq.step_number,
            from_=current.isoformat(),
            to=new_at.isoformat(),
        )

    await db.flush()
    logger.info(
        "followup_reschedule.complete",
        prospect_id=prospect.id,
        return_date=return_date.isoformat(),
        rows_pushed=pushed_count,
    )
    return pushed_count


def is_within_ooo_window(
    prospect: ProspectedLead,
    now: Optional[datetime] = None,
) -> bool:
    """
    Helper for callers that want to gate sends on the OOO window.

    True iff prospect.out_of_office_until is set and >= today (UTC).
    """
    if prospect.out_of_office_until is None:
        return False
    now = now or datetime.now(timezone.utc)
    return prospect.out_of_office_until >= now.date()
