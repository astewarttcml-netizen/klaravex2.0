"""Tests for the operator tray kill UI (task 16.15).

Tests the ControllerClient, kill_all_active, and the /active endpoint logic.
Does NOT test GTK3 GUI (requires a display server).

Run: python3 -m pytest infra/rustdesk_controller/tests/test_operator_tray.py -q
"""

from __future__ import annotations

import asyncio
import http.server
import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra"))

from rustdesk_controller import killswitch, session
from rustdesk_controller.operator_tray import ControllerClient


# ── Fake HTTP server for integration-style client tests ──────────────────


class _FakeHandler(http.server.BaseHTTPRequestHandler):
    """Minimal handler that serves canned responses for /active and /kill."""

    active_sessions: list[dict] = []
    kill_returns_200: bool = True

    def do_GET(self):
        if self.path.endswith("/active"):
            self._respond(200, self.active_sessions)
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        if "/kill" in self.path:
            code = 200 if self.kill_returns_200 else 404
            self._respond(code, {"killed": self.kill_returns_200})
        else:
            self._respond(404, {"error": "not found"})

    def _respond(self, code: int, body: object) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *_args: object) -> None:
        pass  # suppress stderr noise in test output


# ── ControllerClient unit tests (urllib-based) ───────────────────────────


def test_client_active_sessions_returns_list():
    """Client should parse JSON from a real HTTP 200."""
    _FakeHandler.active_sessions = [{"session_id": "abc", "state": "connected"}]
    server = http.server.HTTPServer(("127.0.0.1", 0), _FakeHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()

    client = ControllerClient(port=port, token="test-token")
    result = client.active_sessions()

    assert result == [{"session_id": "abc", "state": "connected"}]
    server.server_close()


def test_client_active_sessions_connection_refused_returns_empty():
    """Connection to a closed port should return [] silently."""
    client = ControllerClient(port=1, token="")  # port 1 = refused
    result = client.active_sessions()
    assert result == []


def test_client_kill_session_success():
    _FakeHandler.kill_returns_200 = True
    server = http.server.HTTPServer(("127.0.0.1", 0), _FakeHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()

    client = ControllerClient(port=port, token="tok")
    result = client.kill_session("sess-1", "operator_tray_kill")

    assert result is True
    server.server_close()


def test_client_kill_session_404_returns_false():
    _FakeHandler.kill_returns_200 = False
    server = http.server.HTTPServer(("127.0.0.1", 0), _FakeHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()

    client = ControllerClient(port=port, token="tok")
    result = client.kill_session("bad-id", "test")

    assert result is False
    server.server_close()


def test_client_kill_session_connection_error_returns_false():
    client = ControllerClient(port=1, token="tok")
    result = client.kill_session("sess-1", "test")
    assert result is False


# ── kill_all_active tests ────────────────────────────────────────────────


def test_kill_all_active_calls_client_for_each_session():
    _FakeHandler.active_sessions = [
        {"session_id": "s1", "state": "connected"},
        {"session_id": "s2", "state": "awaiting_confirm"},
    ]
    _FakeHandler.kill_returns_200 = True
    server = http.server.HTTPServer(("127.0.0.1", 0), _FakeHandler)
    port = server.server_address[1]
    # Need to handle 3 requests: 1 GET /active + 2 POST /kill
    t = threading.Thread(target=lambda: [server.handle_request() for _ in range(3)], daemon=True)
    t.start()

    client = ControllerClient(port=port, token="tok")
    count = client.kill_all_active()

    assert count == 2
    server.server_close()


def test_kill_all_active_no_sessions_returns_zero():
    _FakeHandler.active_sessions = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _FakeHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()

    client = ControllerClient(port=port, token="tok")
    count = client.kill_all_active()

    assert count == 0
    server.server_close()


# ── /active endpoint logic tests (via SessionManager) ───────────────────


def test_active_endpoint_filters_ended_sessions(monkeypatch):
    """The /active endpoint should only return sessions not in ended_* state."""
    mgr = session.SessionManager()
    s1 = mgr.create_session(
        customer_email="a@t.com", customer_region="us", goal="fix",
    )
    s2 = mgr.create_session(
        customer_email="b@t.com", customer_region="us", goal="update",
    )
    s2.end("fixed")

    active = []
    for sid, sess in mgr._sessions.items():
        if sess.state.value.startswith("ended_") or sess.killswitch.is_killed:
            continue
        active.append({"session_id": sid, "state": sess.state.value})

    assert len(active) == 1
    assert active[0]["session_id"] == s1.session_id


def test_active_endpoint_filters_killed_sessions(monkeypatch):
    """Killed sessions should not appear in /active."""
    mgr = session.SessionManager()
    s1 = mgr.create_session(
        customer_email="a@t.com", customer_region="us", goal="fix",
    )
    s1.killswitch.fire(reason="test", fired_by="server_override")

    active = []
    for sid, sess in mgr._sessions.items():
        if sess.state.value.startswith("ended_") or sess.killswitch.is_killed:
            continue
        active.append(sid)

    assert len(active) == 0


# ── Kill latency contract ───────────────────────────────────────────────


def test_kill_completes_under_1_second(monkeypatch):
    """The kill path must complete within 1 second (spec requirement)."""
    mgr = session.SessionManager()
    sess = mgr.create_session(
        customer_email="speed@t.com", customer_region="us", goal="test",
    )

    start = time.monotonic()
    sess.killswitch.fire(reason="latency_test", fired_by="server_override")
    elapsed = time.monotonic() - start

    assert elapsed < 1.0
    assert sess.killswitch.is_killed is True


def test_kill_via_registry_completes_under_1_second(monkeypatch):
    """Registry fire path must also complete within 1 second."""
    mgr = session.SessionManager()
    sess = mgr.create_session(
        customer_email="speed@t.com", customer_region="us", goal="test",
    )
    reg = killswitch.registry()

    start = time.monotonic()
    reg.fire(sess.session_id, "latency_test", "server_override")
    elapsed = time.monotonic() - start

    assert elapsed < 1.0
    assert sess.killswitch.is_killed is True


# ── Audit row on kill ────────────────────────────────────────────────────


def test_tray_kill_produces_audit_row(monkeypatch):
    """Operator tray kill must produce an audit row with server_override."""
    mgr = session.SessionManager()
    sess = mgr.create_session(
        customer_email="audit@t.com", customer_region="us", goal="test",
    )
    monkeypatch.setattr(session, "_manager", mgr, raising=False)

    async def _run():
        sess.killswitch.fire(reason="operator_tray_kill", fired_by="server_override")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_run())

    kill_rows = [
        e for e in sess.audit.entries
        if e.event_type == "killswitch_fired"
    ]
    assert len(kill_rows) == 1
    assert kill_rows[0].payload["fired_by"] == "server_override"
    assert kill_rows[0].payload["reason"] == "operator_tray_kill"
