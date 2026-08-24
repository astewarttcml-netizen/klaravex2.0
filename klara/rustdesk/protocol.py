"""RustDesk client protocol — operator-side transport.

The RustDesk wire protocol is protobuf-over-TCP after a NAT-rendezvous
handshake with the hbbs ID server. The operator joins a session by
presenting the customer's RustDesk ID + session password, and from there
exchanges:

    customer → operator : VideoFrame (codec=VP9/H264, RGB raw, or jpeg)
    operator → customer : MouseEvent / KeyEvent / SystemEvent

Three feasible implementations of the operator side were enumerated:

    a) FFI into librustdesk (Rust → cdylib → Python via cffi/pyo3).
    b) Subprocess-drive a small Rust shim or rustdesk-cli, exchange
       frames + events over stdin/stdout.
    c) Re-implement the protobuf schema in pure Python.

DECISION: **(b)** — see `G34.1-binding-decision.md`. The Python side
spawns a subprocess that speaks the v0 JSON line protocol defined in
`rdshim_ipc.py`. Two subprocess implementations satisfy the contract:

    * **`klx-rdshim`** (Rust binary, `klx-rdshim/`) — production target.
      Scaffolded; librustdesk linkage lands in G34.2a.
    * **`mock_customer_shim`** (Python script, `mock_customer_shim.py`)
      — conformance target used by the operator e2e test. Generates
      real JPEG frames on a simulated 320x240 framebuffer and applies
      input events to a virtual cursor. Same wire protocol as the Rust
      shim — proves the operator Python path BEFORE the Rust toolchain
      cross-compile lands.

CURRENT STATE OF THE BINDING (as of G34.1 close — 2026-06-12):
    * `_connect`     → IMPLEMENTED. Spawns shim subprocess, runs
                        handshake + connect against any binary speaking v0.
    * `_recv_frame`  → IMPLEMENTED. Reads `frame` events from the
                        underlying ShimSubprocessTransport queue.
    * `_send_event`  → IMPLEMENTED. Writes `event` commands via the
                        subprocess stdin.

WHAT'S STUBBED / PARTIAL:
    * `klx-rdshim`'s `connect` handler still returns `not_implemented`
      until G34.2a links libs/hbb_common + libs/scrap. Until then the
      production path runs against `mock_customer_shim` for tests, and
      the real binary will need its connect implementation filled in.
    * Frame codec is currently jpeg only. VP9 / H264 decode is deferred
      until librustdesk linkage (those codecs live inside `libs/scrap`).
    * Symmetric-NAT TURN/relay fallback (hbbr 21117 traffic) is not yet
      surfaced as an operator-side metric.

Reference: github.com/rustdesk/rustdesk/blob/master/libs/hbb_common/protos/rendezvous.proto
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Protocol

log = logging.getLogger("klaravex.rustdesk.protocol")

# Hetzner public-edge relay default. See infra/rustdesk-server-DEPLOYED.md.
# NOTE (2026-07-10): 87.99.147.244 (Hetzner CX22) is read-only since the
# 2026-07-05/06 Azure migration and 2026-07-01/02 rig+USA HA cutover.
# runbooks/rig-usa-ha-stack-2026-07-01.md §4 does NOT list RustDesk in the
# current container inventory. Verify actual relay placement in prod and set
# RUSTDESK_RELAY_HOST env var to override this default if the relay moved.
DEFAULT_RELAY_HOST = os.environ.get("RUSTDESK_RELAY_HOST", "87.99.147.244")
DEFAULT_RELAY_KEY = os.environ.get(
    "RUSTDESK_RELAY_KEY",
    "E2+699SkYhlEsyjaizRhI+2kuvxxGheisWarfJHbkVA=",
)
# Deployed listeners (see infra/rustdesk-server-DEPLOYED.md):
#   TCP 21115 = hbbs ID server (signal channel — reachability proxy)
#   UDP 21116 = hbbs NAT hole-punch (not TCP-probable)
#   TCP 21117 = hbbr relay fallback (used when P2P fails)
DEFAULT_HBBS_ID_PORT = 21115  # TCP — used for reachability probe
DEFAULT_HBBS_PORT = 21116  # NAT registration / UDP hole-punching
DEFAULT_HBBR_PORT = 21117  # TCP relay fallback
DEFAULT_PROBE_TIMEOUT_S = 3.0


class EventKind(str, Enum):
    MOUSE_MOVE = "mouse_move"
    MOUSE_CLICK = "mouse_click"
    MOUSE_SCROLL = "mouse_scroll"
    KEY_DOWN = "key_down"
    KEY_UP = "key_up"
    KEY_PRESS = "key_press"  # convenience: down + up
    PASTE_TEXT = "paste_text"


@dataclass(frozen=True)
class InputEvent:
    kind: EventKind
    # Coordinates are normalized 0.0–1.0 of the remote framebuffer so the
    # controller does not need to know the customer's display resolution
    # until the first frame arrives.
    x: float | None = None
    y: float | None = None
    button: str | None = None  # "left" | "right" | "middle"
    key: str | None = None  # X11 keysym name, e.g. "Return", "ctrl+c"
    text: str | None = None
    modifiers: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Frame:
    session_id: str
    sequence: int
    width: int
    height: int
    codec: str  # "rgb" | "jpeg" | "vp9" | "h264"
    payload: bytes
    timestamp_ms: int


@dataclass(frozen=True)
class ConnectionConfig:
    relay_host: str = DEFAULT_RELAY_HOST
    relay_key: str = DEFAULT_RELAY_KEY
    hbbs_port: int = DEFAULT_HBBS_PORT
    hbbr_port: int = DEFAULT_HBBR_PORT
    # Customer-side identity issued by support.klaravex.com at download time.
    customer_id: str = ""
    session_password: str = ""
    # Frame downsample: helper captures at 10–15fps locally; we sub-sample to
    # the LLM at 1–2fps because vision inference is 2–5s. See spec §3.
    fps_to_controller: float = 1.5


class RustDeskTransport(Protocol):
    async def connect(self, cfg: ConnectionConfig) -> None: ...
    async def frames(self) -> AsyncIterator[Frame]: ...
    async def send_event(self, event: InputEvent) -> None: ...
    async def close(self) -> None: ...


# ── Reachability probe ─────────────────────────────────────────────────────
# Cheap TCP-connect check so the session loop can fail fast with a clear
# diagnostic instead of stalling inside librustdesk when the relay is
# unreachable (firewall, DNS, Hetzner outage). UDP 21116 is intentionally
# skipped — there is no portable connectionless reachability check, and
# successful TCP on hbbs 21115 + hbbr 21117 is sufficient evidence the box
# is up and the IPS rules are correct.


@dataclass(frozen=True)
class ProbeResult:
    host: str
    port: int
    reachable: bool
    latency_ms: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class RelayProbe:
    host: str
    hbbs: ProbeResult
    hbbr: ProbeResult

    @property
    def ok(self) -> bool:
        """True iff BOTH the ID server and the relay fallback are reachable.

        The session can technically run as long as hbbs is up (P2P happy
        path), but hbbr-down means symmetric-NAT customers will silently
        fail. Treat both ports as required for "green".
        """
        return self.hbbs.reachable and self.hbbr.reachable


async def probe_endpoint(
    host: str, port: int, timeout: float = DEFAULT_PROBE_TIMEOUT_S,
) -> ProbeResult:
    """TCP-connect to (host, port) and immediately close. Returns ProbeResult.

    Used by `RustDeskClient.probe_relay()` and by the dry-run CLI's
    optional --probe flag. Does not raise — failures are encoded in the
    returned ProbeResult so callers can render a status table.
    """
    loop = asyncio.get_event_loop()
    started = loop.time()
    writer: asyncio.StreamWriter | None = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout,
        )
    except asyncio.TimeoutError:
        return ProbeResult(host=host, port=port, reachable=False, error="timeout")
    except OSError as exc:
        return ProbeResult(
            host=host, port=port, reachable=False, error=f"{type(exc).__name__}: {exc}",
        )
    else:
        latency = (loop.time() - started) * 1000.0
        return ProbeResult(host=host, port=port, reachable=True, latency_ms=latency)
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass


async def probe_relay(
    cfg: ConnectionConfig | None = None,
    timeout: float = DEFAULT_PROBE_TIMEOUT_S,
) -> RelayProbe:
    """Probe both hbbs (TCP 21115) and hbbr (TCP 21117) on the configured relay."""
    cfg = cfg or ConnectionConfig()
    hbbs_res, hbbr_res = await asyncio.gather(
        probe_endpoint(cfg.relay_host, DEFAULT_HBBS_ID_PORT, timeout),
        probe_endpoint(cfg.relay_host, cfg.hbbr_port, timeout),
    )
    return RelayProbe(host=cfg.relay_host, hbbs=hbbs_res, hbbr=hbbr_res)


class RustDeskClient:
    """Default operator-side transport.

    Dual-mode by design:

      1. **Bound mode** — when `connect()` is called and a shim binary is
         configured (via `$KLX_RDSHIM_BIN` or `shim_bin=` ctor arg), the
         client spawns the subprocess, completes the v0 handshake, and
         exposes a real frame round-trip. This is the G34.1 production
         path.

      2. **In-process mode** — when no shim is configured, the client
         remains an in-process stub whose frame queue is fed by
         `_inject_frame_for_tests`. Preserves the pre-G34.1 contract for
         the session-loop unit tests, dry-run CLI, and CI environments
         without the Rust toolchain.

    The mode is decided at `connect()` time based on `shim_bin` / env.
    Once selected, the mode does not change for the lifetime of the
    client instance.

    Higher-level callers (session loop, killswitch, recording) target
    only the public Protocol — `connect / frames / send_event / close` —
    so they remain mode-agnostic.
    """

    def __init__(
        self,
        cfg: ConnectionConfig,
        shim_bin: str | None = None,
    ):
        self.cfg = cfg
        self._connected = False
        self._frame_queue: asyncio.Queue[Frame] = asyncio.Queue(maxsize=8)
        self._sequence = 0
        # Bound-mode state. None means "in-process / stub mode".
        self._shim_bin = shim_bin
        self._shim_transport = None  # type: ignore[var-annotated]
        self._shim_frame_task: asyncio.Task | None = None

    async def probe_relay(self, timeout: float = DEFAULT_PROBE_TIMEOUT_S) -> RelayProbe:
        """Pre-flight relay reachability — call before `connect()` to fail fast.

        Returns the RelayProbe so the caller (session loop / dry-run CLI) can
        log a clear diagnostic. Does not mutate the client.
        """
        return await probe_relay(self.cfg, timeout=timeout)

    def _resolve_shim_bin(self) -> str | None:
        """Returns the shim binary to spawn, or None for in-process mode.

        Priority: ctor arg > `$KLX_RDSHIM_BIN` env. Empty/whitespace
        values are treated as unset so an accidental empty export does
        not silently turn off the stub path.
        """
        candidate = self._shim_bin or os.environ.get("KLX_RDSHIM_BIN", "")
        candidate = candidate.strip()
        return candidate or None

    async def _connect(self) -> None:
        """Internal connect — spawn shim if configured, else stay in-process.

        Split from `connect()` so the public method retains its old
        signature and the bound-mode lifecycle is isolated for tests.
        """
        shim_bin = self._resolve_shim_bin()
        if shim_bin is None:
            # In-process mode: nothing to do beyond marking connected.
            log.info(
                "rustdesk connect (in-process) relay=%s customer_id=%s",
                self.cfg.relay_host,
                self.cfg.customer_id[:6] + "…",
            )
            return

        # Bound mode: spawn shim and drive the v0 protocol.
        # Lazy import to keep `protocol` import-cycle-free (rdshim_ipc
        # imports from protocol).
        from .rdshim_ipc import ShimSubprocessTransport, build_shim_argv

        argv = build_shim_argv(binary=shim_bin)
        log.info("rustdesk connect (bound) shim=%s argv=%s", shim_bin, argv)
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        transport = ShimSubprocessTransport(process=process)
        try:
            hello = await transport.handshake()
            log.info(
                "rustdesk shim hello version=%s commit=%s",
                hello.shim_version,
                hello.librustdesk_commit,
            )
            await transport.connect(self.cfg)
        except Exception:
            # Clean up the subprocess before the exception bubbles up so
            # we don't leak a zombie when, e.g., the shim refuses the
            # connect command.
            try:
                await transport.close()
            except Exception:  # noqa: BLE001
                pass
            raise

        self._shim_transport = transport
        # Pump frames from the shim's queue into our local queue so the
        # `frames()` async-iterator contract stays identical between
        # in-process and bound modes.
        self._shim_frame_task = asyncio.create_task(self._pump_frames_from_shim())

    async def _pump_frames_from_shim(self) -> None:
        """Background task — copies frames from shim queue → local queue.

        Runs only in bound mode. Exits cleanly on shim disconnect.
        """
        if self._shim_transport is None:
            return
        try:
            async for frame in self._shim_transport.frames():
                # Bounded queue — back-pressure is intentional. If the
                # operator is slower than the customer (rare; we
                # sub-sample to 1.5fps for the LLM), older frames drop.
                if self._frame_queue.full():
                    try:
                        self._frame_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                await self._frame_queue.put(frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("rustdesk frame-pump exited: %s", exc)

    async def _recv_frame(self, timeout: float = 10.0) -> Frame | None:
        """Internal frame receive — used by `frames()` async-iterator.

        Returns the next Frame, or None if the connection has closed
        and the queue is drained.
        """
        try:
            return await asyncio.wait_for(self._frame_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def _send_event(self, event: InputEvent) -> None:
        """Internal event send — bound mode delegates to shim, in-process is a no-op log.

        Raises RuntimeError if connect() has not been called.
        """
        if not self._connected:
            raise RuntimeError("connect() first")
        if self._shim_transport is not None:
            await self._shim_transport.send_event(event)
            return
        # In-process mode: log only, useful for dry-run CLI.
        log.info(
            "rustdesk send_event (in-process) kind=%s xy=(%s,%s)",
            event.kind.value,
            event.x,
            event.y,
        )

    async def connect(self, cfg: ConnectionConfig | None = None) -> None:
        if cfg is not None:
            self.cfg = cfg
        if not self.cfg.customer_id:
            raise ValueError("customer_id required")
        if not self.cfg.session_password:
            raise ValueError("session_password required")
        await self._connect()
        self._connected = True

    async def frames(self) -> AsyncIterator[Frame]:
        if not self._connected:
            raise RuntimeError("connect() first")
        while self._connected:
            frame = await self._recv_frame(timeout=10.0)
            if frame is None:
                log.warning("rustdesk frame timeout — queue empty for 10s")
                continue
            yield frame

    async def send_event(self, event: InputEvent) -> None:
        await self._send_event(event)

    async def close(self) -> None:
        self._connected = False
        if self._shim_frame_task is not None:
            self._shim_frame_task.cancel()
            try:
                await self._shim_frame_task
            except (asyncio.CancelledError, Exception):
                pass
            self._shim_frame_task = None
        if self._shim_transport is not None:
            try:
                await self._shim_transport.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("rustdesk shim close error: %s", exc)
            self._shim_transport = None
        log.info("rustdesk close")

    # ── Test hook ────────────────────────────────────────────────────────────
    async def _inject_frame_for_tests(self, frame: Frame) -> None:
        """Tests push synthesized frames in; production replaces this with
        the librustdesk callback."""
        await self._frame_queue.put(frame)
