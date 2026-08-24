"""Tests for infra/cron/calendly_brief_sender.run_once.

Coverage:
  1. empty pending rows → returns 0 immediately (early return)
  2. all rows sent successfully → correct count returned
  3. success path → UPDATE sets status='sent', id arg present
  4. send_email failure → UPDATE sets status='failed', error truncated to 512
  5. nested exception (failure-UPDATE itself raises) → swallowed, no propagation
  6. fetch SQL has LIMIT 50
  7. fetch SQL has ORDER BY send_at
  8. fetch SQL targets klaravex_scheduled_briefs
  9. _send_telegram no-ops when TELEGRAM_TOKEN unset
  10. _send_telegram no-ops when TELEGRAM_CHAT unset
  11. _send_telegram truncates text to 4096 chars
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

INFRA = Path(__file__).resolve().parents[2]  # infra/
sys.path.insert(0, str(INFRA))

pytest.importorskip("httpx")

from cron.calendly_brief_sender import run_once, _send_telegram  # noqa: E402


# ── fake asyncpg row ──────────────────────────────────────────────────────────

def _row(id="row-001", subject="Pre-meeting: Alice", body="Brief body here."):
    return {"id": id, "subject": subject, "body": body}


# ── minimal DB fakes (Pattern 28) ────────────────────────────────────────────

class _FakeConn:
    def __init__(self, rows=(), captured=None):
        self._rows = list(rows)
        self._cap = [] if captured is None else captured

    async def fetch(self, sql: str, *args):
        self._cap.append(("fetch", sql, list(args)))
        return self._rows

    async def execute(self, sql: str, *args):
        self._cap.append(("execute", sql, list(args)))


class _FailExecConn:
    async def execute(self, *args):
        raise RuntimeError("DB execute failure")


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_):
        pass


class _FakePool:
    """All acquires share `captured`. Fetch returns `rows`."""

    def __init__(self, rows=(), captured=None):
        self._rows = rows
        self._cap = [] if captured is None else captured

    def acquire(self):
        return _FakeAcquire(_FakeConn(self._rows, self._cap))


class _SplitPool:
    """First acquire returns rows; subsequent acquires raise on execute (for nested-except tests)."""

    def __init__(self, rows, captured):
        self._rows = rows
        self._cap = captured
        self._n = 0

    def acquire(self):
        self._n += 1
        if self._n == 1:
            return _FakeAcquire(_FakeConn(self._rows, self._cap))
        return _FakeAcquire(_FailExecConn())


def _run(coro):
    return asyncio.run(coro)


# ── run_once tests ────────────────────────────────────────────────────────────

class TestRunOnce:

    def test_empty_rows_returns_zero(self):
        pool = _FakePool(rows=())
        with patch("cron.calendly_brief_sender.get_pool", return_value=pool), \
             patch("cron.calendly_brief_sender.send_email", new_callable=AsyncMock):
            assert _run(run_once()) == 0

    def test_returns_sent_count(self):
        rows = [_row(id="r1"), _row(id="r2")]
        cap: list = []
        pool = _FakePool(rows=rows, captured=cap)
        with patch("cron.calendly_brief_sender.get_pool", return_value=pool), \
             patch("cron.calendly_brief_sender.send_email", new_callable=AsyncMock), \
             patch("cron.calendly_brief_sender._send_telegram", new_callable=AsyncMock):
            result = _run(run_once())
        assert result == 2

    def test_success_updates_status_sent_with_id(self):
        row_id = "uuid-success"
        cap: list = []
        pool = _FakePool(rows=[_row(id=row_id)], captured=cap)
        with patch("cron.calendly_brief_sender.get_pool", return_value=pool), \
             patch("cron.calendly_brief_sender.send_email", new_callable=AsyncMock), \
             patch("cron.calendly_brief_sender._send_telegram", new_callable=AsyncMock):
            _run(run_once())

        exec_calls = [(sql, args) for op, sql, args in cap if op == "execute"]
        assert len(exec_calls) == 1, "exactly one UPDATE expected"
        sql, args = exec_calls[0]
        assert "sent" in sql.lower()
        assert row_id in args

    def test_failure_updates_status_failed_error_truncated(self):
        row_id = "uuid-fail"
        long_err = "E" * 1000
        cap: list = []
        pool = _FakePool(rows=[_row(id=row_id)], captured=cap)
        with patch("cron.calendly_brief_sender.get_pool", return_value=pool), \
             patch("cron.calendly_brief_sender.send_email", side_effect=RuntimeError(long_err)), \
             patch("cron.calendly_brief_sender._send_telegram", new_callable=AsyncMock):
            result = _run(run_once())

        assert result == 0
        exec_calls = [(sql, args) for op, sql, args in cap if op == "execute"]
        assert len(exec_calls) == 1
        sql, args = exec_calls[0]
        assert "failed" in sql.lower()
        assert args[0] == row_id        # $1 = id
        assert args[1] == long_err[:512]  # $2 = error, truncated
        assert len(args[1]) == 512

    def test_nested_failure_update_exception_swallowed(self):
        """send_email raises AND the 'failed' status UPDATE also raises → no propagation."""
        cap: list = []
        pool = _SplitPool(rows=[_row()], captured=cap)
        with patch("cron.calendly_brief_sender.get_pool", return_value=pool), \
             patch("cron.calendly_brief_sender.send_email", side_effect=RuntimeError("send fail")), \
             patch("cron.calendly_brief_sender._send_telegram", new_callable=AsyncMock):
            result = _run(run_once())  # must not raise
        assert result == 0

    def test_fetch_sql_has_limit_50(self):
        cap: list = []
        pool = _FakePool(rows=(), captured=cap)
        with patch("cron.calendly_brief_sender.get_pool", return_value=pool), \
             patch("cron.calendly_brief_sender.send_email", new_callable=AsyncMock):
            _run(run_once())
        fetch_sql = next(sql for op, sql, _ in cap if op == "fetch")
        assert "limit 50" in fetch_sql.lower()

    def test_fetch_sql_has_order_by_send_at(self):
        cap: list = []
        pool = _FakePool(rows=(), captured=cap)
        with patch("cron.calendly_brief_sender.get_pool", return_value=pool), \
             patch("cron.calendly_brief_sender.send_email", new_callable=AsyncMock):
            _run(run_once())
        fetch_sql = next(sql for op, sql, _ in cap if op == "fetch")
        assert "send_at" in fetch_sql.lower()

    def test_fetch_sql_targets_correct_table(self):
        cap: list = []
        pool = _FakePool(rows=(), captured=cap)
        with patch("cron.calendly_brief_sender.get_pool", return_value=pool), \
             patch("cron.calendly_brief_sender.send_email", new_callable=AsyncMock):
            _run(run_once())
        fetch_sql = next(sql for op, sql, _ in cap if op == "fetch")
        # Pattern 47: assert table name first before column assertions
        assert "klaravex_scheduled_briefs" in fetch_sql


# ── _send_telegram tests ──────────────────────────────────────────────────────

class TestSendTelegram:

    def test_no_op_without_token(self):
        with patch("cron.calendly_brief_sender.TELEGRAM_TOKEN", ""), \
             patch("cron.calendly_brief_sender.TELEGRAM_CHAT", "12345"), \
             patch("cron.calendly_brief_sender.httpx") as mock_httpx:
            _run(_send_telegram("hello"))
        mock_httpx.AsyncClient.assert_not_called()

    def test_no_op_without_chat_id(self):
        with patch("cron.calendly_brief_sender.TELEGRAM_TOKEN", "tok:abc"), \
             patch("cron.calendly_brief_sender.TELEGRAM_CHAT", ""), \
             patch("cron.calendly_brief_sender.httpx") as mock_httpx:
            _run(_send_telegram("hello"))
        mock_httpx.AsyncClient.assert_not_called()

    def test_truncates_text_to_4096(self):
        captured_payloads: list = []

        class _MockClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                pass

            async def post(self, url, json=None):
                captured_payloads.append(json)

        with patch("cron.calendly_brief_sender.TELEGRAM_TOKEN", "tok:abc"), \
             patch("cron.calendly_brief_sender.TELEGRAM_CHAT", "99"), \
             patch("cron.calendly_brief_sender.httpx.AsyncClient", _MockClient):
            _run(_send_telegram("Z" * 5000))

        assert len(captured_payloads) == 1
        assert len(captured_payloads[0]["text"]) == 4096
