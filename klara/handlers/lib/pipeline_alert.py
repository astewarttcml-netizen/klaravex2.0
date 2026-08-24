"""
Pipeline alert helper — single Telegram + email dispatch for Celery beat pipelines.

Purpose: replace the 10+ scattered _send_telegram() copies with one shared,
best-effort function so SEO / freelancer / socials / leads tasks can surface
health signals without duplicating alert logic.

Usage (from any async task context):
    from infra.klara.handlers.lib.pipeline_alert import pipeline_alert
    await pipeline_alert("seo", "agent_not_found", "critical",
                         "SEO agent not found in registry")

Levels:
  - "info"    → Telegram only, daily summary / health signal
  - "warning" → Telegram only, something needs attention
  - "critical"→ Telegram + email, action needed now

Always best-effort. Failures are logged and swallowed — a broken alert channel
must never crash the pipeline it's monitoring.
"""
from __future__ import annotations

import logging
import os
from typing import Literal

import httpx

from .email import send_email

log = logging.getLogger("klaravex.pipeline_alert")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")

AlertLevel = Literal["info", "warning", "critical"]


async def pipeline_alert(
    pipeline: str,
    event: str,
    level: AlertLevel,
    message: str,
) -> None:
    """Send a pipeline health alert via Telegram (+ email for critical)."""
    label = f"[{pipeline}] {event}"
    text = f"*Klaravex/{pipeline.upper()}* — {level.upper()}\n{message}"

    # ── Telegram ──────────────────────────────────────────────────────────
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": TELEGRAM_CHAT_ID,
                        "text": text,
                        "parse_mode": "Markdown",
                    },
                )
            if r.status_code >= 400:
                log.warning("pipeline_alert.telegram_failed status=%s body=%s",
                            r.status_code, r.text[:200])
        except Exception as exc:
            log.warning("pipeline_alert.telegram_exception: %s", exc)
    else:
        log.debug("pipeline_alert.telegram_skipped — no token or chat_id")

    # ── Email (critical only) ─────────────────────────────────────────────
    if level == "critical":
        try:
            await send_email(
                to=ALERT_EMAIL,
                subject=f"[Klaravex/{pipeline}] {event}",
                body=text.replace("*", "").replace("`", ""),
            )
        except Exception as exc:
            log.warning("pipeline_alert.email_failed: %s", exc)
