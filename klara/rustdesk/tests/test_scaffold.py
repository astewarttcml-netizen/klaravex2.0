"""Scaffold-level tests for the G34 RustDesk controller.

These tests validate the contracts that downstream iterations (G34.1
protocol, G34.2 vision, G34.3 storage) must continue to honour. They
do NOT cover the librustdesk transport or Anthropic computer-use call —
those are stubbed in the scaffold and covered by integration tests in
the next iteration.

Run: `python3 -m pytest infra/rustdesk_controller/tests -q` from repo root.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# The package lives under infra/ — add it to sys.path so tests run from
# any working directory.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra"))

from rustdesk_controller import (  # noqa: E402
    consent,
    killswitch,
    protocol,
    recording,
    session,
    vision,
    voice_tools,
)


# ── consent / audit chain ──────────────────────────────────────────────────


def test_consent_record_includes_session_id_in_text():
    rec = consent.make_consent_record(
        session_id="abc123",
        customer_email="customer@example.com",
        ip_address="203.0.113.7",
        user_agent="Mozilla/5.0",
    )
    assert "abc123" in rec.consent_text
    assert rec.consent_text_version == consent.CONSENT_TEXT_VERSION


def test_audit_chain_verifies_when_intact():
    log = consent.HashChainAuditLog()
    log.append("s1", "consent", {"ip": "1.1.1.1"})
    log.append("s1", "action_predicted", {"event_kind": "mouse_move"})
    log.append("s1", "action_executed", {"event_kind": "mouse_move"})
    assert log.verify() is True


def test_audit_chain_detects_payload_tamper():
    log = consent.HashChainAuditLog()
    log.append("s1", "consent", {"ip": "1.1.1.1"})
    log.append("s1", "action_predicted", {"event_kind": "mouse_move"})
    log.append("s1", "action_executed", {"event_kind": "mouse_move"})
    log.entries[1].payload["event_kind"] = "paste_text"
    assert log.verify() is False


def test_audit_chain_persists_to_disk(tmp_path):
    sink = tmp_path / "audit.jsonl"
    log = consent.HashChainAuditLog(sink_path=sink)
    log.append("s1", "consent", {"ip": "1.1.1.1"})
    log.append("s1", "session_end", {"outcome": "fixed"})
    assert sink.exists()
    rows = sink.read_text().strip().splitlines()
    assert len(rows) == 2


# ── killswitch ─────────────────────────────────────────────────────────────


def test_killswitch_fire_sets_state_and_metadata():
    ks = killswitch.KillSwitch(session_id="s1")
    assert ks.is_killed is False
    ks.fire(reason="customer_pressed_stop", fired_by="customer_tray")
    assert ks.is_killed is True
    assert ks.reason == "customer_pressed_stop"
    assert ks.fired_by == "customer_tray"
    assert ks.fired_at  # timestamp set


def test_killswitch_second_fire_is_idempotent():
    ks = killswitch.KillSwitch(session_id="s1")
    ks.fire(reason="first", fired_by="server")
    ks.fire(reason="second", fired_by="customer_tray")
    assert ks.reason == "first"
    assert ks.fired_by == "server"


def test_killswitch_wait_returns_after_fire():
    ks = killswitch.KillSwitch(session_id="s1")

    async def runner():
        async def fire_soon():
            await asyncio.sleep(0.01)
            ks.fire(reason="test", fired_by="server")

        await asyncio.gather(fire_soon(), ks.wait())

    asyncio.run(runner())
    assert ks.is_killed is True


# ── protocol contract ──────────────────────────────────────────────────────


def test_protocol_defaults_match_deployed_relay():
    """The deployed Hetzner relay IP + key MUST stay in sync with the docs.
    If the relay is rotated, update DEFAULT_RELAY_HOST/KEY in protocol.py.
    """
    assert protocol.DEFAULT_RELAY_HOST == "87.99.147.244"
    assert protocol.DEFAULT_RELAY_KEY == "E2+699SkYhlEsyjaizRhI+2kuvxxGheisWarfJHbkVA="
    assert protocol.DEFAULT_HBBS_PORT == 21116
    assert protocol.DEFAULT_HBBR_PORT == 21117


def test_input_event_kinds_cover_required_actions():
    """spec §3 requires move / click / scroll / key. Compile-time check the
    enum keeps those names so downstream code is not silently broken by a
    rename."""
    required = {"MOUSE_MOVE", "MOUSE_CLICK", "MOUSE_SCROLL", "KEY_PRESS", "PASTE_TEXT"}
    assert required.issubset({k.name for k in protocol.EventKind})


def test_rustdesk_client_requires_credentials():
    client = protocol.RustDeskClient(protocol.ConnectionConfig())

    async def runner():
        with pytest.raises(ValueError, match="customer_id"):
            await client.connect()

    asyncio.run(runner())


def test_rustdesk_client_stub_connect_with_creds():
    cfg = protocol.ConnectionConfig(customer_id="abc", session_password="pw")
    client = protocol.RustDeskClient(cfg)

    async def runner():
        await client.connect()
        await client.send_event(protocol.InputEvent(kind=protocol.EventKind.MOUSE_MOVE, x=0.5, y=0.5))
        await client.close()

    asyncio.run(runner())


# ── vision ─────────────────────────────────────────────────────────────────


def test_vision_predictor_returns_safe_noop_without_api_key():
    pred = vision.VisionPredictor(api_key="")
    frame = protocol.Frame(
        session_id="s1", sequence=0, width=1024, height=768,
        codec="jpeg", payload=b"x", timestamp_ms=0,
    )

    async def runner():
        return await pred.predict(frame, goal="fix wifi")

    action = asyncio.run(runner())
    assert action.confidence == 0.0
    assert action.low_confidence is True
    assert action.event.kind == protocol.EventKind.MOUSE_MOVE


# ── recording ──────────────────────────────────────────────────────────────


def test_recording_enabled_for_any_region(tmp_path):
    # US-only codebase (refactor 812ade82): customer_region is metadata-only
    # and recording is always enabled. EU-disable was deliberately removed.
    # Register an event for each region; recording must proceed identically.
    for region in ("eu", "us", "other"):
        rec = recording.SessionRecorder(
            session_id=f"s-{region}", customer_email="a@b.com",
            customer_region=region, sink_dir=tmp_path / region,
        )
        assert rec.enabled is True, region
        rec.write_event("test", {"x": 1})
        assert rec.events_written == 1, region
        summary = rec.close("fixed")
        assert summary["enabled"] is True, region


def test_recording_enabled_for_us_region(tmp_path):
    rec = recording.SessionRecorder(
        session_id="s1", customer_email="a@b.com", customer_region="us",
        sink_dir=tmp_path / "s1",
    )
    assert rec.enabled is True
    rec.write_event("consent", {"ip": "1.1.1.1"})
    rec.write_event("action_predicted", {"event_kind": "mouse_move"})
    assert rec.events_written == 2
    summary = rec.close("fixed")
    assert summary["enabled"] is True
    assert summary["events_written"] == 2
    assert (tmp_path / "s1" / "events.jsonl").exists()


# ── session lifecycle ─────────────────────────────────────────────────────


def test_session_manager_creates_and_drops():
    mgr = session.SessionManager()
    sess = mgr.create_session(customer_email="a@b.com", customer_region="us", goal="fix wifi")
    assert mgr.get(sess.session_id) is sess
    mgr.drop(sess.session_id)
    assert mgr.get(sess.session_id) is None


def test_session_end_records_outcome_and_audit_intact():
    mgr = session.SessionManager()
    sess = mgr.create_session(customer_email="a@b.com", customer_region="us", goal="fix wifi")
    sess.record_consent(ip_address="1.1.1.1", user_agent="ua")
    summary = sess.end("fixed")
    assert summary["audit_chain_intact"] is True
    assert sess.state == session.SessionState.ENDED_FIXED


def test_session_end_rejects_unknown_outcome():
    mgr = session.SessionManager()
    sess = mgr.create_session(customer_email="a@b.com", customer_region="us", goal="fix wifi")
    with pytest.raises(ValueError, match="bad outcome"):
        sess.end("merged-to-main")


# ── voice tools router ────────────────────────────────────────────────────


def test_voice_tools_router_registers_four_endpoints():
    """spec §4 demands exactly four Klara tools — guard against accidental
    rename / drop."""
    paths = {r.path for r in voice_tools.router.routes}  # type: ignore[attr-defined]
    assert "/start_rustdesk_session" in paths
    assert "/next_screen_action" in paths
    assert "/confirm_action" in paths
    assert "/end_rustdesk_session" in paths


def test_download_url_encodes_relay_in_filename():
    url = voice_tools._download_url()
    assert "host=87.99.147.244" in url
    assert "key=E2+699SkYhlEsyjaizRhI" in url  # prefix check, key has +/=
    assert url.endswith(".exe")


# ── frame cache + next_screen_action wiring ────────────────────────────────


def _make_frame(session_id: str) -> protocol.Frame:
    return protocol.Frame(
        session_id=session_id, sequence=0, width=1024, height=768,
        codec="jpeg", payload=b"\x00", timestamp_ms=0,
    )


def test_session_cache_frame_stores_latest():
    sess = session.RemoteSession(
        session_id="s-cache", customer_email="a@b.com",
        customer_region="us", goal="fix wifi",
    )
    assert sess.latest_frame is None
    sess.cache_frame(_make_frame("s-cache"))
    assert sess.latest_frame is not None
    assert sess.latest_frame.session_id == "s-cache"
    # Overwrites on second call — only the latest survives.
    second = protocol.Frame(
        session_id="s-cache", sequence=1, width=800, height=600,
        codec="jpeg", payload=b"\x01", timestamp_ms=100,
    )
    sess.cache_frame(second)
    assert sess.latest_frame is second


def _install_manager(monkeypatch, mgr: session.SessionManager) -> None:
    """Pin a SessionManager into the voice_tools module so endpoints see it.

    Uses monkeypatch so pytest restores the prior value automatically even
    if the test raises — avoids leaking the manager into adjacent tests
    (the failure mode behind earlier flaky runs).
    """
    monkeypatch.setattr(session, "_manager", mgr, raising=False)


def test_next_screen_action_returns_awaiting_first_frame_when_cache_empty(monkeypatch):
    mgr = session.SessionManager()
    sess = mgr.create_session(customer_email="a@b.com", customer_region="us", goal="fix wifi")
    _install_manager(monkeypatch, mgr)
    req = voice_tools.NextActionRequest(session_id=sess.session_id)
    result = asyncio.run(voice_tools.next_screen_action(req))
    assert result["status"] == "awaiting_first_frame"
    assert result["awaiting_confirmation"] is False
    assert "first frame" in result["action_description"]


def test_next_screen_action_dispatches_prediction_when_frame_cached(monkeypatch):
    mgr = session.SessionManager()
    sess = mgr.create_session(customer_email="a@b.com", customer_region="us", goal="fix wifi")
    cached = _make_frame(sess.session_id)
    sess.cache_frame(cached)
    _install_manager(monkeypatch, mgr)

    # Spy on request_next_action so we can pin call contract deterministically
    # without relying on asyncio scheduler timing (was a flaky-test gap).
    calls: list[protocol.Frame] = []

    def _spy(frame: protocol.Frame) -> asyncio.Future[bool]:
        calls.append(frame)
        loop = asyncio.get_event_loop()
        return loop.create_future()

    monkeypatch.setattr(sess, "request_next_action", _spy)

    req = voice_tools.NextActionRequest(session_id=sess.session_id)
    result = asyncio.run(voice_tools.next_screen_action(req))

    assert result["status"] == "predicting"
    assert result["awaiting_confirmation"] is False
    assert "G34.1" not in result.get("action_description", "")
    # request_next_action was called exactly once with the cached frame.
    assert len(calls) == 1
    assert calls[0] is cached


def test_next_screen_action_returns_404_for_unknown_session(monkeypatch):
    mgr = session.SessionManager()
    _install_manager(monkeypatch, mgr)
    req = voice_tools.NextActionRequest(session_id="does-not-exist")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(voice_tools.next_screen_action(req))
    assert excinfo.value.status_code == 404


def test_next_screen_action_returns_killed_when_killswitch_fired(monkeypatch):
    mgr = session.SessionManager()
    sess = mgr.create_session(customer_email="a@b.com", customer_region="us", goal="fix wifi")
    sess.cache_frame(_make_frame(sess.session_id))
    sess.killswitch.fire(reason="customer_abort", fired_by="customer")
    _install_manager(monkeypatch, mgr)

    # The dispatch path must not be taken when killed.
    def _explode(frame: protocol.Frame) -> asyncio.Future[bool]:
        raise AssertionError("request_next_action must not run on killed session")

    monkeypatch.setattr(sess, "request_next_action", _explode)

    req = voice_tools.NextActionRequest(session_id=sess.session_id)
    result = asyncio.run(voice_tools.next_screen_action(req))
    assert result["status"] == "killed"
    assert result["awaiting_confirmation"] is False
    assert result["reason"] == "customer_abort"


def test_next_screen_action_returns_awaiting_confirmation_when_pending(monkeypatch):
    """Idempotency on Klara double-poll: a second call while a prediction is
    pending must echo the same pending action, not dispatch a second one."""
    mgr = session.SessionManager()
    sess = mgr.create_session(customer_email="a@b.com", customer_region="us", goal="fix wifi")
    _install_manager(monkeypatch, mgr)

    # Hand-build a PendingConfirmation rather than going through the async
    # vision path so the test is deterministic.
    loop = asyncio.new_event_loop()
    try:
        future: asyncio.Future[bool] = loop.create_future()
        action = vision.PredictedAction(
            event=protocol.InputEvent(
                kind=protocol.EventKind.MOUSE_CLICK, x=0.5, y=0.5, button="left",
            ),
            target_description="the WiFi icon",
            rationale="clicking the WiFi icon to open the menu",
            confidence=0.92,
        )
        sess.pending_confirmation = session.PendingConfirmation(action=action, future=future)

        # Dispatch path must NOT run while a confirmation is already pending.
        def _explode(frame: protocol.Frame) -> asyncio.Future[bool]:
            raise AssertionError("request_next_action must not run when pending")

        monkeypatch.setattr(sess, "request_next_action", _explode)

        req = voice_tools.NextActionRequest(session_id=sess.session_id)
        result = loop.run_until_complete(voice_tools.next_screen_action(req))
    finally:
        loop.close()

    assert result["status"] == "awaiting_confirmation"
    assert result["awaiting_confirmation"] is True
    assert result["action_description"] == "clicking the WiFi icon to open the menu"
    assert result["confidence"] == pytest.approx(0.92)


# ── frame pump: transport.frames() → cache_frame ───────────────────────────


class _FakeTransport:
    """Minimal RustDeskTransport that yields a fixed list of frames then waits.

    Used to test the pump in isolation from the real RustDeskClient (which
    requires connect() and a wire handshake before frames() yields).
    """

    def __init__(self, frames_to_yield: list[protocol.Frame]) -> None:
        self._frames = list(frames_to_yield)
        self._closed = asyncio.Event()
        self.closed_calls = 0

    async def connect(self, cfg):  # pragma: no cover - unused
        return None

    async def frames(self):
        for frame in self._frames:
            yield frame
        # Block until close() is called so the pump task stays alive long
        # enough for the test to assert on cancellation semantics.
        await self._closed.wait()

    async def send_event(self, event):  # pragma: no cover - unused
        return None

    async def close(self):
        self.closed_calls += 1
        self._closed.set()


def _attach_fake_transport(sess: session.RemoteSession, fake: _FakeTransport) -> None:
    """Swap the stub transport for a fake without going through the factory."""
    selection = session.TransportSelection(kind="fake", reason="test")
    sess.attach_transport(fake, selection)


def test_start_frame_pump_drains_transport_into_cache():
    async def _run():
        sess = session.RemoteSession(
            session_id="pump-1", customer_email="a@b.com",
            customer_region="us", goal="fix wifi",
        )
        f1 = _make_frame("pump-1")
        f2 = protocol.Frame(
            session_id="pump-1", sequence=1, width=10, height=10,
            codec="jpeg", payload=b"\x02", timestamp_ms=10,
        )
        fake = _FakeTransport([f1, f2])
        _attach_fake_transport(sess, fake)
        sess.start_frame_pump()
        # Yield until the pump drains both frames. The fake blocks afterwards
        # so the pump stays parked on the close event.
        for _ in range(20):
            await asyncio.sleep(0)
            if sess.latest_frame is f2:
                break
        assert sess.latest_frame is f2
        # Clean shutdown.
        sess._stop_frame_pump()
        await fake.close()
    asyncio.run(_run())


def test_start_frame_pump_is_idempotent():
    async def _run():
        sess = session.RemoteSession(
            session_id="pump-2", customer_email="a@b.com",
            customer_region="us", goal="fix wifi",
        )
        fake = _FakeTransport([])
        _attach_fake_transport(sess, fake)
        first = sess.start_frame_pump()
        second = sess.start_frame_pump()
        assert first is second, "double start must reuse the existing pump task"
        sess._stop_frame_pump()
        await fake.close()
    asyncio.run(_run())


def test_end_cancels_frame_pump():
    async def _run():
        sess = session.RemoteSession(
            session_id="pump-3", customer_email="a@b.com",
            customer_region="us", goal="fix wifi",
        )
        fake = _FakeTransport([])
        _attach_fake_transport(sess, fake)
        task = sess.start_frame_pump()
        assert task is not None
        sess.end("fixed")
        # Give the cancellation a tick to propagate.
        for _ in range(10):
            await asyncio.sleep(0)
            if task.cancelled() or task.done():
                break
        assert task.cancelled() or task.done()
    asyncio.run(_run())


def test_killswitch_stops_frame_pump():
    async def _run():
        sess = session.RemoteSession(
            session_id="pump-4", customer_email="a@b.com",
            customer_region="us", goal="fix wifi",
        )
        fake = _FakeTransport([])
        _attach_fake_transport(sess, fake)
        task = sess.start_frame_pump()
        sess.killswitch.fire(reason="test", fired_by="customer")
        for _ in range(10):
            await asyncio.sleep(0)
            if task.cancelled() or task.done():
                break
        assert task.cancelled() or task.done()
        # Killswitch's _on_kill hook sequences _stop_frame_pump() THEN
        # `await transport.close()`. Regression-lock the close-on-kill
        # ordering: if a future refactor drops the close() call or runs it
        # before pump cancellation, closed_calls will not be 1.
        assert fake.closed_calls == 1
    asyncio.run(_run())


# ── frame pump: error swallow + audit + lifecycle edge cases ────────────────


class _RaisingTransport(_FakeTransport):
    """Transport whose frames() yields one frame then raises mid-stream.

    Used to verify the pump's exception-swallow branch: a transport that
    crashes mid-iteration MUST NOT bubble into the FastAPI worker. The
    pump task transitions to done (not exception=raised) and the session
    remains usable.
    """

    def __init__(self, frames_to_yield, exc: Exception) -> None:
        super().__init__(frames_to_yield)
        self._exc = exc

    async def frames(self):
        for frame in self._frames:
            yield frame
        raise self._exc


class _NaturalEndTransport(_FakeTransport):
    """Transport whose frames() yields a fixed list then returns (no park).

    Models a real transport that closes its async iterator gracefully.
    The pump should exit with task.done() is True and exception() is None.
    """

    async def frames(self):
        for frame in self._frames:
            yield frame
        # No park — the async generator returns naturally.


async def _drain_until(predicate, *, ticks: int = 50) -> bool:
    for _ in range(ticks):
        await asyncio.sleep(0)
        if predicate():
            return True
    return False


def test_pump_swallows_transport_exception():
    async def _run():
        sess = session.RemoteSession(
            session_id="pump-err-1", customer_email="a@b.com",
            customer_region="us", goal="fix wifi",
        )
        f1 = _make_frame("pump-err-1")
        fake = _RaisingTransport([f1], RuntimeError("transport blew up"))
        _attach_fake_transport(sess, fake)
        task = sess.start_frame_pump()
        # Pump must (a) drain the first frame into cache, (b) catch the
        # RuntimeError, (c) end with task.done() and no exception bubbling.
        drained = await _drain_until(lambda: task.done())
        assert drained, "pump did not exit after transport raise"
        assert task.exception() is None, "exception leaked out of pump"
        assert sess.latest_frame is f1
        # Session remains usable — calls into request_next_action would
        # still be accepted (killswitch unfired, no pending confirmation).
        assert not sess.killswitch.is_killed
        await fake.close()
    asyncio.run(_run())


def test_pump_natural_completion_leaves_task_done_clean():
    async def _run():
        sess = session.RemoteSession(
            session_id="pump-nat-1", customer_email="a@b.com",
            customer_region="us", goal="fix wifi",
        )
        f1 = _make_frame("pump-nat-1")
        fake = _NaturalEndTransport([f1])
        _attach_fake_transport(sess, fake)
        task = sess.start_frame_pump()
        done = await _drain_until(lambda: task.done())
        assert done, "pump did not exit when frames() returned"
        assert task.exception() is None
        assert not task.cancelled()
        assert sess.latest_frame is f1
    asyncio.run(_run())


def test_start_frame_pump_emits_audit_row_with_transport_kind():
    async def _run():
        sess = session.RemoteSession(
            session_id="pump-audit-1", customer_email="a@b.com",
            customer_region="us", goal="fix wifi",
        )
        fake = _FakeTransport([])
        _attach_fake_transport(sess, fake)
        sess.start_frame_pump()
        rows = [
            e for e in sess.audit.entries
            if e.event_type == "frame_pump_started"
        ]
        assert len(rows) == 1, "frame_pump_started audit row missing"
        assert rows[0].payload == {"transport_kind": "fake"}
        sess._stop_frame_pump()
        await fake.close()
    asyncio.run(_run())


def test_stop_frame_pump_is_safe_before_start():
    """`_stop_frame_pump()` must be a no-op when no pump task exists.

    Covers the `task is None` early-return branch — exercised in real
    sessions where end() is invoked on a session that never had its pump
    started (e.g. abort during PENDING_CONNECT before consent).
    """
    sess = session.RemoteSession(
        session_id="pump-stop-1", customer_email="a@b.com",
        customer_region="us", goal="fix wifi",
    )
    assert sess.frame_pump_task is None
    sess._stop_frame_pump()  # must not raise
    assert sess.frame_pump_task is None


def test_stop_frame_pump_is_safe_after_killswitch_then_end():
    """end() after killswitch.fire() must not re-cancel a cleared task.

    Realistic sequence: killswitch fires → _on_kill cancels the pump and
    clears the field → caller still invokes end("handoff"). end() must
    enter `_stop_frame_pump()` on a None task and return cleanly.
    """
    async def _run():
        sess = session.RemoteSession(
            session_id="pump-stop-2", customer_email="a@b.com",
            customer_region="us", goal="fix wifi",
        )
        fake = _FakeTransport([])
        _attach_fake_transport(sess, fake)
        task = sess.start_frame_pump()
        sess.killswitch.fire(reason="test", fired_by="customer")
        await _drain_until(lambda: task.cancelled() or task.done())
        # field is cleared by _stop_frame_pump on the kill path
        assert sess.frame_pump_task is None
        # Now end() must also tolerate the cleared field
        summary = sess.end("handoff")
        assert summary["audit_chain_intact"] is True
    asyncio.run(_run())


def test_start_remote_does_not_auto_start_frame_pump():
    """Regression-lock: SessionManager.start_remote() MUST NOT spawn the
    pump. The pump is caller-owned because transport.frames() requires
    connect() to have been called first (Pattern 19).
    """
    async def _run():
        mgr = session.SessionManager()
        sess = mgr.create_session(
            customer_email="a@b.com", customer_region="us", goal="fix wifi",
        )
        # Defaults to stub transport (no shim binary required in tests).
        await mgr.start_remote(sess, prefer_shim=False)
        assert sess.frame_pump_task is None, (
            "start_remote() must not auto-start the frame pump"
        )
    asyncio.run(_run())


# ── voice tool warmup wiring (Pattern 19 producer side) ────────────────────


def test_start_rustdesk_session_schedules_warmup_task(monkeypatch):
    """Producer-side wiring: the voice tool MUST schedule sess.warmup_task
    and return its task name so observability tooling can correlate the
    background warmup with the voice-call session_id.
    """
    mgr = session.SessionManager()
    _install_manager(monkeypatch, mgr)

    async def _run():
        req = voice_tools.StartRequest(
            customer_email="caller@example.com",
            problem_summary="my wifi is broken",
            customer_region="us",
            customer_rustdesk_id="123456789",
        )
        result = await voice_tools.start_rustdesk_session(req)
        sess = mgr.get(result["session_id"])
        assert sess is not None
        assert sess.warmup_task is not None
        assert result["warmup_task_name"] == sess.warmup_task.get_name()
        assert result["warmup_task_name"].startswith("warmup-")
        assert result["customer_rustdesk_id"] == "123456789"
        # Drain the warmup so the task doesn't leak between tests. With no
        # shim binary configured the warmup hits the stub branch and exits
        # cleanly without starting the pump.
        await sess.warmup_task
        assert sess.warmup_task.done()
        assert sess.warmup_task.exception() is None
        assert sess.frame_pump_task is None, (
            "stub-path warmup must not start the pump"
        )
    asyncio.run(_run())


def test_warmup_skips_pump_on_stub_transport(monkeypatch):
    """Stub-transport branch: when start_remote returns kind='stub' (the CI
    / no-$KLX_RDSHIM_BIN path), _warmup_transport MUST exit without
    starting the frame pump. Starting it on the stub would crash on the
    first iteration of RustDeskClient.frames() with "connect() first".
    """
    mgr = session.SessionManager()
    _install_manager(monkeypatch, mgr)
    sess = mgr.create_session(
        customer_email="a@b.com", customer_region="us", goal="fix wifi",
    )

    async def _run():
        await voice_tools._warmup_transport(sess)
        assert sess.frame_pump_task is None
    asyncio.run(_run())


def test_warmup_starts_pump_on_shim_transport(monkeypatch):
    """Shim-transport branch: when start_remote returns kind != 'stub',
    _warmup_transport MUST call transport.connect(cfg) and then start the
    frame pump. We swap start_remote with a stub that attaches a
    _FakeTransport and returns kind='shim' so the production code path
    runs without spawning a real subprocess.
    """
    mgr = session.SessionManager()
    _install_manager(monkeypatch, mgr)
    sess = mgr.create_session(
        customer_email="a@b.com", customer_region="us", goal="fix wifi",
    )
    fake = _FakeTransport([_make_frame(sess.session_id)])
    connect_calls: list[object] = []

    original_connect = fake.connect

    async def _spy_connect(cfg):
        connect_calls.append(cfg)
        return await original_connect(cfg)

    fake.connect = _spy_connect  # type: ignore[assignment]

    async def _fake_start_remote(target_sess, **kwargs):
        selection = session.TransportSelection(
            kind="shim", reason="test-shim", binary="/fake/klx-rdshim",
        )
        target_sess.attach_transport(fake, selection)
        return selection

    monkeypatch.setattr(mgr, "start_remote", _fake_start_remote)

    async def _run():
        await voice_tools._warmup_transport(sess)
        assert len(connect_calls) == 1, (
            "warmup must call transport.connect(cfg) on the shim path"
        )
        assert sess.frame_pump_task is not None
        assert not sess.frame_pump_task.done()
        # Audit-row side effects (iter-39): transport_attached fires from
        # attach_transport, warmup_completed fires from _warmup_transport
        # itself. Pin both — a refactor that drops either should break
        # the post-mortem dashboard, which means it should break this test.
        event_types = [e.event_type for e in sess.audit.entries]
        assert "transport_attached" in event_types
        assert "warmup_completed" in event_types
        completed = next(
            e for e in sess.audit.entries if e.event_type == "warmup_completed"
        )
        assert completed.payload == {"transport_kind": "shim"}
        # Drain the pump so it cancels cleanly.
        sess._stop_frame_pump()
        await fake.close()
    asyncio.run(_run())


def test_session_end_cancels_warmup_task():
    """end() must cancel a still-running warmup task so background work
    doesn't leak past session lifetime. The warmup may be parked on
    start_remote() or transport.connect() when the caller invokes end().
    """
    async def _run():
        sess = session.RemoteSession(
            session_id="warmup-end-1", customer_email="a@b.com",
            customer_region="us", goal="fix wifi",
        )
        # A coroutine that parks forever — simulates start_remote hanging
        # on a subprocess spawn that never completes.
        async def _parked():
            await asyncio.Event().wait()

        sess.warmup_task = asyncio.create_task(_parked(), name="warmup-test")
        # Yield once so the task is actually scheduled.
        await asyncio.sleep(0)
        assert not sess.warmup_task.done()

        summary = sess.end("handoff")
        await _drain_until(
            lambda: sess.warmup_task is None or sess.warmup_task.done()
        )
        # _stop_warmup clears the field on the cancel path.
        assert sess.warmup_task is None
        assert summary["audit_chain_intact"] is True
    asyncio.run(_run())


def test_killswitch_cancels_warmup_task():
    """Killswitch's _on_kill hook must cancel the warmup task as well as
    the frame pump — the warmup may be parked on transport.connect() when
    the customer hits STOP before the helper has handshaken.
    """
    async def _run():
        sess = session.RemoteSession(
            session_id="warmup-kill-1", customer_email="a@b.com",
            customer_region="us", goal="fix wifi",
        )

        async def _parked():
            await asyncio.Event().wait()

        sess.warmup_task = asyncio.create_task(_parked(), name="warmup-test")
        await asyncio.sleep(0)
        assert not sess.warmup_task.done()

        sess.killswitch.fire(reason="customer_stop", fired_by="customer")
        await _drain_until(
            lambda: sess.warmup_task is None or sess.warmup_task.done()
        )
        assert sess.warmup_task is None
    asyncio.run(_run())


def test_warmup_swallows_generic_exception(monkeypatch):
    """iter-38 code-review High: the `except Exception` branch in
    _warmup_transport MUST swallow start_remote / connect errors to a warn
    log so a bad shim binary doesn't crash the FastAPI worker on the next
    event-loop tick via an un-retrieved task exception.
    """
    mgr = session.SessionManager()
    _install_manager(monkeypatch, mgr)
    sess = mgr.create_session(
        customer_email="a@b.com", customer_region="us", goal="fix wifi",
    )

    async def _exploding_start_remote(target_sess, **kwargs):
        raise FileNotFoundError("klx-rdshim binary missing")

    monkeypatch.setattr(mgr, "start_remote", _exploding_start_remote)

    async def _run():
        # Run as a task so we can assert task.exception() — direct await
        # would let the exception propagate before we could inspect it.
        task = asyncio.create_task(voice_tools._warmup_transport(sess))
        await task
        assert task.done()
        assert task.exception() is None, (
            "warmup must swallow start_remote errors; got " f"{task.exception()!r}"
        )
        assert sess.frame_pump_task is None
    asyncio.run(_run())


def test_warmup_reraises_cancelled_error_mid_flight(monkeypatch):
    """iter-38 code-review High: the `except CancelledError: raise` branch
    MUST re-raise cleanly when the warmup is cancelled mid-flight. Without
    this guard a future refactor that demotes CancelledError to swallow
    would silently absorb cancellation and leave the warmup task in a
    'done with no exception' state — looks like success in dashboards.
    """
    mgr = session.SessionManager()
    _install_manager(monkeypatch, mgr)
    sess = mgr.create_session(
        customer_email="a@b.com", customer_region="us", goal="fix wifi",
    )

    parked = asyncio.Event()

    async def _hanging_start_remote(target_sess, **kwargs):
        await parked.wait()  # parks until the test cancels the task
        return session.TransportSelection(kind="stub", reason="never-returned")

    monkeypatch.setattr(mgr, "start_remote", _hanging_start_remote)

    async def _run():
        task = asyncio.create_task(voice_tools._warmup_transport(sess))
        await asyncio.sleep(0)  # let task park inside start_remote
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()
        # pump must not have started: cancellation hit before the connect
        # branch ran.
        assert sess.frame_pump_task is None
    asyncio.run(_run())


def test_warmup_skipped_stub_emits_audit_row(monkeypatch):
    """iter-39: post-mortem dashboards need to distinguish 'warmup never
    ran' from 'warmup ran and skipped because stub transport'. The stub
    branch MUST emit warmup_skipped_stub with the factory's reason string
    so SREs can correlate stub-mode sessions with the env-var that
    triggered them.
    """
    mgr = session.SessionManager()
    _install_manager(monkeypatch, mgr)
    sess = mgr.create_session(
        customer_email="a@b.com", customer_region="us", goal="fix wifi",
    )

    async def _run():
        await voice_tools._warmup_transport(sess)
        rows = [e for e in sess.audit.entries if e.event_type == "warmup_skipped_stub"]
        assert len(rows) == 1
        assert "reason" in rows[0].payload
        assert rows[0].payload["reason"]  # non-empty
        assert sess.frame_pump_task is None
    asyncio.run(_run())


def test_warmup_failed_emits_audit_row_with_error_type(monkeypatch):
    """iter-39: when warmup raises, log + warn is not enough — the post
    mortem dashboard reads sess.audit.entries, not the FastAPI worker log.
    The warmup_failed row MUST carry error_type so dashboards can
    aggregate by exception class without parsing strings.
    """
    mgr = session.SessionManager()
    _install_manager(monkeypatch, mgr)
    sess = mgr.create_session(
        customer_email="a@b.com", customer_region="us", goal="fix wifi",
    )

    async def _exploding_start_remote(target_sess, **kwargs):
        raise FileNotFoundError("klx-rdshim binary missing")

    monkeypatch.setattr(mgr, "start_remote", _exploding_start_remote)

    async def _run():
        await voice_tools._warmup_transport(sess)
        rows = [e for e in sess.audit.entries if e.event_type == "warmup_failed"]
        assert len(rows) == 1
        assert rows[0].payload["error_type"] == "FileNotFoundError"
        assert "klx-rdshim binary missing" in rows[0].payload["error"]
    asyncio.run(_run())


def test_warmup_failed_truncates_oversized_error_message(monkeypatch):
    """iter-39 hardening: an audit row payload must not balloon past the
    row size budget on a pathological transport exception. The 512-char
    truncation is the cheap defence — a misbehaving shim that puts a
    megabyte of detail in str(exc) shouldn't break the hash chain.
    """
    mgr = session.SessionManager()
    _install_manager(monkeypatch, mgr)
    sess = mgr.create_session(
        customer_email="a@b.com", customer_region="us", goal="fix wifi",
    )

    huge = "X" * 10_000

    async def _exploding_start_remote(target_sess, **kwargs):
        raise RuntimeError(huge)

    monkeypatch.setattr(mgr, "start_remote", _exploding_start_remote)

    async def _run():
        await voice_tools._warmup_transport(sess)
        rows = [e for e in sess.audit.entries if e.event_type == "warmup_failed"]
        assert len(rows) == 1
        assert len(rows[0].payload["error"]) == 512
    asyncio.run(_run())


def test_warmup_aborted_killswitch_emits_audit_row(monkeypatch):
    """iter-39: the race-guard branch (killswitch fires during connect)
    must surface itself on the hash chain. A silent skip would let a
    refactor that drops the guard look identical to a healthy run in
    audit logs — the regression would be invisible until production
    repro'd the leak Mistake #25 documents.
    """
    mgr = session.SessionManager()
    _install_manager(monkeypatch, mgr)
    sess = mgr.create_session(
        customer_email="a@b.com", customer_region="us", goal="fix wifi",
    )
    fake = _FakeTransport([])

    async def _connect_then_kill(cfg):
        sess.killswitch.fire(reason="race", fired_by="customer")
        return None

    fake.connect = _connect_then_kill  # type: ignore[assignment]

    async def _fake_start_remote(target_sess, **kwargs):
        selection = session.TransportSelection(
            kind="shim", reason="test", binary="/fake",
        )
        target_sess.attach_transport(fake, selection)
        return selection

    monkeypatch.setattr(mgr, "start_remote", _fake_start_remote)

    async def _run():
        await voice_tools._warmup_transport(sess)
        rows = [
            e for e in sess.audit.entries
            if e.event_type == "warmup_aborted_killswitch"
        ]
        assert len(rows) == 1
        assert rows[0].payload["reason"] == "race"
        assert sess.frame_pump_task is None
    asyncio.run(_run())


# ── iter-40: warmup_state / frame_pump_state observability derivations ────


def test_warmup_state_absent_when_no_audit_no_task():
    sess = session.RemoteSession(
        session_id="ws-1", customer_email="a@b.com",
        customer_region="us", goal="fix wifi",
    )
    assert sess.warmup_state() == "absent"


def test_warmup_state_running_when_task_alive_no_terminal_row():
    async def _run():
        sess = session.RemoteSession(
            session_id="ws-2", customer_email="a@b.com",
            customer_region="us", goal="fix wifi",
        )

        async def _parked():
            await asyncio.Event().wait()

        sess.warmup_task = asyncio.create_task(_parked(), name="warmup-test")
        await asyncio.sleep(0)
        try:
            assert sess.warmup_state() == "running"
        finally:
            sess.warmup_task.cancel()
    asyncio.run(_run())


def test_warmup_state_skipped_stub_from_audit_row():
    sess = session.RemoteSession(
        session_id="ws-3", customer_email="a@b.com",
        customer_region="us", goal="fix wifi",
    )
    sess.audit.append(sess.session_id, "warmup_skipped_stub", {"reason": "no shim"})
    assert sess.warmup_state() == "skipped_stub"


def test_warmup_state_completed_from_audit_row():
    sess = session.RemoteSession(
        session_id="ws-4", customer_email="a@b.com",
        customer_region="us", goal="fix wifi",
    )
    sess.audit.append(sess.session_id, "warmup_completed", {"transport_kind": "shim"})
    assert sess.warmup_state() == "completed"


def test_warmup_state_failed_from_audit_row():
    sess = session.RemoteSession(
        session_id="ws-5", customer_email="a@b.com",
        customer_region="us", goal="fix wifi",
    )
    sess.audit.append(
        sess.session_id, "warmup_failed",
        {"error_type": "RuntimeError", "error": "boom"},
    )
    assert sess.warmup_state() == "failed"


def test_warmup_state_aborted_killswitch_from_audit_row():
    sess = session.RemoteSession(
        session_id="ws-6", customer_email="a@b.com",
        customer_region="us", goal="fix wifi",
    )
    sess.audit.append(
        sess.session_id, "warmup_aborted_killswitch", {"reason": "test"},
    )
    assert sess.warmup_state() == "aborted_killswitch"


def test_warmup_state_most_recent_terminal_wins_on_retry():
    """If a future retry supervisor re-runs warmup after a failure, the
    most recent terminal row should be the surfaced state — otherwise
    dashboards would show the session as 'failed' forever even after a
    successful retry. Lock this even though no retry supervisor exists
    yet (Pattern 19 forecasts this future change).
    """
    sess = session.RemoteSession(
        session_id="ws-7", customer_email="a@b.com",
        customer_region="us", goal="fix wifi",
    )
    sess.audit.append(sess.session_id, "warmup_failed", {"error_type": "X", "error": "x"})
    sess.audit.append(sess.session_id, "warmup_completed", {"transport_kind": "shim"})
    assert sess.warmup_state() == "completed"


def test_warmup_state_ignores_non_terminal_warmup_prefixed_rows():
    """iter-42 Test Analyzer High #1: warmup_state() does exact-match
    against the 4-key terminal set. A hypothetical warmup_started or
    warmup_retrying row MUST NOT be picked up — only the documented
    terminal event types resolve to a dashboard state. Pin the exact
    semantics so a future refactor that over-broadens the filter (e.g.
    to .startswith("warmup_")) breaks the test loudly rather than
    silently changing dashboard behavior.
    """
    sess = session.RemoteSession(
        session_id="ws-non-term", customer_email="a@b.com",
        customer_region="us", goal="fix wifi",
    )
    # Non-terminal warmup_-prefixed rows that future code might add.
    sess.audit.append(sess.session_id, "warmup_started", {})
    sess.audit.append(sess.session_id, "warmup_retrying", {"attempt": 2})
    # No terminal row → state is "absent" (task is None).
    assert sess.warmup_state() == "absent"


def test_warmup_failed_audit_append_failure_is_swallowed(monkeypatch):
    """iter-42 Test Analyzer High #2: the nested try/except around the
    warmup_failed audit.append (voice_tools.py) is the last line of
    defence against a failure-path side effect failing invisibly. If
    audit.append itself raises (disk full, hash chain breakage), the
    warmup task MUST NOT end with an unhandled exception — that would
    just hit asyncio's "Task exception was never retrieved" path,
    exactly the failure mode Patterns 21 + 26 codified against.
    """
    mgr = session.SessionManager()
    _install_manager(monkeypatch, mgr)
    sess = mgr.create_session(
        customer_email="a@b.com", customer_region="us", goal="fix wifi",
    )

    async def _exploding_start_remote(target_sess, **kwargs):
        raise RuntimeError("transport spawn failed")

    monkeypatch.setattr(mgr, "start_remote", _exploding_start_remote)

    original_append = sess.audit.append

    def _append_or_explode(session_id, event_type, payload):
        if event_type == "warmup_failed":
            raise RuntimeError("hash chain sink full")
        return original_append(session_id, event_type, payload)

    monkeypatch.setattr(sess.audit, "append", _append_or_explode)

    async def _run():
        # If the nested try/except is removed, this would propagate
        # RuntimeError out of _warmup_transport and the asyncio.create_task
        # wrapper would log "Task exception was never retrieved".
        task = asyncio.create_task(voice_tools._warmup_transport(sess))
        await task
        assert task.done()
        assert task.exception() is None, (
            "nested audit failure must not escape the warmup task"
        )
    asyncio.run(_run())


def test_on_kill_emits_warmup_aborted_when_warmup_alive():
    """iter-42 code-review High: when killswitch fires with a parked
    warmup task (parked on start_remote() or connect() before reaching
    the in-warmup race guard), the kill hook MUST emit
    warmup_aborted_killswitch so warmup_state() resolves to
    "aborted_killswitch" rather than the silent "absent" fallback.
    """
    async def _run():
        sess = session.RemoteSession(
            session_id="kill-warmup-alive", customer_email="a@b.com",
            customer_region="us", goal="fix wifi",
        )

        async def _parked():
            await asyncio.Event().wait()

        sess.warmup_task = asyncio.create_task(_parked(), name="warmup-parked")
        await asyncio.sleep(0)
        assert not sess.warmup_task.done()

        sess.killswitch.fire(reason="customer_stop", fired_by="customer")
        await _drain_until(
            lambda: sess.warmup_task is None or sess.warmup_task.done()
        )

        # The new row from _on_kill must exist and warmup_state must
        # report the correct terminal state.
        rows = [
            e for e in sess.audit.entries
            if e.event_type == "warmup_aborted_killswitch"
        ]
        assert len(rows) == 1
        assert rows[0].payload["reason"] == "customer_stop"
        assert sess.warmup_state() == "aborted_killswitch"
    asyncio.run(_run())


# ── iter-44 / migration-023 DRAFT: warmup state persistence ───────────────


class _FakePersistConn:
    """Captures execute() calls to UPDATE klaravex_remote_sessions."""

    def __init__(self, raise_undef: bool = False) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self._raise_undef = raise_undef

    async def execute(self, query: str, *args) -> None:
        if self._raise_undef:
            # Simulate UndefinedColumnError before migration 023 applies.
            raise RuntimeError("column \"warmup_state\" does not exist")
        self.calls.append((query, args))


class _FakePersistPool:
    def __init__(self, conn: _FakePersistConn) -> None:
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *exc):
                return None

        return _Ctx()


def _install_fake_persist_pool(monkeypatch, *, raise_undef: bool = False):
    """Monkeypatch the klara.handlers.lib.db.get_pool that
    _persist_warmup_state lazy-imports. Returns the fake conn so tests
    can introspect the execute() calls.
    """
    conn = _FakePersistConn(raise_undef=raise_undef)
    pool = _FakePersistPool(conn)

    async def _fake_get_pool():
        return pool

    import sys
    db_mod_name = "klara.handlers.lib.db"
    if db_mod_name in sys.modules:
        monkeypatch.setattr(sys.modules[db_mod_name], "get_pool", _fake_get_pool)
    else:
        # Fabricate a minimal stub module so the lazy import succeeds.
        import types
        stub = types.ModuleType(db_mod_name)
        stub.get_pool = _fake_get_pool
        sys.modules[db_mod_name] = stub
        # Ensure parent packages exist as importable.
        for parent in ("klara.handlers", "klara.handlers.lib"):
            if parent not in sys.modules:
                sys.modules[parent] = types.ModuleType(parent)
        monkeypatch.setitem(sys.modules, db_mod_name, stub)
    return conn


def test_persist_warmup_state_writes_completed_row(monkeypatch):
    """iter-44 DRAFT: the completed-path persists a row with state +
    completed_at to klaravex_remote_sessions. The UPDATE uses COALESCE so
    a retry doesn't overwrite the first completion timestamp.
    """
    conn = _install_fake_persist_pool(monkeypatch)

    async def _run():
        await voice_tools._persist_warmup_state("sess-1", "completed")
        assert len(conn.calls) == 1
        query, args = conn.calls[0]
        assert "UPDATE klaravex_remote_sessions" in query
        assert "warmup_state" in query
        assert args[0] == "completed"
        assert args[2] is None  # error_type
        assert args[3] is None  # error_message
        assert args[4] == "sess-1"
    asyncio.run(_run())


def test_persist_warmup_state_writes_failed_with_error_columns(monkeypatch):
    """Failure path persists error_type + error_message alongside the state."""
    conn = _install_fake_persist_pool(monkeypatch)

    async def _run():
        await voice_tools._persist_warmup_state(
            "sess-2", "failed",
            error_type="FileNotFoundError",
            error_message="klx-rdshim missing",
        )
        assert len(conn.calls) == 1
        _, args = conn.calls[0]
        assert args[0] == "failed"
        assert args[2] == "FileNotFoundError"
        assert args[3] == "klx-rdshim missing"
    asyncio.run(_run())


def test_persist_warmup_state_swallows_undefined_column_pre_migration(monkeypatch):
    """DEPLOY-SAFETY contract: if the migration-023 columns don't exist
    yet, the UPDATE raises (simulated UndefinedColumnError) and
    _persist_warmup_state MUST swallow to a log without propagating.
    This is the load-bearing test that lets iter-44 ship to staging
    BEFORE migration-023 applies.
    """
    _install_fake_persist_pool(monkeypatch, raise_undef=True)

    async def _run():
        # Must not raise.
        await voice_tools._persist_warmup_state("sess-3", "completed")
    asyncio.run(_run())


def test_persist_warmup_state_swallows_missing_db_module(monkeypatch):
    """If klara.handlers.lib.db is not importable (test env, dev box
    without the klara.handlers package), the helper is a soft no-op."""
    import sys
    # Remove the module to force ImportError on the lazy import.
    for mod in list(sys.modules.keys()):
        if mod.startswith("klara.handlers"):
            monkeypatch.delitem(sys.modules, mod, raising=False)

    # Also block re-import by inserting a finder that refuses
    # klara.handlers — simpler: monkeypatch builtins __import__ to raise
    # ImportError for the target path. Cleanest is just to delete and
    # rely on the fact that klara.handlers isn't on the rustdesk_controller
    # test sys.path by default. If it IS already imported and on path,
    # this test degrades into "no execute call" which is also fine.
    async def _run():
        await voice_tools._persist_warmup_state("sess-4", "completed")
    asyncio.run(_run())


def test_warmup_completed_path_invokes_persistence(monkeypatch):
    """End-to-end on the persistence wiring: a successful warmup
    (shim-kind, connect succeeds, pump starts) MUST trigger
    _persist_warmup_state('completed') exactly once."""
    mgr = session.SessionManager()
    _install_manager(monkeypatch, mgr)
    sess = mgr.create_session(
        customer_email="a@b.com", customer_region="us", goal="fix wifi",
    )
    fake = _FakeTransport([])

    async def _fake_start_remote(target_sess, **kwargs):
        selection = session.TransportSelection(
            kind="shim", reason="test", binary="/fake",
        )
        target_sess.attach_transport(fake, selection)
        return selection

    monkeypatch.setattr(mgr, "start_remote", _fake_start_remote)

    persist_calls: list[tuple[str, str]] = []

    async def _spy_persist(session_id, state, **kwargs):
        persist_calls.append((session_id, state))

    monkeypatch.setattr(voice_tools, "_persist_warmup_state", _spy_persist)

    async def _run():
        await voice_tools._warmup_transport(sess)
        assert persist_calls == [(sess.session_id, "completed")]
        sess._stop_frame_pump()
        await fake.close()
    asyncio.run(_run())


def test_warmup_failed_path_invokes_persistence_with_error(monkeypatch):
    """Failure path must call _persist_warmup_state('failed', ...) with
    error_type and a truncated error_message."""
    mgr = session.SessionManager()
    _install_manager(monkeypatch, mgr)
    sess = mgr.create_session(
        customer_email="a@b.com", customer_region="us", goal="fix wifi",
    )

    async def _exploding(target_sess, **kwargs):
        raise FileNotFoundError("shim missing")

    monkeypatch.setattr(mgr, "start_remote", _exploding)

    persist_calls: list[dict] = []

    async def _spy_persist(session_id, state, **kwargs):
        persist_calls.append({"session_id": session_id, "state": state, **kwargs})

    monkeypatch.setattr(voice_tools, "_persist_warmup_state", _spy_persist)

    async def _run():
        await voice_tools._warmup_transport(sess)
        assert len(persist_calls) == 1
        call = persist_calls[0]
        assert call["state"] == "failed"
        assert call["error_type"] == "FileNotFoundError"
        assert call["error_message"] == "shim missing"
    asyncio.run(_run())


def test_warmup_aborted_killswitch_emits_when_kill_fires_pre_connect(monkeypatch):
    """iter-43 coverage-gap close: iter-42 added _on_kill emission of
    warmup_aborted_killswitch when warmup_task is alive. The "alive"
    case covers both before-start_remote and between-attach-and-connect
    windows. Existing tests park warmup on Event().wait() — they don't
    exercise the realistic case where the warmup is parked specifically
    on `await sess.transport.connect(cfg)` AFTER start_remote attached
    the transport. This test drives that exact interleaving: start_remote
    attaches a fake transport, connect() parks forever, kill fires while
    parked → assert warmup_aborted_killswitch row + warmup_state.

    The pre-connect / parked-on-connect window is the most likely real
    production race: a slow handshake to the shim subprocess while the
    customer hits STOP. Without this test, a refactor that moves the
    warmup_aborted_killswitch emission INTO _warmup_transport's
    is_killed branch only (dropping the _on_kill emission) would still
    pass the existing parked-on-Event tests but regress production.
    """
    mgr = session.SessionManager()
    _install_manager(monkeypatch, mgr)
    sess = mgr.create_session(
        customer_email="a@b.com", customer_region="us", goal="fix wifi",
    )

    parked_in_connect = asyncio.Event()
    released = asyncio.Event()
    fake = _FakeTransport([])

    async def _parking_connect(cfg):
        # Signal the test we're parked, then wait until released so the
        # kill can land while we're suspended inside connect().
        parked_in_connect.set()
        await released.wait()
        return None

    fake.connect = _parking_connect  # type: ignore[assignment]

    async def _fake_start_remote(target_sess, **kwargs):
        selection = session.TransportSelection(
            kind="shim", reason="test", binary="/fake",
        )
        target_sess.attach_transport(fake, selection)
        return selection

    monkeypatch.setattr(mgr, "start_remote", _fake_start_remote)

    async def _run():
        warmup = asyncio.create_task(voice_tools._warmup_transport(sess))
        sess.warmup_task = warmup

        # Wait until the warmup is suspended INSIDE connect — proves the
        # transport was attached but the connect handshake hasn't
        # completed. This is the pre-connect race window.
        await asyncio.wait_for(parked_in_connect.wait(), timeout=1.0)
        assert not warmup.done()

        # Fire the killswitch while warmup is parked in connect.
        sess.killswitch.fire(reason="pre_connect_stop", fired_by="customer")
        # Let the kill hook coroutine run.
        await _drain_until(lambda: warmup.done() or warmup.cancelled())
        # Release the connect park so cleanup completes — also tolerates
        # the case where cancellation reached connect.
        released.set()
        try:
            await warmup
        except asyncio.CancelledError:
            pass

        # _on_kill must have emitted the row before _stop_warmup cleared
        # the task field. warmup_state must resolve to aborted_killswitch
        # via the new row, not "absent".
        rows = [
            e for e in sess.audit.entries
            if e.event_type == "warmup_aborted_killswitch"
        ]
        assert len(rows) >= 1
        assert rows[0].payload["reason"] == "pre_connect_stop"
        assert sess.warmup_state() == "aborted_killswitch"
        # Pump never started (we cancelled before reaching start_frame_pump).
        assert sess.frame_pump_task is None
    asyncio.run(_run())


def test_on_kill_does_not_emit_warmup_aborted_when_warmup_already_done():
    """Symmetry test: if the warmup task already completed (done) before
    the kill fires, _on_kill must NOT emit a phantom
    warmup_aborted_killswitch row — that would corrupt the truth table
    (a session that successfully warmed up would later look aborted).
    """
    async def _run():
        sess = session.RemoteSession(
            session_id="kill-warmup-done", customer_email="a@b.com",
            customer_region="us", goal="fix wifi",
        )

        async def _finished():
            return None

        sess.warmup_task = asyncio.create_task(_finished(), name="warmup-done")
        await sess.warmup_task
        assert sess.warmup_task.done()
        # Simulate a warmup that completed successfully on the shim path.
        sess.audit.append(
            sess.session_id, "warmup_completed",
            {"transport_kind": "shim"},
        )

        sess.killswitch.fire(reason="late_cancel", fired_by="server")
        # Drain the kill hook coroutine.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        rows = [
            e for e in sess.audit.entries
            if e.event_type == "warmup_aborted_killswitch"
        ]
        assert len(rows) == 0
        # warmup_state still reports the completion (most-recent-wins
        # would only flip if a phantom row landed).
        assert sess.warmup_state() == "completed"
    asyncio.run(_run())


def test_frame_pump_state_absent_running_stopped():
    async def _run():
        sess = session.RemoteSession(
            session_id="ps-1", customer_email="a@b.com",
            customer_region="us", goal="fix wifi",
        )
        assert sess.frame_pump_state() == "absent"
        fake = _FakeTransport([])
        _attach_fake_transport(sess, fake)
        task = sess.start_frame_pump()
        await asyncio.sleep(0)
        assert sess.frame_pump_state() == "running"
        task.cancel()
        await _drain_until(lambda: task.done())
        assert sess.frame_pump_state() == "stopped"
        await fake.close()
    asyncio.run(_run())


def test_warmup_task_names_are_unique_across_sessions(monkeypatch):
    """iter-39 Test Analyzer Medium: two back-to-back start_rustdesk_session
    calls must produce distinct warmup-{id} task names so the dashboard
    can correlate logs without ambiguity. session_id is uuid4-derived so
    collisions require a UUID collision — assert the property holds at
    the voice-tool seam regardless of any future task-name format change.
    """
    mgr = session.SessionManager()
    _install_manager(monkeypatch, mgr)

    async def _run():
        req = voice_tools.StartRequest(
            customer_email="a@example.com",
            problem_summary="fix wifi",
            customer_region="us",
            customer_rustdesk_id="987654321",
        )
        r1 = await voice_tools.start_rustdesk_session(req)
        r2 = await voice_tools.start_rustdesk_session(req)
        assert r1["warmup_task_name"] != r2["warmup_task_name"]
        assert r1["session_id"] != r2["session_id"]
        # Drain both warmups so they don't leak.
        for sid in (r1["session_id"], r2["session_id"]):
            sess = mgr.get(sid)
            assert sess is not None and sess.warmup_task is not None
            await sess.warmup_task
    asyncio.run(_run())


def test_warmup_does_not_start_pump_if_killswitch_fired_during_connect(monkeypatch):
    """iter-38 code-review High: race close on the killswitch path. If
    `await transport.connect(cfg)` resolves AND THEN the killswitch fires
    (via _on_kill → _stop_warmup) BEFORE the warmup reaches
    `start_frame_pump()`, we must not start the pump — _stop_frame_pump
    will already have run in the kill hook, so starting a pump now leaks
    a task past session lifetime.

    Implementation: monkeypatch a fake start_remote that returns kind=shim,
    monkeypatch transport.connect to fire the killswitch just before
    returning, then assert frame_pump_task is None after the warmup
    completes.
    """
    mgr = session.SessionManager()
    _install_manager(monkeypatch, mgr)
    sess = mgr.create_session(
        customer_email="a@b.com", customer_region="us", goal="fix wifi",
    )
    fake = _FakeTransport([])

    async def _connect_then_kill(cfg):
        # Fire the killswitch synchronously inside connect — this models
        # the worst-case race where the customer hits STOP between the
        # transport handshake completing and the pump starting.
        sess.killswitch.fire(reason="race", fired_by="customer")
        return None

    fake.connect = _connect_then_kill  # type: ignore[assignment]

    async def _fake_start_remote(target_sess, **kwargs):
        selection = session.TransportSelection(
            kind="shim", reason="test-shim", binary="/fake",
        )
        target_sess.attach_transport(fake, selection)
        return selection

    monkeypatch.setattr(mgr, "start_remote", _fake_start_remote)

    async def _run():
        await voice_tools._warmup_transport(sess)
        # Race guard MUST have triggered: pump not started despite a
        # successful connect.
        assert sess.frame_pump_task is None, (
            "warmup must check killswitch after connect to avoid pump leak"
        )
        assert sess.killswitch.is_killed
    asyncio.run(_run())
