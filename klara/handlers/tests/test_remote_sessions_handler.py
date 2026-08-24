"""Handler-level tests for infra/klara.handlers/remote_sessions.py.

iter-41 deferred from iter-40: the warmup_state + frame_pump_state fields
exposed at GET /api/remote-sessions/{session_id} are unit-tested at the derivation
layer (rustdesk_controller/tests/test_scaffold.py) but the wire contract
between the dashboard and the handler was previously unverified. This
file pins the response shape so a future refactor that drops either
field from the in_memory block — or renames one — fails in CI.

We mock the asyncpg pool with a minimal fake that satisfies the
acquire-context-manager + fetchrow-coroutine protocol the handler uses;
no live DB connection is opened.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra"))

from rustdesk_controller import session  # noqa: E402


class _FakeConn:
    """Minimal asyncpg Connection: only fetchrow is used by get_session."""

    def __init__(self, row: dict | None) -> None:
        self._row = row
        self.fetchrow_calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, query: str, *args):
        self.fetchrow_calls.append((query, args))
        return self._row


class _FakeAcquire:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakeConn:
        return self._conn

    async def __aexit__(self, *exc) -> None:
        return None


class _FakePool:
    """Minimal asyncpg Pool: get_session only uses `acquire()` ctx-mgr."""

    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self._conn)


def _install_pool_and_manager(monkeypatch, *, row: dict | None, mgr: session.SessionManager):
    """Wire fake pool + SessionManager into the handler module."""
    from klara.handlers import remote_sessions

    conn = _FakeConn(row)
    pool = _FakePool(conn)

    async def _fake_get_pool():
        return pool

    monkeypatch.setattr(remote_sessions, "get_pool", _fake_get_pool)
    monkeypatch.setattr(remote_sessions, "session_manager", lambda: mgr)
    return remote_sessions, conn


def _db_row(session_id: str) -> dict:
    """Minimal klaravex_remote_sessions row — only session_id is read."""
    return {
        "session_id": session_id,
        "customer_email": "a@b.com",
        "state": "pending_connect",
        "created_at": "2026-06-17T22:00:00Z",
    }


def test_get_session_exposes_warmup_state_and_pump_state_for_live_session(monkeypatch):
    """Wire-contract pin: GET /api/remote-sessions/{session_id} MUST include
    in_memory.warmup_state and in_memory.frame_pump_state. The dashboard
    renders these fields verbatim — dropping or renaming either is a
    breaking contract change that should fail CI.
    """
    mgr = session.SessionManager()
    sess = mgr.create_session(
        customer_email="a@b.com", customer_region="us", goal="fix wifi",
    )
    # Synthetic terminal audit row to lock the warmup_state surface.
    sess.audit.append(sess.session_id, "warmup_completed", {"transport_kind": "shim"})

    remote_sessions, _ = _install_pool_and_manager(
        monkeypatch, row=_db_row(sess.session_id), mgr=mgr,
    )
    result = asyncio.run(remote_sessions.get_session(sess.session_id))

    assert "in_memory" in result
    im = result["in_memory"]
    assert "warmup_state" in im, "dashboard contract: warmup_state field missing"
    assert "frame_pump_state" in im, "dashboard contract: frame_pump_state field missing"
    assert im["warmup_state"] == "completed"
    assert im["frame_pump_state"] == "absent"
    # Existing fields still present (regression-lock for iter-40 not
    # accidentally dropping any).
    assert im["state"] == "pending_connect"
    assert im["killed"] is False
    assert im["audit_chain_intact"] is True


def test_get_session_returns_null_in_memory_when_session_not_resident(monkeypatch):
    """A session row in the DB without a matching SessionManager entry
    (e.g. a worker restart) must return null on every in_memory field
    rather than 500ing. The dashboard treats null as 'session no longer
    held in memory' and falls back to the DB-only view.
    """
    mgr = session.SessionManager()  # empty — no resident session
    remote_sessions, _ = _install_pool_and_manager(
        monkeypatch, row=_db_row("ghost-1"), mgr=mgr,
    )
    result = asyncio.run(remote_sessions.get_session("ghost-1"))

    im = result["in_memory"]
    # iter-42 code-review Medium #5: assert KEY PRESENCE not just is None.
    # A regression that silently drops the key would let
    # `result.in_memory.warmup_state` evaluate to undefined on the
    # dashboard side without breaking this test.
    assert "warmup_state" in im
    assert "frame_pump_state" in im
    assert "state" in im
    assert "killed" in im
    assert im["state"] is None
    assert im["killed"] is None
    assert im["warmup_state"] is None
    assert im["frame_pump_state"] is None


def test_get_session_404s_when_db_row_absent(monkeypatch):
    """No DB row → 404. Even if a SessionManager has the session
    in-memory (race during start), the canonical existence test is the
    DB row — surfaces a clearer error than 'session held but never
    persisted'.
    """
    from fastapi import HTTPException
    mgr = session.SessionManager()
    remote_sessions, _ = _install_pool_and_manager(monkeypatch, row=None, mgr=mgr)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(remote_sessions.get_session("does-not-exist"))
    assert excinfo.value.status_code == 404


def test_get_session_pump_running_state_round_trips(monkeypatch):
    """End-to-end on the dashboard contract: an active pump on the
    in-memory session surfaces as frame_pump_state='running' in the
    handler response, not just in the unit-level derivation.
    """
    mgr = session.SessionManager()
    sess = mgr.create_session(
        customer_email="a@b.com", customer_region="us", goal="fix wifi",
    )

    # Park a fake pump task so frame_pump_state() returns 'running'.
    async def _park():
        await asyncio.Event().wait()

    async def _run():
        sess.frame_pump_task = asyncio.create_task(_park(), name="pump-test")
        await asyncio.sleep(0)
        try:
            remote_sessions, _ = _install_pool_and_manager(
                monkeypatch, row=_db_row(sess.session_id), mgr=mgr,
            )
            result = await remote_sessions.get_session(sess.session_id)
            assert result["in_memory"]["frame_pump_state"] == "running"
        finally:
            sess.frame_pump_task.cancel()
    asyncio.run(_run())
