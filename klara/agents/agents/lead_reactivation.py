"""
app/agents/lead_reactivation.py
─────────────────────────────────
LeadReactivationAgent — P3 outbound.

Re-engages leads that have gone quiet after initial contact (status=qualified,
no booking invite response, inactive 30+ days). Differs from cold_nurture:
  - cold_nurture  → disqualified/lost leads, 3-step automated sequence
  - lead_reactivation → qualified leads that stalled, one personalised outreach
                        queued for P3 approval

Triggered by: manual admin API call, or future weekly Celery beat task.
Input: lead_id (required) OR sweep mode with min_inactive_days=30.
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timedelta, timezone

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select, and_

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)

_REACTIVATION_PROMPT = """\
You are Anthony Stewart, IT Consultant at Klaravex.
Write a short, personal re-engagement email to a lead that went quiet.

Lead name:        {name}
Company:          {company}
Original enquiry: {enquiry}
Days inactive:    {days_inactive}
Language:         {language}

Guidelines:
- 2–3 short paragraphs
- Open with a genuine, non-pushy check-in (not "Just following up")
- Reference something specific from their original enquiry
- Offer concrete value: a quick 20-min call, or answer a specific IT question
- Do NOT use pressure tactics or urgency language
- End with Anthony's name and Klaravex
- Respond in {language}

Output email body only.
"""


class LeadReactivationAgent(BaseAgent):
    name = "lead_reactivation"
    description = (
        "Re-engages qualified leads that have gone silent 30+ days after initial contact. "
        "Generates a personalised reactivation email and queues it for P3 approval. "
        "Run manually or via admin API with lead_id, or in sweep mode."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        lead_id          = input_data.get("lead_id") or context.lead_id
        min_inactive_days = int(input_data.get("min_inactive_days", 30))

        if lead_id:
            result = await context.db.execute(select(Lead).where(Lead.id == lead_id))
            leads = [result.scalar_one_or_none()]
            leads = [l for l in leads if l]
        else:
            # Sweep mode: find stale qualified leads
            cutoff = datetime.now(timezone.utc) - timedelta(days=min_inactive_days)
            result = await context.db.execute(
                select(Lead).where(
                    and_(
                        Lead.status == LeadStatus.qualified,
                        Lead.email.is_not(None),
                        Lead.updated_at <= cutoff,
                        Lead.booking_email_sent_at.is_(None),
                    )
                ).limit(20)
            )
            leads = result.scalars().all()

        if not leads:
            return AgentResult.ok(output={"queued": 0, "status": "no_eligible_leads"}, agent=self.name)

        client   = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        queued   = 0
        errors   = []
        now      = datetime.now(timezone.utc)

        for lead in leads:
            use_german = (lead.email or "").lower().endswith((".de", ".at", ".ch"))
            language   = "German" if use_german else "English"
            days_since = (now - lead.updated_at.replace(tzinfo=timezone.utc)
                          if lead.updated_at.tzinfo is None
                          else now - lead.updated_at).days

            prompt = _REACTIVATION_PROMPT.format(
                name=lead.name or lead.email,
                company=lead.company or "their organisation",
                enquiry=textwrap.shorten(lead.message or "general IT enquiry", width=200, placeholder="…"),
                days_inactive=days_since,
                language=language,
            )
            try:
                resp = await client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=400,
                    messages=[{"role": "user", "content": prompt}],
                )
                try:
                    from klara.rarv.runtime.llm_cost import track_response
                    await track_response(
                        context.db, agent_name=self.name,
                        model="claude-haiku-4-5-20251001",
                        response=resp, lead_id=getattr(context, 'lead_id', None),
                    )
                except Exception:
                    pass
                email_body = resp.content[0].text.strip()
            except Exception as exc:
                logger.error("lead_reactivation.claude_error", lead_id=lead.id, error=str(exc))
                errors.append(str(lead.id))
                continue

            subject = (
                "Kurze Rückfrage — Klaravex" if use_german
                else "Checking in — Klaravex"
            )
            try:
                from app.agents.registry import registry
                approval_mgr = registry.get("approval_manager")
                await approval_mgr(context, {
                    "action":       "create",
                    "action_name":  "lead_reactivation.send",
                    "risk_level":   "P3",
                    "payload": {
                        "lead_id":  str(lead.id),
                        "to_email": lead.email,
                        "to_name":  lead.name or lead.email,
                        "subject":  subject,
                        "body_text": email_body,
                        "language": language,
                    },
                    "justification": (
                        f"Re-engagement email for {lead.name or lead.email} "
                        f"({lead.company}), inactive {days_since} days."
                    ),
                    "requested_by": self.name,
                })
                queued += 1
                logger.info("lead_reactivation.queued", lead_id=lead.id)
            except Exception as exc:
                logger.error("lead_reactivation.approval_error", lead_id=lead.id, error=str(exc))
                errors.append(str(lead.id))

        return AgentResult.ok(output={"queued": queued, "errors": errors}, agent=self.name)
