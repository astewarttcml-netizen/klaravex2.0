"""Klara voice tools for the RustDesk AI Remote Session (spec §4).

Four endpoints Vapi calls via /api/v1/vapi/tool-call dispatch:

    POST start_rustdesk_session    {customer_email, problem_summary}
    POST next_screen_action        {session_id}
    POST confirm_action            {session_id, confirmed}
    POST end_rustdesk_session      {session_id, outcome}

This module renames the legacy `generate_splashtop_link` tool per PRD v2.1
CR-2 — Splashtop SOS is OUT, self-hosted RustDesk is IN. The legacy tool
file is kept for backward compatibility while the Vapi assistant config is
migrated, then removed.

The download URL pattern is `https://support.klaravex.com/dl/<filename>` —
the filename encodes the relay host + server key so the helper auto-configures
on first launch with zero customer typing. See infra/rustdesk-server-DEPLOYED.md.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from .protocol import DEFAULT_RELAY_HOST, DEFAULT_RELAY_KEY, ConnectionConfig
from .session import RemoteSession, manager

log = logging.getLogger("klaravex.rustdesk.voice")
router = APIRouter()

SUPPORT_BASE = os.environ.get("KLARAVEX_SUPPORT_BASE", "https://support.klaravex.com")
HELPER_FILENAME_TEMPLATE = (
    "klaravex-support-host={host},key={key}.exe"
)
# Truncation budget for the str(exc) embedded in a warmup_failed audit
# row's payload. Sized so the serialised JSON row stays well under the
# hash-chain row size budget; see Pattern 25 in .loki/CONTINUITY.md.
_AUDIT_ERROR_MAX_CHARS = 512


class StartRequest(BaseModel):
    customer_email: EmailStr
    problem_summary: str = Field(min_length=3, max_length=500)
    customer_region: str = Field(default="us", pattern="^(us|eu|other)$")
    customer_rustdesk_id: str = Field(pattern=r"^[0-9]{9}$")


class NextActionRequest(BaseModel):
    session_id: str


class ConfirmRequest(BaseModel):
    session_id: str
    confirmed: bool


class EndRequest(BaseModel):
    session_id: str
    outcome: str = Field(pattern="^(fixed|failed|handoff)$")


def _download_url() -> str:
    """The zero-config Windows helper URL. RustDesk reads host= and key= from
    the filename, so the customer sees one click and no settings page."""
    filename = HELPER_FILENAME_TEMPLATE.format(
        host=DEFAULT_RELAY_HOST,
        key=DEFAULT_RELAY_KEY,
    )
    return f"{SUPPORT_BASE}/dl/{filename}"


async def _persist_warmup_state(
    session_id: str,
    state: str,
    *,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    """Persist the terminal warmup state to klaravex_remote_sessions.

    The in-memory `sess.audit.entries` + `RemoteSession.warmup_state()`
    remain the canonical truth for LIVE sessions; this column is the
    POST-MORTEM view that survives `SessionManager.drop()`.

    DEPLOY-SAFE BEFORE MIGRATION 023 APPLIES: catches
    `UndefinedColumnError` and treats it as a soft no-op. Production
    can run this code path against an unmigrated DB without losing any
    warmup audit row — only the persisted view is unavailable until
    the migration applies. Logs at warn so SREs see the gap; the
    backstop is in-memory `warmup_state()` for live observability.

    Tolerates pool unavailability the same way: tests / dev runs
    without DB connectivity get a debug log and no DB call.
    """
    try:
        from klara.handlers.lib.db import get_pool
    except ImportError:
        log.debug("warmup persist skipped: klara.handlers.lib.db not importable")
        return
    try:
        pool = await get_pool()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "warmup persist: get_pool failed session=%s state=%s err=%s",
            session_id, state, exc,
        )
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE klaravex_remote_sessions
                   SET warmup_state = $1,
                       warmup_completed_at = COALESCE(warmup_completed_at, $2::timestamptz),
                       warmup_error_type = $3,
                       warmup_error_message = $4
                 WHERE session_id = $5
                """,
                state, datetime.now(timezone.utc), error_type, error_message, session_id,
            )
    except Exception as exc:  # noqa: BLE001
        # UndefinedColumnError is the EXPECTED pre-migration case; other
        # errors (disk full, deadlock, dropped connection) still get
        # logged but don't propagate. The in-memory warmup_state() is the
        # backstop for live observability; only post-mortem queries lose
        # this row if the persist failed.
        log.warning(
            "warmup persist failed session=%s state=%s err=%s",
            session_id, state, exc,
        )


async def _warmup_transport(sess: RemoteSession) -> None:
    """Background producer for Pattern 19: pick the real transport, connect,
    then start the frame pump.

    Runs as `sess.warmup_task` after `start_rustdesk_session` returns the
    download URL — Klara is already reading instructions to the caller, so
    this work happens in parallel with the customer downloading the helper.

    Stub transport path (no `$KLX_RDSHIM_BIN`, i.e. CI / dev): start_remote
    returns kind="stub" and we do NOT start the pump. The stub's frames()
    raises `RuntimeError("connect() first")` and the operator-e2e test
    explicitly drives transport attachment via _attach_fake_transport.
    Starting the pump on the stub here would just produce a doomed task
    that crashes on the first iteration. The session's pump remains
    None until the operator-e2e harness wires it.

    Shim transport path (production with shim binary): start_remote swaps
    the stub for a freshly-handshaken ShimSubprocessTransport, we then
    await transport.connect(cfg) and start the pump.
    """
    try:
        selection = await manager().start_remote(sess)
        if selection.kind == "stub":
            log.info(
                "warmup: stub transport selected for session=%s; pump not started",
                sess.session_id,
            )
            sess.audit.append(
                sess.session_id,
                "warmup_skipped_stub",
                {"reason": selection.reason},
            )
            await _persist_warmup_state(sess.session_id, "skipped_stub")
            return
        cfg = ConnectionConfig(
            customer_id=sess.customer_rustdesk_id,
            session_password=sess.session_id,
        )
        await sess.transport.connect(cfg)
        # Killswitch / end() race guard (iter-38 code-review High): a kill
        # or end() that fires between the `await connect(cfg)` resolving
        # and us reaching `start_frame_pump()` would have already run
        # `_stop_warmup` (clearing the field) AND `_stop_frame_pump`
        # (cancelling a pump that didn't yet exist). Starting the pump
        # after that point would leak a task past the session's lifetime.
        # Check the killswitch under the same scheduling tick to close
        # the window.
        if sess.killswitch.is_killed:
            log.info(
                "warmup: killswitch fired during connect; pump not started session=%s",
                sess.session_id,
            )
            sess.audit.append(
                sess.session_id,
                "warmup_aborted_killswitch",
                {"reason": sess.killswitch.reason or "unknown"},
            )
            await _persist_warmup_state(sess.session_id, "aborted_killswitch")
            return
        sess.start_frame_pump()
        sess.audit.append(
            sess.session_id,
            "warmup_completed",
            {"transport_kind": selection.kind},
        )
        await _persist_warmup_state(sess.session_id, "completed")
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "warmup failed session=%s err=%s",
            sess.session_id, exc,
        )
        # Audit-row emission (iter-39 code-review Medium): post-mortem
        # dashboards must distinguish "warmup never ran" from "warmup ran
        # and failed", so we surface the failure on the same hash chain
        # as every other lifecycle event. Truncate the error string so a
        # pathological transport exception payload can't blow the row
        # past the audit row size budget.
        try:
            sess.audit.append(
                sess.session_id,
                "warmup_failed",
                {
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:_AUDIT_ERROR_MAX_CHARS],
                },
            )
        except Exception as audit_exc:  # noqa: BLE001
            log.warning(
                "warmup_failed audit row append failed session=%s err=%s",
                sess.session_id, audit_exc,
            )
        # Persist the failed state — bounded by Pattern 25 truncation.
        await _persist_warmup_state(
            sess.session_id,
            "failed",
            error_type=type(exc).__name__,
            error_message=str(exc)[:_AUDIT_ERROR_MAX_CHARS],
        )


@router.post("/start_rustdesk_session")
async def start_rustdesk_session(req: StartRequest) -> dict[str, Any]:
    """Mint a session and begin connecting to the customer's RustDesk peer.

    Path B flow: the customer already has vanilla RustDesk installed from
    rustdesk.com and has shared their 9-digit RustDesk ID with Klara.
    No download URL is needed — the backend connects directly to the
    customer's peer via the relay.
    """
    sess = manager().create_session(
        customer_email=str(req.customer_email),
        customer_region=req.customer_region,
        goal=req.problem_summary,
        customer_rustdesk_id=req.customer_rustdesk_id,
    )
    # Pattern 19 producer wiring: schedule transport setup + pump start in
    # the background so the voice tool returns immediately. The warmup task
    # is tracked on the session so end()/killswitch can cancel it cleanly.
    sess.warmup_task = asyncio.create_task(
        _warmup_transport(sess),
        name=f"warmup-{sess.session_id}",
    )
    log.info(
        "voice start_rustdesk_session session=%s email=%s rustdesk_id=%s warmup_task=%s",
        sess.session_id,
        req.customer_email,
        req.customer_rustdesk_id,
        sess.warmup_task.get_name(),
    )
    return {
        "status": "ok",
        "session_id": sess.session_id,
        "customer_rustdesk_id": req.customer_rustdesk_id,
        "instructions_for_klara": (
            f"The customer's RustDesk ID is {req.customer_rustdesk_id}. "
            "Tell them: 'I can see your screen now. Let me take a look "
            "at what's going on.' Then begin the diagnostic."
        ),
        "relay_host": DEFAULT_RELAY_HOST,
        "recording_enabled": sess.recorder.enabled,
        "warmup_task_name": sess.warmup_task.get_name(),
    }


@router.post("/next_screen_action")
async def next_screen_action(req: NextActionRequest) -> dict[str, Any]:
    """Predict the next action against the latest cached frame.

    Returns `awaiting_confirmation=true` and the rationale Klara reads
    verbatim. The customer's yes/no comes back via /confirm_action.

    Frame ingest contract: the transport pump (SessionManager.start_remote)
    calls `RemoteSession.cache_frame(frame)` for every frame it receives.
    This endpoint reads `sess.latest_frame` synchronously; if the customer
    helper has not yet sent a first frame we return `awaiting_first_frame`
    so Klara can keep the caller informed.
    """
    sess = manager().get(req.session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    if sess.killswitch.is_killed:
        return {
            "status": "killed",
            "reason": sess.killswitch.reason,
            "awaiting_confirmation": False,
        }
    if sess.pending_confirmation is not None:
        action = sess.pending_confirmation.action
        return {
            "status": "awaiting_confirmation",
            "session_id": sess.session_id,
            "awaiting_confirmation": True,
            "action_description": action.rationale,
            "confidence": action.confidence,
        }
    if sess.latest_frame is None:
        return {
            "status": "awaiting_first_frame",
            "session_id": sess.session_id,
            "awaiting_confirmation": False,
            "action_description": (
                "Waiting for the customer helper to send the first frame. "
                "Klara should ask the caller to confirm the helper window "
                "is open and not blocked by a Windows permission prompt."
            ),
        }
    sess.request_next_action(sess.latest_frame)
    return {
        "status": "predicting",
        "session_id": sess.session_id,
        "awaiting_confirmation": False,
        "action_description": (
            "Vision call dispatched against the latest frame. "
            "Klara should fill the line with a 'one moment while I look "
            "at your screen' snippet and poll this endpoint again."
        ),
    }


@router.post("/confirm_action")
async def confirm_action(req: ConfirmRequest) -> dict[str, Any]:
    sess = manager().get(req.session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    if sess.pending_confirmation is None:
        return {"status": "no_pending", "executed": False}
    result = await sess.confirm(req.confirmed)
    return {"status": "ok", **result}


@router.post("/end_rustdesk_session")
async def end_rustdesk_session(req: EndRequest) -> dict[str, Any]:
    sess = manager().get(req.session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    summary = sess.end(req.outcome)
    manager().drop(req.session_id)
    return {"status": "ok", "summary": summary}
