"""
Klaravex Smartlead reply-webhook handler — drop-in FastAPI router.

Mount with:
    from infra.klara.handlers.smartlead_webhook import router as smartlead_router
    app.include_router(smartlead_router, prefix="/api/v1/smartlead")

Smartlead reply webhook payload (representative fields):
    {
      "event": "email_reply_received",
      "campaign_id": 123,
      "campaign_name": "KLX-01",
      "lead": { "id": ..., "email": "...", "first_name": "...", "company_name": "...",
                "linkedin_url": "...", "custom_fields": {...} },
      "reply": { "subject": "...", "text": "...", "html": "...", "received_at": "..." }
    }
"""

import hashlib
import hmac
import os
import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request

from .lib import tickets as tickets_lib
from .lib.email import send_email

log = logging.getLogger("klaravex.smartlead_webhook")
router = APIRouter()

ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
APOLLO_KEY = os.environ.get("APOLLO_API_KEY", "")


def _verify_smartlead_signature(body: bytes, signature: str | None) -> None:
    secret = os.environ.get("SMARTLEAD_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="smartlead webhook secret not configured")
    if not signature:
        raise HTTPException(status_code=401, detail="missing signature")
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="invalid signature")


async def _enrich_via_apollo(email: str) -> dict[str, Any] | None:
    if not APOLLO_KEY or not email:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.apollo.io/v1/people/match",
                headers={"X-Api-Key": APOLLO_KEY, "Content-Type": "application/json"},
                json={"email": email, "reveal_personal_emails": False, "reveal_phone_number": False},
            )
            if r.status_code == 200:
                return r.json().get("person")
    except Exception as e:  # noqa: BLE001
        log.warning("apollo enrich failed: %s", e)
    return None


async def _send_telegram(text: str) -> None:
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT):
        return
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": text},
        )


@router.post("/webhook", status_code=202)
async def smartlead_webhook(request: Request) -> dict[str, str]:
    raw = await request.body()
    _verify_smartlead_signature(raw, request.headers.get("X-Smartlead-Signature"))
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")

    event = (payload.get("event") or payload.get("event_type") or "unknown").lower()
    lead = payload.get("lead") or {}
    email = lead.get("email") or ""
    campaign = payload.get("campaign_name") or payload.get("campaign_id") or "—"

    # Log every event
    log.info(
        "smartlead event | event=%s campaign=%s email=%s lead_first=%s payload_keys=%s",
        event, campaign, email, lead.get("first_name", ""),
        sorted(payload.keys()),
    )

    # Only alert on replies
    if event not in {"email_reply_received"}:
        return {"status": "logged", "event": event}

    reply = payload.get("reply") or {}
    enrichment = await _enrich_via_apollo(email)

    title = (enrichment or {}).get("title") or "—"
    company = lead.get("company_name") or (enrichment or {}).get("organization", {}).get("name") or "—"
    linkedin = lead.get("linkedin_url") or (enrichment or {}).get("linkedin_url") or "—"

    subject = f"[Klaravex Reply] {campaign} — {lead.get('first_name','')} @ {company}".strip()
    body = (
        f"Campaign: {campaign}\n"
        f"From:     {lead.get('first_name','')} {lead.get('last_name','')} <{email}>\n"
        f"Title:    {title}\n"
        f"Company:  {company}\n"
        f"LinkedIn: {linkedin}\n"
        f"Received: {reply.get('received_at','—')}\n\n"
        f"Reply:\n{(reply.get('text') or reply.get('html') or '')[:4000]}\n"
    )

    ticket_id: str | None = None
    if email:
        try:
            ticket_id = await tickets_lib.create_ticket(
                client_email=email,
                subject=f"Outbound reply: {campaign} — {company}",
                severity="high",
                status="open",
                source="smartlead",
                summary=(reply.get("text") or reply.get("html") or "")[:500],
                segment_hint="b2b",
                metadata={
                    "campaign": str(campaign),
                    "first_name": lead.get("first_name"),
                    "last_name": lead.get("last_name"),
                    "title": title,
                    "company": company,
                    "linkedin": linkedin,
                    "received_at": reply.get("received_at"),
                },
            )
        except Exception as e:  # noqa: BLE001
            log.warning("smartlead ticket persistence failed (continuing): %s", e)

    try:
        await send_email(ALERT_EMAIL, subject, body + (f"\nTicket: {ticket_id}\n" if ticket_id else ""))
        await _send_telegram(f"{subject}\n\n{body[:1500]}")
    except Exception as e:  # noqa: BLE001
        log.exception("smartlead alert dispatch failed: %s", e)
    return {"status": "ok", "ticket_id": ticket_id or ""}
