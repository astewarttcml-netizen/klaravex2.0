"""
app/agents/testimonial_requester.py
──────────────────────────────────────
P3 agent — requests a testimonial / Google review from a client 7 days
after onboarding email is sent (i.e. 7 days post-win).

Triggered by: Celery beat daily sweep task.
Also callable directly via POST /api/v1/agents/run with
  agent="testimonial_requester".

Eligibility criteria (all must be true):
  - status == won
  - onboarding_sent_at IS NOT NULL (client has been onboarded)
  - onboarding_sent_at <= now - 7 days
  - testimonial_sent_at IS NULL (idempotency)
  - gdpr_consent == True

Flow:
  1. Query eligible leads
  2. For each: draft a personalised review request (Claude Haiku)
  3. Queue each for P3 approval (one approval record per lead)
  4. Stamp testimonial_sent_at immediately to prevent duplicate queueing

Permission: P3 — external send to client, requires Anthony approval.
  Requests are commercial (asking for public review) — do not auto-send.
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

_REVIEW_PROMPT = textwrap.dedent("""\
You are Anthony Stewart, IT Consultant at Klaravex.
Write a short, warm, personal testimonial / review request email to a satisfied client.

Client name:     {name}
Company:         {company}
Services done:   {services}
Language:        {language}

Guidelines:
- Open with genuine thanks for working with them
- Reference the specific service(s) completed (not generic)
- Politely ask for a Google Review — provide the placeholder link [GOOGLE_REVIEW_LINK]
- Mention it takes only 2 minutes and helps other businesses find honest IT support
- No pressure — purely optional and appreciated
- Tone: warm, honest, not marketing-speak
- Length: 3–4 short paragraphs max
- End with a personal sign-off from Anthony
- Respond in {language}

Output the email body only. No subject line, no meta-commentary.
""")

_REVIEW_PROMPT_DE = textwrap.dedent("""\
Sie sind Anthony Stewart, IT-Berater bei Klaravex.
Schreiben Sie eine kurze, persönliche E-Mail an einen zufriedenen Kunden und bitten
ihn um eine Google-Bewertung.

Kundenname:      {name}
Unternehmen:     {company}
Abgeschlossene Leistungen: {services}

Richtlinien:
- Bedanken Sie sich aufrichtig für die Zusammenarbeit
- Erwähnen Sie die konkret durchgeführten Leistungen (nicht generisch)
- Bitten Sie höflich um eine Google-Bewertung — Platzhalter: [GOOGLE_REVIEW_LINK]
- Hinweis: dauert nur 2 Minuten, hilft anderen Unternehmen
- Kein Druck — vollkommen freiwillig
- Ton: herzlich, ehrlich, kein Marketing-Jargon
- Länge: 3–4 kurze Absätze
- Persönliche Grußformel von Anthony am Ende
- Antwort auf DEUTSCH

Ausgabe: nur der E-Mail-Text. Keine Betreffzeile, keine Meta-Kommentare.
""")


class TestimonialRequesterAgent(BaseAgent):
    name = "testimonial_requester"
    permission_level = PermissionLevel.P2
    description = (
        "Daily sweep: finds won clients 7+ days post-onboarding who haven't been "
        "asked for a review. Drafts a personalised Google review request via Claude "
        "Haiku and queues each for P3 approval. Stamps testimonial_sent_at to "
        "prevent duplicates. P3 — external commercial request, requires approval."
    )

    async def run(self, context: AgentContext, payload: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)

        rows = (await context.db.execute(
            select(Lead)
            .where(Lead.status == LeadStatus.won)
            .where(Lead.gdpr_consent.is_(True))
            .where(Lead.onboarding_sent_at.is_not(None))
            .where(Lead.onboarding_sent_at <= seven_days_ago)
            .where(Lead.testimonial_sent_at.is_(None))
            .where(Lead.email.is_not(None))
        )).scalars().all()

        if not rows:
            log.info("testimonial_requester.no_eligible_leads")
            return AgentResult.ok({"status": "no_eligible_leads", "queued": 0})

        log.info("testimonial_requester.eligible", count=len(rows))

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        queued = 0
        errors = []

        for lead in rows:
            language = _detect_language(lead)
            services = lead.services_interest or "IT consulting services"
            company = lead.company or ""
            name = lead.name or lead.email

            prompt_template = _REVIEW_PROMPT_DE if language == "de" else _REVIEW_PROMPT
            prompt_kwargs = dict(
                name=name,
                company=company or "their organisation",
                services=services,
                language="German" if language == "de" else "English",
            )

            try:
                response = await client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=400,
                    messages=[{
                        "role": "user",
                        "content": prompt_template.format(**prompt_kwargs),
                    }],
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
                log.error("testimonial_requester.claude_error",
                          lead_id=lead.id, error=str(exc))
                errors.append(str(lead.id))
                continue

            if language == "de":
                subject = "Kurze Bitte — Ihre Bewertung für Klaravex"
            else:
                subject = "A small favour — your review of Klaravex"

            from app.services.draft_validator import (
                DraftValidationError,
                validate_no_placeholders,
            )
            try:
                validate_no_placeholders(
                    agent_name=self.name,
                    fields={"subject": subject, "body_text": email_body},
                )
            except DraftValidationError as exc:
                log.error("testimonial_requester.placeholder_lint_failed",
                          lead_id=lead.id, violations=exc.field_violations)
                errors.append(str(lead.id))
                continue

            try:
                from app.agents.registry import registry
                approval_agent = registry.get("approval_manager")
                await approval_agent(context, {
                    "action": "create",
                    "action_name": "send_testimonial_request",
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
                        f"Review request for {lead.name or lead.email} "
                        f"({company}). Onboarded {str(lead.onboarding_sent_at)[:10]}. "
                        f"Language: {language.upper()}."
                    ),
                    "requested_by": self.name,
                })
            except Exception as exc:
                log.error("testimonial_requester.queue_error",
                          lead_id=lead.id, error=str(exc))
                errors.append(str(lead.id))
                continue

            # Stamp idempotency — prevents re-queue on next sweep
            lead_row = (await context.db.execute(
                select(Lead).where(Lead.id == lead.id)
            )).scalar_one_or_none()
            if lead_row:
                lead_row.testimonial_sent_at = now
                await context.db.flush()

            queued += 1
            log.info("testimonial_requester.queued",
                     lead_id=lead.id,
                     to_email=lead.email)

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
