"""Integration tests for the G34 session loop.

These exercise the end-to-end predict -> queue confirmation -> confirm/reject
-> execute path that the scaffold tests in test_scaffold.py only cover at the
unit level. They use a stub VisionPredictor so the loop doesn't depend on an
ANTHROPIC_API_KEY at test time.

Run: `python3 -m pytest infra/rustdesk_controller/tests -q` from repo root.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra"))

from rustdesk_controller import protocol, session, vision  # noqa: E402
from rustdesk_controller.vision import PredictedAction  # noqa: E402


# ── Test doubles ───────────────────────────────────────────────────────────


class _StubVision(vision.VisionPredictor):
    """Vision predictor that returns a caller-supplied action without I/O.

    The real predictor needs ANTHROPIC_API_KEY; we override predict() so
    integration tests can drive the loop deterministically.
    """

    def __init__(self, action: PredictedAction):
        super().__init__(api_key="stub-key")
        self._action = action
        self.calls = 0

    async def predict(self, frame: protocol.Frame, goal: str) -> PredictedAction:
        self.calls += 1
        return self._action


def _high_confidence_action(x: float = 0.4, y: float = 0.6) -> PredictedAction:
    return PredictedAction(
        event=protocol.InputEvent(
            kind=protocol.EventKind.MOUSE_CLICK, x=x, y=y, button="left",
        ),
        target_description="the WiFi icon",
        rationale="I'm going to click the WiFi icon to open the network menu.",
        confidence=0.92,
    )


def _make_session_with_vision(predictor: vision.VisionPredictor) -> session.RemoteSession:
    mgr = session.SessionManager()
    sess = mgr.create_session(
        customer_email="cust@example.com",
        customer_region="us",
        goal="fix wifi",
    )
    # Use a temp dir for audit + recording so tests don't pollute .loki/.
    sess.vision = predictor
    return sess


def _stub_frame(sequence: int = 0) -> protocol.Frame:
    return protocol.Frame(
        session_id="s1",
        sequence=sequence,
        width=1920,
        height=1080,
        codec="jpeg",
        payload=b"\xff\xd8\xff\xd9",  # minimal jpeg marker pair
        timestamp_ms=0,
    )


async def _wait_for_state(sess: session.RemoteSession, target: session.SessionState, timeout: float = 1.0) -> None:
    """Polling helper — request_next_action queues an asyncio task that flips
    state asynchronously."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if sess.state == target:
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"state never reached {target} (current={sess.state})")


# ── happy path: predict -> confirm -> execute ────────────────────────────


def test_happy_path_predict_confirm_execute():
    """One full cycle: request action, confirm yes, see execute fire and the
    transport receive the event."""
    sess = _make_session_with_vision(_StubVision(_high_confidence_action()))
    # Mark transport as already connected so send_event doesn't raise.
    sess.transport._connected = True

    sent_events: list[protocol.InputEvent] = []
    original_send = sess.transport.send_event

    async def _capturing_send(event: protocol.InputEvent) -> None:
        sent_events.append(event)
        await original_send(event)

    sess.transport.send_event = _capturing_send  # type: ignore[assignment]

    async def runner():
        future = sess.request_next_action(_stub_frame())
        await _wait_for_state(sess, session.SessionState.AWAITING_CONFIRM)
        assert sess.pending_confirmation is not None
        assert sess.pending_confirmation.action.confidence == 0.92

        result = await sess.confirm(True)
        assert result["executed"] is True
        assert result["rejection_streak"] == 0
        assert await future is True
        assert sess.state == session.SessionState.CONNECTED
        assert sess.pending_confirmation is None

    asyncio.run(runner())

    assert len(sent_events) == 1
    assert sent_events[0].kind == protocol.EventKind.MOUSE_CLICK
    assert sent_events[0].x == 0.4
    assert sent_events[0].y == 0.6


# ── rejection flow: 1 reject keeps streak, 2 rejects fires killswitch ────


def test_single_rejection_increments_streak_keeps_session_connected():
    sess = _make_session_with_vision(_StubVision(_high_confidence_action()))
    sess.transport._connected = True

    async def runner():
        future = sess.request_next_action(_stub_frame())
        await _wait_for_state(sess, session.SessionState.AWAITING_CONFIRM)
        result = await sess.confirm(False)
        assert result["executed"] is False
        assert result["rejection_streak"] == 1
        assert await future is False
        assert sess.state == session.SessionState.CONNECTED
        assert sess.killswitch.is_killed is False

    asyncio.run(runner())


def test_two_consecutive_rejections_fire_killswitch_and_handoff():
    """Spec §3: 2 consecutive customer rejections → abort + voice handoff."""
    sess = _make_session_with_vision(_StubVision(_high_confidence_action()))
    sess.transport._connected = True

    async def runner():
        # First rejection.
        f1 = sess.request_next_action(_stub_frame(0))
        await _wait_for_state(sess, session.SessionState.AWAITING_CONFIRM)
        r1 = await sess.confirm(False)
        assert r1["rejection_streak"] == 1
        assert await f1 is False

        # Second rejection — should fire killswitch + flip to ENDED_HANDOFF.
        f2 = sess.request_next_action(_stub_frame(1))
        await _wait_for_state(sess, session.SessionState.AWAITING_CONFIRM)
        r2 = await sess.confirm(False)
        assert r2["rejection_streak"] == 2
        assert await f2 is False

        assert sess.killswitch.is_killed is True
        assert sess.killswitch.reason == "2_consecutive_rejections"
        assert sess.state == session.SessionState.ENDED_HANDOFF

    asyncio.run(runner())


def test_confirm_after_reject_resets_streak():
    """A successful confirmation must clear the rejection streak so a
    customer who says no once isn't penalised forever."""
    sess = _make_session_with_vision(_StubVision(_high_confidence_action()))
    sess.transport._connected = True

    async def runner():
        f1 = sess.request_next_action(_stub_frame(0))
        await _wait_for_state(sess, session.SessionState.AWAITING_CONFIRM)
        await sess.confirm(False)
        await f1

        assert sess.rejection_streak == 1

        f2 = sess.request_next_action(_stub_frame(1))
        await _wait_for_state(sess, session.SessionState.AWAITING_CONFIRM)
        r2 = await sess.confirm(True)
        await f2

        assert r2["executed"] is True
        assert r2["rejection_streak"] == 0
        assert sess.rejection_streak == 0
        assert sess.killswitch.is_killed is False

    asyncio.run(runner())


# ── confidence-abort policy ──────────────────────────────────────────────


def test_low_confidence_action_fires_auto_abort_killswitch():
    """Spec §3 OPEN: vision confidence <0.6 → abort + voice handoff."""
    low_conf = PredictedAction(
        event=protocol.InputEvent(kind=protocol.EventKind.MOUSE_MOVE, x=0.5, y=0.5),
        target_description="(unsure)",
        rationale="I'm not sure where to click.",
        confidence=0.4,
    )
    sess = _make_session_with_vision(_StubVision(low_conf))
    sess.transport._connected = True

    async def runner():
        future = sess.request_next_action(_stub_frame())
        # No pending_confirmation should ever be created — the auto-abort
        # path resolves the future to False directly.
        assert await future is False
        assert sess.pending_confirmation is None
        assert sess.killswitch.is_killed is True
        assert sess.killswitch.fired_by == "auto_abort_low_conf"
        assert "low_confidence=0.40" in sess.killswitch.reason

    asyncio.run(runner())


# ── concurrency guards ──────────────────────────────────────────────────


def test_double_request_while_pending_raises():
    """The loop is single-shot: a second request_next_action while one is
    pending must raise so callers can't double-queue actions."""
    sess = _make_session_with_vision(_StubVision(_high_confidence_action()))
    sess.transport._connected = True

    async def runner():
        first = sess.request_next_action(_stub_frame(0))
        await _wait_for_state(sess, session.SessionState.AWAITING_CONFIRM)
        with pytest.raises(RuntimeError, match="already awaiting"):
            sess.request_next_action(_stub_frame(1))
        # Clean up: confirm to release the pending future so we don't leak it.
        await sess.confirm(True)
        await first

    asyncio.run(runner())


def test_confirm_without_pending_raises():
    sess = _make_session_with_vision(_StubVision(_high_confidence_action()))

    async def runner():
        with pytest.raises(RuntimeError, match="no pending"):
            await sess.confirm(True)

    asyncio.run(runner())


def test_request_after_killswitch_raises():
    """Once the killswitch fires, the loop must refuse further work — fail
    closed, not silently."""
    sess = _make_session_with_vision(_StubVision(_high_confidence_action()))
    sess.killswitch.fire(reason="customer_pressed_stop", fired_by="customer_tray")

    with pytest.raises(RuntimeError, match="killed"):
        sess.request_next_action(_stub_frame())


# ── audit + recording cross-cut ─────────────────────────────────────────


def test_full_cycle_audit_chain_intact_with_executed_and_rejected_actions():
    """A realistic flow — consent, predicted, executed, predicted, rejected,
    session_end — must produce a chain that verify() accepts."""
    sess = _make_session_with_vision(_StubVision(_high_confidence_action()))
    sess.transport._connected = True

    async def runner():
        sess.record_consent(ip_address="203.0.113.7", user_agent="Mozilla/5.0")

        f1 = sess.request_next_action(_stub_frame(0))
        await _wait_for_state(sess, session.SessionState.AWAITING_CONFIRM)
        await sess.confirm(True)
        await f1

        f2 = sess.request_next_action(_stub_frame(1))
        await _wait_for_state(sess, session.SessionState.AWAITING_CONFIRM)
        await sess.confirm(False)
        await f2

        summary = sess.end("fixed")
        assert summary["audit_chain_intact"] is True

    asyncio.run(runner())

    event_types = [e.event_type for e in sess.audit.entries]
    # consent, predicted, confirmed, executed, predicted, rejected, end
    assert event_types == [
        "consent",
        "action_predicted",
        "action_confirmed",
        "action_executed",
        "action_predicted",
        "action_rejected",
        "session_end",
    ]


def test_recording_captures_predicted_and_executed_events_for_us_region(tmp_path, monkeypatch):
    """US region → recording enabled → predicted + executed events land on
    disk via the recorder's JSONL sink."""
    sess = _make_session_with_vision(_StubVision(_high_confidence_action()))
    sess.transport._connected = True

    # Re-point the recorder at a tmp sink — the default uses .loki/remote-sessions.
    from rustdesk_controller import recording

    sess.recorder = recording.SessionRecorder(
        session_id=sess.session_id,
        customer_email=sess.customer_email,
        customer_region="us",
        sink_dir=tmp_path / sess.session_id,
    )

    async def runner():
        f1 = sess.request_next_action(_stub_frame(0))
        await _wait_for_state(sess, session.SessionState.AWAITING_CONFIRM)
        await sess.confirm(True)
        await f1

    asyncio.run(runner())

    assert sess.recorder.events_written == 2  # predicted + executed
    events_file = tmp_path / sess.session_id / "events.jsonl"
    assert events_file.exists()
    rows = events_file.read_text().strip().splitlines()
    assert len(rows) == 2


def test_vision_predict_called_exactly_once_per_request():
    """Defends against accidental double-prediction inside _run()."""
    predictor = _StubVision(_high_confidence_action())
    sess = _make_session_with_vision(predictor)
    sess.transport._connected = True

    async def runner():
        future = sess.request_next_action(_stub_frame())
        await _wait_for_state(sess, session.SessionState.AWAITING_CONFIRM)
        await sess.confirm(True)
        await future

    asyncio.run(runner())
    assert predictor.calls == 1
