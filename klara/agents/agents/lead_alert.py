"""
app/agents/lead_alert.py
─────────────────────────
LeadAlertAgent — P2 internal notification.

Sends Anthony an immediate rich HTML email the moment a HOT or WARM lead is
routed, giving full context to act within seconds.

Called inline from RoutingAgent for tier == "HOT" or "WARM".
No approval gate — this is a read-only internal notification.
No idempotency column needed: routing fires once per lead submission.

Email content:
  - Tier badge (HOT / WARM) with colour
  - Lead score (0–100)
  - Contact: name, company, email
  - Message snippet (first 300 chars)
  - AI qualification: services fit, urgency, company size, decision-maker flag
  - Recommended next step from Claude
  - Direct link to admin approval dashboard
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


class LeadAlertAgent(BaseAgent):
    name = "lead_alert"
    description = (
        "Sends Anthony an immediate rich HTML email when a HOT or WARM lead is routed. "
        "Includes score, qualification summary, and a direct link to the approval dashboard."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        lead_id   = context.lead_id or input_data.get("lead_id")
        tier      = input_data.get("tier", "WARM")
        score     = input_data.get("score", 0)
        qual      = input_data.get("qualification", {})

        # ── Load lead from DB ────────────────────────────────────────────────
        lead: Lead | None = None
        if lead_id:
            result = await context.db.execute(
                select(Lead).where(Lead.id == lead_id)
            )
            lead = result.scalar_one_or_none()

        if not lead:
            logger.warning("lead_alert.no_lead", lead_id=lead_id)
            return AgentResult.fail("lead_alert: lead not found", agent=self.name)

        # ── Build email ──────────────────────────────────────────────────────
        alert_mode = input_data.get("alert_mode", "standard")
        is_callback = alert_mode == "callback" or lead.source == "callback_request"

        if is_callback:
            subject = _build_callback_subject(lead)
            body_html = _build_callback_html(lead, qual, context.settings)
            body_text = _build_callback_text(lead, qual)
        else:
            subject = _build_subject(tier, lead, score)
            body_html = _build_html(tier, score, lead, qual, context.settings)
            body_text = _build_text(tier, score, lead, qual)

        # ── Send via Resend API (non-blocking — agent returns success either way) ──
        try:
            from klara.rarv.runtime.email_sender import send_resend_email
            recipient = context.settings.approval_notify_email
            sent = await send_resend_email(
                context.settings,
                to_email=recipient,
                to_name="Anthony Stewart",
                subject=subject,
                body_html=body_html,
                body_text=body_text,
            )
            logger.info(
                "lead_alert.sent",
                agent=self.name,
                lead_id=lead_id,
                tier=tier,
                score=score,
                to=recipient,
                sent=sent,
            )
        except Exception as exc:
            logger.error("lead_alert.send_error", agent=self.name, lead_id=lead_id, error=str(exc))
            # Non-fatal — routing should continue even if alert fails
            return AgentResult.ok(
                output={"alerted": False, "error": str(exc)},
                agent=self.name,
            )

        return AgentResult.ok(
            output={"alerted": True, "tier": tier, "score": score},
            agent=self.name,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_subject(tier: str, lead: Lead, score: float) -> str:
    icon = "🔥" if tier == "HOT" else "☀️"
    company = lead.company or "Unknown Company"
    name    = lead.name or "Unknown Contact"
    return f"{icon} {tier} Lead — {name} @ {company} (Score: {int(score)}/100)"


def _build_html(tier: str, score: float, lead: Lead, qual: dict, settings) -> str:
    colour      = "#C0392B" if tier == "HOT" else "#E67E22"
    tier_label  = tier.upper()
    icon        = "🔥" if tier == "HOT" else "☀️"
    company     = lead.company or "—"
    name        = lead.name or "—"
    email_addr  = lead.email or "—"
    message_raw = lead.message or ""
    message     = textwrap.shorten(message_raw, width=300, placeholder="…")
    source      = lead.source or "—"
    ts          = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Qualification fields
    services    = ", ".join(qual.get("services_fit") or []) or "—"
    urgency     = (qual.get("urgency") or "—").replace("-", "–")
    co_size     = qual.get("company_size_est") or "—"
    dm          = "Yes ✅" if qual.get("decision_maker") else "No"
    confidence  = qual.get("confidence")
    conf_pct    = f"{int(confidence * 100)}%" if confidence is not None else "—"
    next_step   = qual.get("next_step") or "—"

    dashboard_url = f"https://api.klaravex.de/admin/"

    # Score bar (simple HTML progress-style bar)
    bar_width = max(4, int(score))  # at least 4% so bar is visible
    bar_colour = colour

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  body  {{ font-family: Arial, sans-serif; font-size: 14px; color: #1a1a1a;
           max-width: 640px; margin: 0 auto; padding: 24px; }}
  .badge {{ display: inline-block; background: {colour}; color: #fff;
            font-weight: bold; font-size: 18px; padding: 8px 20px;
            border-radius: 4px; letter-spacing: 1px; }}
  .score-wrap {{ margin: 16px 0; }}
  .score-bar  {{ background: #eee; border-radius: 6px; height: 14px;
                 width: 100%; overflow: hidden; }}
  .score-fill {{ background: {bar_colour}; height: 14px;
                 width: {bar_width}%; border-radius: 6px; }}
  table   {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
  td      {{ padding: 8px 10px; border-bottom: 1px solid #eee;
             vertical-align: top; }}
  td:first-child {{ font-weight: bold; white-space: nowrap; width: 38%; color: #555; }}
  .msg    {{ background: #f9f9f9; border-left: 4px solid {colour};
             padding: 12px 14px; border-radius: 0 4px 4px 0;
             font-style: italic; color: #444; margin: 12px 0; }}
  .cta    {{ display: inline-block; margin-top: 20px; background: {colour};
             color: #fff; padding: 12px 24px; border-radius: 4px;
             text-decoration: none; font-weight: bold; font-size: 15px; }}
  .footer {{ color: #aaa; font-size: 11px; margin-top: 32px;
             border-top: 1px solid #eee; padding-top: 10px; }}
</style>
</head>
<body>

<div class="badge">{icon} {tier_label} LEAD</div>

<div class="score-wrap">
  <strong>Score: {int(score)}/100</strong>
  <div class="score-bar"><div class="score-fill"></div></div>
</div>

<table>
  <tr><td>Name</td><td>{name}</td></tr>
  <tr><td>Company</td><td>{company}</td></tr>
  <tr><td>Email</td><td><a href="mailto:{email_addr}">{email_addr}</a></td></tr>
  <tr><td>Source</td><td>{source}</td></tr>
</table>

<p style="font-weight:bold; margin:12px 0 4px;">Message</p>
<div class="msg">{message or '<em>(no message)</em>'}</div>

<p style="font-weight:bold; margin:16px 0 4px;">AI Qualification</p>
<table>
  <tr><td>Services Fit</td><td>{services}</td></tr>
  <tr><td>Urgency</td><td>{urgency}</td></tr>
  <tr><td>Company Size</td><td>{co_size}</td></tr>
  <tr><td>Decision Maker</td><td>{dm}</td></tr>
  <tr><td>Confidence</td><td>{conf_pct}</td></tr>
  <tr><td>Recommended Next Step</td><td>{next_step}</td></tr>
</table>

<a class="cta" href="{dashboard_url}">Open Approval Dashboard →</a>

<div class="footer">
  Klaravex Lead Alert · {ts} · Lead ID: {lead.id}
</div>

</body>
</html>"""


def _build_text(tier: str, score: float, lead: Lead, qual: dict) -> str:
    icon    = "🔥" if tier == "HOT" else "☀️"
    company = lead.company or "—"
    name    = lead.name or "—"
    email   = lead.email or "—"
    message = textwrap.shorten(lead.message or "", width=300, placeholder="…")
    services = ", ".join(qual.get("services_fit") or []) or "—"
    urgency  = qual.get("urgency") or "—"
    co_size  = qual.get("company_size_est") or "—"
    dm       = "Yes" if qual.get("decision_maker") else "No"
    next_step = qual.get("next_step") or "—"

    return f"""{icon} {tier} LEAD — Score: {int(score)}/100

CONTACT
  Name:    {name}
  Company: {company}
  Email:   {email}

MESSAGE
  {message}

AI QUALIFICATION
  Services Fit:    {services}
  Urgency:         {urgency}
  Company Size:    {co_size}
  Decision Maker:  {dm}
  Next Step:       {next_step}

Dashboard: https://api.klaravex.de/admin/

Lead ID: {lead.id}
"""


# ── Callback (Rückruf) alert builders ─────────────────────────────────────────
# Phone is the hero element. Anthony needs to call back — not email, not Calendly.

def _build_callback_subject(lead: Lead) -> str:
    name    = lead.name or "Unbekannt"
    company = lead.company or ""
    suffix  = f" @ {company}" if company else ""
    return f"📞 Rückruf angefordert — {name}{suffix}"


def _build_callback_html(lead: Lead, qual: dict, settings) -> str:
    name     = lead.name or "—"
    phone    = lead.phone or "—"
    company  = lead.company or "—"
    email    = lead.email or "—"
    message  = textwrap.shorten(lead.message or "", width=400, placeholder="…")
    cb_time  = getattr(lead, "preferred_callback_time", None) or "—"
    ts       = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    services  = ", ".join(qual.get("services_fit") or []) or "—"
    urgency   = (qual.get("urgency") or "—").replace("-", "–")
    co_size   = qual.get("company_size_est") or "—"
    next_step = qual.get("next_step") or "—"

    dashboard_url = "https://api.klaravex.de/admin/"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  body  {{ font-family: Arial, sans-serif; font-size: 14px; color: #1a1a1a;
           max-width: 640px; margin: 0 auto; padding: 24px; }}
  .badge {{ display: inline-block; background: #1565C0; color: #fff;
            font-weight: bold; font-size: 18px; padding: 8px 20px;
            border-radius: 4px; letter-spacing: 1px; }}
  .phone-hero {{ background: #E3F2FD; border: 2px solid #1565C0;
                 border-radius: 8px; padding: 20px 24px; margin: 20px 0;
                 text-align: center; }}
  .phone-hero .label {{ font-size: 13px; color: #555; text-transform: uppercase;
                        letter-spacing: 1px; margin-bottom: 6px; }}
  .phone-hero .number {{ font-size: 28px; font-weight: bold; color: #1565C0;
                         letter-spacing: 2px; }}
  .phone-hero .window {{ font-size: 13px; color: #444; margin-top: 8px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
  td    {{ padding: 8px 10px; border-bottom: 1px solid #eee; vertical-align: top; }}
  td:first-child {{ font-weight: bold; white-space: nowrap; width: 38%; color: #555; }}
  .msg  {{ background: #f9f9f9; border-left: 4px solid #1565C0;
           padding: 12px 14px; border-radius: 0 4px 4px 0;
           font-style: italic; color: #444; margin: 12px 0; }}
  .cta  {{ display: inline-block; margin-top: 20px; background: #1565C0;
           color: #fff; padding: 12px 24px; border-radius: 4px;
           text-decoration: none; font-weight: bold; font-size: 15px; }}
  .footer {{ color: #aaa; font-size: 11px; margin-top: 32px;
             border-top: 1px solid #eee; padding-top: 10px; }}
</style>
</head>
<body>

<div class="badge">📞 RÜCKRUF ANGEFORDERT</div>

<div class="phone-hero">
  <div class="label">Anrufen</div>
  <div class="number">{phone}</div>
  <div class="window">Bevorzugtes Zeitfenster: <strong>{cb_time}</strong></div>
</div>

<table>
  <tr><td>Name</td><td>{name}</td></tr>
  <tr><td>Unternehmen</td><td>{company}</td></tr>
  <tr><td>E-Mail</td><td>{f'<a href="mailto:{email}">{email}</a>' if email != "—" else "—"}</td></tr>
</table>

<p style="font-weight:bold; margin:12px 0 4px;">Nachricht</p>
<div class="msg">{message or '<em>(keine Nachricht)</em>'}</div>

{'<p style="font-weight:bold; margin:16px 0 4px;">AI Vorqualifizierung</p><table>'
 + f'<tr><td>Themen</td><td>{services}</td></tr>'
 + f'<tr><td>Dringlichkeit</td><td>{urgency}</td></tr>'
 + f'<tr><td>Unternehmensgröße</td><td>{co_size}</td></tr>'
 + f'<tr><td>Empfohlener nächster Schritt</td><td>{next_step}</td></tr>'
 + '</table>'
 if qual else ''}

<a class="cta" href="{dashboard_url}">Admin Dashboard →</a>

<div class="footer">
  Klaravex Rückruf-Alert · {ts} · Lead ID: {lead.id}
</div>

</body>
</html>"""


def _build_callback_text(lead: Lead, qual: dict) -> str:
    name    = lead.name or "—"
    phone   = lead.phone or "—"
    company = lead.company or "—"
    email   = lead.email or "—"
    message = textwrap.shorten(lead.message or "", width=400, placeholder="…")
    cb_time = getattr(lead, "preferred_callback_time", None) or "—"
    services  = ", ".join(qual.get("services_fit") or []) or "—"
    urgency   = qual.get("urgency") or "—"
    next_step = qual.get("next_step") or "—"

    return f"""📞 RÜCKRUF ANGEFORDERT

╔══════════════════════════════════╗
║  ANRUFEN: {phone:<24}║
║  Zeitfenster: {cb_time:<20}║
╚══════════════════════════════════╝

KONTAKT
  Name:        {name}
  Unternehmen: {company}
  E-Mail:      {email}

NACHRICHT
  {message or "(keine Nachricht)"}

AI VORQUALIFIZIERUNG
  Themen:    {services}
  Dringlichkeit: {urgency}
  Nächster Schritt: {next_step}

Dashboard: https://api.klaravex.de/admin/

Lead ID: {lead.id}
"""
