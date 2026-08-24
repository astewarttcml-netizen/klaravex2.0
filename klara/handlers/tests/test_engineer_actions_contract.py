"""Contract test: EngineerAgent.queue_action() → klaravex_engineer_actions schema.

Verifies the INSERT produced by queue_action() targets the correct table
(klaravex_engineer_actions, not the old engineer_actions) and passes
columns that match what engineers/router.py::list_actions reads back.

No real DB required — FakeConn captures SQL and args, then re-plays a
SELECT against the same in-memory store to prove the reader chain works.

Closes review-20260618T071900Z-5 Critical finding #2.
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from infra.klara.handlers.engineers.base import EngineerAgent  # noqa: E402


# ── in-memory store shared across INSERT + SELECT within one test ──────────

_FAKE_UUID = "aabbccdd-1234-5678-9abc-def012345678"


class _FakeConn:
    """Captures INSERT into klaravex_engineer_actions; serves SELECT back."""

    def __init__(self, store: dict):
        self._store = store
        self.last_sql: str = ""
        self.last_args: tuple = ()

    async def fetchval(self, sql: str, *args):
        norm = " ".join(sql.split()).lower()
        assert "klaravex_engineer_actions" in norm, (
            f"queue_action() targeted wrong table.\n"
            f"SQL: {sql.strip()}"
        )
        assert "engineer_actions" in norm  # same assertion via substring

        self.last_sql = sql
        self.last_args = args

        # args order: engineer, pillar, ticket_id, project_id, client_email,
        #             action_type, title, body_markdown, proposed_payload,
        #             reasoning, approval_token
        (
            engineer, pillar, ticket_id, project_id, client_email,
            action_type, title, body_markdown, proposed_payload_json,
            reasoning, approval_token,
        ) = args

        row_id = _FAKE_UUID
        self._store[row_id] = {
            "id": row_id,
            "engineer": engineer,
            "pillar": pillar,
            "ticket_id": ticket_id,
            "project_id": project_id,
            "client_email": client_email,
            "action_type": action_type,
            "title": title,
            "body_markdown": body_markdown,
            "proposed_payload": json.loads(proposed_payload_json),
            "reasoning": reasoning,
            "approval_token": approval_token,
            "status": "pending",
        }
        return row_id  # RETURNING id::text

    async def fetch(self, sql: str, *args):
        """Simulates list_actions SELECT — returns pending rows."""
        norm = " ".join(sql.split()).lower()
        assert "klaravex_engineer_actions" in norm
        status_filter = args[0] if args else "pending"
        return [
            r for r in self._store.values()
            if r["status"] == status_filter
        ]

    async def execute(self, sql: str, *args):
        """Simulates approve/reject UPDATE."""
        norm = " ".join(sql.split()).lower()
        assert "klaravex_engineer_actions" in norm
        action_id = args[0]
        if "approved" in norm and action_id in self._store:
            self._store[action_id]["status"] = "approved"
        elif "rejected" in norm and action_id in self._store:
            self._store[action_id]["status"] = "rejected"


class _FakePool:
    def __init__(self, conn: _FakeConn):
        self._conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self._conn


def _fake_pool_factory(store: dict):
    conn = _FakeConn(store)
    return _FakePool(conn), conn


# ── concrete subclass (matches production engineer name format) ────────────

class _TestEngineer(EngineerAgent):
    name = "engineer_managed_security"
    display_name = "Managed Security Engineer"
    pillar = "managed_security"
    system_prompt = "You are the Managed Security Engineer."
    specialty_keywords = ["firewall", "EDR"]
    secondary_keywords = ["patch"]


class _NoPillarEngineer(EngineerAgent):
    """Base class default: pillar = '' — must not write empty string to DB."""
    name = "engineer_strategic_advisory"
    display_name = "Strategic Advisory"
    pillar = ""
    system_prompt = "You are the Strategic Advisory Engineer."
    specialty_keywords = []
    secondary_keywords = []


# ── tests ──────────────────────────────────────────────────────────────────

class TestQueueActionTableTarget(unittest.TestCase):
    """queue_action() must INSERT into klaravex_engineer_actions (not engineer_actions)."""

    def _run(self, coro):
        return asyncio.run(coro)

    def _make_action(self, **overrides) -> dict[str, Any]:
        base = {
            "action_type": "investigation_plan",
            "title": "Firewall policy review",
            "body_markdown": "## Plan\n- Step 1\n- Step 2",
            "proposed_payload": {"next_steps": ["review config"]},
            "reasoning": "Client reported lateral movement.",
        }
        base.update(overrides)
        return base

    def test_targets_correct_table(self):
        store: dict = {}
        pool, conn = _fake_pool_factory(store)
        eng = _TestEngineer()

        async def _run():
            with patch("infra.klara.handlers.engineers.base.get_pool", return_value=pool):
                return await eng.queue_action(action=self._make_action())

        action_id = self._run(_run())
        self.assertEqual(action_id, _FAKE_UUID)
        self.assertIn("klaravex_engineer_actions", conn.last_sql)

    def test_not_old_table_name(self):
        """Old table name 'engineer_actions' must not appear as standalone table reference."""
        store: dict = {}
        pool, conn = _fake_pool_factory(store)
        eng = _TestEngineer()

        async def _run():
            with patch("infra.klara.handlers.engineers.base.get_pool", return_value=pool):
                return await eng.queue_action(action=self._make_action())

        self._run(_run())
        # The SQL may mention engineer_actions as substring of klaravex_engineer_actions,
        # but must NOT reference it as a bare table (INSERT INTO engineer_actions).
        sql_lower = " ".join(conn.last_sql.split()).lower()
        self.assertNotIn("insert into engineer_actions ", sql_lower)

    def test_engineer_name_written(self):
        store: dict = {}
        pool, _ = _fake_pool_factory(store)
        eng = _TestEngineer()

        async def _run():
            with patch("infra.klara.handlers.engineers.base.get_pool", return_value=pool):
                await eng.queue_action(action=self._make_action())

        self._run(_run())
        row = store[_FAKE_UUID]
        self.assertEqual(row["engineer"], "engineer_managed_security")

    def test_pillar_written(self):
        store: dict = {}
        pool, _ = _fake_pool_factory(store)
        eng = _TestEngineer()

        async def _run():
            with patch("infra.klara.handlers.engineers.base.get_pool", return_value=pool):
                await eng.queue_action(action=self._make_action())

        self._run(_run())
        self.assertEqual(store[_FAKE_UUID]["pillar"], "managed_security")

    def test_empty_pillar_becomes_none(self):
        """Engineers with pillar='' must not write empty string (fails DB CHECK)."""
        store: dict = {}
        pool, _ = _fake_pool_factory(store)
        eng = _NoPillarEngineer()

        async def _run():
            with patch("infra.klara.handlers.engineers.base.get_pool", return_value=pool):
                await eng.queue_action(action=self._make_action())

        self._run(_run())
        self.assertIsNone(store[_FAKE_UUID]["pillar"])

    def test_action_fields_mapped_to_columns(self):
        """action dict fields land in the correct typed columns."""
        store: dict = {}
        pool, _ = _fake_pool_factory(store)
        eng = _TestEngineer()
        action = self._make_action(
            action_type="client_reply",
            title="Reply to firewall ticket",
            body_markdown="## Response\nSee attached.",
            proposed_payload={"to": "client@example.com"},
            reasoning="Urgent client request.",
        )

        async def _run():
            with patch("infra.klara.handlers.engineers.base.get_pool", return_value=pool):
                await eng.queue_action(action=action)

        self._run(_run())
        row = store[_FAKE_UUID]
        self.assertEqual(row["action_type"], "client_reply")
        self.assertEqual(row["title"], "Reply to firewall ticket")
        self.assertIn("Response", row["body_markdown"])
        self.assertEqual(row["proposed_payload"], {"to": "client@example.com"})
        self.assertEqual(row["reasoning"], "Urgent client request.")

    def test_approval_token_generated(self):
        """approval_token must be non-empty so the approve link works."""
        store: dict = {}
        pool, _ = _fake_pool_factory(store)
        eng = _TestEngineer()

        async def _run():
            with patch("infra.klara.handlers.engineers.base.get_pool", return_value=pool):
                await eng.queue_action(action=self._make_action())

        self._run(_run())
        token = store[_FAKE_UUID]["approval_token"]
        self.assertIsNotNone(token)
        self.assertGreater(len(token), 8)

    def test_ticket_and_project_ids_forwarded(self):
        store: dict = {}
        pool, _ = _fake_pool_factory(store)
        eng = _TestEngineer()

        async def _run():
            with patch("infra.klara.handlers.engineers.base.get_pool", return_value=pool):
                await eng.queue_action(
                    action=self._make_action(),
                    ticket_id="t-111",
                    project_id="p-222",
                    client_email="client@acme.com",
                )

        self._run(_run())
        row = store[_FAKE_UUID]
        self.assertEqual(row["ticket_id"], "t-111")
        self.assertEqual(row["project_id"], "p-222")
        self.assertEqual(row["client_email"], "client@acme.com")

    def test_missing_action_fields_get_defaults(self):
        """Sparse action dict must not crash; defaults keep NOT NULL columns satisfied."""
        store: dict = {}
        pool, _ = _fake_pool_factory(store)
        eng = _TestEngineer()

        async def _run():
            with patch("infra.klara.handlers.engineers.base.get_pool", return_value=pool):
                await eng.queue_action(action={})  # completely empty

        self._run(_run())
        row = store[_FAKE_UUID]
        self.assertIsNotNone(row["action_type"])
        self.assertIsNotNone(row["title"])
        self.assertIsNotNone(row["body_markdown"])
        self.assertIsInstance(row["proposed_payload"], dict)


class TestQueueActionReaderChain(unittest.TestCase):
    """Verify the inserted row is readable by the list_actions SELECT shape."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_inserted_row_readable_by_list_actions_select(self):
        """queue_action() → fetch() round-trip mirrors engineers/router.py::list_actions."""
        store: dict = {}
        pool, conn = _fake_pool_factory(store)
        eng = _TestEngineer()

        action = {
            "action_type": "playbook",
            "title": "EDR Deployment Playbook",
            "body_markdown": "# Steps\n1. Deploy agent",
            "proposed_payload": {"next_steps": ["deploy"]},
            "reasoning": "Proactive hardening.",
        }

        async def _run():
            with patch("infra.klara.handlers.engineers.base.get_pool", return_value=pool):
                action_id = await eng.queue_action(action=action)

            # Simulate list_actions SELECT (from engineers/router.py:144-151)
            list_sql = """
                SELECT id::text, engineer, ticket_id::text, action_type, title,
                       status, created_at, reasoning
                  FROM klaravex_engineer_actions
                 WHERE status = $1
                 ORDER BY created_at DESC LIMIT $2
            """
            rows = await conn.fetch(list_sql, "pending", 50)
            return action_id, rows

        action_id, rows = self._run(_run())

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["id"], action_id)
        self.assertEqual(row["engineer"], "engineer_managed_security")
        self.assertEqual(row["action_type"], "playbook")
        self.assertEqual(row["title"], "EDR Deployment Playbook")
        self.assertEqual(row["status"], "pending")

    def test_approved_row_no_longer_in_pending_list(self):
        """After approve UPDATE, row leaves the pending list."""
        store: dict = {}
        pool, conn = _fake_pool_factory(store)
        eng = _TestEngineer()

        action = {
            "action_type": "client_reply",
            "title": "Incident Summary",
            "body_markdown": "All clear.",
            "proposed_payload": {},
            "reasoning": "Client asked for update.",
        }

        approve_sql = """
            UPDATE klaravex_engineer_actions
               SET status='approved', approved_at=now(), updated_at=now()
             WHERE id=$1 AND status='pending'
        """

        async def _run():
            with patch("infra.klara.handlers.engineers.base.get_pool", return_value=pool):
                action_id = await eng.queue_action(action=action)

            await conn.execute(approve_sql, action_id)

            pending_rows = await conn.fetch(
                "SELECT id FROM klaravex_engineer_actions WHERE status = $1", "pending", 50
            )
            approved_rows = await conn.fetch(
                "SELECT id FROM klaravex_engineer_actions WHERE status = $1", "approved", 50
            )
            return pending_rows, approved_rows

        pending, approved = self._run(_run())
        self.assertEqual(len(pending), 0)
        self.assertEqual(len(approved), 1)


if __name__ == "__main__":
    unittest.main()
