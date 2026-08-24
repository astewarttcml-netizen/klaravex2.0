"""
app/agents/calendar_integration.py
────────────────────────────────────
CalendarIntegrationAgent — P2 internal outreach.

Sends a bilingual (German for .de domains, English otherwise) booking-invite
email to HOT/WARM leads with a Calendly link so they can book a discovery call
at their convenience.

Called inline from RoutingAgent for tier == "HOT" or "WARM", after lead_alert.
Idempotent: sets booking_email_sent_at on the Lead; will NOT resend if already stamped.

Email includes:
  - Personalised greeting
  - 1–2 sentence context referencing their enquiry
  - Calendly booking link (BOOKING_URL env var)
  - Anthony's contact details
  - GDPR-compliant footer
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.lead import Lead

logger = structlog.get_logger(__name__)


class CalendarIntegrationAgent(BaseAgent):
    name = "calendar_integration"
    description = (
        "Sends a booking-invite email to HOT/WARM leads with a Calendly discovery-call "
        "link. Bilingual (DE for .de/.at/.ch domains, EN otherwise). "
        "Idempotent — will not resend if booking_email_sent_at is already set."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        lead_id = context.lead_id or input_data.get("lead_id")
        tier    = input_data.get("tier", "WARM")

        # ── Load lead ────────────────────────────────────────────────────────
        result = await context.db.execute(select(Lead).where(Lead.id == lead_id))
        lead: Lead | None = result.scalar_one_or_none()
        if not lead:
            logger.warning("calendar_integration.no_lead", lead_id=lead_id)
            return AgentResult.fail("calendar_integration: lead not found", agent=self.name)

        if not lead.email:
            logger.info("calendar_integration.no_email", lead_id=lead_id)
            return AgentResult.ok(output={"sent": False, "reason": "no_email"}, agent=self.name)

        # ── Idempotency ──────────────────────────────────────────────────────
        if lead.booking_email_sent_at:
            logger.info("calendar_integration.already_sent",
                        lead_id=lead_id, sent_at=str(lead.booking_email_sent_at))
            return AgentResult.ok(
                output={"sent": False, "reason": "already_sent"},
                agent=self.name,
            )

        # ── Detect language ──────────────────────────────────────────────────
        email = lead.email.lower()
        use_german = any(email.endswith(tld) for tld in (".de", ".at", ".ch"))

        booking_url = context.settings.booking_url
        name    = lead.name or "there"
        company = lead.company or ""
        snippet = textwrap.shorten(lead.message or "", width=120, placeholder="…")

        # ── Build email ──────────────────────────────────────────────────────
        if use_german:
            subject   = f"Nächste Schritte — Klaravex"
            body_html = _build_html_de(name, company, snippet, booking_url, tier)
            body_text = _build_text_de(name, company, snippet, booking_url)
        else:
            subject   = f"Next Steps — Klaravex"
            body_html = _build_html_en(name, company, snippet, booking_url, tier)
            body_text = _build_text_en(name, company, snippet, booking_url)

        # ── Send ─────────────────────────────────────────────────────────────
        try:
            from klara.rarv.runtime.email_sender import send_transactional_email
            sent = await send_transactional_email(
                context.settings,
                to_email=lead.email,
                to_name=lead.name or "",
                subject=subject,
                body_html=body_html,
                body_text=body_text,
            )
        except Exception as exc:
            logger.error("calendar_integration.send_error",
                         lead_id=lead_id, error=str(exc))
            return AgentResult.ok(
                output={"sent": False, "error": str(exc)},
                agent=self.name,
            )

        # ── Stamp idempotency field ───────────────────────────────────────────
        if sent:
            lead.booking_email_sent_at = datetime.now(timezone.utc)
            await context.db.flush()
            logger.info("calendar_integration.sent",
                        lead_id=lead_id, tier=tier, to=lead.email)

        return AgentResult.ok(
            output={"sent": sent, "tier": tier, "language": "de" if use_german else "en"},
            agent=self.name,
        )


# ── Email builders ─────────────────────────────────────────────────────────────

def _build_html_de(name: str, company: str, snippet: str, booking_url: str, tier: str) -> str:
    company_line = f" von {company}" if company else ""
    context_line = (
        f'<p>Bezüglich Ihrer Anfrage{company_line}: <em>"{snippet}"</em></p>'
        if snippet else ""
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family: Arial, sans-serif; font-size: 14px; color: #222;
         max-width: 600px; margin: 0 auto; padding: 24px; }}
  .cta {{ display:inline-block; margin:20px 0; background:#1a3a5c; color:#fff;
          padding:12px 28px; border-radius:4px; text-decoration:none;
          font-weight:bold; font-size:15px; }}
  .footer {{ color:#aaa; font-size:11px; margin-top:32px;
             border-top:1px solid #eee; padding-top:10px; }}
</style></head>
<body>
<p>Hallo {name},</p>
<p>vielen Dank für Ihr Interesse an Klaravex.
Ich freue mich, dass wir Ihnen weiterhelfen können.</p>
{context_line}
<p>Am einfachsten vereinbaren wir einen kurzen Kennenlerntermin (30 Min.),
um Ihre IT-Anforderungen gemeinsam zu besprechen.
Wählen Sie einfach einen Termin, der Ihnen passt:</p>
<a class="cta" href="{booking_url}">Termin buchen →</a>
<p>Falls Sie vorab Fragen haben, antworten Sie einfach auf diese E-Mail.</p>
<p>Mit freundlichen Grüßen,<br>
<strong>Anthony Stewart</strong><br>
Klaravex<br>
<a href="mailto:anthony@klaravex.de">anthony@klaravex.de</a></p>
<div class="footer">
  Klaravex · Diese E-Mail wurde gesendet, weil Sie über unser
  Kontaktformular Anfrage gestellt haben (DSGVO Art. 6 Abs. 1 lit. b).
</div>
</body></html>"""


def _build_text_de(name: str, company: str, snippet: str, booking_url: str) -> str:
    company_line = f" von {company}" if company else ""
    return f"""Hallo {name},

vielen Dank für Ihr Interesse an Klaravex.
{'Bezüglich Ihrer Anfrage' + company_line + ': "' + snippet + '"' if snippet else ''}

Buchen Sie gerne einen 30-minütigen Kennenlernanruf:
{booking_url}

Bei Fragen antworten Sie einfach auf diese E-Mail.

Mit freundlichen Grüßen,
Anthony Stewart
Klaravex
anthony@klaravex.de
"""


def _build_html_en(name: str, company: str, snippet: str, booking_url: str, tier: str) -> str:
    company_line = f" from {company}" if company else ""
    context_line = (
        f'<p>Regarding your enquiry{company_line}: <em>"{snippet}"</em></p>'
        if snippet else ""
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family: Arial, sans-serif; font-size: 14px; color: #222;
         max-width: 600px; margin: 0 auto; padding: 24px; }}
  .cta {{ display:inline-block; margin:20px 0; background:#1a3a5c; color:#fff;
          padding:12px 28px; border-radius:4px; text-decoration:none;
          font-weight:bold; font-size:15px; }}
  .footer {{ color:#aaa; font-size:11px; margin-top:32px;
             border-top:1px solid #eee; padding-top:10px; }}
</style></head>
<body>
<p>Hi {name},</p>
<p>Thank you for reaching out to Klaravex — I'd love to help.</p>
{context_line}
<p>The easiest next step is a quick 30-minute call so we can talk through
your IT requirements and figure out the best way forward.
Pick a time that works for you:</p>
<a class="cta" href="{booking_url}">Book a Discovery Call →</a>
<p>If you have any questions in the meantime, just reply to this email.</p>
<p>Best regards,<br>
<strong>Anthony Stewart</strong><br>
Klaravex<br>
<a href="mailto:anthony@klaravex.de">anthony@klaravex.de</a></p>
<div class="footer">
  Klaravex · You received this email because you submitted an enquiry
  via our contact form (GDPR Art. 6(1)(b)).
</div>
</body></html>"""


def _build_text_en(name: str, company: str, snippet: str, booking_url: str) -> str:
    company_line = f" from {company}" if company else ""
    return f"""Hi {name},

Thank you for reaching out to Klaravex.
{'Regarding your enquiry' + company_line + ': "' + snippet + '"' if snippet else ''}

Book a 30-minute discovery call here:
{booking_url}

Feel free to reply if you have any questions.

Best regards,
Anthony Stewart
Klaravex
anthony@klaravex.de
"""
