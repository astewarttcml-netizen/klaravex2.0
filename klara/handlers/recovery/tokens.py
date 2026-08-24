"""HMAC-signed tokens for dropped-call recovery CTAs.

A caller who paid $79 but had their call drop receives an email with
three buttons. Each button is a public URL of the form:

    https://api.klaravex.com/api/v1/recovery/<action>?token=<token>

The token encodes which call the customer is acting on plus the action,
signed with APP_SECRET_KEY so an attacker cannot forge one. TTL = 7 days
so the email stays clickable for a week.

Format
------
    token = base64url(payload_json) + "." + base64url(hmac_sha256(payload_json))

Payload
-------
    {"sid": "<vapi_call_id>", "act": "<resolved|callback|refund>",
     "exp": <unix_ts>, "v": 1}
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Literal

Action = Literal["resolved", "callback", "refund"]

_VALID_ACTIONS: tuple[str, ...] = ("resolved", "callback", "refund")
_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


class TokenError(ValueError):
    """Raised when a token cannot be verified."""


def _key() -> bytes:
    secret = os.environ.get("APP_SECRET_KEY", "")
    if not secret:
        raise TokenError("APP_SECRET_KEY not configured")
    return secret.encode()


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def make_token(call_sid: str, action: Action, ttl_seconds: int = _TTL_SECONDS) -> str:
    """Mint a signed token for one CTA on one call."""
    if action not in _VALID_ACTIONS:
        raise ValueError(f"action must be one of {_VALID_ACTIONS}")
    payload = {"sid": call_sid, "act": action, "exp": int(time.time()) + ttl_seconds, "v": 1}
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(_key(), payload_bytes, hashlib.sha256).digest()
    return f"{_b64e(payload_bytes)}.{_b64e(sig)}"


def verify_token(token: str) -> dict:
    """Verify signature + expiry. Returns the decoded payload or raises TokenError."""
    if not token or "." not in token:
        raise TokenError("malformed token")
    payload_part, sig_part = token.split(".", 1)
    try:
        payload_bytes = _b64d(payload_part)
        sig = _b64d(sig_part)
    except Exception as e:
        raise TokenError("base64 decode failed") from e
    expected = hmac.new(_key(), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise TokenError("bad signature")
    try:
        payload = json.loads(payload_bytes)
    except Exception as e:
        raise TokenError("payload not json") from e
    if payload.get("v") != 1:
        raise TokenError("unsupported token version")
    if payload.get("act") not in _VALID_ACTIONS:
        raise TokenError("invalid action")
    if not payload.get("sid"):
        raise TokenError("missing call sid")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise TokenError("token expired")
    return payload
