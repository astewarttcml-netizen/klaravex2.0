"""
app/agents/client_satisfaction.py
────────────────────────────────────
P2 agent — sends an NPS / satisfaction survey to clients 30 days after
project kickoff (i.e. 30 days after onboarding_sent_at).

Triggered by: Celery beat daily sweep task.
Also callable directly via POST /api/v1/agents/run with
  agent="client_satisfaction".

Eligibility criteria:
  - status == won
  - onboarding_sent_at <= now - 30 days
  - satisfaction_sent_at IS NULL (idempotency)
  - gdpr_consent == True
  - email IS NOT NULL

Survey mechanics:
  - Simple 0–10 NPS question embedded in email as clickable score links
  - Each link hits /api/v1/survey/nps?lead_id=X&score=N
  - Agent writes satisfaction_sent_at; the API endpoint writes satisfaction_score
    when the client clicks (handled separately by a lightweight survey endpoint)

Permission: P2 — survey request to existing client. No financial content,
  no legal content. Informational/feedback collection. P2 appropriate.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from app.agents.base import BaseAgent, AgentContext, AgentResult, PermissionLevel
from app.models.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)


def _render_nps_email_en(
    first_name: str,
    lead_id: str,
    services: str,
    base_url: str,
) -> str:
    """Render English NPS survey email with clickable score buttons."""
    score_buttons = ""
    for score in range(11):
        color = "#c62828" if score <= 6 else ("#f57c00" if score <= 8 else "#2e7d32")
        score_buttons += (
            f"<a href='{base_url}/api/v1/survey/nps?lead_id={lead_id}&score={score}' "
            f"style='display:inline-block;width:36px;height:36px;line-height:36px;"
            f"text-align:center;background:{color};color:#fff;border-radius:4px;"
            f"text-decoration:none;font-weight:bold;margin:2px;'>{score}</a>"
        )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;
             padding:20px;color:#222;">
<h2 style="color:#1565c0;">How did we do? — Klaravex</h2>

<p>Hi {first_name},</p>

<p>It's been about a month since we started work on your {services} project.
I'd love to hear how you think it went.</p>

<p>On a scale of <strong>0–10</strong>, how likely are you to recommend
Klaravex to a colleague or fellow business owner?</p>

<div style="margin:20px 0;padding:16px;background:#f5f5f5;border-radius:6px;">
  <p style="margin:0 0 8px;font-size:13px;color:#666;">
    0 = Not at all likely &nbsp;|&nbsp; 10 = Extremely likely
  </p>
  <div>{score_buttons}</div>
</div>

<p>If you have any specific feedback — positive or constructive — simply
reply to this email. I read every response personally.</p>

<p>Thank you for trusting Klaravex with your IT infrastructure.</p>

<p>Best regards,<br>
<strong>Anthony Stewart</strong><br>
Klaravex<br>
<a href="https://klaravex.de">klaravex.de</a>
</p>

<hr style="border:none;border-top:1px solid #eee;">
<p style="font-size:11px;color:#999;">
  This survey is optional and anonymous. Klaravex ·
  klaravex.de
</p>
</body>
</html>"""


def _render_nps_email_de(
    first_name: str,
    lead_id: str,
    services: str,
    base_url: str,
) -> str:
    """Render German NPS survey email with clickable score buttons."""
    score_buttons = ""
    for score in range(11):
        color = "#c62828" if score <= 6 else ("#f57c00" if score <= 8 else "#2e7d32")
        score_buttons += (
            f"<a href='{base_url}/api/v1/survey/nps?lead_id={lead_id}&score={score}' "
            f"style='display:inline-block;width:36px;height:36px;line-height:36px;"
            f"text-align:center;background:{color};color:#fff;border-radius:4px;"
            f"text-decoration:none;font-weight:bold;margin:2px;'>{score}</a>"
        )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;
             padding:20px;color:#222;">
<h2 style="color:#1565c0;">Wie zufrieden sind Sie? — Klaravex</h2>

<p>Guten Tag {first_name},</p>

<p>seit etwa einem Monat arbeiten wir zusammen an Ihrem {services}-Projekt.
Ich würde mich sehr über Ihr Feedback freuen.</p>

<p>Auf einer Skala von <strong>0–10</strong>: Wie wahrscheinlich ist es, dass
Sie Klaravex einem Kollegen oder Geschäftspartner weiterempfehlen?</p>

<div style="margin:20px 0;padding:16px;background:#f5f5f5;border-radius:6px;">
  <p style="margin:0 0 8px;font-size:13px;color:#666;">
    0 = Sehr unwahrscheinlich &nbsp;|&nbsp; 10 = Sehr wahrscheinlich
  </p>
  <div>{score_buttons}</div>
</div>

<p>Falls Sie konkretes Feedback haben — positiv oder konstruktiv — antworten
Sie bitte einfach auf diese E-Mail. Ich lese jede Rückmeldung persönlich.</p>

<p>Vielen Dank für Ihr Vertrauen in Klaravex.</p>

<p>Mit freundlichen Grüßen,<br>
<strong>Anthony Stewart</strong><br>
Klaravex<br>
<a href="https://klaravex.de">klaravex.de</a>
</p>

<hr style="border:none;border-top:1px solid #eee;">
<p style="font-size:11px;color:#999;">
  Diese Umfrage ist freiwillig und anonym. Klaravex ·
  klaravex.de
</p>
</body>
</html>"""


class ClientSatisfactionAgent(BaseAgent):
    name = "client_satisfaction"
    permission_level = PermissionLevel.P2
    description = (
        "Daily sweep: finds won clients 30+ days post-onboarding who haven't received "
        "an NPS survey. Sends a clickable 0–10 score email directly (P2). Scores are "
        "captured via GET /api/v1/survey/nps and written to satisfaction_score. "
        "Stamps satisfaction_sent_at. P2 — feedback collection, no approval needed."
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
            .where(Lead.satisfaction_sent_at.is_(None))
            .where(Lead.email.is_not(None))
        )).scalars().all()

        if not rows:
            log.info("client_satisfaction.no_eligible_leads")
            return AgentResult.ok({"status": "no_eligible_leads", "sent": 0})

        log.info("client_satisfaction.eligible", count=len(rows))

        # Base URL for NPS click tracking — use settings or fallback
        base_url = getattr(context.settings, "api_base_url",
                           "https://api.klaravex.de")

        sent_count = 0
        errors = []

        for lead in rows:
            language = _detect_language(lead)
            first_name = (lead.name or "").split()[0] if lead.name else (
                "there" if language == "en" else "Sie"
            )
            services = (lead.services_interest or "IT consulting").strip("[]\"")

            if language == "de":
                html = _render_nps_email_de(
                    first_name=first_name,
                    lead_id=str(lead.id),
                    services=services[:60],
                    base_url=base_url,
                )
                subject = "Kurze Frage zu Ihrer Zufriedenheit — Klaravex"
                body_text = (
                    f"Guten Tag {first_name},\n\n"
                    "Ich würde mich sehr über Ihr Feedback freuen.\n\n"
                    "Auf einer Skala von 0–10: Wie wahrscheinlich ist es, dass Sie "
                    "Klaravex weiterempfehlen?\n\n"
                    "Antworten Sie einfach auf diese E-Mail.\n\n"
                    "Mit freundlichen Grüßen,\nAnthony Stewart\nKlaravex"
                )
            else:
                html = _render_nps_email_en(
                    first_name=first_name,
                    lead_id=str(lead.id),
                    services=services[:60],
                    base_url=base_url,
                )
                subject = "Quick question about your experience — Klaravex"
                body_text = (
                    f"Hi {first_name},\n\n"
                    "I'd love to hear how your project went.\n\n"
                    "On a scale of 0–10, how likely are you to recommend "
                    "Klaravex to a colleague?\n\n"
                    "Simply reply to this email with your thoughts.\n\n"
                    "Best regards,\nAnthony Stewart\nKlaravex"
                )

            try:
                from app.services.email_sender import send_transactional_email
                await send_transactional_email(
                    context.settings,
                    to_email=lead.email,
                    to_name=lead.name or lead.email,
                    subject=subject,
                    body_html=html,
                    body_text=body_text,
                )
            except Exception as exc:
                log.error("client_satisfaction.email_failed",
                          lead_id=lead.id, error=str(exc))
                errors.append(str(lead.id))
                continue

            # Stamp idempotency
            lead_row = (await context.db.execute(
                select(Lead).where(Lead.id == lead.id)
            )).scalar_one_or_none()
            if lead_row:
                lead_row.satisfaction_sent_at = now
                await context.db.flush()

            sent_count += 1
            log.info("client_satisfaction.sent",
                     lead_id=lead.id, to_email=lead.email)

        return AgentResult.ok({
            "status": "done",
            "eligible": len(rows),
            "sent": sent_count,
            "errors": errors,
        })


def _detect_language(lead: Lead) -> str:
    email = lead.email or ""
    if email.endswith(".de") or email.endswith(".at") or email.endswith(".ch"):
        return "de"
    return "en"
