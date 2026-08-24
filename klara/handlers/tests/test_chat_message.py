"""Regression test for POST /api/v1/chat/message.

Sibling of test_chat_start.py. Locks the contract the klaravex.com /
personal.klaravex.com chat widget relies on for the agentic reply turn.
Same origin-gate as /chat/start — drift here reproduces the same
widget-fallback-to-canned-message symptom that took 8 days to detect
when /chat/start was missing.

Since commit 2300a804 the endpoint is AGENTIC: it routes every turn to
klara.handlers.chat_agent.run_chat_agent and returns {reply, session_token}.
The old KB-lookup translation layer (kb_lib.answer_question → {reply,
citations, match_type}) no longer exists and its tests were retired.

Contract:
- 200 with {reply, session_token} on allowed origin
- 403 on disallowed / missing origin
- 422 on empty message (Pydantic min_length=1)
- 422 on oversize message (Pydantic max_length=CHAT_MAX_MESSAGE_LEN)

Implementation notes:
- run_chat_agent is monkeypatched per-test so no LLM/proxy/DB round-trip
  happens. Tests assert the handler's origin gate + shape translation,
  not the agent itself (chat_agent has its own coverage).
- Each test uses a distinct X-Forwarded-For so the 10/min per-IP limiter
  bucket on this endpoint doesn't cross-contaminate sibling tests
  (limiter.client_key prefers XFF — see lib/rate_limit.py:client_key).
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from infra import main as main_module
from infra.main import CHAT_MAX_MESSAGE_LEN, app


client = TestClient(app)


def _post(
    origin: str | None,
    body: dict[str, Any] | None = None,
    *,
    xff: str,
):
    headers: dict[str, str] = {"X-Forwarded-For": xff}
    if origin is not None:
        headers["Origin"] = origin
    return client.post("/api/v1/chat/message", json=body or {}, headers=headers)


def _stub_agent(monkeypatch: pytest.MonkeyPatch, reply: str) -> None:
    """Make run_chat_agent a coroutine returning a canned ``reply``."""

    async def _fake(**kwargs: Any) -> dict[str, Any]:
        return {"reply": reply, "session_token": "tok-stub", "portal_bridged": False}

    # The handler defers `from klara.handlers.chat_agent import run_chat_agent`
    # inside the request path (main.py:1172), so patch the module attribute the
    # import resolves — not main_module.run_chat_agent (which never exists).
    from klara.handlers import chat_agent

    monkeypatch.setattr(chat_agent, "run_chat_agent", _fake)


def _stub_kb(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    """No-op kept for callers that only need the origin/validation gate.

    The KB translation layer was removed in 2300a804 (agentic chat); this
    helper now just stubs run_chat_agent so the request reaches the handler's
    origin + Pydantic guards without hitting the live proxy. ``payload`` is
    unused but retained to avoid touching every historical call site.
    """
    _stub_agent(monkeypatch, "reply truncated by agent")


# ── shape contract ────────────────────────────────────────────────────────────


def test_chat_message_returns_agentic_reply_and_session_token(monkeypatch):
    # Agentic chat (2300a804): handler returns {reply, session_token} — the
    # widget stores session_token client-side for the next turn.
    _stub_agent(monkeypatch, "Try resetting your password via the profile page.")
    r = _post(
        "https://klaravex.com",
        {"message": "how do I reset my password"},
        xff="203.0.113.1",
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"reply", "session_token"}
    assert body["reply"] == "Try resetting your password via the profile page."
    assert body["session_token"] == "tok-stub"


def test_chat_message_forwards_agent_session_token(monkeypatch):
    # The handler must pass the client's session_token through to the agent so
    # conversation state carries across turns.
    captured: dict[str, Any] = {}

    async def _fake(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"reply": "ok", "session_token": kwargs.get("session_token", ""), "portal_bridged": False}

    from klara.handlers import chat_agent

    monkeypatch.setattr(chat_agent, "run_chat_agent", _fake)
    r = _post(
        "https://klaravex.com",
        {"message": "continue with my issue"},
        xff="203.0.113.2",
    )
    assert r.status_code == 200, r.text
    assert captured["message"] == "continue with my issue"
    assert captured["session_token"] == ""  # no prior token supplied
    assert captured["is_business"] is True   # non-personal source => business agent


# ── origin gate ───────────────────────────────────────────────────────────────


def test_chat_message_rejects_disallowed_origin(monkeypatch):
    _stub_kb(monkeypatch, {"found": False, "answer_hint": "n/a", "citations": []})
    r = _post(
        "https://attacker.example",
        {"message": "hi"},
        xff="203.0.113.3",
    )
    assert r.status_code == 403


def test_chat_message_rejects_missing_origin(monkeypatch):
    _stub_kb(monkeypatch, {"found": False, "answer_hint": "n/a", "citations": []})
    r = _post(None, {"message": "hi"}, xff="203.0.113.4")
    assert r.status_code == 403


def test_chat_message_origin_match_is_case_insensitive(monkeypatch):
    _stub_kb(monkeypatch, {"found": False, "answer_hint": "n/a", "citations": []})
    r = _post(
        "HTTPS://Klaravex.com",
        {"message": "hi"},
        xff="203.0.113.5",
    )
    assert r.status_code == 200, r.text


def test_chat_message_supports_all_documented_origins(monkeypatch):
    _stub_kb(monkeypatch, {"found": False, "answer_hint": "n/a", "citations": []})
    # Pattern 29 — must round-trip with the literal set defined in main.py:_CHAT_ALLOWED_ORIGINS.
    # Distinct XFF per origin so the 10/min bucket doesn't trip during the loop.
    origins = [
        "https://klaravex.com",
        "https://www.klaravex.com",
        "https://support.klaravex.com",
    ]
    for idx, origin in enumerate(origins):
        r = _post(origin, {"message": "hi"}, xff=f"203.0.113.{10 + idx}")
        assert r.status_code == 200, f"origin {origin!r} rejected: {r.text}"


# ── input validation ──────────────────────────────────────────────────────────


def test_chat_message_rejects_empty_message_whitespace(monkeypatch):
    # Pydantic min_length=1 catches the bare empty string; the handler's
    # explicit .strip() check catches whitespace-only input that bypasses it.
    _stub_kb(monkeypatch, {"found": False, "answer_hint": "n/a", "citations": []})
    r = _post(
        "https://klaravex.com",
        {"message": "   "},
        xff="203.0.113.20",
    )
    assert r.status_code == 422


def test_chat_message_rejects_missing_message_field():
    # No KB stub needed — Pydantic 422 fires before the handler body runs.
    r = _post("https://klaravex.com", {}, xff="203.0.113.21")
    assert r.status_code == 422


def test_chat_message_rejects_oversize_message():
    # Pydantic max_length=CHAT_MAX_MESSAGE_LEN — defends OpenAI budget against
    # attacker-supplied prompts (V3 pentest 2026-06-12).
    r = _post(
        "https://klaravex.com",
        {"message": "x" * (CHAT_MAX_MESSAGE_LEN + 1)},
        xff="203.0.113.22",
    )
    assert r.status_code == 422


def test_chat_message_accepts_message_at_max_length(monkeypatch):
    # Boundary check — exactly CHAT_MAX_MESSAGE_LEN must be accepted, else
    # widget messages near the cap regress to 422 on innocuous wording changes.
    _stub_agent(monkeypatch, "ok")
    r = _post(
        "https://klaravex.com",
        {"message": "x" * CHAT_MAX_MESSAGE_LEN},
        xff="203.0.113.23",
    )
    assert r.status_code == 200, r.text
    assert set(r.json().keys()) == {"reply", "session_token"}


# ── Pydantic field-cap contract on client_email (iter-5 symmetric fix) ────────
# Pattern 34 — method-family invariant: every attacker-supplied string field on
# ChatRequest must have a max_length, not just `message`. Pre-iter-5 the
# `client_email` field was uncapped while `message` was capped at 1500, leaving
# the OpenAI-budget attack surface re-openable via a 100k-char email payload.
# RFC 5321 caps email at 254 chars; lock that as the contract.
CLIENT_EMAIL_MAX_LEN = 254


def test_chat_message_rejects_oversize_client_email():
    # Pydantic 422 fires before the handler runs — no KB stub or origin gate
    # needed (validation precedes the dispatch).
    r = _post(
        "https://klaravex.com",
        {"message": "hi", "client_email": "a" * (CLIENT_EMAIL_MAX_LEN + 1) + "@x"},
        xff="203.0.113.30",
    )
    assert r.status_code == 422


def test_chat_message_accepts_client_email_at_max_length(monkeypatch):
    # Boundary check — exactly 254 chars must be accepted so a legitimate
    # long-but-RFC-valid address isn't bounced.
    _stub_kb(monkeypatch, {"found": False, "answer_hint": "n/a", "citations": []})
    email = "a" * (CLIENT_EMAIL_MAX_LEN - len("@example.com")) + "@example.com"
    assert len(email) == CLIENT_EMAIL_MAX_LEN
    r = _post(
        "https://klaravex.com",
        {"message": "hi", "client_email": email},
        xff="203.0.113.31",
    )
    assert r.status_code == 200, r.text


def test_chat_message_accepts_null_client_email(monkeypatch):
    # Default null must remain accepted — the field is optional on the widget.
    _stub_kb(monkeypatch, {"found": False, "answer_hint": "n/a", "citations": []})
    r = _post(
        "https://klaravex.com",
        {"message": "hi", "client_email": None},
        xff="203.0.113.32",
    )
    assert r.status_code == 200, r.text
