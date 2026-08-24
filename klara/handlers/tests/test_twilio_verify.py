"""
Tests for klara.handlers.lib.twilio_verify.verify_twilio_signature.

Coverage
--------
1. valid signature → handler runs (no exception)
2. missing X-Twilio-Signature header → 401
3. tampered signature → 401
4. TWILIO_AUTH_TOKEN unset → 503 (fail-CLOSED)
5. URL reconstruction uses TWILIO_PUBLIC_HOST, not the inbound URL

These tests mount a minimal FastAPI app per case so we don't drag in the
full Klaravex backend (which requires DATABASE_URL etc.). Verification
state on the twilio_verify module is monkeypatched directly — that's the
documented test seam.

Run with:
    pytest infra/klara.handlers/tests/test_twilio_verify.py -v
"""
import importlib
import sys
from pathlib import Path

import pytest

# Ensure infra/ is on the path so `klara.handlers.*` resolves.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
INFRA_DIR = PROJECT_ROOT / "infra"
sys.path.insert(0, str(INFRA_DIR))


# Skip the whole module if FastAPI/test deps are missing — CI installs them
# but local Bun-first dev environments may not.
fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")
twilio_pkg = pytest.importorskip("twilio")
from twilio.request_validator import RequestValidator  # noqa: E402


def _reload_tv():
    """Force a real re-execution of the module body so _TOKEN / _validator
    pick up the current os.environ. sys.modules.pop + `from ... import ...`
    is insufficient because the parent package keeps a cached attribute
    on `klara.handlers.lib` that shadows the re-import; importlib.reload
    walks the right path."""
    from klara.handlers.lib import twilio_verify as tv
    return importlib.reload(tv)


@pytest.fixture()
def fresh_module(monkeypatch):
    """Reimport twilio_verify with controllable env state per test."""
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token-1234")
    monkeypatch.setenv("TWILIO_PUBLIC_HOST", "https://api.klaravex.com")
    return _reload_tv()


def _build_app(tv_module):
    from fastapi import Depends, FastAPI, Form

    app = FastAPI()

    @app.post("/api/v1/voice/inbound", dependencies=[Depends(tv_module.verify_twilio_signature)])
    async def inbound(CallSid: str = Form("")) -> dict:
        return {"ok": True, "call": CallSid}

    return app


def _sign(token: str, url: str, params: dict) -> str:
    return RequestValidator(token).compute_signature(url, params)


def test_valid_signature_passes(fresh_module):
    tv = fresh_module
    app = _build_app(tv)
    client = testclient.TestClient(app)

    params = {"CallSid": "CA123", "From": "+15551234"}
    url = "https://api.klaravex.com/api/v1/voice/inbound"
    sig = _sign("test-token-1234", url, params)

    r = client.post("/api/v1/voice/inbound", data=params, headers={"X-Twilio-Signature": sig})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "call": "CA123"}


def test_missing_signature_returns_401(fresh_module):
    app = _build_app(fresh_module)
    client = testclient.TestClient(app)
    r = client.post("/api/v1/voice/inbound", data={"CallSid": "CA123"})
    assert r.status_code == 401
    assert "missing twilio signature" in r.json()["detail"].lower()


def test_tampered_signature_returns_401(fresh_module):
    tv = fresh_module
    app = _build_app(tv)
    client = testclient.TestClient(app)

    params = {"CallSid": "CA123"}
    url = "https://api.klaravex.com/api/v1/voice/inbound"
    sig = _sign("test-token-1234", url, params)
    # Flip a single character to tamper.
    bad_sig = ("A" if sig[0] != "A" else "B") + sig[1:]

    r = client.post("/api/v1/voice/inbound", data=params, headers={"X-Twilio-Signature": bad_sig})
    assert r.status_code == 401
    assert "invalid twilio signature" in r.json()["detail"].lower()


def test_missing_token_returns_503(monkeypatch):
    """Server with no TWILIO_AUTH_TOKEN must reject everything with 503."""
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("TWILIO_PUBLIC_HOST", "https://api.klaravex.com")
    tv = _reload_tv()

    # When the env var is missing the module sets _validator=None at import time.
    assert tv._validator is None

    app = _build_app(tv)
    client = testclient.TestClient(app)

    # Any request — even a "correctly" signed one — must 503.
    r = client.post(
        "/api/v1/voice/inbound",
        data={"CallSid": "CA123"},
        headers={"X-Twilio-Signature": "anything"},
    )
    assert r.status_code == 503
    assert "misconfigured" in r.json()["detail"].lower()


def test_url_uses_public_host_not_inbound_host(fresh_module):
    """Twilio signs against the public URL. A signature computed against a
    different host must NOT validate — proves we reconstruct from
    TWILIO_PUBLIC_HOST, not from request.url.
    """
    tv = fresh_module
    app = _build_app(tv)
    client = testclient.TestClient(app)

    params = {"CallSid": "CA999"}
    # Sign against the INTERNAL Azure URL — should fail because the
    # dependency rebuilds the URL with TWILIO_PUBLIC_HOST.
    internal_url = "https://klaravex-api.internal.azurecontainerapps.io/api/v1/voice/inbound"
    sig = _sign("test-token-1234", internal_url, params)

    r = client.post("/api/v1/voice/inbound", data=params, headers={"X-Twilio-Signature": sig})
    assert r.status_code == 401
