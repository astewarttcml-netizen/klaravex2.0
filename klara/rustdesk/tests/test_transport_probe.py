"""Tests for G34 transport reachability probe (protocol.probe_endpoint / probe_relay).

These cover the pre-flight check the session loop runs before consenting +
recording, so an unreachable relay surfaces as a clear diagnostic instead of
stalling inside librustdesk. They use loopback TCP listeners — no network
dependency on the live Hetzner relay.

Run: `python3 -m pytest infra/rustdesk_controller/tests -q` from repo root.
"""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra"))

from rustdesk_controller import protocol  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────


async def _start_loopback_listener() -> tuple[asyncio.AbstractServer, int]:
    """Bind a TCP server on 127.0.0.1:0 that accepts then immediately closes."""

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass

    server = await asyncio.start_server(_handle, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    return server, port


def _grab_closed_port() -> int:
    """Bind+release a socket on 127.0.0.1 to learn a port that is definitely closed."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ── probe_endpoint ─────────────────────────────────────────────────────────


def test_probe_endpoint_reachable_on_open_loopback_port():
    async def run() -> None:
        server, port = await _start_loopback_listener()
        try:
            result = await protocol.probe_endpoint("127.0.0.1", port, timeout=1.0)
        finally:
            server.close()
            await server.wait_closed()

        assert result.reachable is True
        assert result.host == "127.0.0.1"
        assert result.port == port
        assert result.error is None
        assert result.latency_ms is not None and result.latency_ms >= 0.0

    asyncio.run(run())


def test_probe_endpoint_unreachable_on_closed_port_returns_error_string():
    closed_port = _grab_closed_port()

    async def run() -> None:
        return await protocol.probe_endpoint("127.0.0.1", closed_port, timeout=1.0)

    result = asyncio.run(run())

    assert result.reachable is False
    assert result.host == "127.0.0.1"
    assert result.port == closed_port
    assert result.latency_ms is None
    assert result.error is not None
    # OSError class name shows up in the encoded error so operators can
    # tell "connection refused" apart from "timeout" in logs.
    assert "Error" in result.error or "refused" in result.error.lower()


def test_probe_endpoint_times_out_against_unroutable_address():
    """RFC 5737 TEST-NET-1 (192.0.2.0/24) is reserved for documentation and
    should never route, giving us a deterministic timeout path without
    depending on a closed loopback port."""

    async def run() -> None:
        return await protocol.probe_endpoint("192.0.2.1", 21115, timeout=0.25)

    result = asyncio.run(run())
    # Either "timeout" (most platforms) or an immediate OSError ("no route to
    # host") is an acceptable outcome — both mean the relay is unreachable
    # and both encode that as reachable=False with a non-empty error.
    assert result.reachable is False
    assert result.error
    assert result.latency_ms is None


# ── probe_relay ────────────────────────────────────────────────────────────


def test_probe_relay_calls_both_hbbs_and_hbbr_ports(monkeypatch):
    captured: list[tuple[str, int]] = []

    async def fake_probe_endpoint(host, port, timeout=protocol.DEFAULT_PROBE_TIMEOUT_S):
        captured.append((host, port))
        return protocol.ProbeResult(host=host, port=port, reachable=True, latency_ms=4.2)

    monkeypatch.setattr(protocol, "probe_endpoint", fake_probe_endpoint)

    cfg = protocol.ConnectionConfig(relay_host="relay.test")
    relay = asyncio.run(protocol.probe_relay(cfg))

    assert relay.host == "relay.test"
    assert (cfg.relay_host, protocol.DEFAULT_HBBS_ID_PORT) in captured
    assert (cfg.relay_host, cfg.hbbr_port) in captured
    assert len(captured) == 2
    assert relay.ok is True


def test_probe_relay_ok_false_when_either_port_unreachable(monkeypatch):
    async def half_down(host, port, timeout=protocol.DEFAULT_PROBE_TIMEOUT_S):
        # hbbs (21115) up, hbbr (21117) down
        if port == protocol.DEFAULT_HBBS_ID_PORT:
            return protocol.ProbeResult(host=host, port=port, reachable=True, latency_ms=3.0)
        return protocol.ProbeResult(host=host, port=port, reachable=False, error="timeout")

    monkeypatch.setattr(protocol, "probe_endpoint", half_down)

    relay = asyncio.run(protocol.probe_relay())
    assert relay.hbbs.reachable is True
    assert relay.hbbr.reachable is False
    assert relay.ok is False


def test_rustdesk_client_probe_relay_delegates_to_module_function(monkeypatch):
    """The client method must use its own cfg, not a default ConnectionConfig,
    so operators can probe staging vs prod without re-instantiating."""

    seen: list[str] = []

    async def fake(cfg, timeout=protocol.DEFAULT_PROBE_TIMEOUT_S):
        seen.append(cfg.relay_host)
        return protocol.RelayProbe(
            host=cfg.relay_host,
            hbbs=protocol.ProbeResult(cfg.relay_host, 21115, True, latency_ms=1.0),
            hbbr=protocol.ProbeResult(cfg.relay_host, 21117, True, latency_ms=1.0),
        )

    monkeypatch.setattr(protocol, "probe_relay", fake)

    cfg = protocol.ConnectionConfig(relay_host="staging.klaravex")
    client = protocol.RustDeskClient(cfg)
    relay = asyncio.run(client.probe_relay())

    assert seen == ["staging.klaravex"]
    assert relay.ok is True
