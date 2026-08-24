"""Per-session state machine + main predict→confirm→execute loop.

Spec §3 action-confirmation gate (mandatory, every action):
    1. Predict — vision returns {action, target, rationale, confidence}
    2. Speak — Klara verbalizes the rationale ("I'm going to click X — okay?")
    3. Confirm — customer says yes/no, no action fires without affirmative
    4. Execute — controller emits the event, captures next frame, loop

Latency budget (spec §4): <8s end-to-end per action. While Klara waits on
the vision call, she fills silence with pre-recorded "one moment while I
look at your screen…" snippets.

Abort policy (spec §3 OPEN):
    - 2 consecutive customer rejections → abort + voice handoff (§7)
    - Vision confidence <0.6 → abort + voice handoff
    - Killswitch fired (customer or server) → abort immediately
    - Per-action timeout (no customer confirm in 60s) → abort

The confirm step itself is async — the Klara Vapi assistant calls back
via `voice_tools.confirm_action` to set the answer. This module exposes
the future so the loop can await it.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .consent import (
    ConsentNotRecorded,
    HashChainAuditLog,
    ensure_consent_recorded,
    make_consent_record,
    persist_consent,
)
from .factory import TransportSelection, make_stub_transport
from .killswitch import (
    FIRED_BY_SERVER,
    FIRED_BY_SESSION_END,
    KillSwitch,
    registry as killswitch_registry,
)
from .protocol import ConnectionConfig, Frame, InputEvent, RustDeskTransport
from .recording import SessionRecorder
from .vision import PredictedAction, VisionPredictor

log = logging.getLogger("klaravex.rustdesk.session")


class SessionState(str, Enum):
    PENDING_CONNECT = "pending_connect"
    CONNECTED = "connected"
    AWAITING_CONFIRM = "awaiting_confirm"
    EXECUTING = "executing"
    ENDED_FIXED = "ended_fixed"
    ENDED_FAILED = "ended_failed"
    ENDED_HANDOFF = "ended_handoff"
    ENDED_KILLED = "ended_killed"


@dataclass
class PendingConfirmation:
    action: PredictedAction
    future: asyncio.Future[bool]
    issued_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class RemoteSession:
    """Holds all per-session state. Owned by the SessionManager.

    Lifecycle:
        SessionManager.create_session()  → PENDING_CONNECT
        Klara calls start_rustdesk_session voice tool, which:
          1. mints session_id + signed download URL
          2. customer downloads pre-keyed helper
          3. helper connects to relay → callback flips state to CONNECTED
        Klara calls next_screen_action / confirm_action repeatedly
        Klara calls end_rustdesk_session → final state
    """

    session_id: str
    customer_email: str
    customer_region: str
    customer_rustdesk_id: str = "000000000"  # 9-digit RustDesk peer ID from the customer
    goal: str = ""  # "fix the customer's WiFi"
    state: SessionState = SessionState.PENDING_CONNECT
    rejection_streak: int = 0
    pending_confirmation: PendingConfirmation | None = None
    latest_frame: Frame | None = None
    frame_pump_task: asyncio.Task[None] | None = None
    warmup_task: asyncio.Task[None] | None = None
    killswitch: KillSwitch = field(init=False)
    audit: HashChainAuditLog = field(init=False)
    recorder: SessionRecorder = field(init=False)
    transport: RustDeskTransport = field(init=False)
    transport_selection: TransportSelection = field(init=False)
    vision: VisionPredictor = field(init=False)

    def __post_init__(self) -> None:
        self.killswitch = KillSwitch(session_id=self.session_id)
        # Register so HTTP /kill handler can fire by session_id alone.
        killswitch_registry().register(self.killswitch)
        sink = Path(".loki/remote-sessions") / self.session_id
        self.audit = HashChainAuditLog(sink_path=sink / "audit.jsonl")
        self.recorder = SessionRecorder(
            session_id=self.session_id,
            customer_email=self.customer_email,
            customer_region=self.customer_region,
            sink_dir=sink,
        )
        # Audit-log every kill, regardless of which path triggered it.
        async def _on_kill(sid: str, reason: str, fired_by: str) -> None:
            self.audit.append(sid, "killswitch_fired",
                              {"reason": reason, "fired_by": fired_by})
            # iter-42 code-review High: if the kill fires while the warmup
            # task is still alive (parked on start_remote() or connect()),
            # the warmup's `except CancelledError: raise` propagates
            # without emitting warmup_aborted_killswitch. Without this
            # extra row, warmup_state() reads "absent" instead of
            # "aborted_killswitch" — the dashboard would show "warmup
            # never ran" rather than "customer hit STOP while we were
            # spinning up". Emit the row HERE so the truth table is
            # complete regardless of where in _warmup_transport the
            # cancellation lands.
            if self.warmup_task is not None and not self.warmup_task.done():
                self.audit.append(sid, "warmup_aborted_killswitch",
                                  {"reason": reason})
                # iter-44 (post-migration-023) persistence — post-mortem
                # queries against klaravex_remote_sessions need this row
                # to survive SessionManager.drop(). Lazy-import the
                # voice_tools helper to avoid a load-time cycle (voice
                # tools imports from session).
                try:
                    from .voice_tools import _persist_warmup_state
                    await _persist_warmup_state(sid, "aborted_killswitch")
                except Exception as persist_exc:  # noqa: BLE001
                    log.warning(
                        "warmup persist on kill failed session=%s err=%s",
                        sid, persist_exc,
                    )
            self._stop_warmup()
            self._stop_frame_pump()
            try:
                if hasattr(self.transport, "close"):
                    await self.transport.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("transport close on kill failed: %s", exc)
        self.killswitch.register_hook(_on_kill)
        cfg = ConnectionConfig(
            customer_id=self.customer_rustdesk_id,
            session_password=self.session_id,
        )
        # G34.4: transport is chosen by the synchronous stub factory at
        # __post_init__ time. The shim path is async (spawns subprocess)
        # and is reserved for the SessionManager.start_remote() entrypoint
        # added in G34.5. Keeping __post_init__ sync preserves the
        # dataclass contract that existing tests rely on.
        self.transport, self.transport_selection = make_stub_transport(cfg)
        self.vision = VisionPredictor()

    # ── Transport attachment (G34.4 seam) ────────────────────────────────────

    def attach_transport(
        self,
        transport: RustDeskTransport,
        selection: TransportSelection,
    ) -> None:
        """Swap in a freshly-spawned shim transport in place of the stub.

        Used by `SessionManager.start_remote()` after awaiting
        `transport_factory(prefer_shim=True)`. The audit log records the
        swap so post-mortems can correlate transport type with session
        outcome.
        """
        prior = self.transport_selection.kind
        self.transport = transport
        self.transport_selection = selection
        self.audit.append(
            self.session_id,
            "transport_attached",
            {"kind": selection.kind, "reason": selection.reason, "prior": prior},
        )

    # ── Frame cache (voice-tool seam) ────────────────────────────────────────

    def cache_frame(self, frame: Frame) -> None:
        """Store the most recent frame the transport pumped in.

        The transport pump loop in `SessionManager.start_remote()` feeds
        frames into `RemoteSession.cache_frame()` so the synchronous voice
        endpoint `/next_screen_action` can predict against the latest one
        without itself awaiting the async iterator.
        """
        self.latest_frame = frame

    def start_frame_pump(self) -> asyncio.Task[None]:
        """Spawn the background task that drains transport.frames() into
        cache_frame() until close. Idempotent — calling twice returns the
        existing task without spawning a second drainer.

        Crash policy: the pump swallows transport exceptions to a warn
        log so a flaky transport never bubbles into the FastAPI worker.
        Cancellation (session end / killswitch) re-raises CancelledError
        cleanly.
        """
        if self.frame_pump_task is not None and not self.frame_pump_task.done():
            return self.frame_pump_task

        async def _pump() -> None:
            try:
                async for frame in self.transport.frames():
                    self.cache_frame(frame)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "frame pump exited session=%s err=%s",
                    self.session_id, exc,
                )

        self.frame_pump_task = asyncio.create_task(
            _pump(), name=f"frame-pump-{self.session_id}"
        )
        self.audit.append(
            self.session_id,
            "frame_pump_started",
            {"transport_kind": self.transport_selection.kind},
        )
        return self.frame_pump_task

    def _stop_frame_pump(self) -> None:
        """Cancel the pump if running. Safe to call from sync contexts."""
        task = self.frame_pump_task
        if task is None or task.done():
            return
        task.cancel()
        self.frame_pump_task = None

    # ── Observability (dashboard surface) ────────────────────────────────────

    def warmup_state(self) -> str:
        """Return the warmup task's observable state for the admin dashboard.

        The state is derived from `sess.audit.entries` first (the canonical
        log) with `sess.warmup_task` as fallback for the "still running"
        case. The 4 terminal states are emitted by `_warmup_transport`:
        `warmup_skipped_stub`, `warmup_aborted_killswitch`,
        `warmup_completed`, `warmup_failed`. If none are on the chain yet
        and the task is alive, we return `"running"`. If neither row nor
        task is present, `"absent"` — the session was created but the
        warmup hasn't started (e.g. test harness that doesn't go through
        start_rustdesk_session).
        """
        terminal = {
            "warmup_skipped_stub": "skipped_stub",
            "warmup_aborted_killswitch": "aborted_killswitch",
            "warmup_completed": "completed",
            "warmup_failed": "failed",
        }
        # Walk in reverse so the most recent terminal row wins if the
        # warmup somehow emitted more than one (current code emits at
        # most one, but a future retry supervisor might re-run warmup).
        for entry in reversed(self.audit.entries):
            if entry.event_type in terminal:
                return terminal[entry.event_type]
        if self.warmup_task is not None and not self.warmup_task.done():
            return "running"
        return "absent"

    def frame_pump_state(self) -> str:
        """Return the pump task's observable state for the admin dashboard.

        `"running"`: task alive. `"stopped"`: task created then ended
        (clean StopAsyncIteration, cancellation, or swallowed exception).
        `"absent"`: never started (stub-warmup path, or session ended
        before warmup completed).
        """
        task = self.frame_pump_task
        if task is None:
            return "absent"
        return "running" if not task.done() else "stopped"

    def _stop_warmup(self) -> None:
        """Cancel the warmup task if running. Safe to call from sync contexts.

        The warmup coroutine (voice_tools._warmup_transport) may be parked
        on `manager().start_remote()` or `transport.connect()` when the
        session ends or the killswitch fires; cancelling it prevents a
        background task leaking past session lifetime.
        """
        task = self.warmup_task
        if task is None or task.done():
            return
        task.cancel()
        self.warmup_task = None

    # ── Voice-tool entry points ──────────────────────────────────────────────

    def request_next_action(self, frame: Frame) -> asyncio.Future[bool]:
        """Predict + queue confirmation, return future Klara awaits."""
        if self.killswitch.is_killed:
            raise RuntimeError("session killed")
        if self.pending_confirmation is not None:
            raise RuntimeError("already awaiting confirmation")
        loop = asyncio.get_event_loop()
        future: asyncio.Future[bool] = loop.create_future()

        async def _run() -> None:
            action = await self.vision.predict(frame, self.goal)
            self.audit.append(
                self.session_id,
                "action_predicted",
                {
                    "event_kind": action.event.kind.value,
                    "x": action.event.x,
                    "y": action.event.y,
                    "confidence": action.confidence,
                    "rationale": action.rationale,
                },
            )
            self.recorder.write_event("action_predicted", {
                "rationale": action.rationale,
                "confidence": action.confidence,
            })
            if action.low_confidence:
                self.killswitch.fire(
                    reason=f"low_confidence={action.confidence:.2f}",
                    fired_by="auto_abort_low_conf",
                )
                future.set_result(False)
                return
            self.pending_confirmation = PendingConfirmation(action=action, future=future)
            self.state = SessionState.AWAITING_CONFIRM

        asyncio.create_task(_run())
        return future

    async def confirm(self, confirmed: bool) -> dict[str, Any]:
        if self.pending_confirmation is None:
            raise RuntimeError("no pending confirmation")
        pending = self.pending_confirmation
        self.pending_confirmation = None
        self.audit.append(
            self.session_id,
            "action_confirmed" if confirmed else "action_rejected",
            {"confidence": pending.action.confidence},
        )
        if not confirmed:
            self.rejection_streak += 1
            pending.future.set_result(False)
            if self.rejection_streak >= 2:
                self.killswitch.fire(
                    reason="2_consecutive_rejections",
                    fired_by="auto_abort_rejections",
                )
                self.state = SessionState.ENDED_HANDOFF
            else:
                self.state = SessionState.CONNECTED
            return {"executed": False, "rejection_streak": self.rejection_streak}

        self.rejection_streak = 0
        self.state = SessionState.EXECUTING
        # Hard consent gate (spec §4 requirement 1) — refuse to control
        # without a recorded consent row. In tests / no-DB environments
        # this is a permissive no-op; production deploys require migration
        # 021_remote_sessions.sql applied.
        try:
            await ensure_consent_recorded(self.session_id)
        except ConsentNotRecorded as exc:
            log.warning("consent gate blocked execute session=%s: %s",
                        self.session_id, exc)
            self.killswitch.fire(reason="no_consent", fired_by=FIRED_BY_SERVER)
            self.state = SessionState.ENDED_KILLED
            pending.future.set_result(False)
            return {"executed": False, "blocked": "no_consent"}
        await self.transport.send_event(pending.action.event)
        self.audit.append(
            self.session_id,
            "action_executed",
            {
                "event_kind": pending.action.event.kind.value,
                "x": pending.action.event.x,
                "y": pending.action.event.y,
            },
        )
        self.recorder.write_event("action_executed", {
            "event_kind": pending.action.event.kind.value,
        })
        pending.future.set_result(True)
        self.state = SessionState.CONNECTED
        return {"executed": True, "rejection_streak": 0}

    def record_consent(self, ip_address: str, user_agent: str) -> "ConsentRecord":  # type: ignore[name-defined]
        """Record customer consent. Synchronous side: hash chain entry +
        in-memory mutation. Async side (DB upsert): scheduled on the
        running loop if one exists; otherwise the caller is expected to
        await `persist_consent(record)` themselves.

        Returns the ConsentRecord so the FastAPI handler can echo the
        signature back to the helper for receipt.
        """
        record = make_consent_record(
            session_id=self.session_id,
            customer_email=self.customer_email,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.audit.append(self.session_id, "consent", {
            "consent_text_version": record.consent_text_version,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "signature_sha256": record.signature_sha256,
        })
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(persist_consent(record))
        except RuntimeError:
            log.debug("no running loop — caller must await persist_consent(record)")
        # Once consent is recorded, the session can proceed past
        # PENDING_CONNECT into the active loop. The transport itself is
        # still attached separately via start_remote().
        if self.state == SessionState.PENDING_CONNECT:
            # We don't flip to CONNECTED here — the transport handshake
            # owns that. We just mark it OK for the handshake to begin.
            pass
        return record

    def end(self, outcome: str) -> dict[str, Any]:
        if outcome not in ("fixed", "failed", "handoff"):
            raise ValueError(f"bad outcome: {outcome}")
        self.state = {
            "fixed": SessionState.ENDED_FIXED,
            "failed": SessionState.ENDED_FAILED,
            "handoff": SessionState.ENDED_HANDOFF,
        }[outcome]
        self.audit.append(self.session_id, "session_end", {"outcome": outcome})
        # Graceful end — close the transport synchronously without going
        # through the killswitch (firing it would add an extra
        # killswitch_fired audit row that pollutes the canonical session
        # log). Abnormal terminations route through the killswitch path
        # and DO append the killswitch_fired row.
        self._stop_warmup()
        self._stop_frame_pump()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running() and hasattr(self.transport, "close"):
                loop.create_task(self.transport.close())
        except RuntimeError:
            pass
        summary = self.recorder.close(outcome)
        summary["audit_chain_intact"] = self.audit.verify()
        killswitch_registry().drop(self.session_id)
        return summary


class SessionManager:
    """Holds the live sessions keyed by session_id.

    Singleton pattern — one instance per FastAPI process. G34.6 makes this
    multi-worker safe by promoting state to Postgres + Redis pubsub.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, RemoteSession] = {}

    def create_session(
        self,
        customer_email: str,
        customer_region: str,
        goal: str,
        customer_rustdesk_id: str = "000000000",
    ) -> RemoteSession:
        session_id = uuid.uuid4().hex[:12]
        sess = RemoteSession(
            session_id=session_id,
            customer_email=customer_email,
            customer_region=customer_region,
            customer_rustdesk_id=customer_rustdesk_id,
            goal=goal,
        )
        self._sessions[session_id] = sess
        log.info("session created id=%s region=%s", session_id, customer_region)
        return sess

    def get(self, session_id: str) -> RemoteSession | None:
        return self._sessions.get(session_id)

    def drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    async def start_remote(
        self,
        sess: RemoteSession,
        *,
        prefer_shim: bool | None = None,
        binary: str | None = None,
    ) -> TransportSelection:
        """Async entrypoint that swaps the session's stub transport for the
        factory-chosen one.

        `prefer_shim=None` defers to `$KLX_RDSHIM_BIN`; explicit True forces
        the shim path and propagates `FileNotFoundError` if the binary is
        missing; explicit False is a no-op (the stub already wired in
        `__post_init__` is kept).

        Returns the new `TransportSelection`. The caller is expected to
        call `await sess.transport.connect(cfg)` after this returns.
        """
        from .factory import transport_factory  # local import: avoid cycle

        cfg = ConnectionConfig(
            customer_id=sess.customer_rustdesk_id,
            session_password=sess.session_id,
        )
        transport, selection = await transport_factory(
            cfg, prefer_shim=prefer_shim, binary=binary,
        )
        if selection.kind == "stub":
            # Factory returned the same kind we already wired; just refresh
            # the selection record so the audit log captures the explicit
            # call (the original was implicit at __post_init__ time).
            sess.transport_selection = selection
            return selection
        sess.attach_transport(transport, selection)
        return selection


_manager: SessionManager | None = None


def manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager
