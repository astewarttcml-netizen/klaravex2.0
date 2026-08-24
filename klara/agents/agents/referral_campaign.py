"""
app/agents/referral_campaign.py
──────────────────────────────────
P3 agent — sends a personalised referral ask to won clients 30 days
after onboarding.

Triggered by: Celery beat daily sweep task.
Also callable directly via POST /api/v1/agents/run with
  agent="referral_campaign".

Eligibility criteria:
  - status == won
  - onboarding_sent_at <= now - 30 days
  - referral_sent_at IS NULL (idempotency)
  - gdpr_consent == True
  - email IS NOT NULL

Flow:
  1. Query eligible leads
  2. Draft a personalised referral email (Claude Haiku)
  3. Queue each for P3 approval
  4. Stamp referral_sent_at to prevent re-queue

Referral mechanics included in email:
  - No formal referral programme — keep it simple and human
  - Ask if they know anyone who might benefit from similar services
  - Offer a €100 thank-you credit on future work if the referral converts
  - Link to contact page / Calendly for the referred party

Permission: P3 — client-facing commercial request, requires approval.
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timedelta, timezone

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from app.agents.base import BaseAgent, AgentContext, AgentResult, PermissionLevel
from app.models.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)

_REFERRAL_PROMPT_EN = textwrap.dedent("""\
You are Anthony Stewart, IT Consultant at Klaravex.
Write a short, genuine referral request email to a satisfied client.

Client name:  {name}
Company:      {company}
Services:     {services}

Guidelines:
- Open by referencing how the project went and expressing genuine thanks
- Mention that your business grows mainly through word-of-mouth referrals
- Ask if they know any colleagues, peers, or other businesses who might benefit
  from similar IT services (be specific to their industry/role if possible)
- Offer a €100 credit on future work if the referral converts to a paid project
- Include placeholder [CONTACT_LINK] where the referred person should reach out
- Tone: genuine and personal — not a mass-marketing email
- Length: 3 paragraphs max
- Sign off personally from Anthony

Output the email body only. No subject line, no meta-commentary.
""")

_REFERRAL_PROMPT_DE = textwrap.dedent("""\
Sie sind Anthony Stewart, IT-Berater bei Klaravex.
Schreiben Sie eine kurze, persönliche E-Mail an einen zufriedenen Kunden und bitten
ihn, Sie weiterzuempfehlen.

Kundenname:   {name}
Unternehmen:  {company}
Leistungen:   {services}

Richtlinien:
- Erwähnen Sie kurz, wie das Projekt verlaufen ist, und bedanken Sie sich herzlich
- Weisen Sie darauf hin, dass Ihr Geschäft hauptsächlich durch Weiterempfehlungen wächst
- Fragen Sie, ob sie Kollegen oder andere Unternehmen kennen, die von ähnlichen
  IT-Leistungen profitieren könnten
- Bieten Sie ein €100-Guthaben für zukünftige Arbeiten an, wenn die Empfehlung zu
  einem bezahlten Projekt führt
- Platzhalter [CONTACT_LINK] für den Erstkontakt der empfohlenen Person
- Ton: persönlich und ehrlich — keine Massen-Marketing-E-Mail
- Länge: max. 3 Absätze
- Persönliche Grußformel von Anthony
- Antwort auf DEUTSCH

Ausgabe: nur der E-Mail-Text.
""")


class ReferralCampaignAgent(BaseAgent):
    name = "referral_campaign"
    permission_level = PermissionLevel.P2
    description = (
        "Daily sweep: finds won clients 30+ days post-onboarding who haven't received "
        "a referral ask. Drafts a personalised referral email (Claude Haiku) with €100 "
        "credit incentive. Queues each for P3 approval. Stamps referral_sent_at. "
        "P3 — commercial client email, requires approval."
    )

    async def run(self, context: AgentContext, payload: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)

        rows = (await context.db.execute(
            select(Lead)
            .where(Lead.status == LeadStatus.won)
            .where(Lead.gdpr_consent.is_(True))
            .where(Lead.onboarding_sent_at.is_not(None))
            .where(Lead.onboarding_sent_at <= thirty_days_ago)
            .where(Lead.referral_sent_at.is_(None))
            .where(Lead.email.is_not(None))
        )).scalars().all()

        if not rows:
            log.info("referral_campaign.no_eligible_leads")
            return AgentResult.ok({"status": "no_eligible_leads", "queued": 0})

        log.info("referral_campaign.eligible", count=len(rows))

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        queued = 0
        errors = []

        for lead in rows:
            language = _detect_language(lead)
            services = lead.services_interest or "IT consulting services"
            company = lead.company or ""
            name = lead.name or lead.email

            prompt = (
                _REFERRAL_PROMPT_DE if language == "de"
                else _REFERRAL_PROMPT_EN
            ).format(
                name=name,
                company=company or "their organisation",
                services=services,
            )

            try:
                response = await client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=400,
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
                log.error("referral_campaign.claude_error",
                          lead_id=lead.id, error=str(exc))
                errors.append(str(lead.id))
                continue

            subject = (
                "Kennen Sie jemanden, dem ich helfen könnte?"
                if language == "de"
                else "Do you know someone I could help?"
            )

            try:
                from app.agents.registry import registry
                approval_agent = registry.get("approval_manager")
                await approval_agent(context, {
                    "action": "create",
                    "action_name": "send_referral_email",
                    "risk_level": "P3",
                    "payload": {
                        "lead_id": str(lead.id),
                        "to_email": lead.email,
                        "to_name": lead.name or lead.email,
                        "subject": subject,
                        "body_text": email_body,
                        "language": language,
                    },
                    "justification": (
                        f"Referral ask for {lead.name or lead.email} "
                        f"({company}). 30 days since onboarding "
                        f"({str(lead.onboarding_sent_at)[:10]}). "
                        f"Language: {language.upper()}."
                    ),
                    "requested_by": self.name,
                })
            except Exception as exc:
                log.error("referral_campaign.queue_error",
                          lead_id=lead.id, error=str(exc))
                errors.append(str(lead.id))
                continue

            lead_row = (await context.db.execute(
                select(Lead).where(Lead.id == lead.id)
            )).scalar_one_or_none()
            if lead_row:
                lead_row.referral_sent_at = now
                await context.db.flush()

            queued += 1
            log.info("referral_campaign.queued",
                     lead_id=lead.id, to_email=lead.email)

        return AgentResult.ok({
            "status": "done",
            "eligible": len(rows),
            "queued": queued,
            "errors": errors,
        })


def _detect_language(lead: Lead) -> str:
    email = lead.email or ""
    if email.endswith(".de") or email.endswith(".at") or email.endswith(".ch"):
        return "de"
    return "en"
