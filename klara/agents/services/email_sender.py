"""
app/services/email_sender.py
─────────────────────────────
Three async-safe email senders:

  send_transactional_email()              — MS Graph API from noreply@klaravex.de.
                                            Used for ALL transactional mail: lead alerts,
                                            booking invites, portal notices, reports,
                                            magic links, payment receipts, approvals.

  send_resend_email()                     — Resend API (httpx) for cold outreach from
                                            outreach.klaravex.de subdomain.
                                            Used ONLY for outreach_email + followup_nurture.
                                            Keeps main domain reputation clean.

  send_transactional_email_with_attachment() — MS Graph with base64 attachment.
                                            Used by InvoiceGeneratorAgent for PDF delivery.

  send_email()                            — Legacy SMTP path. Not used in production.
                                            Kept for reference only.

Usage:
    from klara.rarv.runtime.email_sender import send_transactional_email, send_resend_email
    ok = await send_transactional_email(settings, to_email="...", ...)
    ok = await send_resend_email(settings, to_email="...", ...)
"""
from __future__ import annotations

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

import httpx
import structlog

logger = structlog.get_logger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
MS_GRAPH_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
MS_GRAPH_SEND_URL  = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"


async def send_email(
    settings,
    *,
    to_email: str,
    to_name: str = "",
    subject: str,
    body_html: str,
    body_text: str,
    reply_to: str | None = None,
) -> bool:
    """
    Send a STARTTLS SMTP email in a thread executor so the async event loop
    is never blocked.

    Returns True on success, False on any failure (errors are logged but not
    re-raised — callers decide how to handle partial failure).
    """
    if not settings.smtp_user or not settings.smtp_password:
        logger.warning(
            "email_sender.skipped",
            reason="SMTP credentials not configured",
            to=to_email,
        )
        return False

    def _send_sync() -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr((settings.smtp_from_name, settings.smtp_from_email))
        msg["To"] = formataddr((to_name, to_email)) if to_name else to_email
        msg["Reply-To"] = reply_to or settings.smtp_from_email

        # Attach plain text first, HTML second (RFC 2046: last = preferred)
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from_email, [to_email], msg.as_string())

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _send_sync)
        logger.info("email_sender.sent", to=to_email, subject=subject)
        return True
    except smtplib.SMTPAuthenticationError as exc:
        logger.error("email_sender.auth_error", to=to_email, error=str(exc))
        return False
    except smtplib.SMTPException as exc:
        logger.error("email_sender.smtp_error", to=to_email, error=str(exc))
        return False
    except Exception as exc:
        logger.error("email_sender.error", to=to_email, error=str(exc))
        return False


async def _get_ms_graph_token(settings) -> str | None:
    """
    Acquire a client-credentials Bearer token from Azure AD.
    Returns the access_token string, or None if credentials are missing/invalid.
    """
    if not settings.ms_graph_configured:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                MS_GRAPH_TOKEN_URL.format(tenant_id=settings.ms_graph_tenant_id),
                data={
                    "grant_type":    "client_credentials",
                    "client_id":     settings.ms_graph_client_id,
                    "client_secret": settings.ms_graph_client_secret,
                    "scope":         "https://graph.microsoft.com/.default",
                },
            )
        if resp.status_code == 200:
            return resp.json().get("access_token")
        logger.error(
            "email_sender.ms_graph_token_error",
            status_code=resp.status_code,
            body=resp.text[:200],
        )
        return None
    except Exception as exc:
        logger.error("email_sender.ms_graph_token_exception", error=str(exc))
        return None


async def send_transactional_email(
    settings,
    *,
    to_email: str,
    to_name: str = "",
    subject: str,
    body_html: str,
    body_text: str,
    reply_to: str | None = None,
) -> bool:
    """
    Send a transactional email via MS Graph API from noreply@klaravex.de.

    Used for ALL non-outreach email: portal notices, magic links, payment receipts,
    approval alerts, reports, booking invites, project kickoffs, satisfaction surveys,
    contract renewals, and any other system-to-client or system-to-Anthony message.

    Returns True on delivery acceptance, False on any error.
    """
    token = await _get_ms_graph_token(settings)
    if not token:
        logger.warning(
            "email_sender.transactional_skipped",
            reason="MS Graph credentials not configured",
            to=to_email,
        )
        return False

    sender = settings.transactional_from_email  # noreply@klaravex.de

    to_recipient: dict = {"emailAddress": {"address": to_email}}
    if to_name:
        to_recipient["emailAddress"]["name"] = to_name

    message: dict = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": body_html},
        "toRecipients": [to_recipient],
    }
    if reply_to:
        message["replyTo"] = [{"emailAddress": {"address": reply_to}}]

    payload = {"message": message, "saveToSentItems": False}

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                MS_GRAPH_SEND_URL.format(sender=sender),
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type":  "application/json",
                },
            )

        if response.status_code == 202:
            logger.info(
                "email_sender.transactional_sent",
                to=to_email,
                subject=subject,
                sender=sender,
            )
            return True

        logger.error(
            "email_sender.transactional_error",
            to=to_email,
            status_code=response.status_code,
            body=response.text[:300],
        )
        return False

    except httpx.TimeoutException:
        logger.error("email_sender.transactional_timeout", to=to_email)
        return False
    except Exception as exc:
        logger.error("email_sender.transactional_exception", to=to_email, error=str(exc))
        return False


async def send_resend_email(
    settings,
    *,
    to_email: str,
    to_name: str = "",
    subject: str,
    body_html: str,
    body_text: str,
    reply_to: str | None = None,
) -> bool:
    """
    Send a cold outreach email via the Resend API.

    Uses the outreach subdomain (outreach.klaravex.de) to protect the
    main klaravex.de domain reputation.  The Resend API key must have
    the outreach domain verified.

    Returns True on delivery acceptance, False on any error.
    """
    if not settings.resend_configured:
        logger.warning(
            "email_sender.resend_skipped",
            reason="RESEND_API_KEY not configured",
            to=to_email,
        )
        return False

    from_address = (
        f"{settings.outreach_from_name} <{settings.outreach_from_email}>"
        if settings.outreach_from_name
        else settings.outreach_from_email
    )
    to_address = (
        f"{to_name} <{to_email}>" if to_name else to_email
    )

    payload: dict = {
        "from": from_address,
        "to": [to_address],
        "subject": subject,
        "html": body_html,
        "text": body_text,
    }
    if reply_to:
        payload["reply_to"] = [reply_to]

    # phase13-001: Circuit-breaker guard. After FAILURE_THRESHOLD consecutive
    # failures, short-circuit and return False — keeps the bool contract so
    # callers don't need to know about degradation.
    from klara.rarv.runtime.circuit_breaker import get_breaker
    breaker = get_breaker("resend")
    if not breaker.can_attempt():
        logger.warning("email_sender.resend_breaker_open", to=to_email)
        return False

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                RESEND_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
            )

        if response.status_code in (200, 201):
            breaker.record_success()
            data = response.json()
            logger.info(
                "email_sender.resend_sent",
                to=to_email,
                subject=subject,
                resend_id=data.get("id"),
            )
            return True

        breaker.record_failure()
        logger.error(
            "email_sender.resend_error",
            to=to_email,
            status_code=response.status_code,
            body=response.text[:300],
        )
        return False

    except httpx.TimeoutException:
        breaker.record_failure()
        logger.error("email_sender.resend_timeout", to=to_email)
        return False
    except Exception as exc:
        breaker.record_failure()
        logger.error("email_sender.resend_exception", to=to_email, error=str(exc))
        return False


async def send_transactional_email_with_attachment(
    settings,
    *,
    to_email: str,
    to_name: str = "",
    subject: str,
    body_html: str,
    body_text: str,
    attachment_bytes: bytes,
    attachment_filename: str,
    reply_to: str | None = None,
) -> bool:
    """
    Send a transactional email with a single binary attachment via MS Graph API.

    Used by InvoiceGeneratorAgent to deliver the PDF invoice to the client
    after P3 approval.  Sends from noreply@klaravex.de.

    Returns True on delivery acceptance, False on any error.
    """
    import base64

    token = await _get_ms_graph_token(settings)
    if not token:
        logger.warning(
            "email_sender.attachment_skipped",
            reason="MS Graph credentials not configured",
            to=to_email,
        )
        return False

    sender = settings.transactional_from_email  # noreply@klaravex.de

    to_recipient: dict = {"emailAddress": {"address": to_email}}
    if to_name:
        to_recipient["emailAddress"]["name"] = to_name

    encoded = base64.b64encode(attachment_bytes).decode("ascii")

    message: dict = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": body_html},
        "toRecipients": [to_recipient],
        "attachments": [
            {
                "@odata.type":  "#microsoft.graph.fileAttachment",
                "name":         attachment_filename,
                "contentBytes": encoded,
            }
        ],
    }
    if reply_to:
        message["replyTo"] = [{"emailAddress": {"address": reply_to}}]

    payload = {"message": message, "saveToSentItems": False}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                MS_GRAPH_SEND_URL.format(sender=sender),
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type":  "application/json",
                },
            )

        if response.status_code == 202:
            logger.info(
                "email_sender.attachment_sent",
                to=to_email,
                subject=subject,
                filename=attachment_filename,
                size_bytes=len(attachment_bytes),
            )
            return True

        logger.error(
            "email_sender.attachment_error",
            to=to_email,
            status_code=response.status_code,
            body=response.text[:300],
        )
        return False

    except httpx.TimeoutException:
        logger.error("email_sender.attachment_timeout", to=to_email)
        return False
    except Exception as exc:
        logger.error("email_sender.attachment_exception", to=to_email, error=str(exc))
        return False
