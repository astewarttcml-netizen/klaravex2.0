"""
Tests for calendly_webhook HMAC signature verification (V5 pentest fix).

Coverage:
  1. valid signature → handler proceeds (200/202)
  2. CALENDLY_WEBHOOK_SIGNING_KEY unset → 503 fail-closed
  3. missing Calendly-Webhook-Signature header → 401
  4. malformed signature header → 401
  5. stale timestamp (> tolerance) → 401
  6. bad signature → 401

Run with:
    pytest infra/klara.handlers/tests/test_calendly_verify.py -v
"""
from __future__ import annotations

import hashlib
import hmac
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INFRA_DIR = PROJECT_ROOT / "infra"
sys.path.insert(0, str(INFRA_DIR))

pytest.importorskip("fastapi")


def _sign(body: bytes, key: str, ts: int) -> str:
    payload = f"{ts}.".encode("utf-8") + body
    return hmac.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _reload_module(monkeypatch, signing_key: str | None, tolerance: str = "300"):
    if signing_key is None:
        monkeypatch.delenv("CALENDLY_WEBHOOK_SIGNING_KEY", raising=False)
    else:
        monkeypatch.setenv("CALENDLY_WEBHOOK_SIGNING_KEY", signing_key)
    monkeypatch.setenv("CALENDLY_SIG_TOLERANCE_SECONDS", tolerance)
    import importlib

    from klara.handlers import calendly_webhook as mod

    importlib.reload(mod)
    return mod


def test_verifier_rejects_when_key_unset(monkeypatch):
    mod = _reload_module(monkeypatch, signing_key=None)
    with pytest.raises(Exception) as exc:
        mod._verify_calendly_signature(b'{"x":1}', "t=1,v1=abc")
    assert getattr(exc.value, "status_code", None) == 503


def test_verifier_rejects_missing_header(monkeypatch):
    mod = _reload_module(monkeypatch, signing_key="k1")
    with pytest.raises(Exception) as exc:
        mod._verify_calendly_signature(b'{"x":1}', None)
    assert getattr(exc.value, "status_code", None) == 401


def test_verifier_rejects_malformed_header(monkeypatch):
    mod = _reload_module(monkeypatch, signing_key="k1")
    with pytest.raises(Exception) as exc:
        mod._verify_calendly_signature(b'{"x":1}', "garbage")
    assert getattr(exc.value, "status_code", None) == 401


def test_verifier_rejects_stale_timestamp(monkeypatch):
    mod = _reload_module(monkeypatch, signing_key="k1", tolerance="60")
    body = b'{"x":1}'
    stale_ts = int(time.time()) - 999
    sig = _sign(body, "k1", stale_ts)
    with pytest.raises(Exception) as exc:
        mod._verify_calendly_signature(body, f"t={stale_ts},v1={sig}")
    assert getattr(exc.value, "status_code", None) == 401


def test_verifier_rejects_bad_signature(monkeypatch):
    mod = _reload_module(monkeypatch, signing_key="k1")
    body = b'{"x":1}'
    ts = int(time.time())
    with pytest.raises(Exception) as exc:
        mod._verify_calendly_signature(body, f"t={ts},v1=deadbeef")
    assert getattr(exc.value, "status_code", None) == 401


def test_verifier_accepts_valid_signature(monkeypatch):
    mod = _reload_module(monkeypatch, signing_key="k1")
    body = b'{"x":1}'
    ts = int(time.time())
    sig = _sign(body, "k1", ts)
    # no exception means pass
    mod._verify_calendly_signature(body, f"t={ts},v1={sig}")
