"""
app/agents/cold_nurture.py
───────────────────────────
P3 agent — 3-touch re-engagement sequence for COLD / dead leads
(status disqualified or lost, with GDPR consent, no prior nurture).

Triggered by: Celery beat daily sweep task.
Also callable directly via POST /api/v1/agents/run with agent="cold_nurture".

Sequence:
  Step 0 → Step 1: Wait 14 days since cold_nurture_sent_at (or initial status change)
  Step 1 → Step 2: Wait 21 days since step 1
  Step 2 → done:   Wait 30 days since step 2 (final touch — no further nurture)

Touch content:
  Step 1 — "Just checking in" — soft re-engagement, reference original enquiry
  Step 2 — "Industry tip / recent work" — value-add, no hard sell
  Step 3 — "Last check-in" — explicit opt-out if no interest, clean close

Eligibility criteria per step:
  - status IN (disqualified, lost)
  - gdpr_consent == True
  - email IS NOT NULL
  - cold_nurture_step < 3
  - Step 1: cold_nurture_sent_at IS NULL
  - Step 2: cold_nurture_sent_at <= now - 21 days AND cold_nurture_step == 1
  - Step 3: cold_nurture_sent_at <= now - 30 days AND cold_nurture_step == 2

Permission: P3 — external email to cold prospect, requires approval.
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timedelta, timezone
from typing import Sequence

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select, or_

from app.agents.base import BaseAgent, AgentContext, AgentResult, PermissionLevel
from app.models.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)

_STEP_GAPS_DAYS = {1: 0, 2: 21, 3: 30}  # days since last touch for each step

_NURTURE_PROMPT = textwrap.dedent("""\
You are Anthony Stewart, IT Consultant at Klaravex.
Write a short, non-pushy re-engagement email for a cold lead.

Lead name:        {name}
Company:          {company}
Original enquiry: {original_message}
Nurture step:     {step} of 3
Language:         {language}

Step 1 — Soft check-in: Reference their original enquiry briefly. Ask if
  their IT needs have evolved or if timing was simply off. Keep it personal.
Step 2 — Value-add: Share one concrete insight or tip relevant to their
  likely IT challenges (e.g. a common M365 migration pitfall, or a Defender
  for Business tip for SMBs). No hard sell — just genuine value.
Step 3 — Final touch: Acknowledge you've reached out a couple of times.
  Explicitly offer to close the loop if not the right time, and offer a simple
  reply to opt out of further messages. Gracious and clean.

Guidelines:
- 2–3 short paragraphs max
- Tone: professional, warm, never pushy or automated-sounding
- Respond in {language}
- End with Anthony's signature
- No [PLACEHOLDER] tags — write a complete email body

Output email body only.
""")


class ColdNurtureAgent(BaseAgent):
    name = "cold_nurture"
    permission_level = PermissionLevel.P2
    description = (
        "Daily sweep: 3-touch re-engagement sequence for disqualified/lost leads "
        "with GDPR consent. Step 1 (check-in), Step 2 (value-add, 21d later), "
        "Step 3 (gracious close, 30d later). Each step queued for P3 approval. "
        "Stamps cold_nurture_step + cold_nurture_sent_at. P3 — external send."
    )

    async def run(self, context: AgentContext, payload: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        now = datetime.now(timezone.utc)
        queued = 0
        errors = []
        processed = []

        # -- Step 1 candidates: no nurture sent yet --------------------------
        step1_rows = (await context.db.execute(
            select(Lead)
            .where(Lead.status.in_([LeadStatus.disqualified, LeadStatus.lost]))
            .where(Lead.gdpr_consent.is_(True))
            .where(Lead.email.is_not(None))
            .where(Lead.cold_nurture_step == 0)
            .where(Lead.cold_nurture_sent_at.is_(None))
        )).scalars().all()

        # -- Step 2 candidates: step 1 done >= 21 days ago -------------------
        twenty_one_ago = now - timedelta(days=21)
        step2_rows = (await context.db.execute(
            select(Lead)
            .where(Lead.status.in_([LeadStatus.disqualified, LeadStatus.lost]))
            .where(Lead.gdpr_consent.is_(True))
            .where(Lead.email.is_not(None))
            .where(Lead.cold_nurture_step == 1)
            .where(Lead.cold_nurture_sent_at <= twenty_one_ago)
        )).scalars().all()

        # -- Step 3 candidates: step 2 done >= 30 days ago -------------------
        thirty_ago = now - timedelta(days=30)
        step3_rows = (await context.db.execute(
            select(Lead)
            .where(Lead.status.in_([LeadStatus.disqualified, LeadStatus.lost]))
            .where(Lead.gdpr_consent.is_(True))
            .where(Lead.email.is_not(None))
            .where(Lead.cold_nurture_step == 2)
            .where(Lead.cold_nurture_sent_at <= thirty_ago)
        )).scalars().all()

        all_candidates: list[tuple[Lead, int]] = (
            [(lead, 1) for lead in step1_rows]
            + [(lead, 2) for lead in step2_rows]
            + [(lead, 3) for lead in step3_rows]
        )

        if not all_candidates:
            log.info("cold_nurture.no_eligible_leads")
            return AgentResult.ok({"status": "no_eligible_leads", "queued": 0})

        log.info("cold_nurture.eligible", count=len(all_candidates))

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)

        for lead, step in all_candidates:
            language = _detect_language(lead)
            name = lead.name or lead.email
            company = lead.company or ""
            original_message = (lead.message or lead.notes or "")[:300]

            prompt = _NURTURE_PROMPT.format(
                name=name,
                company=company or "their organisation",
                original_message=original_message or "general IT enquiry",
                step=step,
                language="German" if language == "de" else "English",
            )

            try:
                response = await client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=450,
                    messages=[{"role": "user", "content": prompt}],
                )
                try:
                    from app.services.llm_cost import track_response
                    await track_response(
                        context.db, agent_name=self.name,
                        model="claude-haiku-4-5-20251001",
                        response=response, lead_id=getattr(context, 'lead_id', None),
                    )
                except Exception:
                    pass
                email_body = response.content[0].text.strip()
            except Exception as exc:
                log.error("cold_nurture.claude_error",
                          lead_id=lead.id, step=step, error=str(exc))
                errors.append(str(lead.id))
                continue

            if language == "de":
                subjects = {
                    1: "Kurzes Update — Klaravex",
                    2: "Praxistipp für Ihren IT-Bereich",
                    3: "Letzter Kontaktversuch — Klaravex",
                }
            else:
                subjects = {
                    1: "Checking in — Klaravex",
                    2: "A quick IT tip from Anthony",
                    3: "Final check-in — Klaravex",
                }

            subject = subjects[step]

            try:
                from app.agents.registry import registry
                approval_agent = registry.get("approval_manager")
                await approval_agent(context, {
                    "action": "create",
                    "action_name": f"send_cold_nurture_step{step}",
                    "risk_level": "P3",
                    "payload": {
                        "lead_id": str(lead.id),
                        "to_email": lead.email,
                        "to_name": lead.name or lead.email,
                        "subject": subject,
                        "body_text": email_body,
                        "language": language,
                        "nurture_step": step,
                    },
                    "justification": (
                        f"Cold nurture step {step} for {lead.name or lead.email} "
                        f"({company}). Status: {lead.status}. "
                        f"Language: {language.upper()}."
                    ),
                    "requested_by": self.name,
                })
            except Exception as exc:
                log.error("cold_nurture.queue_error",
                          lead_id=lead.id, step=step, error=str(exc))
                errors.append(str(lead.id))
                continue

            # Stamp step + timestamp
            lead_row = (await context.db.execute(
                select(Lead).where(Lead.id == lead.id)
            )).scalar_one_or_none()
            if lead_row:
                lead_row.cold_nurture_step = step
                lead_row.cold_nurture_sent_at = now
                await context.db.flush()

            queued += 1
            processed.append({"lead_id": str(lead.id), "step": step})
            log.info("cold_nurture.queued",
                     lead_id=lead.id, step=step, to_email=lead.email)

        return AgentResult.ok({
            "status": "done",
            "eligible": len(all_candidates),
            "queued": queued,
            "processed": processed,
            "errors": errors,
        })


def _detect_language(lead: Lead) -> str:
    email = lead.email or ""
    if email.endswith(".de") or email.endswith(".at") or email.endswith(".ch"):
        return "de"
    return "en"
