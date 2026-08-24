"""Regression test for POST /api/v1/chat/start.

Locks the contract the klaravex.com / personal.klaravex.com chat widget
relies on. The endpoint was missing pre-2026-06-20 (8-day silent outage)
and shipped in commit e780f25; this test prevents the same shape +
origin-gate from regressing.

Contract:
- 200 with {session_token, reply, language, source} on allowed origin
- 403 on disallowed / missing origin
- language is lowercased + locale-stripped ('en-US' -> 'en')
- de welcome differs from en welcome (i18n branch reachable)
- session_token is unique across calls (urlsafe 24-byte token)
"""
import pytest
from fastapi.testclient import TestClient

from infra.main import app
from klara.handlers.lib.rate_limit import limiter


client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset SlowAPI rate-limiter storage between tests so earlier tests
    don't exhaust the 20/minute budget for later ones."""
    limiter.reset()
    yield


def _post(origin: str | None, body: dict | None = None):
    headers = {"Origin": origin} if origin is not None else {}
    return client.post("/api/v1/chat/start", json=body or {}, headers=headers)


def test_chat_start_allowed_origin_returns_expected_shape():
    r = _post("https://klaravex.com")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"session_token", "reply", "language", "source"}
    assert isinstance(body["session_token"], str) and len(body["session_token"]) >= 24
    assert body["language"] == "en"
    assert "Klara" in body["reply"]
    assert body["source"] == "discovery_call"


def test_chat_start_rejects_disallowed_origin():
    r = _post("https://attacker.example")
    assert r.status_code == 403


def test_chat_start_rejects_missing_origin():
    r = _post(None)
    assert r.status_code == 403


def test_chat_start_strips_locale_suffix():
    r = _post("https://klaravex.com", {"language": "en-US"})
    assert r.status_code == 200
    assert r.json()["language"] == "en"


def test_chat_start_de_branch_returns_german_welcome():
    en = _post("https://klaravex.com", {"language": "en"}).json()
    de = _post("https://klaravex.com", {"language": "de"}).json()
    assert de["language"] == "de"
    assert de["reply"] != en["reply"]
    assert "Hallo" in de["reply"]


def test_chat_start_unknown_language_falls_back_to_en():
    r = _post("https://klaravex.com", {"language": "xx"})
    assert r.status_code == 200
    body = r.json()
    assert body["language"] == "xx"  # echoes parsed language
    assert "Klara" in body["reply"]  # but welcome falls back to en


def test_chat_start_source_passthrough():
    r = _post("https://klaravex.com", {"source": "footer_widget"})
    assert r.status_code == 200
    assert r.json()["source"] == "footer_widget"


def test_chat_start_session_token_uniqueness():
    a = _post("https://klaravex.com").json()["session_token"]
    b = _post("https://klaravex.com").json()["session_token"]
    assert a != b


def test_chat_start_supports_all_documented_origins():
    for origin in (
        "https://klaravex.com",
        "https://www.klaravex.com",
        "https://support.klaravex.com",
    ):
        r = _post(origin)
        assert r.status_code == 200, f"origin {origin!r} rejected: {r.text}"


def test_chat_start_origin_match_is_case_insensitive():
    r = _post("HTTPS://Klaravex.com")
    assert r.status_code == 200


# ── Pydantic field-cap contract (V3 pentest mirror of CHAT_MAX_MESSAGE_LEN) ──
# Locks ChatStartRequest.source max_length=64, language max_length=8, and
# gdpr_consent bool coercion. Drift here re-opens the attacker-supplied
# oversize-field surface that the chat/message handler closes via
# CHAT_MAX_MESSAGE_LEN; the start handler defends the same shape on entry.


def test_chat_start_rejects_oversize_source():
    r = _post("https://klaravex.com", {"source": "x" * 65})
    assert r.status_code == 422


def test_chat_start_rejects_oversize_language():
    r = _post("https://klaravex.com", {"language": "x" * 9})
    assert r.status_code == 422


def test_chat_start_rejects_non_bool_gdpr_consent():
    r = _post("https://klaravex.com", {"gdpr_consent": "not-a-bool"})
    assert r.status_code == 422


def test_chat_start_accepts_source_at_max_length():
    r = _post("https://klaravex.com", {"source": "x" * 64})
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "x" * 64
