"""
app/services/outreach_reply_suppression.py
───────────────────────────────────────────
phase19-006 — Reply-aware suppression.

When an inbound reply arrives from a prospect, any of that prospect's
OutreachSequence rows in (scheduled, pending_approval, approved) for
step_number >= 2 should be transitioned to `suppressed` so they never
send, and their gating ApprovalRequest should be auto-resolved so it
doesn't clog the approval inbox.

The existing `eligible_for_followup()` check in app/services/outreach_followup.py
already prevents NEW step-2 rows from being scheduled once `replied_at`
is set on the prospect. This service closes the gap for rows that were
ALREADY scheduled/queued before the reply arrived.

Contract:
  • Caller (the inbound-reply webhook handler) supplies the matched prospect.
  • Service is a no-op when settings.loki_reply_suppression is False.
  • One AuditLog row per suppressed OutreachSequence row, with
    event_type='outreach.suppressed' and details JSON containing the
    sequence_id, step_number, and reason.
  • Idempotent: sequences already in a terminal state (sent / suppressed /
    cancelled) are skipped silently.
  • Returns the count of rows actually suppressed in this call.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import get_settings
from klara.rarv.approval import ApprovalRequest, ApprovalStatus
from klara.rarv.audit import AuditLog
from klara.rarv.outreach_sequence import OutreachSequence, OutreachSequenceStatus
from klara.rarv.prospected_lead import ProspectedLead

logger = structlog.get_logger(__name__)


SUPPRESS_REASON = "inbound_reply"
AUTO_REVIEWER = "system:reply_suppression"
AUDIT_EVENT_TYPE = "outreach.suppressed"

# Statuses we will transition away from. Rows already terminal are skipped.
_SUPPRESSIBLE_STATUSES = (
    OutreachSequenceStatus.scheduled,
    OutreachSequenceStatus.pending_approval,
    OutreachSequenceStatus.approved,
)


async def suppress_pending_followups_for_reply(
    db: AsyncSession,
    prospect: ProspectedLead,
    now: Optional[datetime] = None,
) -> int:
    """
    Cancel any pending/approved future-step OutreachSequence rows for `prospect`
    because the prospect has replied.

    Returns the number of rows that were transitioned (zero is normal — most
    prospects only ever have one step-2 row, and many have none).
    """
    if not get_settings().loki_reply_suppression:
        return 0

    now = now or datetime.now(timezone.utc)

    rows_q = await db.execute(
        select(OutreachSequence).where(
            OutreachSequence.prospect_id == prospect.id,
            OutreachSequence.step_number >= 2,
            OutreachSequence.status.in_(_SUPPRESSIBLE_STATUSES),
        )
    )
    rows = list(rows_q.scalars().all())
    if not rows:
        return 0

    suppressed_count = 0
    for seq in rows:
        seq.status = OutreachSequenceStatus.suppressed
        seq.suppress_reason = SUPPRESS_REASON

        if seq.approval_id:
            appr_q = await db.execute(
                select(ApprovalRequest).where(ApprovalRequest.id == seq.approval_id)
            )
            appr = appr_q.scalar_one_or_none()
            if appr is not None and appr.status == ApprovalStatus.pending.value:
                appr.status = ApprovalStatus.rejected.value
                appr.reviewed_by = AUTO_REVIEWER
                appr.review_note = "auto-rejected: prospect replied to outreach"
                appr.reviewed_at = now

        db.add(AuditLog(
            id=str(uuid4()),
            event_type=AUDIT_EVENT_TYPE,
            agent_name="outreach_reply_suppression",
            action_name="suppress_pending_followup",
            lead_id=None,
            conversation_id=None,
            approval_id=seq.approval_id,
            details=json.dumps({
                "prospect_id":  prospect.id,
                "sequence_id":  seq.id,
                "step_number":  seq.step_number,
                "reason":       SUPPRESS_REASON,
            }),
            success=True,
            created_at=now,
        ))
        suppressed_count += 1

    await db.flush()
    logger.info(
        "outreach_reply_suppression.completed",
        prospect_id=prospect.id,
        suppressed_count=suppressed_count,
    )
    return suppressed_count
