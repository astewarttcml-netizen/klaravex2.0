"""
app/agents/proposal_followup.py
────────────────────────────────
P3 agent — sweeps proposals that have been sent to a client but received
no response, and drafts a follow-up email for Anthony's approval.

Follow-up schedule (both measured from proposal.emailed_at):
  Pass 1 — 3 days after emailing  (followup_count == 0)
  Pass 2 — 7 days after emailing  (followup_count == 1)
  No further follow-ups after pass 2 (followup_count >= 2)

Triggered by: Celery beat task `proposal_followup` (every 6 hours).
Permission:   P3 — email draft queued for Anthony's approval.

Idempotency:
  followup_sent_at is stamped immediately when a follow-up is queued so
  concurrent beat runs do not double-queue the same proposal.
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timedelta, timezone

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import and_, select

from klara.rarv.runtime import BaseAgent, AgentContext, AgentResult, PermissionLevel
from klara.rarv.lead import Lead
from klara.rarv.proposal import Proposal, ProposalStatus

logger = structlog.get_logger(__name__)

# Days after emailed_at that each follow-up fires
_PASS1_DAYS = 3
_PASS2_DAYS = 7
_MAX_FOLLOWUPS = 2

_FOLLOWUP_PROMPT = textwrap.dedent("""\
You are an IT consulting assistant for Klaravex (klaravex.de).
Write a short, professional follow-up email in {language} for a proposal that
received no response after {days} days.

Context:
  Prospect name:    {name}
  Company:          {company}
  Original message: {message}
  Follow-up number: {followup_num} of {max_followups}

Requirements:
- Tone: warm, professional, not pushy. No pressure tactics.
- Length: 2–3 short paragraphs max.
- Reference their original enquiry naturally.
- Offer to answer questions or adjust the proposal.
- Clear call-to-action: reply to this email or book a call.
- {language_note}
- Sign as: Anthony Stewart, Klaravex

Output ONLY the email body in this format:
Subject: [subject line]

[email body]

Kind regards,
Anthony Stewart
IT Consultant | klaravex.de
""")


class ProposalFollowupAgent(BaseAgent):
    name = "proposal_followup"
    permission_level = PermissionLevel.P2
    description = (
        "Sweeps proposals sent to clients with no response at 3-day and 7-day marks. "
        "Drafts a follow-up email (EN/DE based on lead context) and queues for approval. "
        "Fires via Celery beat every 6 hours."
    )

    async def run(self, context: AgentContext, payload: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        now = datetime.now(timezone.utc)
        pass1_cutoff = now - timedelta(days=_PASS1_DAYS)
        pass2_cutoff = now - timedelta(days=_PASS2_DAYS)

        # Proposals eligible for pass 1: emailed 3+ days ago, followup_count == 0,
        # status is sent_to_client (not yet accepted/declined).
        # Proposals eligible for pass 2: emailed 7+ days ago, followup_count == 1.
        result = await context.db.execute(
            select(Proposal).where(
                and_(
                    Proposal.status == ProposalStatus.sent_to_client,
                    Proposal.emailed_at.isnot(None),
                    Proposal.followup_count < _MAX_FOLLOWUPS,
                    # At least 3 days old and either pass 1 or pass 2 window
                    Proposal.emailed_at <= pass1_cutoff,
                )
            ).order_by(Proposal.emailed_at.asc()).limit(20)
        )
        candidates = result.scalars().all()

        # Filter to only those actually in the right window
        eligible = []
        for p in candidates:
            if p.followup_count == 0:
                # Pass 1: emailed 3+ days ago
                eligible.append(p)
            elif p.followup_count == 1 and p.emailed_at <= pass2_cutoff:
                # Pass 2: emailed 7+ days ago
                eligible.append(p)

        if not eligible:
            log.info("proposal_followup.no_eligible_proposals")
            return AgentResult.ok({"status": "no_eligible_proposals", "processed": 0})

        log.info("proposal_followup.eligible_found", count=len(eligible))

        queued = 0
        failed = 0
        processed_ids = []

        for proposal in eligible:
            # Load associated lead for personalisation
            lead = (await context.db.execute(
                select(Lead).where(Lead.id == proposal.lead_id)
            )).scalar_one_or_none()

            if not lead:
                log.warning("proposal_followup.lead_not_found",
                            proposal_id=str(proposal.id), lead_id=proposal.lead_id)
                failed += 1
                continue

            # Skip if lead already won/lost/anonymised — no point following up
            if lead.status in ("won", "lost", "anonymised"):
                log.info("proposal_followup.lead_terminal",
                         proposal_id=str(proposal.id), lead_status=lead.status)
                # Stamp as max followups to stop future sweeps
                p_row = (await context.db.execute(
                    select(Proposal).where(Proposal.id == proposal.id)
                )).scalar_one_or_none()
                if p_row:
                    p_row.followup_count = _MAX_FOLLOWUPS
                    await context.db.flush()
                continue

            followup_num = proposal.followup_count + 1
            days_elapsed = (now - proposal.emailed_at).days

            # Determine language from lead email domain heuristic
            # German domains → DE, everything else → EN
            language, language_note = _detect_language(lead)

            try:
                draft = await self._generate_draft(
                    context.settings, lead, language, language_note,
                    days_elapsed, followup_num
                )
            except Exception as exc:
                log.error("proposal_followup.claude_error",
                          proposal_id=str(proposal.id), error=str(exc))
                failed += 1
                continue

            subject = _extract_subject(draft)
            body = _extract_body(draft)

            # Stamp idempotency BEFORE queuing to prevent duplicate beat runs
            p_row = (await context.db.execute(
                select(Proposal).where(Proposal.id == proposal.id)
            )).scalar_one_or_none()
            if p_row:
                p_row.followup_sent_at = now
                p_row.followup_count = followup_num
                await context.db.flush()

            # Queue for Anthony's approval
            try:
                from app.agents.registry import registry
                approval_agent = registry.get("approval_manager")
                if approval_agent:
                    await approval_agent(context, {
                        "action": "create",
                        "action_name": "send_proposal_followup_email",
                        "risk_level": "P3",
                        "payload": {
                            "proposal_id": str(proposal.id),
                            "lead_id": str(lead.id),
                            "to_email": lead.email,
                            "to_name": lead.name or lead.email,
                            "subject": subject,
                            "body_html": _render_html(lead, proposal, subject, body, followup_num),
                            "body_text": body,
                            "followup_num": followup_num,
                        },
                        "justification": (
                            f"Follow-up #{followup_num} for proposal to "
                            f"{lead.name or lead.email} ({lead.company or 'unknown'}). "
                            f"Proposal sent {days_elapsed} days ago with no response."
                        ),
                        "requested_by": self.name,
                    })
                    queued += 1
                    processed_ids.append(str(proposal.id))
                    log.info("proposal_followup.queued",
                             proposal_id=str(proposal.id),
                             followup_num=followup_num,
                             subject=subject)
                else:
                    log.warning("proposal_followup.approval_manager_not_found")
                    failed += 1
            except Exception as exc:
                log.error("proposal_followup.queue_error",
                          proposal_id=str(proposal.id), error=str(exc))
                failed += 1

        log.info("proposal_followup.sweep_complete",
                 queued=queued, failed=failed, total=len(eligible))

        return AgentResult.ok({
            "status": "sweep_complete",
            "eligible": len(eligible),
            "queued_for_approval": queued,
            "failed": failed,
            "proposal_ids": processed_ids,
        })

    async def _generate_draft(
        self, settings, lead: Lead, language: str, language_note: str,
        days_elapsed: int, followup_num: int
    ) -> str:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        prompt = _FOLLOWUP_PROMPT.format(
            language=language,
            days=days_elapsed,
            name=lead.name or ("Sehr geehrte Damen und Herren" if language == "German" else "there"),
            company=lead.company or ("Ihr Unternehmen" if language == "German" else "your organisation"),
            message=lead.message or "(no details provided)",
            followup_num=followup_num,
            max_followups=_MAX_FOLLOWUPS,
            language_note=language_note,
        )
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            from klara.rarv.runtime.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model="claude-haiku-4-5-20251001",
                response=response, lead_id=getattr(context, 'lead_id', None),
            )
        except Exception:
            pass
        return response.content[0].text.strip()


# ── Module-level helpers ───────────────────────────────────────────────────────

def _detect_language(lead: Lead) -> tuple[str, str]:
    """Heuristic: German TLD domains → write in German, else English."""
    email = lead.email or ""
    if email.endswith(".de") or email.endswith(".at") or email.endswith(".ch"):
        return (
            "German",
            "Write in formal German (Sie/Ihnen). Use German business email conventions.",
        )
    return (
        "English",
        "Write in professional British/neutral English.",
    )


def _extract_subject(draft: str) -> str:
    for line in draft.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("subject:"):
            return stripped[len("subject:"):].strip()
        if stripped.lower().startswith("betreff:"):
            return stripped[len("betreff:"):].strip()
    return "Following up on your IT consulting proposal"


def _extract_body(draft: str) -> str:
    lines = draft.splitlines()
    body_lines = []
    skip_subject = True
    for line in lines:
        s = line.strip().lower()
        if skip_subject and (s.startswith("subject:") or s.startswith("betreff:")):
            skip_subject = False
            continue
        body_lines.append(line)
    return "\n".join(body_lines).strip()


def _render_html(lead: Lead, proposal: Proposal, subject: str,
                 body_text: str, followup_num: int) -> str:
    name = lead.name or "Prospect"
    company = lead.company or ""
    paragraphs = [p.strip() for p in body_text.split("\n\n") if p.strip()]
    html_paras = "".join(
        f"<p style='margin:10px 0;line-height:1.6;'>{p.replace(chr(10), '<br>')}</p>"
        for p in paragraphs
    )
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;padding:20px;color:#222;">
<div style="border-left:4px solid #1565c0;background:#e3f2fd;padding:10px 14px;border-radius:4px;margin-bottom:20px;">
  <strong style="color:#1565c0;">Proposal Follow-up #{followup_num} Draft</strong><br>
  <span style="font-size:13px;">
    {name}{' · ' + company if company else ''} &nbsp;·&nbsp;
    Proposal ID: {proposal.id[:8]}…
  </span>
</div>
{html_paras}
<hr style="border:none;border-top:1px solid #eee;margin:20px 0;">
<p style="font-size:12px;color:#999;">
  Approval required · Klara AI ProposalFollowupAgent · klaravex.de
</p>
</body>
</html>"""
