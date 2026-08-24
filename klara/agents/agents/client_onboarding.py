"""
app/agents/client_onboarding.py
────────────────────────────────
P3 agent — triggered when Anthony marks a lead as "won" via the admin API.
Generates and queues a personalised bilingual welcome email for new clients.

Triggered by: POST /api/v1/leads/{id}/mark-won  (admin API, X-API-Key)

Flow:
  1. Validate lead is in a closeable state (not anonymised, not already onboarded)
  2. Update lead.status → won
  3. Generate bilingual welcome email via Claude
  4. Queue email for Anthony's approval (P3)
  5. Stamp lead.onboarding_sent_at (idempotency guard)

The welcome email includes:
  - Warm personalised greeting (EN + DE version based on lead language)
  - What happens next (3-step onboarding sequence)
  - Kickoff scheduling link (BOOKING_URL from settings)
  - Anthony's direct contact details

Permission: P3 — sends a client-facing communication requiring approval.
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timezone

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from app.agents.base import BaseAgent, AgentContext, AgentResult, PermissionLevel
from app.models.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)

_ONBOARDING_PROMPT_EN = textwrap.dedent("""\
You are Anthony Stewart, an IT consultant at Klaravex (klaravex.de).
Write a warm, professional client welcome email in English.

New client context:
  Name:             {name}
  Company:          {company}
  Services agreed:  {services}
  Original enquiry: {message}
  Kickoff link:     {booking_url}

Email requirements:
- Tone: warm, confident, professional. This is the start of a business relationship.
- Length: 3–4 short paragraphs
- Welcome them personally, reference what they came to you for
- Outline the 3 immediate next steps:
    1. Schedule a kickoff call (link provided)
    2. Share access / documentation they should prepare
    3. Expect a project brief from Anthony within 48h of kickoff
- End with clear CTA: click the link to book the kickoff call
- Sign as Anthony Stewart, Klaravex

Output ONLY in this format:
Subject: [subject line]

[email body]

Warm regards,
Anthony Stewart
IT Consultant | klaravex.de
Tel: +49 (0) 30 XXX XXXX
""")

_ONBOARDING_PROMPT_DE = textwrap.dedent("""\
Sie sind Anthony Stewart, IT-Berater bei Klaravex (klaravex.de).
Schreiben Sie eine herzliche, professionelle Willkommens-E-Mail auf DEUTSCH.

Neuer Kundenkontakt:
  Name:                 {name}
  Unternehmen:          {company}
  Vereinbarte Leistung: {services}
  Ursprüngliche Anfrage:{message}
  Kickoff-Link:         {booking_url}

Anforderungen an die E-Mail:
- Ton: herzlich, selbstbewusst, professionell. Dies ist der Beginn einer Geschäftsbeziehung.
- Länge: 3–4 kurze Absätze
- Persönliche Begrüßung, Bezug auf das Anliegen des Kunden
- Die 3 nächsten Schritte:
    1. Kickoff-Termin buchen (Link angegeben)
    2. Zugänge / Unterlagen vorbereiten, die benötigt werden
    3. Anthony schickt innerhalb von 48h nach dem Kickoff ein Projektbriefing
- Klare Handlungsaufforderung: Link zum Termin klicken
- Formale Anrede (Sie/Ihnen)
- Absender: Anthony Stewart, Klaravex

Ausgabe NUR in diesem Format:
Betreff: [Betreffzeile]

[E-Mail-Text]

Mit freundlichen Grüßen,
Anthony Stewart
IT-Berater | klaravex.de
Tel: +49 (0) 30 XXX XXXX
""")


class ClientOnboardingAgent(BaseAgent):
    name = "client_onboarding"
    permission_level = PermissionLevel.P2
    description = (
        "Fires when a lead is marked as won via POST /api/v1/leads/{id}/mark-won. "
        "Generates a bilingual (EN or DE) personalised welcome email and queues it "
        "for Anthony's approval (P3). Stamps lead.onboarding_sent_at for idempotency. "
        "Updates lead.status → won."
    )

    async def run(self, context: AgentContext, payload: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        lead_id = context.lead_id or payload.get("lead_id")
        if not lead_id:
            return AgentResult.fail("client_onboarding: 'lead_id' is required.")

        # Load lead
        result = await context.db.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()

        if not lead:
            return AgentResult.fail(f"Lead {lead_id} not found.")

        if lead.status == "anonymised":
            return AgentResult.fail("Cannot onboard anonymised lead.")

        # Idempotency: already onboarded
        if lead.onboarding_sent_at is not None:
            log.info("client_onboarding.already_onboarded",
                     lead_id=lead_id, sent_at=str(lead.onboarding_sent_at))
            return AgentResult.ok({
                "status": "already_onboarded",
                "lead_id": lead_id,
                "onboarding_sent_at": lead.onboarding_sent_at.isoformat(),
            })

        # Use configured booking URL (falls back to hardcoded default if empty)
        booking_url = context.settings.booking_url or "https://calendly.com/klaravex/45-minute-meeting"

        log.info("client_onboarding.generating", lead_id=lead_id, company=lead.company)

        # Detect language
        language = _detect_language(lead)
        prompt_template = _ONBOARDING_PROMPT_DE if language == "de" else _ONBOARDING_PROMPT_EN

        services = lead.services_interest or "IT consulting services"
        prompt = prompt_template.format(
            name=lead.name or ("Sehr geehrte Damen und Herren" if language == "de" else "there"),
            company=lead.company or ("Ihr Unternehmen" if language == "de" else "your organisation"),
            services=services,
            message=lead.message or "(no details on file)",
            booking_url=booking_url,
        )

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            from app.services.prompt_registry import register_prompt
            await register_prompt(
                context.db, agent_name=self.name,
                prompt_name="_ONBOARDING_PROMPT_EN",
                content=str(_ONBOARDING_PROMPT_EN),
            )
        except Exception:
            pass

        try:
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            draft = response.content[0].text.strip()
            from app.services.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model="claude-haiku-4-5-20251001",
                response=response, lead_id=lead_id,
            )
        except Exception as exc:
            log.error("client_onboarding.claude_error", lead_id=lead_id, error=str(exc))
            return AgentResult.fail(str(exc))

        subject = _extract_subject(draft, language)
        body = _extract_body(draft, language)

        now = datetime.now(timezone.utc)

        # Mark lead as won and stamp onboarding idempotency key BEFORE queuing
        lead_row = (await context.db.execute(
            select(Lead).where(Lead.id == lead_id)
        )).scalar_one_or_none()
        if lead_row:
            lead_row.status = LeadStatus.won
            lead_row.onboarding_sent_at = now
            await context.db.flush()

        # Queue for Anthony's approval
        try:
            from app.agents.registry import registry
            approval_agent = registry.get("approval_manager")
            if not approval_agent:
                log.error("client_onboarding.approval_manager_not_found")
                return AgentResult.fail("approval_manager not registered.")

            await approval_agent(context, {
                "action": "create",
                "action_name": "send_client_onboarding_email",
                "risk_level": "P3",
                "payload": {
                    "lead_id": lead_id,
                    "to_email": lead.email,
                    "to_name": lead.name or lead.email,
                    "subject": subject,
                    "body_html": _render_html(lead, subject, body, booking_url, language),
                    "body_text": body,
                    "language": language,
                },
                "justification": (
                    f"Client onboarding welcome email for {lead.name or lead.email} "
                    f"({lead.company or 'unknown'}) — deal marked as won. "
                    f"Language: {language.upper()}."
                ),
                "requested_by": self.name,
            })
        except Exception as exc:
            log.error("client_onboarding.approval_queue_error",
                      lead_id=lead_id, error=str(exc))
            return AgentResult.fail(str(exc))

        log.info("client_onboarding.queued_for_approval",
                 lead_id=lead_id, subject=subject, language=language)

        return AgentResult.ok({
            "status": "queued_for_approval",
            "lead_id": lead_id,
            "lead_status": "won",
            "subject": subject,
            "language": language,
            "tokens_used": response.usage.output_tokens,
        })


# ── Helpers ────────────────────────────────────────────────────────────────────

def _detect_language(lead: Lead) -> str:
    """Return 'de' for German-domain emails, 'en' otherwise."""
    email = lead.email or ""
    if email.endswith(".de") or email.endswith(".at") or email.endswith(".ch"):
        return "de"
    return "en"


def _extract_subject(draft: str, language: str) -> str:
    for line in draft.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("subject:"):
            return stripped[len("subject:"):].strip()
        if stripped.lower().startswith("betreff:"):
            return stripped[len("betreff:"):].strip()
    if language == "de":
        return "Willkommen als Kunde — Klaravex"
    return "Welcome to Klaravex — Let's get started"


def _extract_body(draft: str, language: str) -> str:
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


def _render_html(lead: Lead, subject: str, body_text: str,
                 booking_url: str, language: str) -> str:
    name = lead.name or "Client"
    company = lead.company or ""
    paragraphs = [p.strip() for p in body_text.split("\n\n") if p.strip()]
    html_paras = "".join(
        f"<p style='margin:10px 0;line-height:1.6;'>{p.replace(chr(10), '<br>')}</p>"
        for p in paragraphs
    )
    header_label = "Neuer Kunde — Willkommens-E-Mail" if language == "de" else "New Client — Welcome Email Draft"
    btn_text = "Kickoff-Termin buchen" if language == "de" else "Book Kickoff Call"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;padding:20px;color:#222;">
<div style="border-left:4px solid #2e7d32;background:#e8f5e9;padding:10px 14px;border-radius:4px;margin-bottom:20px;">
  <strong style="color:#2e7d32;">🎉 {header_label}</strong><br>
  <span style="font-size:13px;">{name}{' · ' + company if company else ''}</span>
</div>
{html_paras}
<div style="margin:24px 0;text-align:center;">
  <a href="{booking_url}"
     style="background:#2e7d32;color:white;padding:12px 24px;border-radius:4px;
            text-decoration:none;font-size:14px;font-weight:bold;">
    {btn_text}
  </a>
</div>
<hr style="border:none;border-top:1px solid #eee;margin:20px 0;">
<p style="font-size:12px;color:#999;">
  Approval required · Klara AI ClientOnboardingAgent · klaravex.de
</p>
</body>
</html>"""
