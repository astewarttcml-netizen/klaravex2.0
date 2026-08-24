"""
Klaravex output guardrail — T8.8.

FastAPI middleware + helper ``redact_output(text: str) -> str``.

Applied to every JSON response body before it leaves the server:
  1. Same PII/PHI redaction patterns as guardrails_input.py.
  2. Destructive-action filter — strips / warns if the response body contains
     patterns like ``rm -rf``, ``DROP TABLE``, ``DELETE FROM``, credential-reset
     or firewall-manipulation commands.

Mount order in main.py:
    app.add_middleware(OutputGuardrailMiddleware)   # wraps call_next result
    app.add_middleware(InputGuardrailMiddleware)    # runs on the way in
"""

import json
import logging
import re
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from .guardrails_input import redact_phi, _redact_json_obj

log = logging.getLogger("klaravex.guardrails.output")

# ── Destructive-action patterns ───────────────────────────────────────────────

_DESTRUCTIVE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\brm\s+-[rRfF]{1,4}\b", re.IGNORECASE), "shell rm -rf"),
    (re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE), "SQL DROP TABLE"),
    (re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE), "SQL DELETE FROM"),
    (re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE), "SQL TRUNCATE TABLE"),
    (re.compile(r"\bDROP\s+DATABASE\b", re.IGNORECASE), "SQL DROP DATABASE"),
    (re.compile(r"mkfs\b", re.IGNORECASE), "shell mkfs"),
    (re.compile(r"\bdd\s+if=", re.IGNORECASE), "shell dd"),
    (re.compile(r"\bchmod\s+777\b"), "shell chmod 777"),
    (re.compile(r"passwd\s+--delete\b", re.IGNORECASE), "credential-reset passwd"),
    (re.compile(r"net\s+user\b.*/delete\b", re.IGNORECASE), "Windows net user /delete"),
    (re.compile(r"\bufw\s+(disable|delete)\b", re.IGNORECASE), "firewall ufw disable/delete"),
    (re.compile(r"\biptables\s+-F\b"), "firewall iptables -F"),
]

_DESTRUCTIVE_WARNING = (
    "[KLARAVEX-GUARDRAIL] Potentially destructive instruction detected and removed. "
    "Please contact support@klaravex.com to proceed with human oversight."
)


def _contains_destructive(text: str) -> str | None:
    """Return the label of the first matched destructive pattern, or None."""
    for pattern, label in _DESTRUCTIVE_PATTERNS:
        if pattern.search(text):
            return label
    return None


def _strip_destructive(text: str) -> tuple[str, list[str]]:
    """Replace destructive patterns with a warning. Returns (cleaned_text, [labels])."""
    found: list[str] = []
    for pattern, label in _DESTRUCTIVE_PATTERNS:
        new_text, n = pattern.subn(_DESTRUCTIVE_WARNING, text)
        if n:
            found.append(label)
            text = new_text
    return text, found


def redact_output(text: str) -> str:
    """Apply PHI redaction + destructive-action filter to *text*.

    Returns the cleaned string. Logs a warning if destructive patterns were
    stripped.

    >>> redact_output("Your email foo@bar.com was found")
    'Your email [EMAIL] was found'
    >>> "GUARDRAIL" in redact_output("run rm -rf /")
    True
    """
    text = redact_phi(text)
    text, labels = _strip_destructive(text)
    if labels:
        log.warning("OutputGuardrailMiddleware: destructive patterns stripped: %s", labels)
    return text


def _redact_output_obj(obj: object) -> object:
    """Recursively apply redact_output to all string values in a JSON structure."""
    if isinstance(obj, str):
        return redact_output(obj)
    if isinstance(obj, dict):
        return {k: _redact_output_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_output_obj(item) for item in obj]
    return obj


class OutputGuardrailMiddleware(BaseHTTPMiddleware):
    """Starlette/FastAPI middleware that redacts PII/PHI and strips destructive
    instructions from every JSON response body.

    - Only modifies responses with ``Content-Type: application/json``.
    - Non-JSON responses (TwiML, HTML, binary) are passed through untouched.
    - Updates ``Content-Length`` header to match the rewritten body.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        try:
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk if isinstance(chunk, bytes) else chunk.encode()

            parsed = json.loads(body_bytes)
            cleaned = _redact_output_obj(parsed)
            new_body = json.dumps(cleaned).encode()

            new_headers = dict(response.headers)
            new_headers["content-length"] = str(len(new_body))

            return Response(
                content=new_body,
                status_code=response.status_code,
                headers=new_headers,
                media_type="application/json",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("OutputGuardrailMiddleware: body rewrite failed, passing through: %s", exc)
            return response
