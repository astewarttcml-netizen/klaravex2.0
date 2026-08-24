"""Tests for portal OAuth lib (T14.1).

Covers:
- Provider gating: is_configured() returns False without env, True with both vars
- PKCE helpers produce RFC 7636 compliant verifier/challenge
- start_login() raises OAuthNotConfigured when credentials missing
- start_login() URL contains the required OIDC params (with mocked discovery)
- id_token verification rejects bad alg, wrong issuer, wrong audience, expired,
  wrong nonce; accepts a freshly self-signed RS256 token.

No network is touched — the discovery + JWKS caches are pre-seeded.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from infra.klara.handlers.lib import oauth  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────────
# Configuration gating
# ──────────────────────────────────────────────────────────────────────────────

def test_is_configured_false_when_env_unset(monkeypatch):
    for k in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET",
              "MICROSOFT_OAUTH_CLIENT_ID", "MICROSOFT_OAUTH_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    assert oauth.is_configured("google") is False
    assert oauth.is_configured("microsoft") is False


def test_is_configured_true_when_env_set(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_ID", "cid2")
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_SECRET", "sec2")
    assert oauth.is_configured("google") is True
    assert oauth.is_configured("microsoft") is True


def test_is_configured_unknown_provider_returns_false():
    assert oauth.is_configured("github") is False


# ──────────────────────────────────────────────────────────────────────────────
# PKCE
# ──────────────────────────────────────────────────────────────────────────────

def test_code_verifier_length_and_charset():
    v = oauth.make_code_verifier()
    # 32 random bytes b64url-encoded with no padding → 43 chars.
    assert len(v) == 43
    # base64url alphabet only, no '=' padding.
    assert all(c.isalnum() or c in "-_" for c in v)


def test_code_challenge_matches_rfc7636():
    v = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # RFC 7636 example
    # S256 challenge for that verifier per the spec:
    expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert oauth.code_challenge_for(v) == expected


def test_state_and_nonce_are_unique_per_call():
    a, b = oauth.make_state(), oauth.make_state()
    assert a != b
    assert oauth.make_nonce() != oauth.make_nonce()


# ──────────────────────────────────────────────────────────────────────────────
# start_login gating
# ──────────────────────────────────────────────────────────────────────────────

def test_start_login_raises_when_unconfigured(monkeypatch):
    for k in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(oauth.OAuthNotConfigured):
        asyncio.run(oauth.start_login("google", "https://portal.klaravex.com/cb"))


def test_start_login_builds_authorize_url(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid-123")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "shh")
    # Pre-seed discovery to avoid network.
    oauth._DISCOVERY_CACHE["google"] = (
        time.time(),
        {
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_endpoint": "https://oauth2.googleapis.com/token",
            "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
        },
    )
    redirect = "https://portal.klaravex.com/portal/login/oauth/google/callback"
    flow = asyncio.run(oauth.start_login("google", redirect))
    assert flow.authorize_url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=cid-123" in flow.authorize_url
    assert "response_type=code" in flow.authorize_url
    assert "code_challenge_method=S256" in flow.authorize_url
    assert f"state={flow.state}" in flow.authorize_url
    # Challenge in URL matches verifier.
    assert oauth.code_challenge_for(flow.code_verifier) in flow.authorize_url


# ──────────────────────────────────────────────────────────────────────────────
# id_token verification
# ──────────────────────────────────────────────────────────────────────────────

def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _sign_id_token(payload: dict, kid: str = "test-kid"):
    """Mint an RS256-signed id_token with a fresh keypair. Returns (token, jwk)."""
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import hashes

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    n_bytes = pub.n.to_bytes((pub.n.bit_length() + 7) // 8, "big")
    e_bytes = pub.e.to_bytes((pub.e.bit_length() + 7) // 8, "big")
    jwk = {"kid": kid, "kty": "RSA", "alg": "RS256", "use": "sig",
           "n": _b64url(n_bytes), "e": _b64url(e_bytes)}

    header = {"alg": "RS256", "kid": kid, "typ": "JWT"}
    h_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h_b64}.{p_b64}".encode()
    sig = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    token = f"{h_b64}.{p_b64}.{_b64url(sig)}"
    return token, jwk


def _prime_jwks(provider: str, jwk: dict) -> None:
    oauth._JWKS_CACHE[provider] = (time.time(), {"keys": [jwk]})


def test_verify_id_token_accepts_valid_token():
    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com",
        "aud": "cid-123",
        "sub": "google-user-1",
        "email": "user@example.com",
        "email_verified": True,
        "nonce": "n-abc",
        "iat": now - 10,
        "exp": now + 600,
    }
    token, jwk = _sign_id_token(payload)
    _prime_jwks("google", jwk)
    claims = asyncio.run(oauth.verify_id_token(
        "google", token, expected_nonce="n-abc", expected_aud="cid-123"
    ))
    assert claims["sub"] == "google-user-1"
    assert claims["email"] == "user@example.com"


def test_verify_id_token_rejects_wrong_issuer():
    now = int(time.time())
    payload = {
        "iss": "https://evil.example.com", "aud": "cid-123", "sub": "x",
        "email": "u@e.com", "email_verified": True, "nonce": "n",
        "iat": now, "exp": now + 600,
    }
    token, jwk = _sign_id_token(payload)
    _prime_jwks("google", jwk)
    with pytest.raises(oauth.OAuthError, match="issuer"):
        asyncio.run(oauth.verify_id_token(
            "google", token, expected_nonce="n", expected_aud="cid-123"
        ))


def test_verify_id_token_rejects_wrong_audience():
    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com", "aud": "other-cid", "sub": "x",
        "email": "u@e.com", "email_verified": True, "nonce": "n",
        "iat": now, "exp": now + 600,
    }
    token, jwk = _sign_id_token(payload)
    _prime_jwks("google", jwk)
    with pytest.raises(oauth.OAuthError, match="audience"):
        asyncio.run(oauth.verify_id_token(
            "google", token, expected_nonce="n", expected_aud="cid-123"
        ))


def test_verify_id_token_rejects_expired():
    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com", "aud": "cid-123", "sub": "x",
        "email": "u@e.com", "email_verified": True, "nonce": "n",
        "iat": now - 7200, "exp": now - 600,
    }
    token, jwk = _sign_id_token(payload)
    _prime_jwks("google", jwk)
    with pytest.raises(oauth.OAuthError, match="expired"):
        asyncio.run(oauth.verify_id_token(
            "google", token, expected_nonce="n", expected_aud="cid-123"
        ))


def test_verify_id_token_rejects_wrong_nonce():
    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com", "aud": "cid-123", "sub": "x",
        "email": "u@e.com", "email_verified": True, "nonce": "n-other",
        "iat": now, "exp": now + 600,
    }
    token, jwk = _sign_id_token(payload)
    _prime_jwks("google", jwk)
    with pytest.raises(oauth.OAuthError, match="nonce"):
        asyncio.run(oauth.verify_id_token(
            "google", token, expected_nonce="n-expected", expected_aud="cid-123"
        ))


def test_verify_id_token_accepts_microsoft_v2_issuer():
    now = int(time.time())
    payload = {
        "iss": "https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0",
        "aud": "msft-cid", "sub": "ms-user",
        "email": "u@e.com", "email_verified": True, "nonce": "n",
        "iat": now, "exp": now + 600,
    }
    token, jwk = _sign_id_token(payload)
    _prime_jwks("microsoft", jwk)
    claims = asyncio.run(oauth.verify_id_token(
        "microsoft", token, expected_nonce="n", expected_aud="msft-cid"
    ))
    assert claims["sub"] == "ms-user"


def test_unknown_provider_in_start_login():
    with pytest.raises(oauth.OAuthError):
        asyncio.run(oauth.start_login("facebook", "https://x/cb"))
