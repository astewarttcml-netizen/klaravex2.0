"""A9 Vapi tool: log_session_outcome.

Called by every consumer specialist assistant at end of session to write
the outcome to klaravex_call_transcripts. The DB outcome column is
constrained to ('resolved','escalated','abandoned','payment_completed') —
specialist-specific nuance (needs_followup, refund_requested, couldn't_fix,
etc.) is captured in the `summary` field, prefixed for filtering.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..lib.db import get_pool

log = logging.getLogger("klaravex.vapi.log_session_outcome")
router = APIRouter()

# Maps specialist-facing outcome values onto the DB-constrained set.
# (DB constraint: resolved | escalated | abandoned | payment_completed)
_OUTCOME_MAP: dict[str, str] = {
    "resolved":          "resolved",
    "fixed":             "resolved",
    "needs_followup":    "escalated",
    "follow_up_needed":  "escalated",
    "couldnt_fix":       "escalated",
    "couldn_t_fix":      "escalated",
    "could_not_fix":     "escalated",
    "unable_to_resolve": "escalated",
    "refund_requested":  "escalated",
    "escalated":         "escalated",
    "abandoned":         "abandoned",
    "caller_hung_up":    "abandoned",
}

_VALID_SPECIALISTS = {
    "triage_en",
    "windows_expert",
    "apple_expert",
    "mobile_expert",
    "smart_home_network",
    "identity_recovery",
    "live_troubleshoot",
    "klara_chat",
}


class LogSessionOutcomeRequest(BaseModel):
    call_sid: str = Field(..., min_length=1, max_length=128)
    specialist: str = Field(..., description="Which specialist is logging")
    outcome: str = Field(..., description="Specialist-facing outcome (mapped to DB-constrained set)")
    notes: str | None = Field(default=None, description="1-3 sentences summarizing what happened")
    duration_seconds: int | None = None


@router.post("/log_session_outcome")
async def log_session_outcome(req: LogSessionOutcomeRequest) -> dict[str, Any]:
    spec = req.specialist.strip().lower()
    if spec not in _VALID_SPECIALISTS:
        log.warning("log_session_outcome unknown specialist=%s call_sid=%s", spec, req.call_sid)
        # Don't 4xx — Vapi tool calls failing is worse than a soft-accept.
        # Just record it under a sentinel.
        spec = "unknown"

    raw_outcome = req.outcome.strip().lower().replace("-", "_").replace(" ", "_")
    db_outcome = _OUTCOME_MAP.get(raw_outcome)
    if db_outcome is None:
        log.warning(
            "log_session_outcome unknown outcome=%r call_sid=%s — defaulting to 'escalated'",
            req.outcome, req.call_sid,
        )
        db_outcome = "escalated"

    # Prefix the notes with the specialist tag + the raw outcome, so we can
    # filter and report later without losing the specialist-side detail.
    summary_parts = [f"[{spec}]", f"outcome={raw_outcome}"]
    if req.notes:
        summary_parts.append(req.notes.strip())
    summary = " ".join(summary_parts)[:4000]

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO klaravex_call_transcripts
                    (call_sid, summary, outcome, duration_seconds)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (call_sid) DO UPDATE
                   SET summary          = EXCLUDED.summary,
                       outcome          = EXCLUDED.outcome,
                       duration_seconds = COALESCE(EXCLUDED.duration_seconds, klaravex_call_transcripts.duration_seconds)
                RETURNING id, call_sid, outcome
                """,
                req.call_sid, summary, db_outcome, req.duration_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("log_session_outcome DB write failed call_sid=%s: %s", req.call_sid, exc)
            # Don't break the Vapi call on a DB blip. Acknowledge the tool call.
            raise HTTPException(status_code=502, detail="could not record outcome")

    log.info(
        "log_session_outcome call_sid=%s specialist=%s outcome=%s",
        req.call_sid, spec, db_outcome,
    )
    return {
        "status": "ok",
        "call_sid": row["call_sid"],
        "outcome": row["outcome"],
        "specialist": spec,
    }
