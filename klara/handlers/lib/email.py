"""Shared async email helper — pluggable backend dispatch.

Backends (selected via EMAIL_PROVIDER env var):
  - "graph"  (default) — Microsoft Graph sendMail (M365 client-credentials)
  - "smtp"             — plain SMTP submission (587 STARTTLS) for dev / fallback

send_email() never raises: backend failures are logged and swallowed so
upstream business flows are not coupled to mailbox availability.

T14.2 spec (HANDOFF A2):
  - Graph backend exists in lib/email.py
  - EMAIL_PROVIDER=graph selects Graph; unset (or unknown) falls back to
    legacy SMTP submission so dev environments without an Entra app
    registration can still deliver magic links.
"""

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any

import httpx

log = logging.getLogger("klaravex.email")

# ──────────────────────────────────────────────────────────────────────────────
# Backend selection
# ──────────────────────────────────────────────────────────────────────────────

EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "graph").strip().lower()
_VALID_PROVIDERS = ("graph", "smtp")

# ──────────────────────────────────────────────────────────────────────────────
# Microsoft Graph backend
# ──────────────────────────────────────────────────────────────────────────────

GRAPH_TENANT_ID = os.environ.get("MS_GRAPH_TENANT_ID", "")
GRAPH_CLIENT_ID = os.environ.get("MS_GRAPH_CLIENT_ID", "")
GRAPH_CLIENT_SECRET = os.environ.get("MS_GRAPH_CLIENT_SECRET", "")
GRAPH_FROM_ADDRESS = os.environ.get("MS_GRAPH_SENDER_EMAIL", "support@klaravex.com")

_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_SEND_URL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"

# ──────────────────────────────────────────────────────────────────────────────
# SMTP backend (fallback)
# ──────────────────────────────────────────────────────────────────────────────

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM_ADDRESS = os.environ.get(
    "SMTP_FROM_ADDRESS",
    GRAPH_FROM_ADDRESS or "support@klaravex.com",
)
SMTP_STARTTLS = os.environ.get("SMTP_STARTTLS", "true").strip().lower() != "false"


def _resolve_provider() -> str:
    """Return the active provider name, falling back to 'graph' for unknown values."""
    if EMAIL_PROVIDER in _VALID_PROVIDERS:
        return EMAIL_PROVIDER
    log.warning(
        "EMAIL_PROVIDER=%r is not one of %s; falling back to 'graph'",
        EMAIL_PROVIDER, _VALID_PROVIDERS,
    )
    return "graph"


_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0.0}


async def _get_token() -> str:
    """Fetch (or reuse a cached) OAuth2 client-credentials token from Microsoft identity platform."""
    import time

    now = time.monotonic()
    if _token_cache["access_token"] and now < _token_cache["expires_at"]:
        return _token_cache["access_token"]
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            _TOKEN_URL.format(tenant=GRAPH_TENANT_ID),
            data={
                "client_id": GRAPH_CLIENT_ID,
                "client_secret": GRAPH_CLIENT_SECRET,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )
        r.raise_for_status()
        data = r.json()
        _token_cache["access_token"] = data["access_token"]
        _token_cache["expires_at"] = now + max(int(data.get("expires_in", 3600)) - 60, 0)
        return _token_cache["access_token"]


async def _send_via_graph(
    recipients: list[str],
    subject: str,
    body: str,
    html: str | None,
) -> bool:
    """Return True on 202 Accepted, False on any other outcome."""
    if not (GRAPH_TENANT_ID and GRAPH_CLIENT_ID and GRAPH_CLIENT_SECRET):
        log.warning("Microsoft Graph credentials not set; cannot send to=%s", recipients)
        return False
    content_type = "HTML" if html else "Text"
    content_value = html if html else body
    payload: dict[str, Any] = {
        "message": {
            "subject": subject,
            "body": {"contentType": content_type, "content": content_value},
            "toRecipients": [{"emailAddress": {"address": r}} for r in recipients],
        },
        "saveToSentItems": False,
    }
    token = await _get_token()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            _SEND_URL.format(sender=GRAPH_FROM_ADDRESS),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        if r.status_code == 202:
            log.info("email sent via Graph to=%s subject=%s", recipients, subject)
            return True
        log.warning("Graph sendMail failed: %s %s", r.status_code, r.text)
        return False


def _build_smtp_message(
    recipients: list[str],
    subject: str,
    body: str,
    html: str | None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = SMTP_FROM_ADDRESS
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _send_via_smtp_sync(
    recipients: list[str],
    subject: str,
    body: str,
    html: str | None,
) -> bool:
    """Synchronous SMTP submission. Runs in a thread when called from async."""
    if not SMTP_HOST:
        log.warning("SMTP_HOST not set; cannot send to=%s", recipients)
        return False
    msg = _build_smtp_message(recipients, subject, body, html)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
        s.ehlo()
        if SMTP_STARTTLS:
            s.starttls()
            s.ehlo()
        if SMTP_USERNAME and SMTP_PASSWORD:
            s.login(SMTP_USERNAME, SMTP_PASSWORD)
        s.send_message(msg)
    log.info("email sent via SMTP to=%s subject=%s", recipients, subject)
    return True


async def _send_via_smtp(
    recipients: list[str],
    subject: str,
    body: str,
    html: str | None,
) -> bool:
    import asyncio
    return await asyncio.to_thread(
        _send_via_smtp_sync, recipients, subject, body, html,
    )


async def send_email(
    to: str | list[str],
    subject: str,
    body: str,
    html: str | None = None,
) -> None:
    """Send an email via the configured backend. Logs and returns on failure — never raises."""
    recipients = [to] if isinstance(to, str) else to
    provider = _resolve_provider()
    try:
        if provider == "smtp":
            await _send_via_smtp(recipients, subject, body, html)
        else:
            await _send_via_graph(recipients, subject, body, html)
    except Exception as e:  # noqa: BLE001
        log.warning("email failed to=%s provider=%s: %s", recipients, provider, e)
