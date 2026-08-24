"""Tests for G34.3 transport factory.

Covers:
    - env-driven selection between stub and shim
    - explicit prefer_shim override (force-stub for tests, force-shim for prod)
    - TransportSelection diagnostic payload
    - spawn_shim_transport happy path against a Python-driven mock binary
      that speaks the v0 line protocol (no Rust toolchain required in CI)
    - FileNotFoundError surfaces when binary missing and prefer_shim=True
"""

from __future__ import annotations

import asyncio
import os
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra"))

from rustdesk_controller import factory, protocol  # noqa: E402
from rustdesk_controller.rdshim_ipc import (  # noqa: E402
    IPCVersionMismatch,
    ShimSubprocessTransport,
)


# ── shim_configured ────────────────────────────────────────────────────────


def test_shim_configured_false_when_env_unset(monkeypatch):
    monkeypatch.delenv(factory.SHIM_ENV_VAR, raising=False)
    assert factory.shim_configured() is False


def test_shim_configured_false_when_env_whitespace(monkeypatch):
    monkeypatch.setenv(factory.SHIM_ENV_VAR, "   ")
    assert factory.shim_configured() is False


def test_shim_configured_true_when_env_set(monkeypatch):
    monkeypatch.setenv(factory.SHIM_ENV_VAR, "/tmp/klx-rdshim")
    assert factory.shim_configured() is True


# ── make_stub_transport ────────────────────────────────────────────────────


def test_make_stub_transport_returns_rustdeskclient_with_cfg():
    cfg = protocol.ConnectionConfig(
        relay_host="stub.test", customer_id="abc", session_password="pw",
    )
    transport, selection = factory.make_stub_transport(cfg)
    assert isinstance(transport, protocol.RustDeskClient)
    assert transport.cfg is cfg
    assert selection.kind == "stub"
    assert selection.binary is None
    assert factory.SHIM_ENV_VAR in selection.reason


# ── transport_factory: forced stub path ────────────────────────────────────


def test_transport_factory_force_stub_returns_stub_even_with_env_set(monkeypatch):
    monkeypatch.setenv(factory.SHIM_ENV_VAR, "/nonexistent/klx-rdshim")
    cfg = protocol.ConnectionConfig(
        relay_host="forced.test", customer_id="x", session_password="y",
    )
    transport, selection = asyncio.run(
        factory.transport_factory(cfg, prefer_shim=False)
    )
    assert isinstance(transport, protocol.RustDeskClient)
    assert selection.kind == "stub"


def test_transport_factory_auto_picks_stub_when_env_unset(monkeypatch):
    monkeypatch.delenv(factory.SHIM_ENV_VAR, raising=False)
    cfg = protocol.ConnectionConfig(customer_id="x", session_password="y")
    transport, selection = asyncio.run(factory.transport_factory(cfg))
    assert isinstance(transport, protocol.RustDeskClient)
    assert selection.kind == "stub"


# ── transport_factory: forced shim with binary missing ─────────────────────


def test_transport_factory_force_shim_raises_when_binary_missing(monkeypatch):
    monkeypatch.setenv(factory.SHIM_ENV_VAR, "/definitely/not/here/klx-rdshim")

    cfg = protocol.ConnectionConfig(customer_id="x", session_password="y")

    with pytest.raises(FileNotFoundError):
        asyncio.run(factory.transport_factory(cfg, prefer_shim=True))


# ── transport_factory: shim spawn happy path (Python mock binary) ──────────


def _write_mock_shim(tmp_path: Path, body: str) -> Path:
    """Write a Python script that pretends to be klx-rdshim.

    Returned path is the *script*, not an executable; tests invoke it via
    `binary=sys.executable, extra_argv=[script]` so we sidestep macOS
    shebang quirks with sandboxed temp paths.
    """
    shim = tmp_path / "fake-klx-rdshim.py"
    shim.write_text("import sys\n" + textwrap.dedent(body))
    return shim


def _spawn_args(shim_path: Path) -> dict:
    """Common kwargs to spawn the python mock shim via the factory."""
    return {"binary": sys.executable, "extra_argv": [str(shim_path)]}


def test_spawn_shim_transport_happy_path(tmp_path, monkeypatch):
    # Mock shim that emits a valid v0 hello then idles on stdin.
    shim = _write_mock_shim(
        tmp_path,
        body=textwrap.dedent(
            """\
            sys.stdout.write('{"kind":"hello","shim_version":"0.1.0","librustdesk_commit":"abc123"}\\n')
            sys.stdout.flush()
            # Hold the pipe open so the parent's handshake can succeed and
            # the parent decides when to close us via stdin EOF.
            sys.stdin.read()
            """
        ),
    )

    cfg = protocol.ConnectionConfig(customer_id="x", session_password="y")

    async def run():
        transport, selection = await factory.spawn_shim_transport(
            cfg, **_spawn_args(shim),
        )
        try:
            assert isinstance(transport, ShimSubprocessTransport)
            assert transport.hello is not None
            assert transport.hello.shim_version == "0.1.0"
            assert transport.hello.major_version == "0"
            assert selection.kind == "shim"
            assert selection.binary == sys.executable
        finally:
            await transport.close()

    asyncio.run(run())


def test_spawn_shim_transport_rejects_unsupported_major_version(tmp_path):
    shim = _write_mock_shim(
        tmp_path,
        body=textwrap.dedent(
            """\
            sys.stdout.write('{"kind":"hello","shim_version":"99.0.0","librustdesk_commit":"x"}\\n')
            sys.stdout.flush()
            sys.stdin.read()
            """
        ),
    )

    cfg = protocol.ConnectionConfig(customer_id="x", session_password="y")

    async def run():
        with pytest.raises(IPCVersionMismatch):
            await factory.spawn_shim_transport(cfg, **_spawn_args(shim))

    asyncio.run(run())


# ── transport_factory auto-spawns shim when env points at real binary ──────


def test_transport_factory_auto_spawns_shim_when_env_set(
    tmp_path, monkeypatch,
):
    """When env is set AND prefer_shim is not forced False, factory takes
    the shim branch (not the stub). We pass an explicit binary+extra_argv
    pair to actually succeed at spawn, since the env-var contract is
    'shim is configured', not 'env value is the literal argv[0]'."""
    shim = _write_mock_shim(
        tmp_path,
        body=textwrap.dedent(
            """\
            sys.stdout.write('{"kind":"hello","shim_version":"0.2.3","librustdesk_commit":"deadbeef"}\\n')
            sys.stdout.flush()
            sys.stdin.read()
            """
        ),
    )
    monkeypatch.setenv(factory.SHIM_ENV_VAR, "/marker/value-not-used-when-binary-overridden")

    cfg = protocol.ConnectionConfig(customer_id="x", session_password="y")

    async def run():
        transport, selection = await factory.transport_factory(
            cfg, **_spawn_args(shim),
        )
        try:
            assert isinstance(transport, ShimSubprocessTransport)
            assert selection.kind == "shim"
        finally:
            await transport.close()

    asyncio.run(run())
