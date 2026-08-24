"""
app/agents/followup_nurture.py
───────────────────────────────
FollowupNurtureAgent — P2 automated follow-up.

Sends a bilingual follow-up email to HOT/WARM leads that received a booking
invite (booking_email_sent_at is set) but haven't booked yet, 3+ days later.

Triggered by: Celery beat hourly sweep (app.tasks.followup_nurture).
Also callable directly via POST /api/v1/agents/run with agent="followup_nurture".

Eligibility:
  - status IN (qualified)
  - booking_email_sent_at IS NOT NULL
  - booking_email_sent_at <= now - FOLLOWUP_DAYS_AFTER_BOOKING (default 3)
  - followup_sent_at IS NULL   (idempotency — send only once)
  - email IS NOT NULL

Content:
  - Warm check-in referencing the booking link
  - Suggests alternative: just reply to this email
  - German for .de/.at/.ch domains, English otherwise
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, and_

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)

_DEFAULT_FOLLOWUP_DAYS = 3


class FollowupNurtureAgent(BaseAgent):
    name = "followup_nurture"
    description = (
        "Hourly sweep: sends a single follow-up email to HOT/WARM leads that received "
        "a booking invite ≥3 days ago but haven't booked (followup_sent_at IS NULL). "
        "Bilingual (DE/.de/.at/.ch, EN otherwise). Stamps followup_sent_at. "
        "P2 — automated outreach to an already-engaged warm lead."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        followup_days = int(
            input_data.get("followup_days")
            or getattr(context.settings, "followup_days_after_booking", _DEFAULT_FOLLOWUP_DAYS)
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=followup_days)

        # ── Find eligible leads ──────────────────────────────────────────────
        result = await context.db.execute(
            select(Lead).where(
                and_(
                    Lead.status == LeadStatus.qualified,
                    Lead.email.is_not(None),
                    Lead.booking_email_sent_at.is_not(None),
                    Lead.booking_email_sent_at <= cutoff,
                    Lead.followup_sent_at.is_(None),
                )
            )
        )
        leads = result.scalars().all()

        if not leads:
            logger.info("followup_nurture.no_eligible_leads")
            return AgentResult.ok(output={"sent": 0, "status": "no_eligible_leads"}, agent=self.name)

        sent_count = 0
        errors = []
        booking_url = context.settings.booking_url

        for lead in leads:
            use_german = any(
                lead.email.lower().endswith(tld) for tld in (".de", ".at", ".ch")
            )
            name    = lead.name or "there"
            company = lead.company or ""
            snippet = textwrap.shorten(lead.message or "", width=100, placeholder="…")

            if use_german:
                subject   = "Haben Sie bereits einen Termin gebucht? — Klaravex"
                body_html = _html_de(name, company, snippet, booking_url)
                body_text = _text_de(name, company, snippet, booking_url)
            else:
                subject   = "Did you manage to book a call? — Klaravex"
                body_html = _html_en(name, company, snippet, booking_url)
                body_text = _text_en(name, company, snippet, booking_url)

            try:
                from app.services.email_sender import send_transactional_email
                ok = await send_transactional_email(
                    context.settings,
                    to_email=lead.email,
                    to_name=lead.name or "",
                    subject=subject,
                    body_html=body_html,
                    body_text=body_text,
                )
            except Exception as exc:
                logger.error("followup_nurture.send_error",
                             lead_id=lead.id, error=str(exc))
                errors.append(str(lead.id))
                continue

            if ok:
                lead.followup_sent_at = datetime.now(timezone.utc)
                await context.db.flush()
                sent_count += 1
                logger.info("followup_nurture.sent",
                            lead_id=lead.id, to=lead.email,
                            lang="de" if use_german else "en")

        return AgentResult.ok(
            output={"sent": sent_count, "errors": errors},
            agent=self.name,
        )


# ── Email builders ─────────────────────────────────────────────────────────────

def _html_de(name: str, company: str, snippet: str, booking_url: str) -> str:
    company_line = f" ({company})" if company else ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family:Arial,sans-serif; font-size:14px; color:#222;
         max-width:600px; margin:0 auto; padding:24px; }}
  .cta {{ display:inline-block; margin:16px 0; background:#1a3a5c; color:#fff;
          padding:10px 24px; border-radius:4px; text-decoration:none;
          font-weight:bold; font-size:14px; }}
  .footer {{ color:#aaa; font-size:11px; margin-top:28px;
             border-top:1px solid #eee; padding-top:10px; }}
</style></head>
<body>
<p>Hallo {name},</p>
<p>ich wollte mich kurz melden — vor einigen Tagen hatte ich Ihnen{company_line}
einen Link zur Terminbuchung geschickt.</p>
<p>Falls die Zeit noch nicht gepasst hat, können Sie hier jederzeit einen
30-minütigen Kennenlerntermin buchen:</p>
<a class="cta" href="{booking_url}">Jetzt Termin buchen →</a>
<p>Oder antworten Sie einfach auf diese E-Mail — ich melde mich dann direkt
bei Ihnen.</p>
<p>Mit freundlichen Grüßen,<br>
<strong>Anthony Stewart</strong><br>
Klaravex</p>
<div class="footer">
  Klaravex · DSGVO Art. 6 Abs. 1 lit. b — Anfrage-Follow-up
</div>
</body></html>"""


def _text_de(name: str, company: str, snippet: str, booking_url: str) -> str:
    company_line = f" ({company})" if company else ""
    return f"""Hallo {name},

ich wollte mich kurz melden{company_line} — vor einigen Tagen hatte ich Ihnen
einen Link zur Terminbuchung geschickt.

Falls die Zeit noch nicht gepasst hat:
{booking_url}

Oder antworten Sie einfach auf diese E-Mail.

Mit freundlichen Grüßen,
Anthony Stewart
Klaravex
"""


def _html_en(name: str, company: str, snippet: str, booking_url: str) -> str:
    company_line = f" ({company})" if company else ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family:Arial,sans-serif; font-size:14px; color:#222;
         max-width:600px; margin:0 auto; padding:24px; }}
  .cta {{ display:inline-block; margin:16px 0; background:#1a3a5c; color:#fff;
          padding:10px 24px; border-radius:4px; text-decoration:none;
          font-weight:bold; font-size:14px; }}
  .footer {{ color:#aaa; font-size:11px; margin-top:28px;
             border-top:1px solid #eee; padding-top:10px; }}
</style></head>
<body>
<p>Hi {name},</p>
<p>I just wanted to follow up{company_line} — I sent you a booking link a few
days ago for a discovery call.</p>
<p>If you haven't had a chance to book yet, you're welcome to grab a slot
here at any time:</p>
<a class="cta" href="{booking_url}">Book a 30-Min Call →</a>
<p>Alternatively, just reply to this email and we can sort out a time directly.</p>
<p>Best regards,<br>
<strong>Anthony Stewart</strong><br>
Klaravex</p>
<div class="footer">
  Klaravex · GDPR Art. 6(1)(b) — follow-up on your enquiry
</div>
</body></html>"""


def _text_en(name: str, company: str, snippet: str, booking_url: str) -> str:
    company_line = f" ({company})" if company else ""
    return f"""Hi {name},

Just following up{company_line} — I sent you a booking link a few days ago.

If you haven't had a chance yet:
{booking_url}

Or just reply to this email.

Best regards,
Anthony Stewart
Klaravex
"""
