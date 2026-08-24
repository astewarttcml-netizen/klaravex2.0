"""
Tests for klara.handlers.lib.vapi_verify.verify_vapi_secret.

Coverage
--------
1. valid x-vapi-secret → handler runs
2. missing x-vapi-secret header → 401
3. mismatched secret → 401
4. VAPI_SHARED_SECRET unset → 503 (fail-CLOSED)
5. constant-time compare path runs (no exception on weird length input)

Run with:
    pytest infra/klara.handlers/tests/test_vapi_verify.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INFRA_DIR = PROJECT_ROOT / "infra"
sys.path.insert(0, str(INFRA_DIR))

fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")


def _build_app():
    from fastapi import Depends, FastAPI

    from klara.handlers.lib.vapi_verify import verify_vapi_secret

    app = FastAPI()

    @app.post("/api/v1/vapi/payment_link", dependencies=[Depends(verify_vapi_secret)])
    async def payment_link() -> dict:
        return {"ok": True}

    return app


def test_valid_secret_passes(monkeypatch):
    monkeypatch.setenv("VAPI_SHARED_SECRET", "shhh-it-is-secret")
    app = _build_app()
    client = testclient.TestClient(app)

    r = client.post("/api/v1/vapi/payment_link", headers={"x-vapi-secret": "shhh-it-is-secret"})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


def test_missing_secret_header_returns_401(monkeypatch):
    monkeypatch.setenv("VAPI_SHARED_SECRET", "shhh-it-is-secret")
    app = _build_app()
    client = testclient.TestClient(app)

    r = client.post("/api/v1/vapi/payment_link")
    assert r.status_code == 401
    assert "vapi" in r.json()["detail"].lower()


def test_mismatched_secret_returns_401(monkeypatch):
    monkeypatch.setenv("VAPI_SHARED_SECRET", "shhh-it-is-secret")
    app = _build_app()
    client = testclient.TestClient(app)

    r = client.post("/api/v1/vapi/payment_link", headers={"x-vapi-secret": "wrong-token"})
    assert r.status_code == 401
    assert "invalid vapi secret" in r.json()["detail"].lower()


def test_missing_env_var_returns_503(monkeypatch):
    """Server with no VAPI_SHARED_SECRET must reject everything 503 — fail-CLOSED."""
    monkeypatch.delenv("VAPI_SHARED_SECRET", raising=False)
    app = _build_app()
    client = testclient.TestClient(app)

    r = client.post("/api/v1/vapi/payment_link", headers={"x-vapi-secret": "anything"})
    assert r.status_code == 503
    assert "misconfigured" in r.json()["detail"].lower()


def test_compare_digest_safe_on_short_input(monkeypatch):
    """secrets.compare_digest raises TypeError on bytes/str mix; the dependency
    should handle any non-matching string safely and return 401, never 500.
    """
    monkeypatch.setenv("VAPI_SHARED_SECRET", "shhh-it-is-secret")
    app = _build_app()
    client = testclient.TestClient(app)

    for bad in ("", "x", "a" * 1024):
        r = client.post("/api/v1/vapi/payment_link", headers={"x-vapi-secret": bad})
        assert r.status_code == 401, f"got {r.status_code} for bad={bad!r}"


# ---------------------------------------------------------------------------
# Dual-secret / watchdog fallback branch (postmortem 2026-06-21)
# ---------------------------------------------------------------------------

def test_valid_watchdog_secret_alone_passes(monkeypatch):
    """WATCHDOG_ESCALATION_SECRET must accept x-watchdog-secret when
    VAPI_SHARED_SECRET is unset (env-regenerator dropout scenario)."""
    monkeypatch.delenv("VAPI_SHARED_SECRET", raising=False)
    monkeypatch.setenv("WATCHDOG_ESCALATION_SECRET", "watchdog-wakes-anthony")
    app = _build_app()
    client = testclient.TestClient(app)

    r = client.post(
        "/api/v1/vapi/payment_link",
        headers={"x-watchdog-secret": "watchdog-wakes-anthony"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


def test_watchdog_header_with_only_vapi_secret_set_fails(monkeypatch):
    """If only VAPI_SHARED_SECRET is configured, presenting x-watchdog-secret
    (even if it matches WATCHDOG value, which is empty) must NOT pass."""
    monkeypatch.setenv("VAPI_SHARED_SECRET", "vapi-only")
    monkeypatch.delenv("WATCHDOG_ESCALATION_SECRET", raising=False)
    app = _build_app()
    client = testclient.TestClient(app)

    r = client.post("/api/v1/vapi/payment_link", headers={"x-watchdog-secret": ""})
    assert r.status_code == 401


def test_both_secrets_set_either_header_passes(monkeypatch):
    """When both env vars are configured, each header independently opens
    the gate — dual channels fail independently."""
    monkeypatch.setenv("VAPI_SHARED_SECRET", "vapi-value")
    monkeypatch.setenv("WATCHDOG_ESCALATION_SECRET", "wd-value")
    app = _build_app()
    client = testclient.TestClient(app)

    r1 = client.post("/api/v1/vapi/payment_link", headers={"x-vapi-secret": "vapi-value"})
    assert r1.status_code == 200

    r2 = client.post("/api/v1/vapi/payment_link", headers={"x-watchdog-secret": "wd-value"})
    assert r2.status_code == 200


def test_both_secrets_set_wrong_headers_fail(monkeypatch):
    """Both secrets configured but presenter mixes values — must 401."""
    monkeypatch.setenv("VAPI_SHARED_SECRET", "vapi-value")
    monkeypatch.setenv("WATCHDOG_ESCALATION_SECRET", "wd-value")
    app = _build_app()
    client = testclient.TestClient(app)

    r = client.post(
        "/api/v1/vapi/payment_link",
        headers={"x-vapi-secret": "wd-value", "x-watchdog-secret": "vapi-value"},
    )
    assert r.status_code == 401


def test_both_env_unset_returns_503_even_with_watchdog_header(monkeypatch):
    """Fail-CLOSED when both env vars unset — presenting watchdog header
    must not open a hole."""
    monkeypatch.delenv("VAPI_SHARED_SECRET", raising=False)
    monkeypatch.delenv("WATCHDOG_ESCALATION_SECRET", raising=False)
    app = _build_app()
    client = testclient.TestClient(app)

    r = client.post(
        "/api/v1/vapi/payment_link",
        headers={"x-watchdog-secret": "guessed-value"},
    )
    assert r.status_code == 503
    assert "misconfigured" in r.json()["detail"].lower()


def test_empty_watchdog_header_with_watchdog_set_fails(monkeypatch):
    """Empty x-watchdog-secret must NOT match an empty-string-not-configured
    scenario — the `presented and expected` guard rejects blanks."""
    monkeypatch.delenv("VAPI_SHARED_SECRET", raising=False)
    monkeypatch.setenv("WATCHDOG_ESCALATION_SECRET", "actual-value")
    app = _build_app()
    client = testclient.TestClient(app)

    r = client.post("/api/v1/vapi/payment_link", headers={"x-watchdog-secret": ""})
    assert r.status_code == 401
