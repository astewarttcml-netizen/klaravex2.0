"""
app/services/support_instructions_email.py
────────────────────────────────────────────
Sends post-payment remote-session instructions to the consumer.

Fired by the Stripe webhook on checkout.session.completed for
source=consumer_pipeline. Confirms payment and tells the client what
to expect next:

  1. Technician will email a Splashtop SOS session link (generated in Atera)
  2. Client clicks the link — no app install required, temporary runner only
  3. Client allows screen sharing and technician connects

The actual Splashtop link is NOT included here — it is generated per-session
by the technician in Atera and emailed directly to the client.

The Vapi phone callback (vapi_outbound.py) remains an optional
bonus channel — it fires only if the consumer provided a phone number.
"""
from __future__ import annotations

import structlog

from app.services.email_sender import send_transactional_email

logger = structlog.get_logger(__name__)


_SUBJECT_EN = "Your IT Support Session is Ready — Ticket #{ticket_number}"
_SUBJECT_DE = "Ihre IT-Support-Sitzung ist bereit — Ticket #{ticket_number}"

_HTML_EN = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Support Session Ready</title>
<style>
  body {{ margin:0; padding:0; background:#f4f6f9; font-family:Arial,Helvetica,sans-serif; color:#1a1a2e; }}
  .wrap {{ max-width:560px; margin:32px auto; background:#fff; border-radius:8px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,.08); }}
  .header {{ background:#1a1a2e; padding:28px 32px; }}
  .header h1 {{ margin:0; color:#fff; font-size:20px; }}
  .header p {{ margin:4px 0 0; color:#aab4cc; font-size:13px; }}
  .body {{ padding:28px 32px; }}
  .body p {{ margin:0 0 16px; font-size:14px; line-height:1.6; }}
  .step {{ display:flex; align-items:flex-start; margin-bottom:16px; }}
  .step-num {{ min-width:28px; height:28px; background:#1a1a2e; color:#fff; border-radius:50%;
               font-size:13px; font-weight:700; display:flex; align-items:center;
               justify-content:center; margin-right:12px; margin-top:1px; }}
  .step-text {{ font-size:14px; line-height:1.5; }}
  .btn {{ display:inline-block; margin:4px 0 20px; padding:12px 28px; background:#e63946;
          color:#fff; border-radius:6px; text-decoration:none; font-weight:700; font-size:14px; }}
  .divider {{ border:none; border-top:1px solid #e8eaf0; margin:20px 0; }}
  .alt {{ background:#f8f9fc; border-radius:6px; padding:16px 20px; font-size:13px; line-height:1.5; color:#555; }}
  .footer {{ background:#f4f6f9; padding:16px 32px; font-size:11px; color:#999; text-align:center; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <h1>Klaravex Remote IT Support</h1>
    <p>Ticket #{ticket_number} &nbsp;·&nbsp; {customer_name}</p>
  </div>
  <div class="body">
    <p>Hi {first_name},</p>
    <p>Payment confirmed — thank you! Here's what happens next:</p>

    <div class="step">
      <div class="step-num">1</div>
      <div class="step-text">
        <strong>Watch your inbox.</strong> Your Klaravex technician is preparing your
        remote session and will email you a <strong>Splashtop SOS link</strong> within
        minutes — we're available 24 hours a day.
      </div>
    </div>

    <div class="step">
      <div class="step-num">2</div>
      <div class="step-text">
        <strong>Click the link.</strong> A small, temporary connection app will download
        and run automatically — no installation or account needed.
      </div>
    </div>

    <div class="step">
      <div class="step-num">3</div>
      <div class="step-text">
        <strong>Allow screen sharing</strong> when prompted. Your technician will
        connect straight away and start working on your issue.
      </div>
    </div>

    <p style="font-size:13px;color:#555;"><strong>Issue:</strong> {problem}<br>
    <strong>Device:</strong> {device}</p>

    <hr class="divider">

    <div class="alt">
      <strong>Prefer to schedule a specific time?</strong><br>
      No problem — just reply to this email and we'll arrange a time that works for you.
      There's no rush; your ticket stays open until the issue is resolved.
    </div>
  </div>
  <div class="footer">
    Klaravex &nbsp;·&nbsp; Remote IT Support &nbsp;·&nbsp; noreply@klaravex.de<br>
    Reply to this email to reach the Klaravex Support Team directly.
  </div>
</div>
</body>
</html>
"""

_TEXT_EN = """\
Hi {first_name},

Payment confirmed — thank you! Ticket #{ticket_number} is open for your {device}.

WHAT HAPPENS NEXT
──────────────────

1. Watch your inbox — your Klaravex technician is preparing your remote session
   and will email you a Splashtop SOS link within minutes.
   We're available 24 hours a day.

2. Click the link. A small, temporary connection app downloads and runs
   automatically — no installation or account needed.

3. Allow screen sharing when prompted. Your technician will connect straight
   away and start working on your issue.

Issue: {problem}
Device: {device}

Prefer to pick a specific time? Just reply and we'll arrange it — no rush,
your ticket stays open until the issue is resolved.

──
Klaravex · Remote IT Support
Reply to reach the Klaravex Support Team directly.
"""

_HTML_DE = """\
<!DOCTYPE html>
<html lang="de">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Support-Sitzung bereit</title>
<style>
  body {{ margin:0; padding:0; background:#f4f6f9; font-family:Arial,Helvetica,sans-serif; color:#1a1a2e; }}
  .wrap {{ max-width:560px; margin:32px auto; background:#fff; border-radius:8px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,.08); }}
  .header {{ background:#1a1a2e; padding:28px 32px; }}
  .header h1 {{ margin:0; color:#fff; font-size:20px; }}
  .header p {{ margin:4px 0 0; color:#aab4cc; font-size:13px; }}
  .body {{ padding:28px 32px; }}
  .body p {{ margin:0 0 16px; font-size:14px; line-height:1.6; }}
  .step {{ display:flex; align-items:flex-start; margin-bottom:16px; }}
  .step-num {{ min-width:28px; height:28px; background:#1a1a2e; color:#fff; border-radius:50%;
               font-size:13px; font-weight:700; display:flex; align-items:center;
               justify-content:center; margin-right:12px; margin-top:1px; }}
  .step-text {{ font-size:14px; line-height:1.5; }}
  .btn {{ display:inline-block; margin:4px 0 20px; padding:12px 28px; background:#e63946;
          color:#fff; border-radius:6px; text-decoration:none; font-weight:700; font-size:14px; }}
  .divider {{ border:none; border-top:1px solid #e8eaf0; margin:20px 0; }}
  .alt {{ background:#f8f9fc; border-radius:6px; padding:16px 20px; font-size:13px; line-height:1.5; color:#555; }}
  .footer {{ background:#f4f6f9; padding:16px 32px; font-size:11px; color:#999; text-align:center; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <h1>Klaravex Remote IT-Support</h1>
    <p>Ticket #{ticket_number} &nbsp;·&nbsp; {customer_name}</p>
  </div>
  <div class="body">
    <p>Hallo {first_name},</p>
    <p>Ihre Zahlung wurde bestätigt — vielen Dank! So geht es weiter:</p>

    <div class="step">
      <div class="step-num">1</div>
      <div class="step-text">
        <strong>Prüfen Sie Ihr Postfach.</strong> Ihr Klaravex-Techniker bereitet Ihre
        Remote-Sitzung vor und schickt Ihnen in Kürze einen <strong>Splashtop SOS-Link</strong>
        per E-Mail — wir sind 24 Stunden am Tag für Sie da.
      </div>
    </div>

    <div class="step">
      <div class="step-num">2</div>
      <div class="step-text">
        <strong>Klicken Sie auf den Link.</strong> Eine kleine, temporäre Verbindungs-App
        wird automatisch heruntergeladen und gestartet — keine Installation oder
        Konto erforderlich.
      </div>
    </div>

    <div class="step">
      <div class="step-num">3</div>
      <div class="step-text">
        <strong>Erlauben Sie den Bildschirmzugriff</strong>, wenn Sie dazu aufgefordert werden.
        Ihr Techniker verbindet sich sofort und beginnt mit der Arbeit.
      </div>
    </div>

    <p style="font-size:13px;color:#555;"><strong>Problem:</strong> {problem}<br>
    <strong>Gerät:</strong> {device}</p>

    <hr class="divider">

    <div class="alt">
      <strong>Möchten Sie lieber einen festen Termin vereinbaren?</strong><br>
      Kein Problem — antworten Sie einfach auf diese E-Mail und wir finden einen passenden Zeitpunkt.
      Ihr Ticket bleibt offen, bis das Problem gelöst ist.
    </div>
  </div>
  <div class="footer">
    Klaravex &nbsp;·&nbsp; Remote IT-Support &nbsp;·&nbsp; noreply@klaravex.de<br>
    Antworten Sie auf diese E-Mail, um das Klaravex Support-Team direkt zu erreichen.
  </div>
</div>
</body>
</html>
"""

_TEXT_DE = """\
Hallo {first_name},

Ihre Zahlung wurde bestätigt — vielen Dank! Ticket #{ticket_number} ist für Ihr {device} geöffnet.

SO GEHT ES WEITER
──────────────────

1. Prüfen Sie Ihr Postfach — Ihr Klaravex-Techniker bereitet Ihre Remote-Sitzung vor
   und schickt Ihnen in Kürze einen Splashtop SOS-Link per E-Mail.
   Wir sind 24 Stunden am Tag für Sie da.

2. Klicken Sie auf den Link. Eine kleine, temporäre App wird automatisch
   heruntergeladen und gestartet — keine Installation oder Konto erforderlich.

3. Erlauben Sie den Bildschirmzugriff, wenn Sie dazu aufgefordert werden.
   Ihr Techniker verbindet sich sofort und beginnt mit der Arbeit.

Problem: {problem}
Gerät: {device}

Möchten Sie lieber einen festen Termin? Antworten Sie einfach — kein Stress,
Ihr Ticket bleibt offen, bis das Problem gelöst ist.

──
Klaravex · Remote IT-Support
Antworten Sie auf diese E-Mail, um das Klaravex Support-Team direkt zu erreichen.
"""


async def send_support_instructions_email(
    settings,
    *,
    customer_email: str,
    customer_name: str,
    device: str,
    problem: str,
    ticket_number: str,
    language: str = "en",
) -> bool:
    """
    Send post-payment Splashtop SOS instructions to the consumer.

    Called by the Stripe webhook after checkout.session.completed
    for source=consumer_pipeline. Tells the client to watch for the
    Splashtop SOS link that the technician will send separately via Atera.
    Uses the MS Graph transactional sender (noreply@klaravex.de).

    Returns True on successful delivery, False on any error.
    """
    first_name = customer_name.split()[0] if customer_name else "there"
    de = language == "de"

    subject = (_SUBJECT_DE if de else _SUBJECT_EN).format(ticket_number=ticket_number)
    html = (_HTML_DE if de else _HTML_EN).format(
        ticket_number=ticket_number,
        customer_name=customer_name or customer_email,
        first_name=first_name,
        device=device or "your device",
        problem=problem or "the issue you reported",
    )
    text = (_TEXT_DE if de else _TEXT_EN).format(
        ticket_number=ticket_number,
        first_name=first_name,
        device=device or "your device",
        problem=problem or "the issue you reported",
    )

    ok = await send_transactional_email(
        settings,
        to_email=customer_email,
        to_name=customer_name,
        subject=subject,
        body_html=html,
        body_text=text,
        reply_to="support@klaravex.de",
    )

    if ok:
        logger.info(
            "support_instructions_email.sent",
            ticket_number=ticket_number,
            to=customer_email,
            language=language,
        )
    else:
        logger.error(
            "support_instructions_email.failed",
            ticket_number=ticket_number,
            to=customer_email,
        )

    return ok
