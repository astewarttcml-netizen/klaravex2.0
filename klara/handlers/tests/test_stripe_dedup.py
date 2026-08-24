"""
H1 — Stripe webhook idempotency tests.

Covers the dedup gate added to infra/klara.handlers/stripe_webhook.py:
  - first-time event → claim succeeds → dispatch runs once
  - duplicate 'done'       → 200 + duplicate_skipped, NO dispatch
  - duplicate 'processing' → 200 + in_flight,         NO dispatch
  - duplicate 'failed'     → 200 + duplicate_failed_skipped, NO dispatch
  - bad signature          → 400 BEFORE the dedup table is touched

Run:
    python3 -m unittest infra.klara.handlers.tests.test_stripe_dedup

The asyncpg pool, send_email, telegram, ticket persistence, welcome email,
and Stripe SDK are all mocked. No network, no DB.
"""
from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Make "infra" importable from project root.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Fake asyncpg pool — supports the two SQL shapes the webhook uses:
#   1. INSERT ... ON CONFLICT DO NOTHING RETURNING event_id   (fetchval)
#   2. SELECT status FROM klaravex_stripe_events ...           (fetchval)
#   3. UPDATE klaravex_stripe_events SET status = $2 ...       (execute)
# ─────────────────────────────────────────────────────────────────────────────


class FakeConn:
    def __init__(self, store: dict):
        self._store = store
        self.executed: list[tuple[str, tuple]] = []

    async def fetchval(self, sql: str, *args):
        sql_norm = " ".join(sql.split()).lower()
        if sql_norm.startswith("insert into klaravex_stripe_events"):
            event_id, event_type, payload_json = args
            if event_id in self._store:
                return None  # ON CONFLICT DO NOTHING
            self._store[event_id] = {
                "event_id": event_id,
                "event_type": event_type,
                "status": "processing",
                "payload": payload_json,
                "error": None,
            }
            return event_id
        if sql_norm.startswith("select status from klaravex_stripe_events"):
            (event_id,) = args
            row = self._store.get(event_id)
            return row["status"] if row else None
        raise AssertionError(f"unexpected fetchval SQL: {sql_norm[:80]}")

    async def execute(self, sql: str, *args):
        self.executed.append((sql, args))
        sql_norm = " ".join(sql.split()).lower()
        if sql_norm.startswith("update klaravex_stripe_events"):
            event_id, status, error = args
            row = self._store.get(event_id)
            if row is not None:
                row["status"] = status
                row["error"] = error
            return "UPDATE 1"
        # tolerate other UPDATEs that may run inside dispatch — not under test
        return "OK"

    async def fetch(self, *_a, **_k):
        return []

    async def fetchrow(self, *_a, **_k):
        return None


class FakeAcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, store: dict):
        self._store = store

    def acquire(self):
        return FakeAcquireCtx(FakeConn(self._store))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_event(event_id: str = "evt_test_1", event_type: str = "invoice.paid") -> dict:
    """Minimal Stripe-shaped event the dispatcher can chew without errors."""
    return {
        "id": event_id,
        "type": event_type,
        "livemode": False,
        "created": 1717000000,
        "data": {
            "object": {
                "id": "in_test_1",
                "customer": None,
                "customer_email": "test@example.com",
                "customer_details": {"email": "test@example.com", "name": "Test"},
                "amount_paid": 5000,
                "amount_total": 5000,
                "currency": "usd",
                "metadata": {"sku": "foundation-monthly"},
            }
        },
    }


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


class StripeDedupTests(unittest.TestCase):
    def setUp(self):
        # Fresh event loop per test (Python 3.10 friendly).
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.store: dict = {}
        self.fake_pool = FakePool(self.store)

        # Import the module fresh and patch every external surface.
        import importlib

        self.sw = importlib.import_module("infra.klara.handlers.stripe_webhook")
        importlib.reload(self.sw)

        # Patch the pool getter to return our fake.
        self._patches = [
            patch.object(self.sw, "get_pool", new=AsyncMock(return_value=self.fake_pool)),
            patch.object(self.sw, "_dispatch_event", new=AsyncMock(return_value=None)),
            # Make construct_event a pass-through that returns whatever JSON
            # was POSTed (we don't test Stripe's verification math — Stripe
            # SDK already does).
            patch.object(
                self.sw.stripe.Webhook,
                "construct_event",
                side_effect=lambda payload, sig, secret: __import__("json").loads(payload),
            ),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.loop.close()

    def _post(self, event: dict, signature: str = "t=1,v1=ok"):
        """Invoke the route function directly."""
        import json as _json

        class _Req:
            def __init__(self, body):
                self._body = body

            async def body(self):
                return self._body

        req = _Req(_json.dumps(event).encode())
        return _run(self.sw.stripe_webhook(req, stripe_signature=signature))

    # ── Cases ────────────────────────────────────────────────────────────────

    def test_first_time_event_dispatches_and_marks_done(self):
        event = _make_event("evt_first")
        resp = self._post(event)
        self.assertEqual(resp["status"], "ok")
        self.assertEqual(resp["event_id"], "evt_first")
        self.sw._dispatch_event.assert_awaited_once()
        # Row should now be 'done' (marked after dispatch).
        self.assertEqual(self.store["evt_first"]["status"], "done")

    def test_duplicate_done_event_short_circuits(self):
        # Seed store as if a prior delivery already finished.
        self.store["evt_done"] = {
            "event_id": "evt_done",
            "event_type": "invoice.paid",
            "status": "done",
            "payload": "{}",
            "error": None,
        }
        event = _make_event("evt_done")
        resp = self._post(event)
        self.assertEqual(resp, {"status": "duplicate_skipped", "event_id": "evt_done"})
        self.sw._dispatch_event.assert_not_awaited()

    def test_duplicate_processing_event_returns_in_flight(self):
        self.store["evt_busy"] = {
            "event_id": "evt_busy",
            "event_type": "invoice.paid",
            "status": "processing",
            "payload": "{}",
            "error": None,
        }
        event = _make_event("evt_busy")
        resp = self._post(event)
        self.assertEqual(resp, {"status": "in_flight", "event_id": "evt_busy"})
        self.sw._dispatch_event.assert_not_awaited()

    def test_duplicate_failed_event_does_not_auto_retry(self):
        self.store["evt_bad"] = {
            "event_id": "evt_bad",
            "event_type": "invoice.paid",
            "status": "failed",
            "payload": "{}",
            "error": "kaboom",
        }
        event = _make_event("evt_bad")
        resp = self._post(event)
        self.assertEqual(
            resp,
            {"status": "duplicate_failed_skipped", "event_id": "evt_bad"},
        )
        self.sw._dispatch_event.assert_not_awaited()

    def test_bad_signature_rejected_before_dedup_table_touched(self):
        from fastapi import HTTPException
        import stripe as _stripe

        # Force construct_event to raise the real verification error.
        def boom(payload, sig, secret):
            raise _stripe.error.SignatureVerificationError(
                "no good", sig, payload
            )

        with patch.object(self.sw.stripe.Webhook, "construct_event", side_effect=boom):
            event = _make_event("evt_signed_bad")
            with self.assertRaises(HTTPException) as cm:
                self._post(event)
            self.assertEqual(cm.exception.status_code, 400)
        # Nothing should have been written to the dedup table.
        self.assertEqual(self.store, {})
        self.sw._dispatch_event.assert_not_awaited()

    def test_dispatch_failure_marks_failed_and_reraises(self):
        # Make dispatch blow up — outer except should mark row failed + re-raise
        # so Stripe sees 500 and retries (retry will hit duplicate_failed_skipped).
        self.sw._dispatch_event = AsyncMock(side_effect=RuntimeError("downstream"))
        event = _make_event("evt_explodes")
        with self.assertRaises(RuntimeError):
            self._post(event)
        self.assertEqual(self.store["evt_explodes"]["status"], "failed")
        self.assertIn("RuntimeError", self.store["evt_explodes"]["error"])


if __name__ == "__main__":
    unittest.main()
