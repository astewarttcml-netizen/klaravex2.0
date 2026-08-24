"""Regression tests locking iter-4 code_review gate residual High findings.

Locks two invariants on the public /api/v1/chat/message endpoint that
review-20260715T120141Z-3 flagged as High:

  1. Origin allow-list enforcement (chat-endpoint-origin-allowlist)
     - Unknown origin -> 403 origin not allowed
     - Allowed klaravex.* origins reach the chat handler
     - personal.klaravex.com is allowlisted (consumer surface)

  2. Agentic reply contract (chat-answer-hint-leak, superseded by 2300a804)
     - Since commit 2300a804 chat is AGENTIC: it routes every turn to
       run_chat_agent and returns {reply, session_token}. There is NO KB
       lookup — the old kb_lib.answer_question / safe-miss-hint path was
       removed. The safe-hint tests were rewritten to assert the agentic
       contract with a stubbed run_chat_agent (no live LLM/proxy round-trip),
       so no debug/error text from the agent can leak unauthenticated.

Run with:
    pytest infra/klara.handlers/tests/test_chat_message_security.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INFRA_DIR = PROJECT_ROOT / "infra"
sys.path.insert(0, str(INFRA_DIR))

pytest.importorskip("fastapi")

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from klara.handlers import chat_agent  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app, raise_server_exceptions=False)


# ── Origin allow-list ────────────────────────────────────────────────────────

def test_origin_allowlist_rejects_unknown(client: TestClient) -> None:
    r = client.post(
        "/api/v1/chat/message",
        headers={"origin": "https://evil.example"},
        json={"message": "hi"},
    )
    assert r.status_code == 403
    assert r.json() == {"detail": "origin not allowed"}


def test_origin_allowlist_rejects_missing_header(client: TestClient) -> None:
    r = client.post("/api/v1/chat/message", json={"message": "hi"})
    assert r.status_code == 403


def test_origin_allowlist_accepts_personal_klaravex(client: TestClient) -> None:
    """personal.klaravex.com (consumer surface) is an allowed chat origin."""
    r = client.post(
        "/api/v1/chat/message",
        headers={"origin": "https://personal.klaravex.com"},
        json={"message": "hi"},
    )
    # Must pass the origin gate (not 403); the exact downstream reply is the
    # agent's concern, covered elsewhere. 200 => origin is allowlisted.
    assert r.status_code == 200


def test_origin_allowlist_contains_exactly_expected_set() -> None:
    assert main._CHAT_ALLOWED_ORIGINS == {
        "https://klaravex.com",
        "https://www.klaravex.com",
        "https://support.klaravex.com",
        "https://personal.klaravex.com",
    }


def test_cors_allowlist_matches_chat_allowlist() -> None:
    """CORS allow-list + chat handler allow-list must stay in sync."""
    assert set(main._CORS_ALLOWED_ORIGINS) == main._CHAT_ALLOWED_ORIGINS


from klara.handlers import chat_agent  # noqa: E402


def _stub_agent(reply: str = "ok") -> AsyncMock:
    """Stub run_chat_agent so the handler's origin + validation gates are tested
    without a live LLM/proxy round-trip. The handler defers
    `from klara.handlers.chat_agent import run_chat_agent` inside the request path
    (main.py:1172), so we patch the module attribute the import resolves.
    """
    return AsyncMock(
        return_value={"reply": reply, "session_token": "tok-sec", "portal_bridged": False}
    )


@pytest.mark.parametrize("origin", [
    "https://klaravex.com",
    "https://www.klaravex.com",
    "https://support.klaravex.com",
])
def test_allowed_origins_reach_agent(client: TestClient, origin: str) -> None:
    """Every allowed origin must pass the 403 gate and hit run_chat_agent."""
    stub = _stub_agent("handled")
    with patch.object(chat_agent, "run_chat_agent", new=stub):
        r = client.post(
            "/api/v1/chat/message",
            headers={"origin": origin},
            json={"message": "test query"},
        )
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"reply", "session_token"}
    assert body["reply"] == "handled"
    stub.assert_awaited_once()


# ── agentic reply contract (no KB) ───────────────────────────────────────────

def test_chat_endpoint_returns_agent_reply_and_session_token(client: TestClient) -> None:
    """End-to-end: chat handler routes to run_chat_agent and returns
    {reply, session_token}. No KB lookup — the agent owns the reply."""
    stub = _stub_agent("Try resetting your password via the profile page.")
    with patch.object(chat_agent, "run_chat_agent", new=stub):
        r = client.post(
            "/api/v1/chat/message",
            headers={"origin": "https://klaravex.com"},
            json={"message": "xyzzy plugh"},
        )
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"reply", "session_token"}
    assert body["reply"] == "Try resetting your password via the profile page."
    stub.assert_awaited_once_with(
        message="xyzzy plugh", session_token="", origin="https://klaravex.com",
        is_business=True, portal_cookie=None,
    )


# ── Message-length guard (V3 pentest) ────────────────────────────────────────

def test_message_length_cap_enforced(client: TestClient) -> None:
    """Pydantic Field(max_length=CHAT_MAX_MESSAGE_LEN) rejects oversize prompts."""
    oversize = "x" * (main.CHAT_MAX_MESSAGE_LEN + 1)
    r = client.post(
        "/api/v1/chat/message",
        headers={"origin": "https://klaravex.com"},
        json={"message": oversize},
    )
    assert r.status_code == 422


def test_empty_message_rejected(client: TestClient) -> None:
    r = client.post(
        "/api/v1/chat/message",
        headers={"origin": "https://klaravex.com"},
        json={"message": ""},
    )
    assert r.status_code == 422
