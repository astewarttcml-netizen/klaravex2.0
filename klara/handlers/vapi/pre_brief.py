"""Phase 12 V7 — B2B lead pre-brief dispatcher.

After create_b2b_lead inserts a row it fires dispatch_lead_pre_brief as an
asyncio.create_task. This function selects the top-N pillar engineers by
keyword score against the lead's pain points, asks each to reason about the
lead, merges their outputs into a "Project Pre-Brief", emails Anthony, and
updates klaravex_b2b_leads.pre_brief_status.

Status lifecycle:
  pending          — row just inserted (create_b2b_lead default)
  drafting         — dispatch running (brief in flight)
  awaiting_approval — brief emailed to Anthony, no approval yet
  skipped          — all engineer calls failed; raw alert already sent
"""

import asyncio
import logging
import os
from typing import Any

from ..engineers.dispatcher import ENGINEERS
from ..lib.agentmail_notify import notify_agent_inbox
from ..lib.email import send_email

log = logging.getLogger("klaravex.vapi.pre_brief")

ALERT_EMAIL = os.environ.get("ANTHONY_ALERT_EMAIL", "astewart@klaravex.com")
_TOP_N = 2  # poll top-2 pillars for dual-angle coverage


# ── Lead → ticket adapter ─────────────────────────────────────────────────────

def _lead_to_ticket(lead: dict[str, Any]) -> dict[str, Any]:
    """Convert a b2b_leads dict into the ticket-shaped dict engineers expect.

    Concatenates pain_points + current_it_setup + urgency into the keyword
    and summary fields engineers score against (pattern-46: realistic payload).
    """
    combined = " ".join(
        str(v)
        for v in (
            lead.get("pain_points") or "",
            lead.get("current_it_setup") or "",
            lead.get("urgency") or "",
        )
        if v
    ).strip()
    company = lead.get("company") or "Unknown"
    return {
        "subject": f"B2B lead — {company}",
        "summary": combined,
        "sku": "",
        "keywords": combined,
        "archetype": "b2b_intake",
    }


def _top_engineers(ticket: dict[str, Any], n: int = _TOP_N) -> list:
    """Return top-N engineers by matches_ticket score (score > 0).

    Falls back to StrategicAdvisoryEngineer when no keyword match so the
    pre-brief is never empty.
    """
    scored = [(e, e.matches_ticket(ticket)) for e in ENGINEERS]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = [e for e, score in scored[:n] if score > 0]
    if not top:
        # Import lazily to avoid circular at module level
        from ..engineers.strategic_advisory import StrategicAdvisoryEngineer
        top = [StrategicAdvisoryEngineer()]
    return top


# ── Per-engineer brief ────────────────────────────────────────────────────────

async def _engineer_brief(eng, ticket: dict[str, Any]) -> str:
    """Ask one engineer to reason about the lead. Returns a markdown section.

    Never raises — callers gather all briefs in parallel.
    """
    try:
        result = await eng.reason_about_ticket(ticket)
        title = result.get("title") or eng.display_name
        body = result.get("body_markdown") or result.get("body") or ""
        return f"### {eng.display_name} — {title}\n\n{body}"
    except Exception as exc:
        log.warning("pre_brief: engineer %s failed: %s", eng.name, exc)
        return f"### {eng.display_name}\n\n*(analysis unavailable — {type(exc).__name__})*"


# ── Status helper ─────────────────────────────────────────────────────────────

async def _set_status(lead_id: str, status: str) -> None:
    """Update pre_brief_status on the lead row. Swallows DB errors (pattern-26)."""
    try:
        from ..lib.db import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE klaravex_b2b_leads
                   SET pre_brief_status = $2,
                       updated_at       = now()
                 WHERE id = $1::uuid
                """,
                lead_id,
                status,
            )
    except Exception as exc:
        log.warning("pre_brief: DB status update failed lead=%s status=%s: %s", lead_id, status, exc)


# ── Public entry point ────────────────────────────────────────────────────────

async def dispatch_lead_pre_brief(lead_id: str, lead: dict[str, Any]) -> None:
    """Build a Project Pre-Brief for a new B2B lead and email Anthony.

    Designed to run as asyncio.create_task — never propagates exceptions.
    """
    await _set_status(lead_id, "drafting")

    try:
        ticket = _lead_to_ticket(lead)
        engineers = _top_engineers(ticket)

        briefs = await asyncio.gather(*[_engineer_brief(e, ticket) for e in engineers])
        merged = "\n\n---\n\n".join(b for b in briefs if b)

        company = lead.get("company") or "Unknown"
        caller = lead.get("caller_name") or ""
        seat_count = lead.get("seat_count")
        pain = lead.get("pain_points") or ""
        urgency = lead.get("urgency") or ""

        subject = f"[Klaravex Pre-Brief] {company} — ready for review (Lead #{lead_id})"
        body = (
            f"Project Pre-Brief\n"
            f"{'=' * 60}\n\n"
            f"Lead ID   : {lead_id}\n"
            f"Company   : {company}\n"
            f"Caller    : {caller}\n"
            f"Seats     : {seat_count or 'not stated'}\n"
            f"Urgency   : {urgency or 'not stated'}\n"
            f"Pain pts  : {pain or '(none captured)'}\n\n"
            f"{'=' * 60}\n\n"
            f"Engineer Analysis\n"
            f"-----------------\n\n"
            f"{merged}\n\n"
            f"{'=' * 60}\n\n"
            f"To approve and forward to the prospect, reply to this email\n"
            f"or visit: https://api.klaravex.com/admin/b2b-leads/{lead_id}\n"
        )

        await send_email(to=ALERT_EMAIL, subject=subject, body=body)

        # M8: also post the pre-brief to the workflow AgentMail inbox so the
        # internal coordination squad sees every new B2B lead immediately.
        await notify_agent_inbox("workflow", subject, body)

        await _set_status(lead_id, "awaiting_approval")

    except Exception as exc:
        log.error("pre_brief: dispatch failed lead=%s: %s", lead_id, exc)
        await _set_status(lead_id, "skipped")
