"""
Klaravex Calendly webhook handler — drop-in FastAPI router.

Handles invitee.created and invitee.canceled events. Schedules a pre-meeting
brief 1 hour before the call (the scheduler hook is left as a TODO since it
depends on which scheduler the Klara AI backend uses — APScheduler, Celery beat,
or just a cron tick). The webhook itself returns 200 immediately.

Mount with:
    from infra.klara.handlers.calendly_webhook import router as calendly_router
    app.include_router(calendly_router, prefix="/api/v1/calendly")
"""

import hashlib
import hmac
import os
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request

from .lib import tickets as tickets_lib
from .lib.db import get_pool
from .lib.email import send_email

log = logging.getLogger("klaravex.calendly_webhook")
router = APIRouter()

ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

CALENDLY_SIGNING_KEY = os.environ.get("CALENDLY_WEBHOOK_SIGNING_KEY", "")
CALENDLY_SIG_TOLERANCE_SECONDS = int(os.environ.get("CALENDLY_SIG_TOLERANCE_SECONDS", "300"))


def _parse_calendly_signature(header: str) -> tuple[str, str] | None:
    """Parse 'Calendly-Webhook-Signature' header of form 't=<ts>,v1=<sig>'."""
    parts: dict[str, str] = {}
    for chunk in header.split(","):
        if "=" not in chunk:
            continue
        k, _, v = chunk.partition("=")
        parts[k.strip()] = v.strip()
    ts = parts.get("t")
    sig = parts.get("v1")
    if not ts or not sig:
        return None
    return ts, sig


def _verify_calendly_signature(raw_body: bytes, sig_header: str | None) -> None:
    """Reject requests without a valid HMAC-SHA256 signature.

    V5 (pentest 2026-06-12) — Calendly signs every webhook with the signing
    key generated when the subscription was created. If CALENDLY_WEBHOOK_SIGNING_KEY
    is unset we fail closed (503) rather than skip verification — anything
    else lets an attacker bypass by posting before the key is provisioned.
    """
    if not CALENDLY_SIGNING_KEY:
        raise HTTPException(status_code=503, detail="webhook verification not configured")
    if not sig_header:
        raise HTTPException(status_code=401, detail="missing signature")
    parsed = _parse_calendly_signature(sig_header)
    if not parsed:
        raise HTTPException(status_code=401, detail="malformed signature")
    ts, provided_sig = parsed
    try:
        ts_int = int(ts)
    except ValueError:
        raise HTTPException(status_code=401, detail="malformed timestamp")
    if abs(time.time() - ts_int) > CALENDLY_SIG_TOLERANCE_SECONDS:
        raise HTTPException(status_code=401, detail="stale signature")
    signed_payload = f"{ts}.".encode("utf-8") + raw_body
    expected = hmac.new(
        CALENDLY_SIGNING_KEY.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, provided_sig):
        raise HTTPException(status_code=401, detail="bad signature")


def _format_brief(invitee: dict[str, Any], event: dict[str, Any]) -> tuple[str, str]:
    name = invitee.get("name") or "—"
    email = invitee.get("email") or "—"
    start = event.get("start_time") or "—"
    answers = invitee.get("questions_and_answers") or []
    qa = "\n".join(f"  Q: {a.get('question')}\n  A: {a.get('answer')}" for a in answers) or "  (no intake answers)"
    subject = f"[Klaravex] Pre-meeting brief — {name} @ {start}"
    body = (
        f"Booking:  {event.get('uri','—')}\n"
        f"When:     {start}\n"
        f"Invitee:  {name} <{email}>\n"
        f"Status:   {invitee.get('status','—')}\n\n"
        f"Intake answers:\n{qa}\n"
    )
    return subject, body


async def _send_telegram(text: str) -> None:
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT):
        return
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": text},
        )


async def _schedule_brief(invitee: dict[str, Any], sched: dict[str, Any]) -> None:
    """Write a pre-meeting brief row to klaravex_scheduled_briefs.

    send_at = start_time - 1 hour. If start_time is within 90 seconds of now
    (same-day booking with less than 90s lead time), send_at = now() so the
    cron job dispatches it on the next tick rather than skipping silently.

    Fails-open on DB unavailability: the immediate email notification already
    went out at booking time, so a missed scheduled brief is low-severity.
    """
    start_str = sched.get("start_time")
    subject, body = _format_brief(invitee, sched)
    if not start_str:
        return
    try:
        start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
    except ValueError:
        log.warning("calendly: could not parse start_time=%r; skipping brief schedule", start_str)
        return

    now_dt = datetime.now(timezone.utc)
    one_hour_before = start_dt - timedelta(hours=1)
    send_at = max(one_hour_before, now_dt)

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO klaravex_scheduled_briefs
                    (event_uri, invitee_email, invitee_name, send_at, subject, body)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT DO NOTHING
                """,
                sched.get("uri") or "",
                invitee.get("email") or "",
                invitee.get("name") or "",
                send_at,
                subject,
                body,
            )
        log.info("calendly: scheduled brief for %s at %s", invitee.get("email"), send_at.isoformat())
    except Exception as exc:  # noqa: BLE001
        log.warning("calendly: brief schedule failed (continuing): %s", exc)


@router.post("/webhook", status_code=202)
async def calendly_webhook(request: Request) -> dict[str, str]:
    raw_body = await request.body()
    _verify_calendly_signature(raw_body, request.headers.get("Calendly-Webhook-Signature"))
    try:
        import json as _json
        payload = _json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")

    event_kind = payload.get("event")
    payload_obj = payload.get("payload") or {}
    invitee = payload_obj
    sched = payload_obj.get("scheduled_event") or {}

    if event_kind == "invitee.created":
        subject, body = _format_brief(invitee, sched)
        try:
            await send_email(ALERT_EMAIL, subject, body)
            await _send_telegram(f"{subject}\n\n{body[:1500]}")
        except Exception as e:  # noqa: BLE001
            log.exception("calendly alert dispatch failed: %s", e)

        email = invitee.get("email")
        ticket_id: str | None = None
        if email:
            try:
                ticket_id = await tickets_lib.create_ticket(
                    client_email=email,
                    subject=f"Calendly booking: {invitee.get('name') or email}",
                    severity="standard",
                    status="open",
                    source="calendly",
                    summary=f"Meeting at {sched.get('start_time','—')}",
                    segment_hint="b2b",
                    metadata={
                        "name": invitee.get("name"),
                        "start_time": sched.get("start_time"),
                        "event_uri": sched.get("uri"),
                        "questions": invitee.get("questions_and_answers") or [],
                    },
                )
            except Exception as e:  # noqa: BLE001
                log.warning("calendly ticket persistence failed (continuing): %s", e)
        await _schedule_brief(invitee, sched)
        return {"status": "ok", "event": event_kind, "ticket_id": ticket_id or ""}

    if event_kind == "invitee.canceled":
        name = invitee.get("name") or "—"
        when = sched.get("start_time") or "—"
        email = invitee.get("email")
        await send_email(ALERT_EMAIL, f"[Klaravex] Cancellation — {name}", f"Invitee canceled. Was scheduled {when}.")
        if email:
            try:
                await tickets_lib.create_ticket(
                    client_email=email,
                    subject=f"Calendly cancellation: {name}",
                    severity="standard",
                    status="closed",
                    source="calendly",
                    summary=f"Canceled; was scheduled {when}",
                    segment_hint="b2b",
                    metadata={"start_time": when},
                )
            except Exception as e:  # noqa: BLE001
                log.warning("calendly cancel ticket persistence failed: %s", e)
        return {"status": "ok", "event": event_kind}

    return {"status": "ignored", "event": event_kind or "unknown"}
