"""Regression test for T-INF-12: system escalations with a synthesised
ticket_id must succeed even when no matching klaravex_tickets row exists.

The fix in klara.handlers/lib/escalation.py catches asyncpg's
ForeignKeyViolationError on the INSERT into klaravex_escalations and
retries with ticket_id=NULL.

Run with:
    pytest infra/klara.handlers/tests/test_escalation_fk_fallback.py -v
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INFRA_DIR = PROJECT_ROOT / "infra"
sys.path.insert(0, str(INFRA_DIR))

asyncpg = pytest.importorskip("asyncpg")
from klara.handlers.lib import escalation as escalation_lib  # noqa: E402


class _FakeConn:
    """Minimal asyncpg connection mock that flips behaviour on each call."""

    def __init__(self, fail_first: bool) -> None:
        self._fail_first = fail_first
        self.calls: list[tuple[Any, ...]] = []

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any]:
        self.calls.append(args)
        # First call carries the synthesised ticket_uuid; raise FK on it.
        if self._fail_first and len(self.calls) == 1:
            raise asyncpg.exceptions.ForeignKeyViolationError(
                "insert or update on table \"klaravex_escalations\" violates "
                "foreign key constraint \"klaravex_escalations_ticket_id_fkey\""
            )
        return {"id": uuid.uuid4()}

    async def __aenter__(self) -> "_FakeConn":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


class _FakePool:
    """Minimal asyncpg connection pool mock.

    Real asyncpg `Pool.acquire()` is synchronous and returns a
    `PoolAcquireContext` that is itself an async context manager (used as
    `async with pool.acquire() as conn:` in escalation.py) — it is NOT a
    coroutine. `acquire` must therefore stay a plain (non-async) method
    returning the `_FakeConn` directly, since `_FakeConn` already implements
    `__aenter__`/`__aexit__`.
    """

    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def acquire(self) -> _FakeConn:
        return self._conn



@pytest.mark.asyncio
async def test_escalate_system_ticket_falls_back_to_null_ticket_id() -> None:
    """A ticket_id with no matching klaravex_tickets row must NOT block the
    escalation. The insert retries with ticket_id=NULL and returns success."""
    conn = _FakeConn(fail_first=True)
    pool = _FakePool(conn)

    with (
        patch.object(escalation_lib, "get_pool", AsyncMock(return_value=pool)),
        patch.object(escalation_lib, "update_status", AsyncMock(return_value=None)),
        patch.object(escalation_lib, "append_event", AsyncMock(return_value=None)),
        patch.object(escalation_lib, "_telegram_send", AsyncMock(return_value=(False, "skipped"))),
        patch.object(escalation_lib, "_smtp_send", AsyncMock(return_value=(False, "skipped"))),
    ):
        result = await escalation_lib.escalate(
            ticket_id=str(uuid.uuid4()),  # valid UUID shape, but not in tickets
            client_email="watchdog@klaravex.com",
            severity="emergency",
            summary="probe failure on /health",
        )

    assert result["escalation_id"], "escalation row should be persisted"
    assert len(conn.calls) == 2, "expected 2 INSERT attempts (first FK-failed, second NULL-retry)"

    first_ticket_arg, *_ = conn.calls[0]
    second_ticket_arg, *_ = conn.calls[1]
    assert isinstance(first_ticket_arg, uuid.UUID), "first attempt sends UUID"
    assert second_ticket_arg is None, "retry sends NULL ticket_id"


@pytest.mark.asyncio
async def test_escalate_real_ticket_does_not_retry() -> None:
    """When the FK is satisfied, the original ticket_uuid is preserved and
    no retry occurs."""
    conn = _FakeConn(fail_first=False)
    pool = _FakePool(conn)

    with (
        patch.object(escalation_lib, "get_pool", AsyncMock(return_value=pool)),
        patch.object(escalation_lib, "update_status", AsyncMock(return_value=None)),
        patch.object(escalation_lib, "append_event", AsyncMock(return_value=None)),
        patch.object(escalation_lib, "_telegram_send", AsyncMock(return_value=(False, "skipped"))),
        patch.object(escalation_lib, "_smtp_send", AsyncMock(return_value=(False, "skipped"))),
    ):
        real_ticket = uuid.uuid4()
        result = await escalation_lib.escalate(
            ticket_id=str(real_ticket),
            client_email="user@example.com",
            severity="high",
            summary="real ticket flow",
        )

    assert result["escalation_id"]
    assert len(conn.calls) == 1, "no retry expected on success"
    assert conn.calls[0][0] == real_ticket, "real ticket UUID preserved"
