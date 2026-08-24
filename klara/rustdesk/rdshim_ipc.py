"""klx-rdshim IPC layer — Python side of the G34.1 binding decision.

This module is the Python-side conformance implementation of the JSON line
protocol documented in `G34.1-binding-decision.md`. It does NOT spawn the
`klx-rdshim` binary itself — iteration 6 (G34.2) lands the Rust shim. What
this module provides today:

    - Typed dataclasses for every IPC message (one direction per dataclass).
    - Pure serialize/parse helpers — no I/O, no asyncio.
    - `ShimSubprocessTransport`, an `asyncio.subprocess`-compatible
      `RustDeskTransport` implementation that drives ANY process speaking
      the v0 line protocol (the real shim, a fake `cat`-style mock, or a
      Python-in-Python harness used by the test suite).

Why split the two:
    Keeping the serializer pure and dependency-free means we can fuzz it
    from unit tests, and the same module covers Iteration-5 conformance
    tests AND production once the Rust shim lands.

Protocol version: v0 (major version only; see `SUPPORTED_MAJOR_VERSIONS`).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from asyncio.subprocess import Process
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterable

from .protocol import (
    ConnectionConfig,
    DEFAULT_HBBR_PORT,
    DEFAULT_HBBS_PORT,
    EventKind,
    Frame,
    InputEvent,
    RustDeskTransport,
)

log = logging.getLogger("klaravex.rustdesk.rdshim")

# Major versions accepted from the shim's hello message. v0 = pre-1.0
# evolving protocol; v1 will signal stable wire format.
SUPPORTED_MAJOR_VERSIONS: frozenset[str] = frozenset({"0"})

SHIM_HELLO_TIMEOUT_S = 5.0
SHIM_CONNECT_TIMEOUT_S = 15.0


class IPCProtocolError(RuntimeError):
    """The shim sent a malformed or unsupported message."""


class IPCVersionMismatch(IPCProtocolError):
    """The shim's hello message did not advertise a supported major version."""


# ─────────────────────────────────────────────────────────────────────────────
# Python → shim messages (commands)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CmdConnect:
    relay_host: str
    relay_key: str
    hbbs_port: int
    hbbr_port: int
    customer_id: str
    session_password: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "kind": "connect",
                "relay_host": self.relay_host,
                "relay_key": self.relay_key,
                "hbbs_port": self.hbbs_port,
                "hbbr_port": self.hbbr_port,
                "customer_id": self.customer_id,
                "session_password": self.session_password,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_config(cls, cfg: ConnectionConfig) -> "CmdConnect":
        return cls(
            relay_host=cfg.relay_host,
            relay_key=cfg.relay_key,
            hbbs_port=cfg.hbbs_port,
            hbbr_port=cfg.hbbr_port,
            customer_id=cfg.customer_id,
            session_password=cfg.session_password,
        )


@dataclass(frozen=True)
class CmdEvent:
    event: InputEvent

    def to_json(self) -> str:
        payload: dict[str, object] = {
            "kind": "event",
            "event_kind": self.event.kind.value,
        }
        if self.event.x is not None:
            payload["x"] = self.event.x
        if self.event.y is not None:
            payload["y"] = self.event.y
        if self.event.button is not None:
            payload["button"] = self.event.button
        if self.event.key is not None:
            payload["key"] = self.event.key
        if self.event.text is not None:
            payload["text"] = self.event.text
        if self.event.modifiers:
            payload["modifiers"] = list(self.event.modifiers)
        return json.dumps(payload, separators=(",", ":"))


@dataclass(frozen=True)
class CmdDisconnect:
    def to_json(self) -> str:
        return json.dumps({"kind": "disconnect"}, separators=(",", ":"))


# ─────────────────────────────────────────────────────────────────────────────
# Shim → Python messages (events)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EvtHello:
    shim_version: str
    librustdesk_commit: str

    @property
    def major_version(self) -> str:
        # "klx-rdshim 0.1.0" → "0", or "0.1.0" → "0"
        version = self.shim_version.split()[-1]
        return version.split(".")[0]


@dataclass(frozen=True)
class EvtConnected:
    session_id: str
    width: int
    height: int


@dataclass(frozen=True)
class EvtFrame:
    session_id: str
    sequence: int
    width: int
    height: int
    codec: str
    payload: bytes
    timestamp_ms: int

    def to_frame(self) -> Frame:
        return Frame(
            session_id=self.session_id,
            sequence=self.sequence,
            width=self.width,
            height=self.height,
            codec=self.codec,
            payload=self.payload,
            timestamp_ms=self.timestamp_ms,
        )


@dataclass(frozen=True)
class EvtEventAck:
    sequence: int
    status: str  # "sent" | "dropped" | "rejected"


@dataclass(frozen=True)
class EvtError:
    code: str
    message: str


@dataclass(frozen=True)
class EvtDisconnected:
    reason: str


ShimEvent = (
    EvtHello | EvtConnected | EvtFrame | EvtEventAck | EvtError | EvtDisconnected
)


def parse_shim_event(line: str) -> ShimEvent:
    """Parse a single newline-delimited JSON message coming from the shim.

    Raises `IPCProtocolError` on malformed input. Whitespace-only / empty
    lines must be filtered by the caller — this function refuses them.
    """
    line = line.strip()
    if not line:
        raise IPCProtocolError("empty line")
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as exc:
        raise IPCProtocolError(f"not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise IPCProtocolError("top-level JSON value must be object")
    kind = obj.get("kind")
    if not isinstance(kind, str):
        raise IPCProtocolError("missing or non-string 'kind'")

    try:
        if kind == "hello":
            return EvtHello(
                shim_version=str(obj["shim_version"]),
                librustdesk_commit=str(obj["librustdesk_commit"]),
            )
        if kind == "connected":
            return EvtConnected(
                session_id=str(obj["session_id"]),
                width=int(obj["width"]),
                height=int(obj["height"]),
            )
        if kind == "frame":
            return EvtFrame(
                session_id=str(obj["session_id"]),
                sequence=int(obj["sequence"]),
                width=int(obj["width"]),
                height=int(obj["height"]),
                codec=str(obj["codec"]),
                payload=base64.b64decode(obj["payload_b64"]),
                timestamp_ms=int(obj["timestamp_ms"]),
            )
        if kind == "event_ack":
            return EvtEventAck(
                sequence=int(obj["sequence"]),
                status=str(obj["status"]),
            )
        if kind == "error":
            return EvtError(
                code=str(obj["code"]),
                message=str(obj["message"]),
            )
        if kind == "disconnected":
            return EvtDisconnected(reason=str(obj["reason"]))
    except (KeyError, TypeError, ValueError, base64.binascii.Error) as exc:
        raise IPCProtocolError(f"malformed {kind!r} message: {exc}") from exc

    raise IPCProtocolError(f"unknown event kind: {kind!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Subprocess transport (implements RustDeskTransport)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ShimSubprocessTransport:
    """Drives any process speaking the v0 line protocol.

    The process is supplied by the caller (`process`), which makes this
    class easy to test against a Python-driven mock without standing up the
    real shim. In production, `process` is the output of
    `asyncio.create_subprocess_exec("klx-rdshim", ...)`.

    Lifecycle:
        1. caller spawns process and wraps it in this transport
        2. `await transport.handshake()` consumes the shim's `hello` and
           validates the major version
        3. `await transport.connect(cfg)` sends `CmdConnect` and waits for
           a `connected` event
        4. `async for frame in transport.frames()` yields decoded Frames
        5. `await transport.send_event(event)` writes a CmdEvent line
        6. `await transport.close()` sends `disconnect` and waits for the
           shim to flush

    Two-task design: a background reader pumps stdout lines into a queue
    so `send_event` never blocks on a stuck reader.
    """

    process: Process
    hello: EvtHello | None = None
    _connected_event: asyncio.Event = field(default_factory=asyncio.Event)
    _frames: asyncio.Queue[EvtFrame] = field(default_factory=asyncio.Queue)
    _last_error: EvtError | None = None
    _disconnected: EvtDisconnected | None = None
    _reader_task: asyncio.Task | None = None
    _event_seq: int = 0

    async def handshake(self, timeout: float = SHIM_HELLO_TIMEOUT_S) -> EvtHello:
        if self.process.stdout is None:
            raise IPCProtocolError("shim process has no stdout pipe")
        line = await asyncio.wait_for(self.process.stdout.readline(), timeout)
        if not line:
            raise IPCProtocolError("shim closed stdout before hello")
        event = parse_shim_event(line.decode("utf-8", errors="replace"))
        if not isinstance(event, EvtHello):
            raise IPCProtocolError(
                f"expected hello, got {type(event).__name__}"
            )
        if event.major_version not in SUPPORTED_MAJOR_VERSIONS:
            raise IPCVersionMismatch(
                f"shim major version {event.major_version!r} not in "
                f"{sorted(SUPPORTED_MAJOR_VERSIONS)}"
            )
        self.hello = event
        # Start background reader once handshake succeeds.
        self._reader_task = asyncio.create_task(self._reader_loop())
        return event

    async def _reader_loop(self) -> None:
        assert self.process.stdout is not None
        while True:
            line = await self.process.stdout.readline()
            if not line:
                return  # shim closed stdout
            try:
                event = parse_shim_event(line.decode("utf-8", errors="replace"))
            except IPCProtocolError as exc:
                log.warning("rdshim parse error: %s | raw=%r", exc, line)
                continue
            await self._dispatch(event)

    async def _dispatch(self, event: ShimEvent) -> None:
        if isinstance(event, EvtConnected):
            self._connected_event.set()
        elif isinstance(event, EvtFrame):
            await self._frames.put(event)
        elif isinstance(event, EvtError):
            self._last_error = event
            log.error("rdshim error: %s — %s", event.code, event.message)
        elif isinstance(event, EvtDisconnected):
            self._disconnected = event
            log.info("rdshim disconnected: %s", event.reason)
            # Signal the frame consumer to wake up.
            await self._frames.put(_SENTINEL_FRAME)
        elif isinstance(event, EvtEventAck):
            log.debug("rdshim ack seq=%d status=%s", event.sequence, event.status)
        elif isinstance(event, EvtHello):
            log.warning("rdshim resent hello after handshake — ignoring")

    async def connect(self, cfg: ConnectionConfig) -> None:
        if self.process.stdin is None:
            raise IPCProtocolError("shim process has no stdin pipe")
        if self.hello is None:
            raise RuntimeError("call handshake() before connect()")
        cmd = CmdConnect.from_config(cfg)
        await self._write_line(cmd.to_json())
        try:
            await asyncio.wait_for(
                self._connected_event.wait(), timeout=SHIM_CONNECT_TIMEOUT_S
            )
        except asyncio.TimeoutError as exc:
            err = self._last_error
            detail = f" (shim error: {err.code} {err.message})" if err else ""
            raise IPCProtocolError(
                f"shim did not emit 'connected' within {SHIM_CONNECT_TIMEOUT_S}s"
                f"{detail}"
            ) from exc

    async def frames(self) -> AsyncIterator[Frame]:
        while True:
            evt = await self._frames.get()
            if evt is _SENTINEL_FRAME:
                return
            yield evt.to_frame()

    async def send_event(self, event: InputEvent) -> None:
        self._event_seq += 1
        await self._write_line(CmdEvent(event=event).to_json())

    async def close(self) -> None:
        if self.process.stdin is not None and not self.process.stdin.is_closing():
            try:
                await self._write_line(CmdDisconnect().to_json())
                self.process.stdin.close()
            except (BrokenPipeError, ConnectionResetError):
                pass
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
        # Drain process; do not block forever on misbehaving shims.
        try:
            await asyncio.wait_for(self.process.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            log.warning("rdshim did not exit within 2s — terminating")
            self.process.terminate()

    async def _write_line(self, line: str) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(line.encode("utf-8") + b"\n")
        await self.process.stdin.drain()


# Sentinel queue entry that signals "no more frames".
# Using a sentinel instead of None lets the type checker keep the queue
# parameterized on EvtFrame in tests / mypy.
_SENTINEL_FRAME = EvtFrame(
    session_id="__sentinel__",
    sequence=-1,
    width=0,
    height=0,
    codec="sentinel",
    payload=b"",
    timestamp_ms=0,
)


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: build the standard shim command
# ─────────────────────────────────────────────────────────────────────────────


def build_shim_argv(binary: str | None = None, extra: Iterable[str] = ()) -> list[str]:
    """Returns the argv used to spawn the shim.

    `binary` defaults to `$KLX_RDSHIM_BIN` or `klx-rdshim` on PATH. The shim
    binary itself lands in iteration 6 (G34.2); this helper exists so
    `session.py` can call it once the binary is shipped without further
    refactoring.
    """
    bin_path = binary or os.environ.get("KLX_RDSHIM_BIN", "klx-rdshim")
    argv = [bin_path]
    argv.extend(extra)
    return argv


__all__ = [
    "SUPPORTED_MAJOR_VERSIONS",
    "SHIM_HELLO_TIMEOUT_S",
    "SHIM_CONNECT_TIMEOUT_S",
    "IPCProtocolError",
    "IPCVersionMismatch",
    "CmdConnect",
    "CmdEvent",
    "CmdDisconnect",
    "EvtHello",
    "EvtConnected",
    "EvtFrame",
    "EvtEventAck",
    "EvtError",
    "EvtDisconnected",
    "ShimEvent",
    "ShimSubprocessTransport",
    "parse_shim_event",
    "build_shim_argv",
    # exported for tests:
    "DEFAULT_HBBS_PORT",
    "DEFAULT_HBBR_PORT",
]


# Type-check shim implements the RustDeskTransport Protocol. This is purely
# for static analysis — at runtime asyncio iterators are duck-typed.
_check_shim_transport: type[RustDeskTransport] = ShimSubprocessTransport  # type: ignore[assignment]
