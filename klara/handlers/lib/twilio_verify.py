"""
Twilio inbound webhook signature verifier.

Why
===
Every inbound Twilio webhook (voice, SMS, WhatsApp) hits a publicly routable
URL. Without signature verification anyone on the internet can POST a forged
payload to /api/v1/voice/* and trigger:
  * outbound Vapi tool calls (paid minutes),
  * Splashtop session links emailed/SMSed to attacker-controlled numbers,
  * Stripe payment links sent to spoofed callers,
  * arbitrary LLM token spend through the SMS resolver.

Twilio signs every webhook with HMAC-SHA1 over the *exact public URL* +
sorted POST body parameters, using the account auth token as the key. We
verify with the official `twilio.request_validator.RequestValidator` and
fail-CLOSED on every misconfiguration:

  - TWILIO_AUTH_TOKEN unset                  → 503
  - X-Twilio-Signature header missing/blank  → 401
  - signature present but invalid            → 401

URL reconstruction is the tricky part. Twilio signs against the URL it
called — which is the public host (api.klaravex.com), NOT the internal
Azure Container Apps URL the request actually arrives at. We therefore
reconstruct the URL from TWILIO_PUBLIC_HOST + request.url.path (+ query).
If TWILIO_PUBLIC_HOST is wrong the validator will return False and every
inbound webhook will 401 — which is by design (better than fail-open).

Testing
-------
See tests/test_twilio_verify.py. The dependency is mockable via the
module-level _validator, _TOKEN, and _PUBLIC_HOST so tests can swap them
without touching the OS env at runtime.
"""

import logging
import os
from typing import Optional

from fastapi import HTTPException, Request

log = logging.getLogger("klaravex.twilio_verify")

# Module-level configuration — read once at import. Tests monkeypatch these
# directly rather than reloading the module.
_TOKEN: str = os.environ.get("TWILIO_AUTH_TOKEN", "")
_PUBLIC_HOST: str = os.environ.get("TWILIO_PUBLIC_HOST", "https://api.klaravex.com").rstrip("/")

# Build the validator lazily — if the SDK isn't installed yet (early dev) we
# don't want module import to crash the whole app. The dependency will 503
# at request time instead.
_validator: Optional[object] = None
try:
    from twilio.request_validator import RequestValidator as _RequestValidator
    if _TOKEN:
        _validator = _RequestValidator(_TOKEN)
except Exception as exc:  # noqa: BLE001 — pragmatic: don't crash app on import
    log.error("twilio.request_validator unavailable: %s", exc)
    _RequestValidator = None  # type: ignore[assignment]


def _rebuild_validator() -> None:
    """Used by tests after monkeypatching _TOKEN to refresh the validator."""
    global _validator
    if _RequestValidator is None or not _TOKEN:
        _validator = None
        return
    _validator = _RequestValidator(_TOKEN)


async def verify_twilio_signature(request: Request) -> None:
    """FastAPI dependency that rejects requests without a valid X-Twilio-Signature.

    Use via:
        @router.post("/inbound", dependencies=[Depends(verify_twilio_signature)])

    Fails CLOSED on every misconfiguration. Never returns False — always
    raises HTTPException so the endpoint never runs on an unverified request.
    """
    if _validator is None:
        log.error(
            "TWILIO_AUTH_TOKEN unset or twilio SDK missing; refusing inbound webhook %s",
            request.url.path,
        )
        raise HTTPException(
            status_code=503,
            detail="twilio verification disabled — server misconfigured",
        )
    sig = request.headers.get("X-Twilio-Signature", "")
    if not sig:
        raise HTTPException(status_code=401, detail="missing twilio signature")

    # Reconstruct the URL Twilio signed against. MUST be the public-facing
    # URL Twilio actually called, not the internal Azure ingress URL.
    url = f"{_PUBLIC_HOST}{request.url.path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    # Twilio signs the URL-encoded form body (for application/x-www-form-urlencoded
    # webhooks, which is what voice/SMS/WhatsApp use). For JSON webhooks Twilio
    # signs the body bytes instead, but Klaravex doesn't use any of those, so
    # this dependency intentionally only supports form-encoded payloads.
    try:
        form = await request.form()
    except Exception as exc:  # noqa: BLE001
        log.warning("twilio_verify: failed to parse form body: %s", exc)
        raise HTTPException(status_code=400, detail="invalid form body") from exc

    params = {k: v for k, v in form.multi_items()} if hasattr(form, "multi_items") else dict(form)

    if not _validator.validate(url, params, sig):  # type: ignore[attr-defined]
        client_host = request.client.host if request.client else "unknown"
        log.warning(
            "twilio signature mismatch for %s from %s (url=%s sig=%s…)",
            request.url.path, client_host, url, sig[:8],
        )
        raise HTTPException(status_code=401, detail="invalid twilio signature")
