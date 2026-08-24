"""
app/agents/project_kickoff.py
───────────────────────────────
P2 agent — sends a structured project kickoff email to a newly won client.

Triggered by: status transition won → kickoff, OR
  POST /api/v1/agents/run with agent="project_kickoff"
  payload: { "lead_id": "<uuid>" }

Flow:
  1. Load lead — must be status=won, must have email
  2. Parse call_notes JSON for pain_points, timeline, next_action
  3. Build a professional kickoff email covering:
     - Welcome & thank-you
     - Project overview (services, timeline)
     - Immediate next steps (Anthony books kickoff call, access requirements)
     - What to expect in the first week
     - Contact & escalation info
  4. Send directly — P2, informational, no sensitive commitments

Idempotency: checked via onboarding_sent_at (shared with ClientOnboardingAgent).
  If onboarding_sent_at is already set, skip and return ok(status="already_sent").

Permission: P2 — client-facing but purely informational and welcome in nature.
  No contract terms, no payment details, no legal content.
"""
from __future__ import annotations

import json
import textwrap
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from app.agents.base import BaseAgent, AgentContext, AgentResult, PermissionLevel
from app.models.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)

_KICKOFF_TEMPLATE_EN = textwrap.dedent("""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;
             padding:20px;color:#222;">

<h2 style="color:#1565c0;border-bottom:2px solid #1565c0;padding-bottom:8px;">
  🚀 Welcome — Let's Get Started
</h2>

<p>Hi {first_name},</p>

<p>Thank you for choosing Klaravex. I'm excited to work with you on
{services_summary}. Here's everything you need to know to get started.</p>

<h3 style="color:#333;margin-top:24px;">📋 Project Overview</h3>
<table style="border-collapse:collapse;width:100%;margin-bottom:16px;">
  <tr style="background:#e3f2fd;">
    <td style="padding:6px 10px;font-weight:bold;width:35%;">Services</td>
    <td style="padding:6px 10px;">{services}</td>
  </tr>
  <tr>
    <td style="padding:6px 10px;font-weight:bold;">Agreed Timeline</td>
    <td style="padding:6px 10px;">{timeline}</td>
  </tr>
  <tr style="background:#f5f5f5;">
    <td style="padding:6px 10px;font-weight:bold;">Project Reference</td>
    <td style="padding:6px 10px;">{lead_ref}</td>
  </tr>
</table>

<h3 style="color:#333;margin-top:24px;">✅ Immediate Next Steps</h3>
<ol style="padding-left:20px;line-height:1.8;">
  <li>I will schedule our <strong>kickoff call</strong> within 2 business days —
      watch for a Calendly link in a separate email.</li>
  <li>Please prepare <strong>admin access credentials</strong> for any systems in
      scope (M365 tenant, Azure portal, network equipment). We'll go through
      access requirements on the kickoff call.</li>
  <li>If there are existing IT contacts or vendors I should be aware of, please
      reply with their details.</li>
  {extra_next_step}
</ol>

<h3 style="color:#333;margin-top:24px;">📅 What to Expect — Week 1</h3>
<ul style="padding-left:20px;line-height:1.8;">
  <li><strong>Day 1–2:</strong> Kickoff call — confirm scope, access, milestones</li>
  <li><strong>Day 3–5:</strong> Discovery and environment assessment</li>
  <li><strong>End of Week 1:</strong> Written project plan with milestones sent to you</li>
</ul>

<h3 style="color:#333;margin-top:24px;">📞 Contact &amp; Escalation</h3>
<p>For day-to-day updates, reply directly to this email. For urgent issues,
reach me at <strong>anthony@klaravex.de</strong>. Response time is
typically &lt;4 hours on business days.</p>

<p style="margin-top:24px;">Looking forward to delivering a smooth, professional
experience for {company_or_you}.</p>

<p>Best regards,<br>
<strong>Anthony Stewart</strong><br>
Klaravex<br>
<a href="https://klaravex.de">klaravex.de</a>
</p>

<hr style="border:none;border-top:1px solid #eee;margin-top:32px;">
<p style="font-size:11px;color:#999;">
  Klaravex · klaravex.de · Ref: {lead_ref}
</p>
</body>
</html>
""")

_KICKOFF_TEMPLATE_DE = textwrap.dedent("""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;
             padding:20px;color:#222;">

<h2 style="color:#1565c0;border-bottom:2px solid #1565c0;padding-bottom:8px;">
  🚀 Willkommen — Wir legen los
</h2>

<p>Guten Tag {first_name},</p>

<p>Herzlichen Dank, dass Sie sich für Klaravex entschieden haben. Ich
freue mich auf die Zusammenarbeit bei {services_summary}. Hier finden Sie alle
wichtigen Informationen zum Projektstart.</p>

<h3 style="color:#333;margin-top:24px;">📋 Projektübersicht</h3>
<table style="border-collapse:collapse;width:100%;margin-bottom:16px;">
  <tr style="background:#e3f2fd;">
    <td style="padding:6px 10px;font-weight:bold;width:35%;">Leistungen</td>
    <td style="padding:6px 10px;">{services}</td>
  </tr>
  <tr>
    <td style="padding:6px 10px;font-weight:bold;">Vereinbarter Zeitrahmen</td>
    <td style="padding:6px 10px;">{timeline}</td>
  </tr>
  <tr style="background:#f5f5f5;">
    <td style="padding:6px 10px;font-weight:bold;">Projektreferenz</td>
    <td style="padding:6px 10px;">{lead_ref}</td>
  </tr>
</table>

<h3 style="color:#333;margin-top:24px;">✅ Sofortige nächste Schritte</h3>
<ol style="padding-left:20px;line-height:1.8;">
  <li>Ich plane unser <strong>Kick-off-Gespräch</strong> innerhalb von 2 Werktagen —
      Sie erhalten einen Calendly-Link per separater E-Mail.</li>
  <li>Bitte bereiten Sie <strong>Admin-Zugangsdaten</strong> für alle relevanten
      Systeme vor (M365-Tenant, Azure-Portal, Netzwerkgeräte). Die genauen
      Zugriffsanforderungen besprechen wir im Kick-off-Gespräch.</li>
  <li>Falls bestehende IT-Kontakte oder -Dienstleister zu berücksichtigen sind,
      teilen Sie mir diese bitte per Antwort auf diese E-Mail mit.</li>
  {extra_next_step}
</ol>

<h3 style="color:#333;margin-top:24px;">📅 Was Sie in Woche 1 erwartet</h3>
<ul style="padding-left:20px;line-height:1.8;">
  <li><strong>Tag 1–2:</strong> Kick-off-Gespräch — Umfang, Zugänge, Meilensteine</li>
  <li><strong>Tag 3–5:</strong> Bestandsaufnahme und Umgebungsanalyse</li>
  <li><strong>Ende Woche 1:</strong> Schriftlicher Projektplan mit Meilensteinen</li>
</ul>

<h3 style="color:#333;margin-top:24px;">📞 Kontakt &amp; Eskalation</h3>
<p>Für laufende Updates antworten Sie bitte direkt auf diese E-Mail. Bei dringenden
Anliegen erreichen Sie mich unter <strong>anthony@klaravex.de</strong>.
Antwortzeit in der Regel &lt;4 Stunden an Werktagen.</p>

<p style="margin-top:24px;">Ich freue mich auf eine reibungslose und
professionelle Zusammenarbeit mit {company_or_you}.</p>

<p>Mit freundlichen Grüßen,<br>
<strong>Anthony Stewart</strong><br>
Klaravex<br>
<a href="https://klaravex.de">klaravex.de</a>
</p>

<hr style="border:none;border-top:1px solid #eee;margin-top:32px;">
<p style="font-size:11px;color:#999;">
  Klaravex · klaravex.de · Ref: {lead_ref}
</p>
</body>
</html>
""")


class ProjectKickoffAgent(BaseAgent):
    name = "project_kickoff"
    permission_level = PermissionLevel.P2
    description = (
        "Sends a structured project kickoff email to a newly won client. "
        "Requires lead_id. Lead must be status=won. Covers services, timeline, "
        "next steps, and contact info. Idempotent via onboarding_sent_at. "
        "Bilingual EN/DE. P2 — welcome/informational, no legal content."
    )

    async def run(self, context: AgentContext, payload: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        lead_id = context.lead_id or payload.get("lead_id")
        if not lead_id:
            return AgentResult.fail("project_kickoff: 'lead_id' is required.")

        lead = (await context.db.execute(
            select(Lead).where(Lead.id == lead_id)
        )).scalar_one_or_none()

        if not lead:
            return AgentResult.fail(f"Lead {lead_id} not found.")
        if lead.status == "anonymised":
            return AgentResult.fail("Cannot send kickoff to anonymised lead.")
        if not lead.email:
            return AgentResult.fail(f"Lead {lead_id} has no email address.")

        # Idempotency guard — shared with ClientOnboardingAgent
        if lead.onboarding_sent_at is not None:
            log.info("project_kickoff.already_sent",
                     lead_id=lead_id,
                     sent_at=str(lead.onboarding_sent_at))
            return AgentResult.ok({
                "status": "already_sent",
                "lead_id": lead_id,
                "onboarding_sent_at": str(lead.onboarding_sent_at),
            })

        # Parse call notes for context
        call_notes: dict = {}
        if lead.call_notes:
            try:
                call_notes = json.loads(lead.call_notes)
            except Exception:
                pass

        services = lead.services_interest or "IT Consulting Services"
        timeline = (
            call_notes.get("timeline")
            or lead.timeline
            or "To be confirmed on kickoff call"
        )
        next_action = call_notes.get("next_action", "")

        # Short services summary for prose sentence
        services_list = services.strip("[]").replace('"', "").replace(",", ", ")
        if len(services_list) > 80:
            services_summary = "your IT project"
        else:
            services_summary = services_list or "your IT project"

        language = _detect_language(lead)
        first_name = (lead.name or "").split()[0] if lead.name else (
            "there" if language == "en" else "Ihnen"
        )
        company_or_you = lead.company or ("your team" if language == "en" else "Ihrem Team")
        lead_ref = str(lead.id)[:8].upper()

        # Optional extra next step derived from call notes
        extra_next_step = ""
        if next_action:
            if language == "de":
                extra_next_step = f"<li>Vereinbarte nächste Maßnahme: <em>{next_action}</em></li>"
            else:
                extra_next_step = f"<li>Agreed next action from our call: <em>{next_action}</em></li>"

        now = datetime.now(timezone.utc)

        if language == "de":
            html = _KICKOFF_TEMPLATE_DE.format(
                first_name=first_name,
                services=services_list,
                services_summary=services_summary,
                timeline=timeline,
                lead_ref=lead_ref,
                company_or_you=company_or_you,
                extra_next_step=extra_next_step,
            )
            subject = f"🚀 Willkommen bei Klaravex — Projektstart"
        else:
            html = _KICKOFF_TEMPLATE_EN.format(
                first_name=first_name,
                services=services_list,
                services_summary=services_summary,
                timeline=timeline,
                lead_ref=lead_ref,
                company_or_you=company_or_you,
                extra_next_step=extra_next_step,
            )
            subject = "🚀 Welcome to Klaravex — Project Kickoff"

        log.info("project_kickoff.sending", lead_id=lead_id, language=language)

        try:
            from app.services.email_sender import send_transactional_email
            await send_transactional_email(
                context.settings,
                to_email=lead.email,
                to_name=lead.name or lead.email,
                subject=subject,
                body_html=html,
                body_text=(
                    f"Hi {first_name},\n\n"
                    f"Thank you for choosing Klaravex.\n\n"
                    f"Services: {services_list}\n"
                    f"Timeline: {timeline}\n"
                    f"Reference: {lead_ref}\n\n"
                    "Next steps: I'll send a Calendly link for our kickoff call "
                    "within 2 business days.\n\n"
                    "Best regards,\nAnthony Stewart\nKlaravex"
                ),
            )
        except Exception as exc:
            log.error("project_kickoff.email_failed", error=str(exc))
            return AgentResult.fail(str(exc))

        # Stamp idempotency guard
        lead_row = (await context.db.execute(
            select(Lead).where(Lead.id == lead_id)
        )).scalar_one_or_none()
        if lead_row:
            lead_row.onboarding_sent_at = now
            await context.db.flush()

        log.info("project_kickoff.sent",
                 lead_id=lead_id,
                 to_email=lead.email,
                 language=language)

        return AgentResult.ok({
            "status": "sent",
            "lead_id": lead_id,
            "to_email": lead.email,
            "language": language,
            "lead_ref": lead_ref,
        })


def _detect_language(lead: Lead) -> str:
    email = lead.email or ""
    if email.endswith(".de") or email.endswith(".at") or email.endswith(".ch"):
        return "de"
    return "en"
