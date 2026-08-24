"""Portal OAuth — Google + Microsoft Entra (OIDC, authorization code + PKCE).

Foundation module for T14.1. Implements the full code-with-PKCE flow:

    /portal/login/oauth/{provider}/start   -> 302 to issuer authorize URL
    /portal/login/oauth/{provider}/callback -> consume code, mint portal session

When provider client_id/client_secret env vars are unset, start_login() and
exchange_code() raise OAuthNotConfigured. The portal router catches that and
shows a friendly "this sign-in method isn't enabled yet" message instead of
500ing. That way the buttons can ship before C1/C2 (Google OAuth client +
Microsoft Entra app registration) are created.

Discovery documents are fetched once and cached per-process:
  Google      https://accounts.google.com/.well-known/openid-configuration
  Microsoft   https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration

id_token signature verification uses the issuer's published JWKS — keys are
cached for 1h and refreshed on kid miss.
"""

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

log = logging.getLogger("klaravex.portal.oauth")

# ──────────────────────────────────────────────────────────────────────────────
# Provider configuration
# ──────────────────────────────────────────────────────────────────────────────

PROVIDERS = ("google", "microsoft")
OAUTH_STATE_TTL_MIN = int(os.environ.get("PORTAL_OAUTH_STATE_TTL_MIN", "10"))

DISCOVERY_URLS = {
    "google": "https://accounts.google.com/.well-known/openid-configuration",
    # 'common' tenant — accepts both personal + work/school accounts.
    "microsoft": "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
}

# Issuers we accept on the id_token. Microsoft's issuer varies by tenant —
# we accept any v2.0 issuer ('https://login.microsoftonline.com/{tenant}/v2.0').
ACCEPTABLE_ISSUERS = {
    "google": {"https://accounts.google.com", "accounts.google.com"},
    "microsoft": None,  # validated by prefix below
}

DEFAULT_SCOPES = {
    "google": "openid email profile",
    "microsoft": "openid email profile offline_access",
}


class OAuthError(Exception):
    """Recoverable OAuth flow error — render to user."""


class OAuthNotConfigured(OAuthError):
    """Provider credentials aren't in the environment yet."""


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    client_id: str
    client_secret: str
    scopes: str


def _provider_config(provider: str) -> ProviderConfig:
    if provider not in PROVIDERS:
        raise OAuthError(f"unknown provider: {provider}")
    if provider == "google":
        cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
        sec = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
    else:
        cid = os.environ.get("MICROSOFT_OAUTH_CLIENT_ID", "")
        sec = os.environ.get("MICROSOFT_OAUTH_CLIENT_SECRET", "")
    if not cid or not sec:
        raise OAuthNotConfigured(
            f"{provider} OAuth credentials not configured "
            f"(set {provider.upper()}_OAUTH_CLIENT_ID + _CLIENT_SECRET)"
        )
    return ProviderConfig(
        provider=provider,
        client_id=cid,
        client_secret=sec,
        scopes=DEFAULT_SCOPES[provider],
    )


def is_configured(provider: str) -> bool:
    try:
        _provider_config(provider)
        return True
    except OAuthNotConfigured:
        return False
    except OAuthError:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Discovery + JWKS cache (in-process; safe across asyncio because dict assign
# is atomic and we only ever overwrite with a fresher value).
# ──────────────────────────────────────────────────────────────────────────────

_DISCOVERY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_DISCOVERY_TTL = 3600.0
_JWKS_TTL = 3600.0


async def _get_discovery(provider: str) -> dict[str, Any]:
    now = time.time()
    cached = _DISCOVERY_CACHE.get(provider)
    if cached and (now - cached[0]) < _DISCOVERY_TTL:
        return cached[1]
    url = DISCOVERY_URLS[provider]
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url)
        r.raise_for_status()
        doc = r.json()
    _DISCOVERY_CACHE[provider] = (now, doc)
    return doc


async def _get_jwks(provider: str, *, force_refresh: bool = False) -> dict[str, Any]:
    now = time.time()
    cached = _JWKS_CACHE.get(provider)
    if cached and not force_refresh and (now - cached[0]) < _JWKS_TTL:
        return cached[1]
    disc = await _get_discovery(provider)
    jwks_uri = disc["jwks_uri"]
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(jwks_uri)
        r.raise_for_status()
        jwks = r.json()
    _JWKS_CACHE[provider] = (now, jwks)
    return jwks


# ──────────────────────────────────────────────────────────────────────────────
# PKCE helpers
# ──────────────────────────────────────────────────────────────────────────────

def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_code_verifier() -> str:
    # 32 random bytes → 43-char base64url string. RFC 7636 allows 43-128 chars.
    return _b64url(secrets.token_bytes(32))


def code_challenge_for(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def make_state() -> str:
    return _b64url(secrets.token_bytes(32))


def make_nonce() -> str:
    return _b64url(secrets.token_bytes(16))


# ──────────────────────────────────────────────────────────────────────────────
# id_token verification (RS256 only — enough for Google + Microsoft)
# ──────────────────────────────────────────────────────────────────────────────

def _rsa_verify(message: bytes, signature: bytes, jwk: dict[str, Any]) -> bool:
    """RS256 verify using the cryptography package. Returns False on failure."""
    try:
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
        from cryptography.hazmat.primitives import hashes
    except ImportError:  # pragma: no cover — should be available in prod
        log.error("cryptography package not available; cannot verify id_token")
        return False
    try:
        n = int.from_bytes(_b64url_decode(jwk["n"]), "big")
        e = int.from_bytes(_b64url_decode(jwk["e"]), "big")
        pubkey = RSAPublicNumbers(e, n).public_key()
        pubkey.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception as exc:
        log.warning("id_token signature check failed: %s", exc)
        return False


async def verify_id_token(
    provider: str,
    id_token: str,
    *,
    expected_nonce: str,
    expected_aud: str,
) -> dict[str, Any]:
    """Verify signature, issuer, audience, expiry, nonce. Return claims dict."""
    parts = id_token.split(".")
    if len(parts) != 3:
        raise OAuthError("malformed id_token")
    header_b64, payload_b64, sig_b64 = parts
    try:
        header = json.loads(_b64url_decode(header_b64))
        claims = json.loads(_b64url_decode(payload_b64))
    except Exception as exc:
        raise OAuthError(f"id_token decode failed: {exc}")

    if header.get("alg") != "RS256":
        raise OAuthError(f"unsupported id_token alg: {header.get('alg')!r}")
    kid = header.get("kid")
    if not kid:
        raise OAuthError("id_token missing kid")

    # Find the signing key. If kid not in cache, refresh once.
    jwks = await _get_jwks(provider)
    keys = {k["kid"]: k for k in jwks.get("keys", []) if "kid" in k}
    jwk = keys.get(kid)
    if jwk is None:
        jwks = await _get_jwks(provider, force_refresh=True)
        keys = {k["kid"]: k for k in jwks.get("keys", []) if "kid" in k}
        jwk = keys.get(kid)
    if jwk is None:
        raise OAuthError(f"id_token kid {kid!r} not found in jwks")

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = _b64url_decode(sig_b64)
    if not _rsa_verify(signing_input, signature, jwk):
        raise OAuthError("id_token signature invalid")

    # Issuer check.
    iss = claims.get("iss")
    if provider == "google":
        if iss not in ACCEPTABLE_ISSUERS["google"]:
            raise OAuthError(f"id_token issuer not trusted: {iss!r}")
    else:
        # Microsoft v2.0 issuer is 'https://login.microsoftonline.com/{tenant}/v2.0'
        if not (isinstance(iss, str) and iss.startswith("https://login.microsoftonline.com/")
                and iss.endswith("/v2.0")):
            raise OAuthError(f"id_token issuer not trusted: {iss!r}")

    # Audience check.
    aud = claims.get("aud")
    if isinstance(aud, list):
        if expected_aud not in aud:
            raise OAuthError("id_token audience mismatch")
    elif aud != expected_aud:
        raise OAuthError("id_token audience mismatch")

    # Expiry.
    now = int(time.time())
    if int(claims.get("exp", 0)) < now - 30:
        raise OAuthError("id_token expired")
    if int(claims.get("iat", now)) > now + 60:
        raise OAuthError("id_token issued in the future")

    # Nonce.
    if claims.get("nonce") != expected_nonce:
        raise OAuthError("id_token nonce mismatch")

    return claims


# ──────────────────────────────────────────────────────────────────────────────
# Flow entry points
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StartedFlow:
    authorize_url: str
    state: str
    code_verifier: str
    nonce: str


async def start_login(provider: str, redirect_uri: str) -> StartedFlow:
    """Build the issuer authorize URL + opaque state/verifier/nonce.

    Caller persists state/code_verifier/nonce keyed by `state` so the callback
    can retrieve them. Provider creds must be configured.
    """
    cfg = _provider_config(provider)
    disc = await _get_discovery(provider)
    authz = disc["authorization_endpoint"]

    state = make_state()
    verifier = make_code_verifier()
    challenge = code_challenge_for(verifier)
    nonce = make_nonce()

    from urllib.parse import urlencode
    params = {
        "client_id": cfg.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": cfg.scopes,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "nonce": nonce,
        # Force a fresh consent screen on Google; Microsoft also honours it.
        "prompt": "select_account",
    }
    url = f"{authz}?{urlencode(params)}"
    return StartedFlow(authorize_url=url, state=state, code_verifier=verifier, nonce=nonce)


@dataclass(frozen=True)
class IdentityResult:
    provider: str
    sub: str
    email: str
    email_verified: bool
    name: Optional[str]
    issuer: str


async def exchange_code(
    provider: str,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    expected_nonce: str,
) -> IdentityResult:
    """Exchange auth code for tokens; verify id_token; return identity claims."""
    cfg = _provider_config(provider)
    disc = await _get_discovery(provider)
    token_endpoint = disc["token_endpoint"]

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
        "code_verifier": code_verifier,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            token_endpoint,
            data=data,
            headers={"Accept": "application/json"},
        )
    if r.status_code >= 400:
        log.warning("token exchange failed [%s] %s: %s", provider, r.status_code, r.text[:300])
        raise OAuthError(f"token exchange failed ({r.status_code})")
    tokens = r.json()
    id_token = tokens.get("id_token")
    if not id_token:
        raise OAuthError("token response missing id_token")

    claims = await verify_id_token(
        provider, id_token, expected_nonce=expected_nonce, expected_aud=cfg.client_id
    )
    email = (claims.get("email") or "").lower()
    if not email:
        raise OAuthError("id_token has no email claim — provider configuration may be missing email scope")
    return IdentityResult(
        provider=provider,
        sub=str(claims["sub"]),
        email=email,
        email_verified=bool(claims.get("email_verified", True)),
        name=claims.get("name"),
        issuer=str(claims.get("iss", "")),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Persistence — state store + linked accounts
# ──────────────────────────────────────────────────────────────────────────────

async def save_oauth_state(
    *,
    state: str,
    provider: str,
    code_verifier: str,
    nonce: str,
    return_to: Optional[str] = None,
) -> None:
    from .db import get_pool
    pool = await get_pool()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=OAUTH_STATE_TTL_MIN)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO klaravex_portal_oauth_states
                (state, provider, code_verifier, nonce, return_to, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            state, provider, code_verifier, nonce, return_to, expires_at,
        )


async def consume_oauth_state(state: str) -> Optional[dict[str, Any]]:
    """Single-use lookup: returns the row + clears it, or None if not valid."""
    from .db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT provider, code_verifier, nonce, return_to, expires_at, used_at
              FROM klaravex_portal_oauth_states
             WHERE state = $1
            """,
            state,
        )
        if not row:
            return None
        if row["used_at"] is not None:
            return None
        if row["expires_at"] < datetime.now(timezone.utc):
            return None
        await conn.execute(
            "UPDATE klaravex_portal_oauth_states SET used_at = now() WHERE state = $1",
            state,
        )
        return dict(row)


async def upsert_linked_account(identity: IdentityResult) -> str:
    """Insert or refresh the link row. Returns the canonical portal email."""
    from .db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO klaravex_portal_linked_accounts
                (email, provider, provider_sub, provider_email, provider_name,
                 id_token_iss, last_login_at)
            VALUES ($1, $2, $3, $4, $5, $6, now())
            ON CONFLICT (provider, provider_sub) DO UPDATE
                SET email = EXCLUDED.email,
                    provider_email = EXCLUDED.provider_email,
                    provider_name = EXCLUDED.provider_name,
                    id_token_iss = EXCLUDED.id_token_iss,
                    last_login_at = now()
            """,
            identity.email, identity.provider, identity.sub,
            identity.email, identity.name, identity.issuer,
        )
    return identity.email
