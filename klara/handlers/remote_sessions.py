"""FastAPI router for the RustDesk remote-session lifecycle (G34.3).

Deploy path: `/opt/loki-agents/app/api/remote_sessions.py` on the Hetzner
box. Local repo path mirrors the existing `klara.handlers/` layout — the
container build script copies this file into the app/api/ directory.

Endpoints (all under /api/remote-sessions):

    POST /                       — create a session row, return id +
                                   download URL the customer can launch.
                                   Session starts in `pending_consent`.
    POST /{sid}/consent          — customer clicks "I authorize" in the
                                   helper. Records the signature into
                                   klaravex_remote_sessions and into the
                                   hash-chained audit log. **GATE**: no
                                   InputEvent can leave the controller
                                   until this returns 200.
    GET  /{sid}/indicator        — persistent-indicator status payload.
                                   The helper polls every 1s; the banner
                                   it draws on the customer screen is
                                   purely client-side, but the message
                                   text + control flag (is_controlling)
                                   comes from this endpoint.
    POST /{sid}/kill             — server-side override (path 3 of 3 in
                                   spec §4 req 4). Fires the killswitch
                                   for the named session within 1 second
                                   and closes the transport. Auth: HMAC
                                   bearer token shared with Anthony's
                                   admin tooling.
    POST /{sid}/kill/customer    — surface for paths 1 + 2 (tray STOP,
                                   global hotkey). The helper hits this
                                   when the customer fires either kill
                                   path. The reason header distinguishes
                                   tray vs hotkey.
    GET  /{sid}                  — read-only session row + audit chain
                                   summary. Admin only.

The router is mounted by the Klara AI app's main.py with:
    app.include_router(remote_sessions_router, prefix="/api/remote-sessions")
"""


import hmac
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

# Local-import the rustdesk_controller package — it lives outside
# klara.handlers/ under infra/. The app entrypoint adds infra/ to sys.path.
try:
    from rustdesk_controller.consent import (
        CONSENT_TEXT_VERSION,
        consent_text_for,
    )
    from rustdesk_controller.killswitch import (
        FIRED_BY_HOTKEY,
        FIRED_BY_SERVER,
        FIRED_BY_TRAY,
        registry as killswitch_registry,
    )
    from rustdesk_controller.session import manager as session_manager
except ImportError as exc:  # pragma: no cover — surfaces at import time on misconfig
    raise RuntimeError(
        "remote_sessions router requires rustdesk_controller on sys.path"
    ) from exc

from .lib.db import get_pool

log = logging.getLogger("klaravex.api.remote_sessions")
router = APIRouter()


# ── Helpers ─────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _server_kill_token() -> str:
    """HMAC bearer token used by Anthony's admin tooling + auto-abort logic.

    Read from env so it can rotate without redeploy.
    """
    return os.environ.get("KLX_REMOTE_KILL_TOKEN", "")


def _require_kill_auth(authorization: str | None) -> None:
    expected = _server_kill_token()
    if not expected:
        # Dev mode: no token configured — allow but warn loudly.
        log.warning("KLX_REMOTE_KILL_TOKEN unset; /kill is unauthenticated")
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer")
    presented = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(presented, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad token")


def _download_url(session_id: str) -> str:
    base = os.environ.get("KLX_SUPPORT_DOWNLOAD_BASE",
                          "https://support.klaravex.com/download")
    return f"{base}/{session_id}"


# ── Request / response models ──────────────────────────────────────────────


class StartRequest(BaseModel):
    customer_email: EmailStr
    customer_region: str = Field("us", pattern=r"^(us|eu|other)$")
    goal: str = Field(..., min_length=3, max_length=500)


class StartResponse(BaseModel):
    session_id: str
    download_url: str
    consent_text: str
    consent_text_version: str
    state: str


class ConsentRequest(BaseModel):
    customer_email: EmailStr
    accepted: bool = Field(..., description="must be true; false rejects the session")


class ConsentResponse(BaseModel):
    session_id: str
    accepted_at: str
    signature_sha256: str
    state: str


class KillRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class KillResponse(BaseModel):
    session_id: str
    killed: bool
    fired_by: str
    fired_at: str


class IndicatorResponse(BaseModel):
    """Payload driving the persistent "AI is controlling your computer" banner.

    The banner widget on the customer machine MUST render this every poll
    cycle and MUST NOT be dismissable while is_controlling=true. The
    spec calls for "cannot be hidden, dismissed only by session end" —
    that constraint is enforced client-side; this endpoint just exports
    the truth signal.
    """
    session_id: str
    is_controlling: bool
    banner_text: str
    can_dismiss: bool
    kill_hotkey: str
    state: str


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.post("", response_model=StartResponse, status_code=status.HTTP_201_CREATED)
async def start_remote_session(body: StartRequest) -> StartResponse:
    """Mint a session. Customer hasn't consented yet — no control allowed.

    Returns the download URL the helper will launch. The session is
    inserted with state=`pending_consent`; control paths refuse to fire
    until POST /consent flips that.
    """
    mgr = session_manager()
    sess = mgr.create_session(
        customer_email=body.customer_email,
        customer_region=body.customer_region,
        goal=body.goal,
    )
    # Insert the DB row eagerly with consent fields NULL — that's the
    # gate `ensure_consent_recorded` reads.
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO klaravex_remote_sessions
                (session_id, customer_email, customer_region, goal, state, started_at)
            VALUES ($1, $2, $3, $4, 'pending_consent', now())
            ON CONFLICT (session_id) DO NOTHING
            """,
            sess.session_id, body.customer_email, body.customer_region, body.goal,
        )
    return StartResponse(
        session_id=sess.session_id,
        download_url=_download_url(sess.session_id),
        consent_text=consent_text_for(sess.session_id),
        consent_text_version=CONSENT_TEXT_VERSION,
        state="pending_consent",
    )


@router.post("/{session_id}/consent", response_model=ConsentResponse)
async def record_consent_endpoint(
    session_id: str,
    body: ConsentRequest,
    request: Request,
    user_agent: str | None = Header(default=None, alias="User-Agent"),
) -> ConsentResponse:
    """Customer clicks 'I authorize' in the helper. Records consent + flips
    the DB gate so the controller is allowed to send InputEvents.

    Rejected consent (`accepted=false`) is final — the session is killed
    immediately and cannot be revived.
    """
    sess = session_manager().get(session_id)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown session")
    if sess.customer_email != body.customer_email:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "email mismatch")
    if not body.accepted:
        sess.killswitch.fire(reason="consent_rejected", fired_by=FIRED_BY_SERVER)
        sess.end("failed")
        raise HTTPException(status.HTTP_409_CONFLICT, "consent rejected")
    ip = request.client.host if request.client else ""
    record = sess.record_consent(ip_address=ip, user_agent=user_agent or "")
    # `record_consent` schedules the DB upsert on the loop; that's the
    # gate `ensure_consent_recorded` reads. Await it explicitly here so
    # the HTTP response only returns AFTER the row is durable.
    from rustdesk_controller.consent import persist_consent  # local import
    await persist_consent(record)
    return ConsentResponse(
        session_id=session_id,
        accepted_at=record.accepted_at,
        signature_sha256=record.signature_sha256,
        state="pending_connect",
    )


@router.get("/{session_id}/indicator", response_model=IndicatorResponse)
async def indicator(session_id: str) -> IndicatorResponse:
    """Driver for the persistent on-screen indicator the customer sees.

    The helper polls every 1s. While the session is active and consented,
    is_controlling=true and can_dismiss=false. Once the session ends
    (any path), is_controlling=false and the helper tears down the banner.
    """
    sess = session_manager().get(session_id)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown session")
    active_states = {"connected", "awaiting_confirm", "executing"}
    is_controlling = sess.state.value in active_states and not sess.killswitch.is_killed
    banner = (
        "Klaravex AI is controlling your computer. "
        "Press Ctrl+Shift+Esc or click STOP to end the session."
    )
    return IndicatorResponse(
        session_id=session_id,
        is_controlling=is_controlling,
        banner_text=banner,
        can_dismiss=not is_controlling,
        kill_hotkey="Ctrl+Shift+Escape",
        state=sess.state.value,
    )


@router.post("/{session_id}/kill", response_model=KillResponse)
async def server_kill(
    session_id: str,
    body: KillRequest,
    authorization: str | None = Header(default=None),
) -> KillResponse:
    """Path 3 of 3 — server-side override killswitch (spec §4 req 4).

    Auth: Bearer <KLX_REMOTE_KILL_TOKEN>. Used by Anthony's admin tooling
    and by the auto-abort logic in session.py for the "AI stuck" case.
    """
    _require_kill_auth(authorization)
    ok = killswitch_registry().fire(session_id, body.reason, FIRED_BY_SERVER)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown session")
    sw = killswitch_registry().get(session_id)
    # Mirror to DB so the audit row is queryable even after the in-memory
    # session is dropped.
    await _persist_kill(session_id, body.reason, FIRED_BY_SERVER)
    assert sw is not None  # registry().fire returned True
    return KillResponse(
        session_id=session_id,
        killed=sw.is_killed,
        fired_by=sw.fired_by,
        fired_at=sw.fired_at,
    )


@router.post("/{session_id}/kill/customer", response_model=KillResponse)
async def customer_kill(
    session_id: str,
    body: KillRequest,
    x_kill_path: str | None = Header(default=None, alias="X-Kill-Path"),
) -> KillResponse:
    """Paths 1 + 2 — customer tray STOP and customer global hotkey.

    The helper signs this with the per-session shim token (rdshim IPC),
    so the auth is mutual TLS at the transport layer — no bearer needed.
    The X-Kill-Path header distinguishes:
        "tray"   → fired_by=customer_tray
        "hotkey" → fired_by=customer_hotkey
    Any other value coerces to tray (defensive default).
    """
    fired_by = FIRED_BY_HOTKEY if x_kill_path == "hotkey" else FIRED_BY_TRAY
    ok = killswitch_registry().fire(session_id, body.reason, fired_by)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown session")
    await _persist_kill(session_id, body.reason, fired_by)
    sw = killswitch_registry().get(session_id)
    assert sw is not None
    return KillResponse(
        session_id=session_id,
        killed=sw.is_killed,
        fired_by=sw.fired_by,
        fired_at=sw.fired_at,
    )


@router.get("/active", response_model=list[dict[str, Any]])
async def list_active_sessions(
    authorization: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    """Return all in-memory sessions that are not yet ended/killed.

    Used by the operator tray to discover which session(s) to kill.
    Auth: same bearer as /kill (operator-only surface).
    """
    _require_kill_auth(authorization)
    mgr = session_manager()
    ended_prefixes = {"ended_"}
    result: list[dict[str, Any]] = []
    for sid, sess in mgr._sessions.items():
        if sess.state.value.startswith("ended_") or sess.killswitch.is_killed:
            continue
        result.append({
            "session_id": sid,
            "state": sess.state.value,
            "customer_email": sess.customer_email,
            "goal": sess.goal,
        })
    return result


@router.get("/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """Admin view. Joins the DB row with the in-memory session summary."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM klaravex_remote_sessions WHERE session_id=$1", session_id,
        )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown session")
    sess = session_manager().get(session_id)
    return {
        "db": dict(row),
        "in_memory": {
            "state": sess.state.value if sess else None,
            "rejection_streak": sess.rejection_streak if sess else None,
            "killed": sess.killswitch.is_killed if sess else None,
            "audit_chain_intact": sess.audit.verify() if sess else None,
            # iter-40 observability: warmup + pump derived states so the
            # admin dashboard (consuming GET /api/remote-sessions/{id})
            # can render lifecycle without grepping the audit chain
            # client-side. Both methods are pure derivations over
            # sess.audit.entries + task handles — see
            # rustdesk_controller/session.py for the truth table.
            "warmup_state": sess.warmup_state() if sess else None,
            "frame_pump_state": sess.frame_pump_state() if sess else None,
        },
    }


# ── DB helpers ──────────────────────────────────────────────────────────────


async def _persist_kill(session_id: str, reason: str, fired_by: str) -> None:
    pool = await get_pool()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE klaravex_remote_sessions
               SET killed=true,
                   killed_at=$1::timestamptz,
                   killed_by=$2,
                   kill_reason=$3,
                   state='ended_killed',
                   ended_at=COALESCE(ended_at, $1::timestamptz),
                   outcome=COALESCE(outcome, 'killed')
             WHERE session_id=$4
            """,
            now, fired_by, reason[:500], session_id,
        )
