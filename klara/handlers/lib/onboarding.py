"""
Day-0 onboarding checklist + kickoff scheduling.

Triggered by stripe_webhook on customer.subscription.created (B2B segment only).
Creates a checklist row with default tasks per segment.

Future Calendly integration drops in via `CALENDLY_EVENT_URL` env — if set, the
kickoff CTA links straight to Calendly; otherwise it routes to a portal form
that emails the support team.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from .db import get_pool
from .email import send_email

log = logging.getLogger("klaravex.onboarding")

PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")
CALENDLY_KICKOFF_URL = os.environ.get("CALENDLY_KICKOFF_URL", "")  # set once Anthony provides
ANTHONY_ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")


B2B_DEFAULT_TASKS = [
    {"key": "kickoff_call",      "title": "Schedule your 30-min kickoff call",                   "owner": "client",   "done": False},
    {"key": "primary_contact",   "title": "Identify your single point of contact (SPOC)",        "owner": "client",   "done": False},
    {"key": "m365_admin",        "title": "Grant Klaravex M365 Global Admin (delegated access)", "owner": "client",   "done": False},
    {"key": "device_inventory",  "title": "Share device inventory (or Atera agent install list)","owner": "client",   "done": False},
    {"key": "compliance_scope",  "title": "Confirm compliance scope (HIPAA / SOC 2 / none)",     "owner": "client",   "done": False},
    {"key": "atera_enrollment",  "title": "Atera RMM agents installed across endpoints",         "owner": "klaravex", "done": False},
    {"key": "baseline_scan",     "title": "Klaravex completes baseline security scan",           "owner": "klaravex", "done": False},
    {"key": "monitoring_active", "title": "Monitoring + alerting confirmed end-to-end",          "owner": "klaravex", "done": False},
]


CONSUMER_DEFAULT_TASKS = [
    {"key": "first_login",       "title": "Sign in to your Klaravex portal",                     "owner": "client",   "done": False},
    {"key": "first_chat",        "title": "Try the AI assistant — ask anything IT-related",      "owner": "client",   "done": False},
    {"key": "device_profile",    "title": "Tell us about your devices (so we can help fast)",    "owner": "client",   "done": False},
]


async def ensure_checklist(email: str, segment: str, client_id: Optional[str] = None) -> dict[str, object]:
    """Idempotent: creates a checklist for this email if none exists."""
    tasks = B2B_DEFAULT_TASKS if segment == "b2b" else CONSUMER_DEFAULT_TASKS
    total = len(tasks)
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id::text, status FROM klaravex_onboarding_checklists WHERE email=$1",
            email.lower(),
        )
        if existing:
            return {"checklist_id": existing["id"], "created": False, "status": existing["status"]}

        if client_id is None:
            client_id = await conn.fetchval(
                "SELECT id FROM klaravex_clients WHERE email=$1",
                email.lower(),
            )

        checklist_id = await conn.fetchval(
            """
            INSERT INTO klaravex_onboarding_checklists
                (client_id, email, segment, tasks, total_count)
            VALUES ($1, $2, $3, $4::jsonb, $5)
            RETURNING id::text
            """,
            client_id, email.lower(), segment, json.dumps(tasks), total,
        )
    log.info("onboarding checklist created for %s (segment=%s, tasks=%d)", email, segment, total)
    return {"checklist_id": checklist_id, "created": True, "tasks_total": total}


async def get_checklist(email: str) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM klaravex_onboarding_checklists WHERE email=$1",
            email.lower(),
        )
    if not row:
        return None
    d = dict(row)
    if isinstance(d.get("tasks"), str):
        try:
            d["tasks"] = json.loads(d["tasks"])
        except Exception:
            d["tasks"] = []
    return d


async def toggle_task(email: str, task_key: str, done: bool) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tasks FROM klaravex_onboarding_checklists WHERE email=$1",
            email.lower(),
        )
        if not row:
            return {"ok": False, "error": "checklist_not_found"}
        tasks = row["tasks"]
        if isinstance(tasks, str):
            tasks = json.loads(tasks)
        for t in tasks:
            if t.get("key") == task_key:
                t["done"] = bool(done)
                t["done_at"] = datetime.now(tz=timezone.utc).isoformat() if done else None
        completed = sum(1 for t in tasks if t.get("done"))
        new_status = "completed" if completed == len(tasks) else "active"
        await conn.execute(
            """
            UPDATE klaravex_onboarding_checklists
               SET tasks=$1::jsonb, completed_count=$2, status=$3, updated_at=now()
             WHERE email=$4
            """,
            json.dumps(tasks), completed, new_status, email.lower(),
        )
        return {"ok": True, "completed": completed, "total": len(tasks), "status": new_status}


async def request_kickoff(email: str, preferred_times: str) -> dict:
    """Client clicks 'Schedule kickoff' → email Anthony with their preferred times."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex_onboarding_checklists SET kickoff_requested_at=now() WHERE email=$1",
            email.lower(),
        )
    try:
        body = (
            f"New onboarding kickoff request from {email}.\n\n"
            f"Preferred times (client-provided):\n{preferred_times}\n\n"
            f"Reply directly to schedule.\n"
        )
        await send_email(
            to=ANTHONY_ALERT_EMAIL,
            subject=f"[Klaravex] Kickoff requested — {email}",
            body=body,
        )
    except Exception as exc:
        log.exception("kickoff notification failed for %s: %s", email, exc)
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


def kickoff_cta_url() -> str:
    """If Calendly URL is configured, use it. Otherwise direct to portal form."""
    return CALENDLY_KICKOFF_URL or f"{PORTAL_BASE_URL.rstrip('/')}/portal/onboarding"
