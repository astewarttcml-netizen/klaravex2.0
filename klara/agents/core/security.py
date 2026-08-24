"""
app/core/security.py
─────────────────────
API key verification for internal endpoints and webhook signature validation.

We use a simple bearer-token scheme for the management API.
WordPress webhook signatures use HMAC-SHA256.
"""
import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from app.config import get_settings

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(_API_KEY_HEADER)) -> str:
    """
    FastAPI dependency — validates the X-API-Key header on management endpoints.
    Returns the key on success; raises 401 on failure.

    The expected key is derived from APP_SECRET_KEY to avoid storing a second secret.
    """
    settings = get_settings()
    expected = _derive_api_key(settings.app_secret_key)

    if not api_key or not secrets.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key


def _derive_api_key(secret: str) -> str:
    """Derive a stable API key from the app secret (HKDF-lite via HMAC)."""
    return hmac.new(
        secret.encode(), b"loki-management-api-v1", hashlib.sha256
    ).hexdigest()


def verify_wp_webhook_signature(request_body: bytes, signature_header: str) -> bool:
    """
    Verify WordPress webhook signature.
    WordPress sends:  X-WP-Signature: sha256=<hex_digest>

    Returns True if valid, False otherwise.
    Callers should raise 403 on False.
    """
    settings = get_settings()
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    received_sig = signature_header[len("sha256="):]
    expected_sig = hmac.new(
        settings.wp_webhook_secret.encode(),
        request_body,
        hashlib.sha256,
    ).hexdigest()

    return secrets.compare_digest(received_sig, expected_sig)


def verify_email_webhook_signature(request_body: bytes, signature_header: str) -> bool:
    """
    Verify inbound-reply webhook signature from the email provider
    (Resend / SendGrid relay) for phase3-002.

    Provider POSTs:  X-Email-Signature: sha256=<hex_digest>

    The shared secret is derived from APP_SECRET_KEY so we don't need a
    separate env var. The email-side configuration uses the same derivation
    pattern as the management API key (different label, different value).

    Returns True if valid, False otherwise. Caller raises 403 on False.
    """
    settings = get_settings()
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected_secret = hmac.new(
        settings.app_secret_key.encode(),
        b"loki-email-inbound-webhook-v1",
        hashlib.sha256,
    ).hexdigest()

    received_sig = signature_header[len("sha256="):]
    expected_sig = hmac.new(
        expected_secret.encode(),
        request_body,
        hashlib.sha256,
    ).hexdigest()

    return secrets.compare_digest(received_sig, expected_sig)
