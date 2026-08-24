"""
Tests for smartlead_webhook HMAC signature verification (iter-4 code_review gate fix).

Closes review-20260715T120141Z-3 Critical findings:
  - HMAC-SHA256 verification deleted from /webhook — endpoint accepted any POST
  - SMARTLEAD_WEBHOOK_SECRET handling + hmac.compare_digest verifier absent

Coverage:
  1. SMARTLEAD_WEBHOOK_SECRET unset → 503 fail-closed
  2. missing X-Smartlead-Signature header → 401
  3. bad signature → 401
  4. valid signature → passes (no exception)
  5. signature computed against a mutated body → 401 (integrity check)

Run with:
    pytest infra/klara.handlers/tests/test_smartlead_verify.py -v
"""
from __future__ import annotations

import hashlib
import hmac
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INFRA_DIR = PROJECT_ROOT / "infra"
sys.path.insert(0, str(INFRA_DIR))

pytest.importorskip("fastapi")


def _sign(body: bytes, key: str) -> str:
    return hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _reload_module(monkeypatch, secret: str | None):
    if secret is None:
        monkeypatch.delenv("SMARTLEAD_WEBHOOK_SECRET", raising=False)
    else:
        monkeypatch.setenv("SMARTLEAD_WEBHOOK_SECRET", secret)
    import importlib

    from klara.handlers import smartlead_webhook as mod

    importlib.reload(mod)
    return mod


def test_verifier_rejects_when_secret_unset(monkeypatch):
    mod = _reload_module(monkeypatch, secret=None)
    with pytest.raises(Exception) as exc:
        mod._verify_smartlead_signature(b'{"x":1}', "abc")
    assert getattr(exc.value, "status_code", None) == 503


def test_verifier_rejects_missing_header(monkeypatch):
    mod = _reload_module(monkeypatch, secret="s1")
    with pytest.raises(Exception) as exc:
        mod._verify_smartlead_signature(b'{"x":1}', None)
    assert getattr(exc.value, "status_code", None) == 401


def test_verifier_rejects_bad_signature(monkeypatch):
    mod = _reload_module(monkeypatch, secret="s1")
    with pytest.raises(Exception) as exc:
        mod._verify_smartlead_signature(b'{"x":1}', "deadbeef")
    assert getattr(exc.value, "status_code", None) == 401


def test_verifier_accepts_valid_signature(monkeypatch):
    mod = _reload_module(monkeypatch, secret="s1")
    body = b'{"event":"email_reply_received"}'
    sig = _sign(body, "s1")
    # no exception means pass
    mod._verify_smartlead_signature(body, sig)


def test_verifier_rejects_mutated_body(monkeypatch):
    """Signature computed against original body must fail against mutated body."""
    mod = _reload_module(monkeypatch, secret="s1")
    original = b'{"amount":100}'
    mutated = b'{"amount":999}'
    sig = _sign(original, "s1")
    with pytest.raises(Exception) as exc:
        mod._verify_smartlead_signature(mutated, sig)
    assert getattr(exc.value, "status_code", None) == 401
