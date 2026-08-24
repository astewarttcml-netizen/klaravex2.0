"""Tests for calendly_webhook._schedule_brief (pre-meeting brief scheduler).

Coverage:
  1. advance booking (> 1h out): send_at = start_time - 1h
  2. same-day booking (< 1h out): send_at clamped to now()
  3. missing start_time: no DB call
  4. unparseable start_time: no DB call, no exception raised
  5. DB failure: fails-open (exception swallowed, caller not affected)
  6. ON CONFLICT DO NOTHING present in SQL
  7. invitee email + name persisted in INSERT args
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

INFRA = Path(__file__).resolve().parents[3] / "infra"
sys.path.insert(0, str(INFRA))

pytest.importorskip("fastapi")

from klara.handlers.calendly_webhook import _schedule_brief  # noqa: E402


# ── fake pool (Pattern 28: minimum-viable DB fake) ────────────────────────────

class _FakeConn:
    def __init__(self, captured: list):
        self._cap = captured

    async def execute(self, sql: str, *args):
        self._cap.append((sql, list(args)))


class _FakeAcquire:
    def __init__(self, captured: list):
        self._cap = captured

    async def __aenter__(self):
        return _FakeConn(self._cap)

    async def __aexit__(self, *_):
        pass


class _FakePool:
    def __init__(self, captured: list):
        self._cap = captured

    def acquire(self):
        return _FakeAcquire(self._cap)


class _BrokenPool:
    def acquire(self):
        raise RuntimeError("db down")


# ── helpers ───────────────────────────────────────────────────────────────────

def _invitee(email="alice@example.com", name="Alice"):
    return {"email": email, "name": name, "questions_and_answers": []}


# per Pattern 48: asyncio.run() not get_event_loop() in unittest helpers
def _run(coro):
    return asyncio.run(coro)


# ── tests ─────────────────────────────────────────────────────────────────────

class TestScheduleBrief:
    def _sched(self, offset_hours=3.0, uri="https://api.calendly.com/events/abc"):
        start = datetime.now(timezone.utc) + timedelta(hours=offset_hours)
        return {"start_time": start.isoformat(), "uri": uri}

    def test_advance_booking_send_at_is_one_hour_before_start(self):
        captured: list = []
        future = datetime.now(timezone.utc) + timedelta(hours=3)
        sched = {"start_time": future.isoformat(), "uri": "u"}

        with patch("klara.handlers.calendly_webhook.get_pool", return_value=_FakePool(captured)):
            _run(_schedule_brief(_invitee(), sched))

        assert len(captured) == 1
        send_at: datetime = captured[0][1][3]
        expected = future - timedelta(hours=1)
        assert abs((send_at - expected).total_seconds()) < 5

    def test_same_day_booking_send_at_clamped_to_now(self):
        captured: list = []
        soon = datetime.now(timezone.utc) + timedelta(minutes=30)
        sched = {"start_time": soon.isoformat(), "uri": "u"}

        with patch("klara.handlers.calendly_webhook.get_pool", return_value=_FakePool(captured)):
            _run(_schedule_brief(_invitee(), sched))

        assert len(captured) == 1
        send_at: datetime = captured[0][1][3]
        now = datetime.now(timezone.utc)
        assert send_at <= now + timedelta(seconds=5)
        assert send_at >= now - timedelta(seconds=5)

    def test_missing_start_time_skips_db(self):
        captured: list = []
        with patch("klara.handlers.calendly_webhook.get_pool", return_value=_FakePool(captured)):
            _run(_schedule_brief(_invitee(), {}))
        assert len(captured) == 0

    def test_invalid_start_time_skips_db(self):
        captured: list = []
        sched = {"start_time": "not-a-date", "uri": "u"}
        with patch("klara.handlers.calendly_webhook.get_pool", return_value=_FakePool(captured)):
            _run(_schedule_brief(_invitee(), sched))
        assert len(captured) == 0

    def test_db_failure_fails_open(self):
        sched = {"start_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(), "uri": "u"}
        with patch("klara.handlers.calendly_webhook.get_pool", return_value=_BrokenPool()):
            _run(_schedule_brief(_invitee(), sched))  # must not raise

    def test_sql_uses_on_conflict_do_nothing(self):
        captured: list = []
        sched = {"start_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(), "uri": "u"}
        with patch("klara.handlers.calendly_webhook.get_pool", return_value=_FakePool(captured)):
            _run(_schedule_brief(_invitee(), sched))
        sql = captured[0][0].lower()
        assert "on conflict" in sql and "nothing" in sql

    def test_invitee_email_and_name_persisted(self):
        captured: list = []
        sched = {"start_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(), "uri": "ev-uri"}
        with patch("klara.handlers.calendly_webhook.get_pool", return_value=_FakePool(captured)):
            _run(_schedule_brief(_invitee("bob@example.com", "Bob"), sched))
        args = captured[0][1]
        assert "bob@example.com" in args
        assert "Bob" in args
