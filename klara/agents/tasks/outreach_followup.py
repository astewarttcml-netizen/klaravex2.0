"""
app/tasks/outreach_followup.py
───────────────────────────────
Celery task: hourly sweep for Day-3 follow-ups on cold outreach (phase3-001).

Schedule: every hour via celery_app.beat_schedule.

Behaviour per run:
  1. Find every ProspectedLead whose initial outreach was sent 66-78 hours ago
     AND has no engagement signal yet AND is not already in "replied" /
     "bounced" / "disqualified" state.
  2. For each one without an existing step-2 OutreachSequence row, build a
     bilingual follow-up draft and call schedule_followup() which creates the
     sequence row + a sequence-level ApprovalRequest.
  3. For each step-2 row whose ApprovalRequest is now approved, mark sent and
     emit. (Actual send_email() integration: TODO — wired in phase3-001b once
     the existing outreach_email.send pipeline is generalised.)

The eligibility logic lives in app.services.outreach_followup so it can be
unit-tested without Celery + DB infrastructure.
"""
from __future__ import annotations

import asyncio
import html as _html_mod
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import structlog
from sqlalchemy import and_, select

from app.config import get_settings
from app.database import db_context
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.outreach_sequence import OutreachSequence, OutreachSequenceStatus
from app.models.prospected_lead import ProspectedLead, ProspectedLeadStatus
from app.services.email_sender import send_resend_email
from app.services.outreach_followup import (
    DAYS_AFTER_INITIAL_BY_STEP,
    FOLLOWUP_STEP_NUMBER,
    MAX_STEP,
    WINDOW_END_HOURS,
    WINDOW_START_HOURS,
    eligible_for_followup,
    eligible_for_next_step,
    mark_followup_sent,
    schedule_followup,
    schedule_next_step,
)
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


def _pick_language(contact_email: str | None) -> str:
    """Return 'de' for .de TLD addresses, 'en' for everything else."""
    if contact_email and contact_email.lower().endswith(".de"):
        return "de"
    return "en"


def _text_to_html(text: str) -> str:
    """Convert plain-text outreach body to minimal HTML for email clients."""
    escaped = _html_mod.escape(text)
    paragraphs = escaped.split("\n\n")
    parts = []
    for para in paragraphs:
        stripped = para.strip()
        if stripped:
            parts.append(f"<p>{stripped.replace(chr(10), '<br>')}</p>")
    return "\n".join(parts) if parts else "<p></p>"


@celery_app.task(
    name="app.tasks.outreach_followup.run_outreach_followup",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def run_outreach_followup(self):
    """Celery entry point — synchronous wrapper."""
    try:
        result = asyncio.run(_run())
        logger.info("outreach_followup.task_complete", **result)
        return result
    except Exception as exc:
        logger.error("outreach_followup.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


# ── Internal async impl ───────────────────────────────────────────────────────

async def _run() -> dict:
    now = datetime.now(timezone.utc)
    scheduled = 0
    sent      = 0
    suppressed = 0

    async with db_context() as db:
        # ── Step 1: schedule new follow-ups for newly-eligible prospects ──
        window_start = now - timedelta(hours=WINDOW_END_HOURS)
        window_end   = now - timedelta(hours=WINDOW_START_HOURS)

        rows = await db.execute(
            select(ProspectedLead).where(
                ProspectedLead.status == ProspectedLeadStatus.sent,
                ProspectedLead.outreach_sent_at.is_not(None),
                ProspectedLead.outreach_sent_at >= window_start,
                ProspectedLead.outreach_sent_at <= window_end,
            )
        )
        for prospect in rows.scalars():
            if not eligible_for_followup(prospect, now):
                continue
            # phase4-005: skip if the recipient is on the global suppression list.
            # This catches unsubscribes that came in through any channel (not
            # just this prospect's own unsubscribed_at field).
            from app.services.suppression import is_suppressed
            if await is_suppressed(db, prospect.contact_email):
                suppressed += 1
                continue
            # Compose a minimal bilingual follow-up. A future iteration can
            # call into outreach_email.py's prompt machinery; for v1 we use a
            # short structured nudge so the operator approves visible content.
            subject_en = f"Re: {prospect.outreach_subject or 'IT support in Berlin'}"
            subject_de = f"Re: {prospect.outreach_subject or 'IT-Support in Berlin'}"
            body_en = (
                f"Hi {prospect.contact_first_name or 'there'},\n\n"
                f"Just bumping this in case it slipped through. Happy to set up a "
                f"30-minute call to walk through your current IT setup — or to send a "
                f"one-page security checklist if that's more useful.\n\n"
                f"Anthony"
            )
            body_de = (
                f"Hallo {prospect.contact_first_name or ''},\n\n"
                f"Ich melde mich kurz nach. Falls ein 30-Minuten-Gespräch passt, "
                f"schaue ich gerne Ihre IT-Umgebung mit Ihnen durch — oder ich "
                f"schicke eine einseitige Sicherheits-Checkliste zu, wenn das "
                f"nützlicher ist.\n\n"
                f"Anthony"
            )
            seq = await schedule_followup(
                db, prospect, now,
                subject_en=subject_en, subject_de=subject_de,
                body_en=body_en,       body_de=body_de,
            )
            if seq is not None and seq.status == OutreachSequenceStatus.pending_approval:
                scheduled += 1

        # ── Step 2: send already-approved follow-ups (steps 2..MAX_STEP) ──
        # phase19-007 generalised from step-2-only to all cadence steps. Step 2
        # is approved via its sequence-level ApprovalRequest (status moves to
        # `approved` only when an operator approves the pending_approval row).
        # Steps 3+ are auto-created in status=`approved` because the
        # sequence-level approval is shared across the cadence.
        settings = get_settings()
        rows = await db.execute(
            select(OutreachSequence, ApprovalRequest, ProspectedLead)
            .join(ApprovalRequest, ApprovalRequest.id == OutreachSequence.approval_id)
            .join(ProspectedLead, ProspectedLead.id == OutreachSequence.prospect_id)
            .where(
                OutreachSequence.step_number.between(2, MAX_STEP),
                OutreachSequence.status.in_([
                    OutreachSequenceStatus.pending_approval,
                    OutreachSequenceStatus.approved,
                ]),
                ApprovalRequest.status == ApprovalStatus.approved.value,
            )
        )
        for seq, _approval, prospect in rows:
            if not prospect.contact_email:
                logger.warning(
                    "outreach_followup.no_email",
                    seq_id=seq.id,
                    prospect_id=prospect.id,
                    step=seq.step_number,
                )
                await mark_followup_sent(db, seq, now)
                sent += 1
                continue
            lang = _pick_language(prospect.contact_email)
            subject  = (seq.subject_de if lang == "de" else seq.subject_en) or ""
            body_txt = (seq.body_de    if lang == "de" else seq.body_en)    or ""
            ok = await send_resend_email(
                settings,
                to_email=prospect.contact_email,
                to_name=prospect.contact_name,
                subject=subject,
                body_html=_text_to_html(body_txt),
                body_text=body_txt,
            )
            if not ok:
                logger.warning(
                    "outreach_followup.send_failed",
                    seq_id=seq.id,
                    prospect_id=prospect.id,
                    step=seq.step_number,
                )
            await mark_followup_sent(db, seq, now)
            sent += 1

        # ── Step 3: schedule next-step rows for prospects in mid-cadence ──
        # phase19-007: when step N is `sent` and step N+1 doesn't exist yet
        # AND the Berlin-anchored cadence window for step N+1 is open AND no
        # engagement signal arrived, create the step N+1 row (reusing the
        # shared approval_id). Cap at MAX_STEP.
        for current_step in range(2, MAX_STEP):
            sent_rows = await db.execute(
                select(OutreachSequence, ProspectedLead)
                .join(ProspectedLead, ProspectedLead.id == OutreachSequence.prospect_id)
                .where(
                    OutreachSequence.step_number == current_step,
                    OutreachSequence.status == OutreachSequenceStatus.sent,
                )
            )
            for prev_seq, prospect in sent_rows:
                if not eligible_for_next_step(prospect, current_step, now):
                    continue
                # Lightweight bilingual body — operator already approved the
                # sequence at step 2, so we don't re-prompt for content here.
                next_step = current_step + 1
                day_label_en = f"Day-{DAYS_AFTER_INITIAL_BY_STEP[next_step]}"
                seq = await schedule_next_step(
                    db, prev_seq, prospect, now,
                    subject_en=f"Re: {prospect.outreach_subject or 'IT support in Berlin'}",
                    subject_de=f"Re: {prospect.outreach_subject or 'IT-Support in Berlin'}",
                    body_en=(
                        f"Hi {prospect.contact_first_name or 'there'},\n\n"
                        f"Last nudge ({day_label_en}) — happy to set up a quick "
                        f"call or send the security checklist if either is useful.\n\n"
                        f"Anthony"
                    ),
                    body_de=(
                        f"Hallo {prospect.contact_first_name or ''},\n\n"
                        f"Letzte Erinnerung ({day_label_en}) — gerne ein kurzes "
                        f"Gespräch oder die Sicherheits-Checkliste, wenn eines "
                        f"davon nützlich ist.\n\n"
                        f"Anthony"
                    ),
                )
                if seq is not None and seq.status == OutreachSequenceStatus.approved:
                    scheduled += 1

        # ── Step 4: suppress sequences where engagement now exists ──
        # phase19-007 generalised from step-2 only to all live steps.
        rows = await db.execute(
            select(OutreachSequence, ProspectedLead)
            .join(ProspectedLead, ProspectedLead.id == OutreachSequence.prospect_id)
            .where(
                OutreachSequence.step_number.between(2, MAX_STEP),
                OutreachSequence.status.in_(
                    [
                        OutreachSequenceStatus.scheduled,
                        OutreachSequenceStatus.pending_approval,
                        OutreachSequenceStatus.approved,
                    ]
                ),
            )
        )
        for seq, prospect in rows:
            if not eligible_for_followup(prospect, now):
                # Some engagement signal arrived after the row was created —
                # don't send, mark suppressed.
                seq.status = OutreachSequenceStatus.suppressed
                seq.suppress_reason = "engagement_after_schedule"
                suppressed += 1

        await db.commit()

    return {"scheduled": scheduled, "sent": sent, "suppressed": suppressed}
