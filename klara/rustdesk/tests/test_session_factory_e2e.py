"""G34.5 end-to-end smoke test — transport_factory(prefer_shim=True) drives
the full predict → confirm → execute loop against a mock klx-rdshim binary.

Why this test exists:
    G34.4 wired RemoteSession to the factory at the seam level (post_init
    picks stub; attach_transport swaps to shim). G34.5 closes the loop:
    we spawn a real subprocess speaking the v0 JSON line protocol, attach
    its transport to a live session, drive a single predict→confirm→execute
    cycle, and verify the shim subprocess actually received the InputEvent
    line on its stdin. That is the contract that has to hold before we
    plug in the real Rust shim binary — without this test, a wire-protocol
    drift between Python and Rust would not be caught until staging.

We do NOT depend on the Rust toolchain. The mock shim is a Python script
that speaks the same v0 protocol the real `klx-rdshim` binary will, and
logs every received command to a JSONL file the test inspects after
shutdown.

Run: `python3 -m pytest infra/rustdesk_controller/tests/test_session_factory_e2e.py -q`
"""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra"))

from rustdesk_controller import factory, protocol, session, vision  # noqa: E402
from rustdesk_controller.rdshim_ipc import ShimSubprocessTransport  # noqa: E402
from rustdesk_controller.vision import PredictedAction  # noqa: E402


# ── Test doubles (kept inline so this file is self-contained) ──────────────


class _StubVision(vision.VisionPredictor):
    """Deterministic vision predictor — no ANTHROPIC_API_KEY required."""

    def __init__(self, action: PredictedAction) -> None:
        super().__init__(api_key="stub-key")
        self._action = action
        self.calls = 0

    async def predict(self, frame: protocol.Frame, goal: str) -> PredictedAction:
        self.calls += 1
        return self._action


def _high_confidence_action(x: float = 0.42, y: float = 0.58) -> PredictedAction:
    return PredictedAction(
        event=protocol.InputEvent(
            kind=protocol.EventKind.MOUSE_CLICK, x=x, y=y, button="left",
        ),
        target_description="the WiFi icon",
        rationale="I'm going to click the WiFi icon.",
        confidence=0.93,
    )


def _stub_frame(sequence: int = 0) -> protocol.Frame:
    return protocol.Frame(
        session_id="e2e-smoke",
        sequence=sequence,
        width=1920,
        height=1080,
        codec="jpeg",
        payload=b"\xff\xd8\xff\xd9",
        timestamp_ms=0,
    )


async def _wait_for_state(
    sess: session.RemoteSession,
    target: session.SessionState,
    timeout: float = 2.0,
) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if sess.state == target:
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"state never reached {target} (current={sess.state})")


# ── Mock shim binary ───────────────────────────────────────────────────────


def _write_mock_shim(tmp_path: Path, log_path: Path) -> Path:
    """Write a Python script that pretends to be klx-rdshim.

    Behavior:
        - Emits hello on startup.
        - Reads NDJSON commands from stdin line-by-line.
        - On `connect`: writes `connected` event.
        - On `event`: appends to log_path, writes `event_ack`.
        - On `disconnect`: writes `disconnected` event and exits.
        - Every received command is mirrored to log_path so the test can
          assert on what the shim observed.

    All received commands are appended to log_path as one JSON object per
    line. The test reads this file after `transport.close()` to verify the
    exact wire payload that crossed the pipe.
    """
    shim = tmp_path / "fake-klx-rdshim.py"
    shim.write_text(textwrap.dedent(f"""
        import sys, json
        log_path = {str(log_path)!r}
        log = open(log_path, "a", buffering=1)
        sys.stdout.write(json.dumps({{"kind": "hello", "shim_version": "0.1.0", "librustdesk_commit": "smoke"}}) + "\\n")
        sys.stdout.flush()
        seq = 0
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            log.write(line + "\\n")
            try:
                obj = json.loads(line)
            except Exception:
                continue
            kind = obj.get("kind")
            if kind == "connect":
                sys.stdout.write(json.dumps({{"kind": "connected", "session_id": "smoke-sess", "width": 1920, "height": 1080}}) + "\\n")
                sys.stdout.flush()
            elif kind == "event":
                seq += 1
                sys.stdout.write(json.dumps({{"kind": "event_ack", "sequence": seq, "status": "sent"}}) + "\\n")
                sys.stdout.flush()
            elif kind == "disconnect":
                sys.stdout.write(json.dumps({{"kind": "disconnected", "reason": "shutdown"}}) + "\\n")
                sys.stdout.flush()
                break
        log.close()
    """))
    return shim


# ── Smoke test ──────────────────────────────────────────────────────────────


def test_e2e_predict_confirm_execute_through_shim_transport(tmp_path, monkeypatch):
    """Full path: factory spawns shim, session attaches it, predict/confirm/
    execute, shim records the event line, audit chain stays intact."""
    monkeypatch.delenv(factory.SHIM_ENV_VAR, raising=False)

    log_path = tmp_path / "shim_recv.jsonl"
    log_path.touch()
    shim_script = _write_mock_shim(tmp_path, log_path)

    mgr = session.SessionManager()
    sess = mgr.create_session(
        customer_email="smoke@example.com",
        customer_region="us",
        goal="fix wifi",
    )
    sess.vision = _StubVision(_high_confidence_action())

    cfg = protocol.ConnectionConfig(
        customer_id=sess.session_id,
        session_password=sess.session_id,
    )

    async def run() -> None:
        # ── Step 1: factory spawns the shim subprocess ────────────────────
        transport, selection = await factory.transport_factory(
            cfg,
            prefer_shim=True,
            binary=sys.executable,
            extra_argv=[str(shim_script)],
        )
        try:
            assert isinstance(transport, ShimSubprocessTransport)
            assert selection.kind == "shim"
            assert selection.binary == sys.executable

            # ── Step 2: connect the shim to the (mock) relay ───────────
            await transport.connect(cfg)

            # ── Step 3: attach to the session (the real entrypoint
            # SessionManager.start_remote would do this; we call the
            # seam directly so we can pass extra_argv) ──────────────────
            sess.attach_transport(transport, selection)
            assert sess.transport is transport
            assert sess.transport_selection.kind == "shim"

            # ── Step 4: drive the predict → confirm → execute loop ─────
            future = sess.request_next_action(_stub_frame())
            await _wait_for_state(sess, session.SessionState.AWAITING_CONFIRM)
            assert sess.pending_confirmation is not None

            result = await sess.confirm(True)
            assert result["executed"] is True
            assert result["rejection_streak"] == 0
            assert await future is True
            assert sess.state == session.SessionState.CONNECTED

            # Give the shim's reader_loop a moment to ack the event so we
            # do not race the close() teardown.
            await asyncio.sleep(0.05)
        finally:
            await transport.close()

    asyncio.run(run())

    # ── Step 5: verify shim subprocess received the wire payload ────────
    received_lines = [
        line for line in log_path.read_text().splitlines() if line.strip()
    ]
    assert received_lines, "mock shim recorded zero commands"

    received = [json.loads(line) for line in received_lines]
    kinds = [obj["kind"] for obj in received]
    assert "connect" in kinds, f"shim never saw connect; kinds={kinds}"
    assert "event" in kinds, f"shim never saw event; kinds={kinds}"
    assert "disconnect" in kinds, f"shim never saw disconnect; kinds={kinds}"

    # The event command must carry the predicted click's coordinates.
    event_cmd = next(obj for obj in received if obj["kind"] == "event")
    assert event_cmd["event_kind"] == protocol.EventKind.MOUSE_CLICK.value
    assert event_cmd["x"] == pytest.approx(0.42)
    assert event_cmd["y"] == pytest.approx(0.58)
    assert event_cmd["button"] == "left"

    # ── Step 6: verify audit chain captured the swap + execution ─────────
    event_types = [e.event_type for e in sess.audit.entries]
    assert "transport_attached" in event_types
    assert "action_predicted" in event_types
    assert "action_confirmed" in event_types
    assert "action_executed" in event_types
    assert sess.audit.verify(), "hash chain must remain intact end-to-end"

    # The transport_attached row must record both the new + prior kind so
    # post-mortems can correlate transport choice with outcome.
    attached_row = next(
        e for e in sess.audit.entries if e.event_type == "transport_attached"
    )
    assert attached_row.payload["kind"] == "shim"
    assert attached_row.payload["prior"] == "stub"


def test_e2e_shim_spawn_handshake_then_clean_close_without_session(tmp_path, monkeypatch):
    """Narrow lifecycle test: factory → handshake → close, no session
    machinery involved. Guards against teardown regressions that the full
    smoke test would mask by also exercising the session loop.
    """
    monkeypatch.delenv(factory.SHIM_ENV_VAR, raising=False)
    log_path = tmp_path / "shim_recv.jsonl"
    log_path.touch()
    shim_script = _write_mock_shim(tmp_path, log_path)

    cfg = protocol.ConnectionConfig(customer_id="x", session_password="y")

    async def run() -> None:
        transport, selection = await factory.transport_factory(
            cfg,
            prefer_shim=True,
            binary=sys.executable,
            extra_argv=[str(shim_script)],
        )
        try:
            assert selection.kind == "shim"
            assert transport.hello is not None
            assert transport.hello.major_version == "0"
        finally:
            await transport.close()

        # Process should be reaped after close.
        assert transport.process.returncode is not None

    asyncio.run(run())

    received_lines = [
        line for line in log_path.read_text().splitlines() if line.strip()
    ]
    # We never sent connect/event, only disconnect from close().
    received = [json.loads(line) for line in received_lines]
    kinds = [obj["kind"] for obj in received]
    assert "disconnect" in kinds, f"close() must send disconnect; kinds={kinds}"
    assert "connect" not in kinds
    assert "event" not in kinds
