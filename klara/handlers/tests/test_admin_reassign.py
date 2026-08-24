"""Tests for /admin/reassign view and logic."""

from __future__ import annotations

import hashlib
import hmac
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

# Adjust path for local imports
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from infra.klara.handlers import admin_index  # For session signing
from infra.klara.handlers import admin_reassign  # The router to test
from infra.klara.handlers.lib.admin_auth import SESSION_COOKIE, require_admin_session

TEST_SECRET = "test-internal-secret-32chars-bbbbb"
TEST_ADMINS = {"admin@klaravex.com", "anthony@klaravex.com"}


# --- Helpers ---

def _sign_session(email: str, ttl_s: int = 3600, secret: str = TEST_SECRET) -> str:
    """Mint a session token signed with the configured LOKI_INTERNAL_SECRET."""
    expires_at = int(time.time()) + ttl_s
    msg = f"{email}|{expires_at}".encode()
    sig = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()[:32]
    return f"{email}|{expires_at}|{sig}"


def _make_app() -> FastAPI:
    app = FastAPI()
    # Mock the dependency directly on the router being tested!
    # This ensures calls to /admin/reassign are authenticated
    app.include_router(admin_reassign.router, prefix="/admin")
    return app


def _create_client_with_mock_data(monkeypatch, ticket_data, user_data):
    """Helper to create a test client with specific mock data."""
    monkeypatch.setattr(admin_index, "_LOKI_SECRET", TEST_SECRET)
    monkeypatch.setattr(admin_index, "_ADMIN_EMAILS", TEST_ADMINS)

    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    # Create AsyncMock for fetch method that returns the provided data
    async def fetch_side_effect(query, *args, **kwargs):
        # Simple logic: if query looks like it's for tickets, return ticket_data
        # if query looks like it's for users, return user_data
        if "klaravex_tickets" in query:
            return ticket_data
        elif "users" in query:
            return user_data
        return []
    
    mock_conn.fetch = AsyncMock(side_effect=fetch_side_effect)

    monkeypatch.setattr("infra.klara.handlers.admin_reassign.get_pool", AsyncMock(return_value=mock_pool))
    monkeypatch.setattr("infra.klara.handlers.admin_reassign._bulk_update_assignees", AsyncMock())
    monkeypatch.setattr("infra.klara.handlers.admin_reassign._notify_status_change", AsyncMock())

    return TestClient(_make_app())


@pytest.fixture
def client_with_tickets(monkeypatch):
    ticket_data = [
        {"id": uuid.UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"), "subject": "Ticket 1", "status": "open", "assignee": "unassigned", "client_email": "client1@example.com", "created_at": "2026-07-18T10:00:00Z"},
        {"id": uuid.UUID("b1eec100-c0d1-e2f3-1122-334455667788"), "subject": "Ticket 2", "status": "in_progress", "assignee": "engineer_a@klaravex.com", "client_email": "client2@example.com", "created_at": "2026-07-18T11:00:00Z"},
    ]
    user_data = [
        {"email": "engineer_a@klaravex.com", "name": "Engineer A"},
        {"email": "engineer_b@klaravex.com", "name": "Engineer B"},
    ]
    return _create_client_with_mock_data(monkeypatch, ticket_data, user_data)


@pytest.fixture
def client_no_tickets(monkeypatch):
    ticket_data = []
    user_data = [
        {"email": "engineer_a@klaravex.com", "name": "Engineer A"},
    ]
    return _create_client_with_mock_data(monkeypatch, ticket_data, user_data)


@pytest.fixture
def client_unauthenticated(monkeypatch):
    monkeypatch.setattr(admin_index, "_LOKI_SECRET", TEST_SECRET)
    monkeypatch.setattr(admin_index, "_ADMIN_EMAILS", TEST_ADMINS)
    
    # Mock the database to avoid real connections
    monkeypatch.setattr("infra.klara.handlers.admin_reassign.get_pool", AsyncMock())
    monkeypatch.setattr("infra.klara.handlers.admin_reassign._bulk_update_assignees", AsyncMock())
    monkeypatch.setattr("infra.klara.handlers.admin_reassign._notify_status_change", AsyncMock())
    
    return TestClient(_make_app())


# --- Tests for GET /admin/reassign ---
def test_reassign_get_unauthenticated(client_unauthenticated):
    r = client_unauthenticated.get("/admin/reassign")
    assert r.status_code == 401

def test_reassign_get_authenticated_no_tickets(client_no_tickets):
    token = _sign_session("admin@klaravex.com")
    r = client_no_tickets.get("/admin/reassign", cookies={admin_index.SESSION_COOKIE: token})
    assert r.status_code == 200
    assert "No items to reassign." in r.text

def test_reassign_get_authenticated_with_data(client_with_tickets):
    token = _sign_session("admin@klaravex.com")
    r = client_with_tickets.get("/admin/reassign", cookies={admin_index.SESSION_COOKIE: token})
    assert r.status_code == 200
    assert "Reassign Items" in r.text
    assert "Ticket 1" in r.text
    assert "engineer_a@klaravex.com" in r.text
    assert "Select assignee" in r.text # Verify dropdown is present
    assert "Reassign Selected" in r.text # Verify submit button is present

# --- Tests for POST /admin/reassign/submit ---
def test_reassign_submit_unauthenticated(client_unauthenticated):
    r = client_unauthenticated.post("/admin/reassign/submit", data={})
    assert r.status_code == 401

def test_reassign_submit_authenticated_with_data(client_with_tickets):
    token = _sign_session("admin@klaravex.com")
    
    # Mock the bulk update function to track calls
    mock_bulk_update = AsyncMock(return_value=[
        ("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11", {
            "client_email": "client1@example.com",
            "subject": "Ticket 1",
            "status": "open",
            "assignee": "engineer_b@klaravex.com"
        })
    ])
    mock_notify = AsyncMock()
    
    with patch('infra.klara.handlers.admin_reassign._bulk_update_assignees', mock_bulk_update), \
         patch('infra.klara.handlers.admin_reassign._notify_status_change', mock_notify):
        
        r = client_with_tickets.post(
            "/admin/reassign/submit",
            cookies={admin_index.SESSION_COOKIE: token},
            data={
                "new_assignee_a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11": "engineer_b@klaravex.com",
                "new_assignee_b1eec100-c0d1-e2f3-1122-334455667788": ""
            }
        )
        
        assert r.status_code == 200
        assert r.json()["success"] == True
        assert "Reassignment successful" in r.json()["message"]
        
        # Verify bulk update was called with correct assignments
        mock_bulk_update.assert_called_once_with({
            "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11": "engineer_b@klaravex.com"
        })
        
        # Verify notification was called
        mock_notify.assert_called_once()

def test_reassign_submit_empty_assignments(client_with_tickets):
    token = _sign_session("admin@klaravex.com")
    
    mock_bulk_update = AsyncMock()
    
    with patch('infra.klara.handlers.admin_reassign._bulk_update_assignees', mock_bulk_update):
        r = client_with_tickets.post(
            "/admin/reassign/submit",
            cookies={admin_index.SESSION_COOKIE: token},
            data={
                "new_assignee_a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11": "",  # Empty assignment
                "new_assignee_b1eec100-c0d1-e2f3-1122-334455667788": ""   # Empty assignment
            }
        )
        
        assert r.status_code == 200
        assert r.json()["success"] == True
        # Should succeed even with no assignments
        mock_bulk_update.assert_not_called()

# --- Tests for _bulk_update_assignees (direct, unmocked) ---
# These exercise the actual SQL query construction rather than mocking the
# function away, so a regression in the query itself (e.g. invalid SQL,
# wrong param shape) fails here instead of silently passing every
# request-level test above.

def test_bulk_update_assignees_issues_single_unnest_query(monkeypatch):
    ticket_a = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
    ticket_b = "b1eec100-c0d1-e2f3-1122-334455667788"

    mock_conn = MagicMock()
    fetched_rows = [
        {"id": ticket_a, "client_email": "client1@example.com", "subject": "Ticket 1", "status": "open", "assignee": "engineer_b@klaravex.com"},
    ]
    mock_conn.fetch = AsyncMock(return_value=fetched_rows)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    monkeypatch.setattr(admin_reassign, "get_pool", AsyncMock(return_value=mock_pool))

    import asyncio
    result = asyncio.run(admin_reassign._bulk_update_assignees({
        ticket_a: "engineer_b@klaravex.com",
        ticket_b: "engineer_a@klaravex.com",
    }))

    # Exactly one query issued — no separate DDL/type-creation statement.
    assert mock_conn.fetch.call_count == 1
    query_arg, ticket_ids_arg, assignees_arg = mock_conn.fetch.call_args.args
    assert "UNNEST($1::uuid[], $2::text[])" in query_arg
    assert set(ticket_ids_arg) == {uuid.UUID(ticket_a), uuid.UUID(ticket_b)}
    assert set(assignees_arg) == {"engineer_b@klaravex.com", "engineer_a@klaravex.com"}

    assert result == [(ticket_a, dict(fetched_rows[0]))]


def test_bulk_update_assignees_empty_input_skips_query():
    import asyncio
    result = asyncio.run(admin_reassign._bulk_update_assignees({}))
    assert result == []


def test_reassign_submit_invalid_ticket_id(client_with_tickets):
    token = _sign_session("admin@klaravex.com")
    
    mock_bulk_update = AsyncMock(return_value=[])  # Empty result for invalid ID
    
    with patch('infra.klara.handlers.admin_reassign._bulk_update_assignees', mock_bulk_update):
        r = client_with_tickets.post(
            "/admin/reassign/submit",
            cookies={admin_index.SESSION_COOKIE: token},
            data={
                "new_assignee_invalid-uuid": "engineer_b@klaravex.com"
            }
        )
        
        assert r.status_code == 200
        # Should succeed but the invalid ID is now rejected before reaching bulk update
        mock_bulk_update.assert_not_called()

