"""G34.3 transport factory — selects the operator-side transport at runtime.

This is the bridge between `session.py` (which only knows the
`RustDeskTransport` Protocol) and the two concrete implementations:

    1. `ShimSubprocessTransport` (rdshim_ipc.py) — production path. Spawns
       `klx-rdshim` (or `$KLX_RDSHIM_BIN`) and drives it via the v0 JSON
       line protocol. Selected when `KLX_RDSHIM_BIN` is set OR when
       `transport_factory(prefer_shim=True)` is called explicitly.

    2. `RustDeskClient` (protocol.py) — stub / dev fallback. Returned when
       no shim binary is configured. Useful for the dry-run CLI, the
       session-loop unit tests, and CI environments where the Rust shim
       has not been built.

The factory is intentionally pure and synchronous — spawning the
subprocess is deferred to the caller's lifecycle (so cancellation and
timeouts compose with `asyncio.TaskGroup`).

G34.4 will retire the stub once the shim ships to all environments.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Iterable

from .protocol import ConnectionConfig, RustDeskClient, RustDeskTransport
from .rdshim_ipc import ShimSubprocessTransport, build_shim_argv

log = logging.getLogger("klaravex.rustdesk.factory")


SHIM_ENV_VAR = "KLX_RDSHIM_BIN"


def shim_configured() -> bool:
    """True iff the environment selects the production shim transport.

    We treat any non-empty value of `$KLX_RDSHIM_BIN` as opt-in. We do
    NOT stat the binary here — the spawn step will surface a clear
    `FileNotFoundError` if the path is wrong, which is a better
    diagnostic than a silent fallback to the stub.
    """
    value = os.environ.get(SHIM_ENV_VAR, "")
    return bool(value.strip())


@dataclass(frozen=True)
class TransportSelection:
    """Diagnostic record describing which transport the factory picked.

    Returned alongside the transport so callers (dry-run CLI, audit log)
    can log which path was taken without re-deriving the decision.
    """

    kind: str  # "shim" | "stub"
    reason: str
    binary: str | None = None  # set when kind == "shim"


async def spawn_shim_transport(
    cfg: ConnectionConfig,
    binary: str | None = None,
    extra_argv: Iterable[str] = (),
) -> tuple[ShimSubprocessTransport, TransportSelection]:
    """Spawn the klx-rdshim binary and return a handshaken transport.

    The returned transport has already completed `handshake()`, so the
    caller's first action is `await transport.connect(cfg)`.

    Raises `FileNotFoundError` if the binary is not on PATH.
    Raises `IPCVersionMismatch` if the shim advertises an unsupported
    major version.
    """
    argv = build_shim_argv(binary=binary, extra=extra_argv)
    log.info("rdshim spawn argv=%s", argv)
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    transport = ShimSubprocessTransport(process=process)
    await transport.handshake()
    selection = TransportSelection(
        kind="shim",
        reason=f"{SHIM_ENV_VAR} set; shim handshake succeeded",
        binary=argv[0],
    )
    return transport, selection


def make_stub_transport(cfg: ConnectionConfig) -> tuple[RustDeskClient, TransportSelection]:
    """Return the in-process stub. Synchronous — no I/O.

    Used when the production shim is unavailable (CI, dev box, dry-run
    CLI without `--real-shim`). The stub satisfies the protocol contract
    but its `frames()` queue is empty until tests inject frames via
    `_inject_frame_for_tests`.
    """
    selection = TransportSelection(
        kind="stub",
        reason=f"{SHIM_ENV_VAR} not set; using in-process stub",
    )
    return RustDeskClient(cfg), selection


async def transport_factory(
    cfg: ConnectionConfig,
    prefer_shim: bool | None = None,
    binary: str | None = None,
    extra_argv: Iterable[str] = (),
) -> tuple[RustDeskTransport, TransportSelection]:
    """Return the transport the session loop should use.

    `prefer_shim`:
        - None (default) — auto-detect from `$KLX_RDSHIM_BIN`.
        - True — force shim; raises if the binary isn't spawnable.
        - False — force stub; useful for dry-run CLI and tests.

    The factory is async because spawning the shim is async; the stub
    branch resolves immediately with no awaits.
    """
    if prefer_shim is None:
        prefer_shim = shim_configured()

    if not prefer_shim:
        return make_stub_transport(cfg)

    return await spawn_shim_transport(cfg, binary=binary, extra_argv=extra_argv)


__all__ = [
    "SHIM_ENV_VAR",
    "TransportSelection",
    "shim_configured",
    "make_stub_transport",
    "spawn_shim_transport",
    "transport_factory",
]
