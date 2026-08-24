"""Tests for G34.1 rdshim_ipc — IPC protocol + ShimSubprocessTransport.

Covers:
    - round-trip serialize / parse for every shim → Python event kind
    - command serialization for connect / event / disconnect
    - version mismatch is rejected at handshake
    - malformed JSON is reported as IPCProtocolError, not crashed
    - end-to-end ShimSubprocessTransport against a fake subprocess that
      speaks the v0 protocol using only Python stdlib (no Rust binary, no
      network) — proves the upper layers don't change when the real shim
      lands in G34.2.

Run: `python3 -m pytest infra/rustdesk_controller/tests -q` from repo root.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra"))

from rustdesk_controller import rdshim_ipc as ipc  # noqa: E402
from rustdesk_controller.protocol import (  # noqa: E402
    ConnectionConfig,
    EventKind,
    InputEvent,
)


# ─────────────────────────────────────────────────────────────────────────────
# Pure parser tests
# ─────────────────────────────────────────────────────────────────────────────


def test_parse_hello() -> None:
    line = json.dumps(
        {"kind": "hello", "shim_version": "klx-rdshim 0.1.0", "librustdesk_commit": "abcd1234"}
    )
    evt = ipc.parse_shim_event(line)
    assert isinstance(evt, ipc.EvtHello)
    assert evt.shim_version == "klx-rdshim 0.1.0"
    assert evt.librustdesk_commit == "abcd1234"
    assert evt.major_version == "0"


def test_parse_hello_bare_semver_extracts_major() -> None:
    line = json.dumps(
        {"kind": "hello", "shim_version": "0.4.7", "librustdesk_commit": "deadbeef"}
    )
    evt = ipc.parse_shim_event(line)
    assert isinstance(evt, ipc.EvtHello)
    assert evt.major_version == "0"


def test_parse_connected() -> None:
    line = json.dumps(
        {"kind": "connected", "session_id": "K-2026-06-12-7f31", "width": 1920, "height": 1080}
    )
    evt = ipc.parse_shim_event(line)
    assert isinstance(evt, ipc.EvtConnected)
    assert evt.session_id == "K-2026-06-12-7f31"
    assert evt.width == 1920 and evt.height == 1080


def test_parse_frame_roundtrips_binary_payload() -> None:
    payload = bytes(range(256))
    line = json.dumps(
        {
            "kind": "frame",
            "session_id": "K-1",
            "sequence": 42,
            "width": 800,
            "height": 600,
            "codec": "jpeg",
            "payload_b64": base64.b64encode(payload).decode("ascii"),
            "timestamp_ms": 1718178501023,
        }
    )
    evt = ipc.parse_shim_event(line)
    assert isinstance(evt, ipc.EvtFrame)
    assert evt.payload == payload
    assert evt.sequence == 42
    assert evt.codec == "jpeg"
    frame = evt.to_frame()
    assert frame.payload == payload
    assert frame.session_id == "K-1"


def test_parse_event_ack() -> None:
    line = json.dumps({"kind": "event_ack", "sequence": 11, "status": "sent"})
    evt = ipc.parse_shim_event(line)
    assert isinstance(evt, ipc.EvtEventAck)
    assert evt.sequence == 11 and evt.status == "sent"


def test_parse_error() -> None:
    line = json.dumps({"kind": "error", "code": "relay_unreachable", "message": "timeout"})
    evt = ipc.parse_shim_event(line)
    assert isinstance(evt, ipc.EvtError)
    assert evt.code == "relay_unreachable"


def test_parse_disconnected() -> None:
    line = json.dumps({"kind": "disconnected", "reason": "peer_closed"})
    evt = ipc.parse_shim_event(line)
    assert isinstance(evt, ipc.EvtDisconnected)
    assert evt.reason == "peer_closed"


def test_parse_rejects_empty_line() -> None:
    with pytest.raises(ipc.IPCProtocolError):
        ipc.parse_shim_event("   \n")


def test_parse_rejects_malformed_json() -> None:
    with pytest.raises(ipc.IPCProtocolError):
        ipc.parse_shim_event("{not json")


def test_parse_rejects_unknown_kind() -> None:
    line = json.dumps({"kind": "telemetry", "foo": "bar"})
    with pytest.raises(ipc.IPCProtocolError):
        ipc.parse_shim_event(line)


def test_parse_rejects_missing_kind() -> None:
    line = json.dumps({"shim_version": "0.1.0"})
    with pytest.raises(ipc.IPCProtocolError):
        ipc.parse_shim_event(line)


def test_parse_rejects_malformed_frame_payload() -> None:
    line = json.dumps(
        {
            "kind": "frame",
            "session_id": "K-1",
            "sequence": 0,
            "width": 1,
            "height": 1,
            "codec": "jpeg",
            "payload_b64": "not!base64!@#",
            "timestamp_ms": 0,
        }
    )
    with pytest.raises(ipc.IPCProtocolError):
        ipc.parse_shim_event(line)


# ─────────────────────────────────────────────────────────────────────────────
# Command serialization tests
# ─────────────────────────────────────────────────────────────────────────────


def test_cmd_connect_serializes_all_fields() -> None:
    cfg = ConnectionConfig(
        relay_host="10.0.0.1",
        relay_key="K==",
        hbbs_port=21116,
        hbbr_port=21117,
        customer_id="4242-1111-9090",
        session_password="hunter2",
    )
    cmd = ipc.CmdConnect.from_config(cfg)
    payload = json.loads(cmd.to_json())
    assert payload == {
        "kind": "connect",
        "relay_host": "10.0.0.1",
        "relay_key": "K==",
        "hbbs_port": 21116,
        "hbbr_port": 21117,
        "customer_id": "4242-1111-9090",
        "session_password": "hunter2",
    }


def test_cmd_event_drops_none_fields() -> None:
    event = InputEvent(kind=EventKind.MOUSE_MOVE, x=0.5, y=0.25)
    cmd = ipc.CmdEvent(event=event)
    payload = json.loads(cmd.to_json())
    assert payload == {"kind": "event", "event_kind": "mouse_move", "x": 0.5, "y": 0.25}
    assert "button" not in payload
    assert "key" not in payload


def test_cmd_event_carries_modifiers_and_text() -> None:
    event = InputEvent(
        kind=EventKind.PASTE_TEXT,
        text="hello",
        modifiers=("ctrl", "shift"),
    )
    payload = json.loads(ipc.CmdEvent(event=event).to_json())
    assert payload["event_kind"] == "paste_text"
    assert payload["text"] == "hello"
    assert payload["modifiers"] == ["ctrl", "shift"]


def test_cmd_disconnect_is_minimal() -> None:
    assert json.loads(ipc.CmdDisconnect().to_json()) == {"kind": "disconnect"}


# ─────────────────────────────────────────────────────────────────────────────
# build_shim_argv
# ─────────────────────────────────────────────────────────────────────────────


def test_build_shim_argv_defaults_to_klx_rdshim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KLX_RDSHIM_BIN", raising=False)
    assert ipc.build_shim_argv() == ["klx-rdshim"]


def test_build_shim_argv_honors_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KLX_RDSHIM_BIN", "/usr/local/bin/klx-rdshim")
    assert ipc.build_shim_argv(extra=["--verbose"]) == [
        "/usr/local/bin/klx-rdshim",
        "--verbose",
    ]


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end ShimSubprocessTransport against a fake subprocess
# ─────────────────────────────────────────────────────────────────────────────


def _make_fake_shim_script(scenario: str) -> str:
    """Generate a tiny Python program that impersonates the shim.

    Reads stdin commands and emits events per the scenario name. Using a
    real subprocess proves the asyncio plumbing, pipe buffering, and
    line-delimited framing all work without depending on a Rust binary.
    """
    return f"""
import base64, json, sys

def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()

scenario = {scenario!r}

# 1. hello
emit({{"kind": "hello", "shim_version": "klx-rdshim 0.1.0", "librustdesk_commit": "deadbeef"}})

if scenario == "version_mismatch":
    # Re-send hello with a bad version. Used by the version-mismatch test
    # which only consumes the first line, so this never actually runs in
    # parse, but the spawn must still complete.
    sys.exit(0)

# 2. wait for connect command
line = sys.stdin.readline()
cmd = json.loads(line)
assert cmd["kind"] == "connect"

if scenario == "relay_unreachable":
    emit({{"kind": "error", "code": "relay_unreachable", "message": "timeout"}})
    emit({{"kind": "disconnected", "reason": "error"}})
    sys.exit(0)

# 3. emit connected + N frames
emit({{"kind": "connected", "session_id": "K-FAKE", "width": 800, "height": 600}})
payload = base64.b64encode(b"FRAMEBYTES").decode("ascii")
for seq in range(3):
    emit({{
        "kind": "frame",
        "session_id": "K-FAKE",
        "sequence": seq,
        "width": 800,
        "height": 600,
        "codec": "jpeg",
        "payload_b64": payload,
        "timestamp_ms": 1000 + seq,
    }})

# 4. read events until disconnect
while True:
    line = sys.stdin.readline()
    if not line:
        break
    cmd = json.loads(line)
    if cmd["kind"] == "event":
        emit({{"kind": "event_ack", "sequence": 1, "status": "sent"}})
    elif cmd["kind"] == "disconnect":
        emit({{"kind": "disconnected", "reason": "peer_closed"}})
        break
"""


async def _spawn_fake_shim(scenario: str) -> asyncio.subprocess.Process:
    script = _make_fake_shim_script(scenario)
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",  # unbuffered stdout so pipe reads see lines immediately
        "-c",
        script,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


def test_handshake_accepts_v0() -> None:
    async def runner() -> None:
        proc = await _spawn_fake_shim(scenario="happy")
        transport = ipc.ShimSubprocessTransport(process=proc)
        hello = await transport.handshake()
        assert hello.major_version == "0"
        assert transport.hello is hello
        await transport.close()
    asyncio.run(runner())


def test_handshake_rejects_unsupported_major() -> None:
    async def runner() -> None:
        script = (
            "import json, sys\n"
            "sys.stdout.write(json.dumps({\"kind\": \"hello\", "
            "\"shim_version\": \"9.0.0\", \"librustdesk_commit\": \"c\"}) + \"\\n\")\n"
            "sys.stdout.flush()\n"
        )
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            "-c",
            script,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        transport = ipc.ShimSubprocessTransport(process=proc)
        with pytest.raises(ipc.IPCVersionMismatch):
            await transport.handshake()
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            proc.kill()
    asyncio.run(runner())


def test_end_to_end_connect_frames_and_event() -> None:
    async def runner() -> None:
        proc = await _spawn_fake_shim(scenario="happy")
        transport = ipc.ShimSubprocessTransport(process=proc)
        await transport.handshake()

        cfg = ConnectionConfig(customer_id="CUST", session_password="PW")
        await transport.connect(cfg)

        received: list = []

        async def _consume() -> None:
            async for frame in transport.frames():
                received.append(frame)
                if len(received) >= 3:
                    break

        await asyncio.wait_for(_consume(), timeout=5.0)

        assert len(received) == 3
        assert received[0].sequence == 0
        assert received[0].payload == b"FRAMEBYTES"
        assert received[2].sequence == 2

        await transport.send_event(
            InputEvent(kind=EventKind.MOUSE_CLICK, x=0.5, y=0.5, button="left"),
        )
        await transport.close()
    asyncio.run(runner())


def test_relay_unreachable_surfaces_as_connect_error() -> None:
    async def runner() -> None:
        proc = await _spawn_fake_shim(scenario="relay_unreachable")
        transport = ipc.ShimSubprocessTransport(process=proc)
        await transport.handshake()
        cfg = ConnectionConfig(customer_id="CUST", session_password="PW")
        original = ipc.SHIM_CONNECT_TIMEOUT_S
        ipc.SHIM_CONNECT_TIMEOUT_S = 1.0
        try:
            with pytest.raises(ipc.IPCProtocolError) as exc_info:
                await transport.connect(cfg)
            assert "relay_unreachable" in str(exc_info.value)
        finally:
            ipc.SHIM_CONNECT_TIMEOUT_S = original
        await transport.close()
    asyncio.run(runner())
