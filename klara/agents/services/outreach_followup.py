"""
app/services/outreach_followup.py
──────────────────────────────────
Day-3 follow-up sequencing for cold outreach (phase3-001).

Functions
─────────
  eligible_for_followup(prospect, now)
        Returns True iff the prospect should receive a step-2 follow-up.
        Checks:
          • status is "sent" (initial cold email delivered to provider)
          • outreach_sent_at is in the 66-78h window before `now`
          • no engagement signals: opened_at, last_clicked_at, replied_at,
            unsubscribed_at all NULL
          • status is not already "replied"

  schedule_followup(db, prospect, now)
        Creates a step-2 OutreachSequence row with status=pending_approval,
        creates a sequence-level ApprovalRequest, links them, and writes
        the approval_id back to the sequence row.
        Idempotent — returns the existing row if one is already present
        for (prospect_id, step_number=2).

  mark_followup_sent(db, sequence_row, now)
        Marks an approved sequence row as sent at `now`. Caller is
        responsible for the actual send_email() call.

  suppress_followup(db, sequence_row, reason)
        Sets status=suppressed with a reason — used when an engagement
        signal arrives between scheduling and the next sweep.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalRequest, ApprovalStatus, RiskLevel
from app.models.outreach_sequence import OutreachSequence, OutreachSequenceStatus
from app.models.prospected_lead import ProspectedLead, ProspectedLeadStatus

logger = structlog.get_logger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

FOLLOWUP_STEP_NUMBER  = 2
WINDOW_START_HOURS    = 66    # earliest send: initial + 66h
WINDOW_END_HOURS      = 78    # latest send:   initial + 78h
APPROVAL_TTL_DAYS     = 7     # ApprovalRequest expires after a week

# ── Multi-touch cadence (phase19-007) ─────────────────────────────────────────
# Days after the INITIAL outreach (step 1) at which each later step targets.
# Cadence: step 1 (T0) -> step 2 (+3d) -> step 3 (+7d) -> step 4 (+14d).
# Adding a step here is the ONLY change required to grow the cadence — both
# eligibility and scheduling read this table directly.
DAYS_AFTER_INITIAL_BY_STEP = {2: 3, 3: 7, 4: 14}
MAX_STEP = max(DAYS_AFTER_INITIAL_BY_STEP)            # 4 — derived, no magic number
STEP_WINDOW_HOURS = 12                                # ±12h tolerance around target

# Cadence math is anchored to Berlin wall-clock: if Anthony sends an initial
# at 09:00 Berlin, every follow-up step targets ~09:00 Berlin on its target
# day. timedelta(days=N) on a UTC timestamp would slip by an hour across DST.
BERLIN_TZ = ZoneInfo("Europe/Berlin")


def step_target_at(initial_sent_at: datetime, step: int) -> datetime:
    """Return the UTC moment at which `step` should be sent, anchored to the
    Berlin wall-clock of `initial_sent_at`.

    DST-safe: adding N calendar days in Berlin local time, then converting
    back to UTC, keeps the wall clock stable across spring-forward /
    fall-back transitions (which a raw timedelta(days=N) on a UTC timestamp
    would silently break).
    """
    if step not in DAYS_AFTER_INITIAL_BY_STEP:
        raise ValueError(f"Step {step} is not in the configured cadence")
    days = DAYS_AFTER_INITIAL_BY_STEP[step]
    local = initial_sent_at.astimezone(BERLIN_TZ)
    target_local_naive = local.replace(tzinfo=None) + timedelta(days=days)
    target_local = target_local_naive.replace(tzinfo=BERLIN_TZ)
    return target_local.astimezone(timezone.utc)


# ── Eligibility ───────────────────────────────────────────────────────────────

def eligible_for_followup(prospect: ProspectedLead, now: Optional[datetime] = None) -> bool:
    """
    True iff prospect should receive a step-2 follow-up.

    Refuses if:
      • Initial outreach was never sent (outreach_sent_at is None)
      • Sent too recently (< WINDOW_START_HOURS ago)
      • Sent too long ago (> WINDOW_END_HOURS ago) — gives up after the window
      • Prospect status is already "replied" (or "bounced", "disqualified", "unsubscribed")
      • Any engagement signal is set (opened_at, last_clicked_at, replied_at,
        unsubscribed_at)
    """
    if prospect.outreach_sent_at is None:
        return False

    now = now or datetime.now(timezone.utc)
    elapsed = now - prospect.outreach_sent_at
    if elapsed < timedelta(hours=WINDOW_START_HOURS):
        return False
    if elapsed > timedelta(hours=WINDOW_END_HOURS):
        return False

    # Status sentinel checks — anything beyond "sent" means we stop
    BLOCKING_STATUSES = {
        ProspectedLeadStatus.replied,
        ProspectedLeadStatus.bounced,
        ProspectedLeadStatus.disqualified,
    }
    if prospect.status in BLOCKING_STATUSES:
        return False

    # Engagement-column checks — phase3-002 populates these. NULL = no signal.
    if getattr(prospect, "opened_at",       None) is not None: return False
    if getattr(prospect, "last_clicked_at", None) is not None: return False
    if getattr(prospect, "replied_at",      None) is not None: return False
    if getattr(prospect, "unsubscribed_at", None) is not None: return False

    # phase4-004: suppress sends while the prospect is out of office.
    ooo = getattr(prospect, "out_of_office_until", None)
    if ooo is not None and ooo >= now.date():
        return False

    return True


# ── Scheduling ────────────────────────────────────────────────────────────────

async def schedule_followup(
    db: AsyncSession,
    prospect: ProspectedLead,
    now: Optional[datetime] = None,
    *,
    subject_en: str = "",
    subject_de: str = "",
    body_en:    str = "",
    body_de:    str = "",
) -> OutreachSequence:
    """
    Create a step-2 OutreachSequence row for `prospect`, plus a
    sequence-level ApprovalRequest. Returns the (new or existing) row.

    Idempotent: if a step-2 row already exists for the prospect, this
    returns it unchanged (no second approval is created).

    The caller (the OutreachFollowupAgent) is responsible for generating
    the bilingual subject/body and passing them in. This service does the
    persistence + approval wiring only.
    """
    now = now or datetime.now(timezone.utc)
    log = logger.bind(prospect_id=prospect.id, step=FOLLOWUP_STEP_NUMBER)

    # Idempotency: existing step-2 row?
    result = await db.execute(
        select(OutreachSequence).where(
            OutreachSequence.prospect_id == prospect.id,
            OutreachSequence.step_number == FOLLOWUP_STEP_NUMBER,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        log.info("outreach_followup.schedule.idempotent_hit", row_id=existing.id)
        return existing

    # Create the sequence row first (without approval_id yet).
    seq = OutreachSequence(
        id=str(uuid4()),
        prospect_id=prospect.id,
        step_number=FOLLOWUP_STEP_NUMBER,
        subject_en=subject_en,
        subject_de=subject_de,
        body_en=body_en,
        body_de=body_de,
        scheduled_at=now,
        status=OutreachSequenceStatus.pending_approval,
    )
    db.add(seq)

    # Sequence-level ApprovalRequest. The payload includes both languages so
    # the operator can review what will be sent before approving.
    approval = ApprovalRequest(
        id=str(uuid4()),
        action_name="outreach_followup.send_step_2",
        risk_level=RiskLevel.MEDIUM.value if hasattr(RiskLevel, "MEDIUM") else "medium",
        payload=json.dumps({
            "prospect_id":   prospect.id,
            "step_number":   FOLLOWUP_STEP_NUMBER,
            "sequence_id":   seq.id,
            "subject_en":    subject_en,
            "subject_de":    subject_de,
            "body_en":       body_en,
            "body_de":       body_de,
            "contact_email": prospect.contact_email,
            "company_name":  prospect.company_name,
        }, ensure_ascii=False),
        justification=(
            f"Day-3 follow-up for {prospect.company_name or '(unknown)'} — "
            f"initial outreach sent {now - prospect.outreach_sent_at} ago "
            f"with no engagement detected."
        ),
        requested_by_agent="outreach_followup",
        lead_id=None,
        conversation_id=None,
        status=ApprovalStatus.pending.value,
        created_at=now,
        expires_at=now + timedelta(days=APPROVAL_TTL_DAYS),
    )
    db.add(approval)

    # Link them.
    seq.approval_id = approval.id

    await db.flush()
    log.info(
        "outreach_followup.schedule.created",
        sequence_id=seq.id,
        approval_id=approval.id,
    )
    return seq


# ── State transitions ─────────────────────────────────────────────────────────

async def mark_followup_sent(
    db: AsyncSession,
    sequence_row: OutreachSequence,
    now: Optional[datetime] = None,
) -> None:
    sequence_row.status  = OutreachSequenceStatus.sent
    sequence_row.sent_at = now or datetime.now(timezone.utc)
    await db.flush()


async def suppress_followup(
    db: AsyncSession,
    sequence_row: OutreachSequence,
    reason: str,
) -> None:
    sequence_row.status          = OutreachSequenceStatus.suppressed
    sequence_row.suppress_reason = reason[:80]
    await db.flush()


# ── Multi-touch cadence (phase19-007) ─────────────────────────────────────────

def eligible_for_next_step(
    prospect: ProspectedLead,
    current_step: int,
    now: Optional[datetime] = None,
) -> bool:
    """
    True iff `prospect` should receive step (current_step + 1).

    Identical engagement gates as eligible_for_followup() — any reply, open,
    click, unsubscribe, OOO, or non-`sent` status blocks. Cadence gate uses
    Berlin wall-clock target ±STEP_WINDOW_HOURS, not raw UTC arithmetic.
    """
    next_step = current_step + 1
    if next_step not in DAYS_AFTER_INITIAL_BY_STEP:
        return False
    if prospect.outreach_sent_at is None:
        return False

    now = now or datetime.now(timezone.utc)
    target = step_target_at(prospect.outreach_sent_at, next_step)
    if now < target - timedelta(hours=STEP_WINDOW_HOURS):
        return False
    if now > target + timedelta(hours=STEP_WINDOW_HOURS):
        return False

    BLOCKING_STATUSES = {
        ProspectedLeadStatus.replied,
        ProspectedLeadStatus.bounced,
        ProspectedLeadStatus.disqualified,
    }
    if prospect.status in BLOCKING_STATUSES:
        return False

    if getattr(prospect, "opened_at",       None) is not None: return False
    if getattr(prospect, "last_clicked_at", None) is not None: return False
    if getattr(prospect, "replied_at",      None) is not None: return False
    if getattr(prospect, "unsubscribed_at", None) is not None: return False

    ooo = getattr(prospect, "out_of_office_until", None)
    if ooo is not None and ooo >= now.date():
        return False

    return True


async def schedule_next_step(
    db: AsyncSession,
    prev_seq: OutreachSequence,
    prospect: ProspectedLead,
    now: Optional[datetime] = None,
    *,
    subject_en: str = "",
    subject_de: str = "",
    body_en:    str = "",
    body_de:    str = "",
) -> Optional[OutreachSequence]:
    """
    Create the step-(N+1) OutreachSequence row for `prospect`, reusing
    `prev_seq.approval_id` per the sequence-level approval contract
    documented on the OutreachSequence model:

        "All steps that belong to one logical sequence share the same
         approval_id. Approving one ApprovalRequest gates every step it
         covers — the operator does not approve each follow-up individually."

    Status is `approved` on creation (the sequence-level approval already
    covers it); the next sweep cycle picks it up and marks it sent. No new
    ApprovalRequest is created.

    Returns the new (or existing — idempotent on (prospect_id, step_number))
    row, or None if `prev_seq.step_number + 1` exceeds MAX_STEP.

    Suppression cascade: rows created here are caught by the
    phase19-006 reply-suppression service (filter is step_number >= 2 AND
    status in scheduled/pending_approval/approved), so an inbound reply
    arriving after step 3/4 is created will cancel them automatically.
    """
    next_step = prev_seq.step_number + 1
    if next_step > MAX_STEP:
        return None
    if next_step not in DAYS_AFTER_INITIAL_BY_STEP:
        return None

    now = now or datetime.now(timezone.utc)
    log = logger.bind(prospect_id=prospect.id, step=next_step)

    # Idempotency: existing step-N row?
    result = await db.execute(
        select(OutreachSequence).where(
            OutreachSequence.prospect_id == prospect.id,
            OutreachSequence.step_number == next_step,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        log.info("outreach_followup.schedule_next.idempotent_hit", row_id=existing.id)
        return existing

    target_at = step_target_at(prospect.outreach_sent_at, next_step)
    seq = OutreachSequence(
        id=str(uuid4()),
        prospect_id=prospect.id,
        step_number=next_step,
        subject_en=subject_en,
        subject_de=subject_de,
        body_en=body_en,
        body_de=body_de,
        scheduled_at=target_at,
        # Sequence-level approval already in place — start in `approved`.
        status=OutreachSequenceStatus.approved,
        approval_id=prev_seq.approval_id,
    )
    db.add(seq)
    await db.flush()
    log.info(
        "outreach_followup.schedule_next.created",
        sequence_id=seq.id,
        target_at=target_at.isoformat(),
        reused_approval_id=prev_seq.approval_id,
    )
    return seq
