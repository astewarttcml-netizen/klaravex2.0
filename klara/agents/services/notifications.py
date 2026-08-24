"""
app/services/notifications.py
───────────────────────────────
Task 5.3 — Transactional email notifications via Resend API (httpx).

THREE event hooks:
  on_lead_created(settings, lead)          → confirmation to the prospect
  on_project_status_updated(settings, ...) → portal update notice to client
  on_payment_succeeded(settings, ...)      → payment receipt to client

Design decisions:
  - All sends are fire-and-forget: try/except wraps every call.
  - Failures are logged as notification.send_failed but NEVER raised.
  - Sends from noreply@klaravex.de (transactional domain, NOT outreach subdomain).
  - This module NEVER sends cold outreach — use OutreachEmailAgent for that.
  - Uses httpx async directly (no resend pip package required).
"""
from __future__ import annotations

from typing import Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Transactional sender — routed via outreach.klaravex.de (the one Resend-verified domain).
# Upgrade Resend plan and verify klaravex.de to switch back to noreply@klaravex.de.
_FROM_ADDR = "Klaravex <noreply@outreach.klaravex.de>"

# Portal URL for "view in portal" links
_PORTAL_URL = "https://klaravex.de/portal"

# Resend API endpoint
_RESEND_API_URL = "https://api.resend.com/emails"


# ---------------------------------------------------------------------------
# Internal send helper
# ---------------------------------------------------------------------------

async def _send(
    settings,
    to_email: str,
    to_name: Optional[str],
    subject: str,
    html: str,
    text: str,
    event_name: str,
) -> None:
    """Non-raising async wrapper. Gracefully no-ops when Resend is not configured."""
    if not settings.resend_configured:
        logger.warning(
            "notification.send_failed",
            notification_event=event_name,
            reason="resend_api_key_not_configured",
        )
        return
    recipient = f"{to_name} <{to_email}>" if to_name else to_email
    payload = {
        "from": _FROM_ADDR,
        "to": [recipient],
        "subject": subject,
        "html": html,
        "text": text,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _RESEND_API_URL,
                json=payload,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            )
        if resp.status_code in (200, 201):
            data = resp.json()
            email_id = data.get("id")
            logger.info(
                "notification.sent",
                notification_event=event_name,
                email_id=email_id,
                to_domain=to_email.split("@")[-1] if "@" in to_email else "unknown",
            )
        else:
            logger.warning(
                "notification.send_failed",
                notification_event=event_name,
                status_code=resp.status_code,
                body=resp.text[:200],
            )
    except httpx.TimeoutException:
        logger.error("notification.send_failed", notification_event=event_name, reason="timeout")
    except Exception as exc:
        logger.error("notification.send_failed", notification_event=event_name, error=str(exc))


# ---------------------------------------------------------------------------
# 5.3.1 — Contact confirmation (on_lead_created)
# ---------------------------------------------------------------------------

async def on_lead_created(settings, lead) -> None:
    """
    Send a friendly confirmation to the prospect after their form submission.

    Called from app/api/leads.py immediately after the lead is saved.
    Does NOT raise on failure.
    """
    to_email = lead.email
    to_name = lead.name

    if not to_email:
        logger.warning("notification.on_lead_created.no_email", lead_id=lead.id)
        return

    subject = "We received your message — Klaravex"

    html = f"""
<html>
<body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
  <p>Hi {to_name or "there"},</p>
  <p>
    Thank you for reaching out to <strong>Klaravex</strong>.
    We have received your message and will get back to you within
    <strong>1 business day</strong>.
  </p>
  <p>
    If your request is urgent, you can reach us directly at
    <a href="mailto:contact@klaravex.de">contact@klaravex.de</a>.
  </p>
  <p>We look forward to speaking with you.</p>
  <p>Best regards,<br>
  The Klaravex Team<br>
  <a href="https://klaravex.de">klaravex.de</a>
  </p>
  <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
  <p style="font-size: 11px; color: #999;">
    You are receiving this email because you submitted a contact form at klaravex.de.
    If you did not make this request, please disregard this message.
  </p>
</body>
</html>
"""

    text = (
        f"Hi {to_name or 'there'},\n\n"
        "Thank you for reaching out to Klaravex. We have received your message "
        "and will get back to you within 1 business day.\n\n"
        "If your request is urgent, contact us at: contact@klaravex.de\n\n"
        "Best regards,\nThe Klaravex Team\nhttps://klaravex.de"
    )

    await _send(settings, to_email, to_name, subject, html, text, "on_lead_created")


# ---------------------------------------------------------------------------
# 5.3.2 — Portal update notice (on_project_status_updated)
# ---------------------------------------------------------------------------

async def on_project_status_updated(
    settings,
    client_email: str,
    client_name: Optional[str],
    project_title: str,
    new_status: str,
    next_action: Optional[str] = None,
) -> None:
    """
    Notify the client when their project status changes in the portal.

    Parameters match the ProjectStatusEvent payload.
    Does NOT raise on failure.
    """
    if not client_email:
        logger.warning("notification.on_project_status_updated.no_email")
        return

    subject = f"Your project has been updated — Klaravex"

    next_action_block_html = (
        f"<p><strong>Next step:</strong> {next_action}</p>" if next_action else ""
    )
    next_action_block_text = (
        f"Next step: {next_action}\n\n" if next_action else ""
    )

    html = f"""
<html>
<body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
  <p>Hi {client_name or 'there'},</p>
  <p>
    Your project <strong>{project_title}</strong> has been updated.
  </p>
  <p>
    <strong>New status:</strong> {new_status}
  </p>
  {next_action_block_html}
  <p>
    <a href="{_PORTAL_URL}" style="
      display: inline-block;
      padding: 10px 20px;
      background: #1a56db;
      color: #fff;
      text-decoration: none;
      border-radius: 4px;
    ">View in Client Portal</a>
  </p>
  <p>Best regards,<br>Klaravex</p>
  <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
  <p style="font-size: 11px; color: #999;">
    To opt out of project notifications, please contact contact@klaravex.de.
  </p>
</body>
</html>
"""

    text = (
        f"Hi {client_name or 'there'},\n\n"
        f"Your project '{project_title}' has been updated.\n"
        f"New status: {new_status}\n\n"
        f"{next_action_block_text}"
        f"View in portal: {_PORTAL_URL}\n\n"
        "Best regards,\nKlaravex"
    )

    await _send(
        settings,
        client_email,
        client_name,
        subject,
        html,
        text,
        "on_project_status_updated",
    )


# ---------------------------------------------------------------------------
# 5.3.3 — Payment receipt (on_payment_succeeded)
# ---------------------------------------------------------------------------

async def on_payment_succeeded(
    settings,
    client_email: str,
    client_name: Optional[str],
    invoice_reference: str,
    amount: float,
    currency: str = "EUR",
) -> None:
    """
    Send a payment receipt after a successful Stripe payment.

    Wired into app/api/webhooks_stripe.py on PaymentStatus.succeeded.
    Does NOT raise on failure.
    """
    if not client_email:
        logger.warning(
            "notification.on_payment_succeeded.no_email",
            invoice_reference=invoice_reference,
        )
        return

    subject = f"Payment received — Invoice {invoice_reference}"

    # Format amount: e.g. 1250.00 EUR → "1,250.00 EUR"
    try:
        amount_formatted = f"{amount:,.2f} {currency.upper()}"
    except (TypeError, ValueError):
        amount_formatted = f"{amount} {currency}"

    html = f"""
<html>
<body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
  <p>Hi {client_name or 'there'},</p>
  <p>
    We have received your payment. Thank you!
  </p>
  <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
    <tr style="background: #f9fafb;">
      <td style="padding: 8px 12px; border: 1px solid #e5e7eb;"><strong>Invoice</strong></td>
      <td style="padding: 8px 12px; border: 1px solid #e5e7eb;">{invoice_reference}</td>
    </tr>
    <tr>
      <td style="padding: 8px 12px; border: 1px solid #e5e7eb;"><strong>Amount</strong></td>
      <td style="padding: 8px 12px; border: 1px solid #e5e7eb;">{amount_formatted}</td>
    </tr>
    <tr style="background: #f9fafb;">
      <td style="padding: 8px 12px; border: 1px solid #e5e7eb;"><strong>Status</strong></td>
      <td style="padding: 8px 12px; border: 1px solid #e5e7eb; color: #16a34a;">Paid</td>
    </tr>
  </table>
  <p>
    You can view your invoice and project details in the client portal:
  </p>
  <p>
    <a href="{_PORTAL_URL}" style="
      display: inline-block;
      padding: 10px 20px;
      background: #1a56db;
      color: #fff;
      text-decoration: none;
      border-radius: 4px;
    ">Open Client Portal</a>
  </p>
  <p>Best regards,<br>Klaravex<br>
  <a href="mailto:contact@klaravex.de">contact@klaravex.de</a>
  </p>
  <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
  <p style="font-size: 11px; color: #999;">
    This is an automated payment receipt from klaravex.de.
    For questions about your invoice, reply to contact@klaravex.de.
  </p>
</body>
</html>
"""

    text = (
        f"Hi {client_name or 'there'},\n\n"
        "We have received your payment. Thank you!\n\n"
        f"Invoice:  {invoice_reference}\n"
        f"Amount:   {amount_formatted}\n"
        f"Status:   Paid\n\n"
        f"View in portal: {_PORTAL_URL}\n\n"
        "Best regards,\nKlaravex\ncontact@klaravex.de"
    )

    await _send(
        settings,
        client_email,
        client_name,
        subject,
        html,
        text,
        "on_payment_succeeded",
    )
