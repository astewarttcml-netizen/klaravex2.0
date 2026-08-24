"""
Klaravex input guardrail — T8.7.

FastAPI middleware + helper function ``redact_phi(text: str) -> str``.

Redacts the following PII/PHI patterns before any request body reaches a
handler or is assembled into a prompt:
  - SSN          (\d{3}-\d{2}-\d{4})           → [SSN]
  - Credit card  (16-digit, spaces/dashes OK)   → [CARD]
  - Email addresses                              → [EMAIL]
  - US/intl phone numbers                        → [PHONE]
  - Date of birth (MM/DD/YYYY, YYYY-MM-DD, etc.)→ [DOB]

Mount order in main.py:
    app.add_middleware(InputGuardrailMiddleware)   # runs first, before routes
"""

import json
import logging
import re
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

log = logging.getLogger("klaravex.guardrails.input")

# ── Compiled patterns (order matters — more-specific first) ──────────────────

_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){15,16}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"""
    (?:
        \+?1[-.\s]?           # optional country code
    )?
    (?:\(\d{3}\)|\d{3})       # area code
    [-.\s]?
    \d{3}
    [-.\s]?
    \d{4}
    \b
    """,
    re.VERBOSE,
)
_DOB_RE = re.compile(
    r"\b(?:"
    r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}"   # MM/DD/YYYY or MM-DD-YYYY
    r"|"
    r"\d{4}[/\-]\d{1,2}[/\-]\d{1,2}"      # YYYY-MM-DD
    r")\b"
)


def redact_phi(text: str) -> str:
    """Return *text* with PII/PHI patterns replaced by safe placeholders.

    Applies patterns in order: SSN → CARD → EMAIL → PHONE → DOB.
    Safe to call on any string — returns original if no patterns match.

    >>> redact_phi("My SSN is 123-45-6789 and email john@example.com")
    'My SSN is [SSN] and email [EMAIL]'
    >>> redact_phi("DOB 01/15/1990, card 4111 1111 1111 1111")
    'DOB [DOB], card [CARD]'
    """
    text = _SSN_RE.sub("[SSN]", text)
    text = _CARD_RE.sub("[CARD]", text)
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    text = _DOB_RE.sub("[DOB]", text)
    return text


def _redact_json_obj(obj: object) -> object:
    """Recursively walk a parsed JSON structure and redact all string values."""
    if isinstance(obj, str):
        return redact_phi(obj)
    if isinstance(obj, dict):
        return {k: _redact_json_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_json_obj(item) for item in obj]
    return obj


class InputGuardrailMiddleware(BaseHTTPMiddleware):
    """Starlette/FastAPI middleware that redacts PII/PHI from every POST request body.

    - Only intercepts requests whose ``Content-Type`` is ``application/json``.
    - Non-JSON bodies (TwiML, form data, etc.) are passed through untouched.
    - Rewrites the ASGI body buffer so the downstream handler sees the redacted
      version; the original is never stored.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        content_type = request.headers.get("content-type", "")
        if request.method == "POST" and "application/json" in content_type:
            try:
                raw = await request.body()
                if raw:
                    parsed = json.loads(raw)
                    redacted = _redact_json_obj(parsed)
                    new_body = json.dumps(redacted).encode()
                    # Patch the body back onto the request scope so FastAPI
                    # reads the redacted version.
                    async def receive():  # noqa: E306
                        return {"type": "http.request", "body": new_body, "more_body": False}
                    request = Request(request.scope, receive)
            except Exception as exc:  # noqa: BLE001
                log.warning("InputGuardrailMiddleware: body parse failed, passing through: %s", exc)

        return await call_next(request)
