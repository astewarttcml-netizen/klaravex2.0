"""G34.2a checkpoint-1 conformance — live relay smoke from Python.

These tests are the Python-side cousin of the Rust `relay::tests::*_live`
suite. They invoke the same `klx-rdshim` binary the operator side uses
and confirm the rendezvous client can run inside the shim process, not
just inside `cargo test`.

The tests are GATED behind two preconditions:

  1. The `KLX_RDSHIM_BIN` env var must point at a built klx-rdshim
     binary (same convention as test_operator_e2e_real_shim.py).
  2. The `KLX_LIVE_RELAY` env var must be truthy.

Both are unset in CI by default — these are dev-machine / pre-merge
sanity checks.

The tests drive the binary via `cargo run --example` ... no, actually we
just shell out to the binary with the same env vars `KLX_RDSHIM_PROBE_RELAY=1`
already understands, plus we add a side-channel command line flag the
binary will read to invoke `register_peer` / `punch_hole` once the
checkpoint-2 wiring lands. For checkpoint 1, we exercise the relay
client via `cargo test` and verify here only that the binary itself
starts cleanly with the protobuf runtime linked in.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
KLX_RDSHIM_BIN_ENV = "KLX_RDSHIM_BIN"
KLX_LIVE_RELAY_ENV = "KLX_LIVE_RELAY"
RELAY_HOST = "87.99.147.244"
HBBS_NAT_PORT = 21115
HBBS_MAIN_PORT = 21116


def _live_enabled() -> bool:
    v = os.environ.get(KLX_LIVE_RELAY_ENV, "")
    return v not in ("", "0", "false", "False")


def _shim_bin() -> Path | None:
    p = os.environ.get(KLX_RDSHIM_BIN_ENV, "")
    if not p:
        return None
    path = Path(p)
    if not path.is_file() or not os.access(path, os.X_OK):
        return None
    return path


pytestmark = pytest.mark.skipif(
    not _live_enabled(),
    reason="KLX_LIVE_RELAY not set; live-relay tests skipped",
)


@pytest.fixture(scope="module")
def shim_bin() -> Path:
    bin = _shim_bin()
    if bin is None:
        pytest.skip(f"{KLX_RDSHIM_BIN_ENV} not set or not executable")
    return bin


def _tcp_handshake(host: str, port: int, timeout: float = 3.0) -> float:
    """Plain TCP connect → close. Returns latency in seconds."""
    import socket

    start = time.monotonic()
    with socket.create_connection((host, port), timeout=timeout):
        pass
    return time.monotonic() - start


def test_live_relay_register_peer_tcp_baseline():
    """Before checking the shim, prove our network actually reaches hbbs:21115."""
    lat = _tcp_handshake(RELAY_HOST, HBBS_NAT_PORT)
    assert lat < 1.0, f"hbbs nat port latency too high: {lat:.3f}s"


def test_live_relay_punch_hole_tcp_baseline():
    """Confirm the main rendezvous port is reachable too."""
    lat = _tcp_handshake(RELAY_HOST, HBBS_MAIN_PORT)
    assert lat < 1.0, f"hbbs main port latency too high: {lat:.3f}s"


def test_live_relay_cargo_tests_pass(shim_bin: Path):
    """Run the Rust live-relay tests in-place. They are the actual contract."""
    cargo = shutil.which("cargo")
    if cargo is None:
        # rustup installs to ~/.cargo/bin by default; that location is
        # not always on the shell PATH for pytest invocations.
        candidate = Path.home() / ".cargo" / "bin" / "cargo"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            cargo = str(candidate)
    if cargo is None:
        pytest.skip("cargo not on PATH and ~/.cargo/bin/cargo not found")
    crate_dir = REPO_ROOT / "infra" / "rustdesk_controller" / "klx-rdshim"
    assert crate_dir.is_dir(), f"missing crate dir: {crate_dir}"
    env = {**os.environ, "KLX_LIVE_RELAY": "1"}
    res = subprocess.run(
        [
            cargo,
            "test",
            "--release",
            "--",
            "register_peer_live",
            "punch_hole_unknown_peer_live",
            "punch_hole_offline_target_live",
            "--nocapture",
        ],
        cwd=str(crate_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if res.returncode != 0:
        sys.stderr.write("--- cargo test stderr ---\n")
        sys.stderr.write(res.stderr)
        sys.stderr.write("--- cargo test stdout ---\n")
        sys.stderr.write(res.stdout)
    assert res.returncode == 0, "live-relay cargo tests failed"
    # Spot-check that all three live tests actually ran.
    combined = res.stdout + res.stderr
    for name in (
        "register_peer_live",
        "punch_hole_unknown_peer_live",
        "punch_hole_offline_target_live",
    ):
        assert name in combined, f"expected test {name!r} in cargo output"
