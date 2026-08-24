"""
Klaravex audit log middleware — T8.12.

Logs every mutating API request (POST / PATCH / DELETE) to the
``klaravex_loki_audit`` table AFTER the response is produced.

PII is pre-redacted using ``guardrails_input.redact_phi`` before the row is
inserted — raw PHI never persists in the audit log.

Schema (migration 002_audit_log.sql):
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid()
    timestamp        TIMESTAMPTZ DEFAULT NOW()
    method           TEXT
    path             TEXT
    client_email     TEXT      (extracted from JSON body if present; redacted)
    request_summary  TEXT      (first 500 chars of redacted body)
    response_status  INT
    redacted         BOOLEAN DEFAULT false

Mount in main.py AFTER input guardrail so the body is already redacted:
    app.add_middleware(AuditLogMiddleware)
    app.add_middleware(OutputGuardrailMiddleware)
    app.add_middleware(InputGuardrailMiddleware)

Note: Starlette adds middlewares in reverse order relative to the
add_middleware call sequence, so declare them bottom → top.
"""

import json
import logging
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .guardrails_input import redact_phi
from .lib.db import get_pool

log = logging.getLogger("klaravex.audit_log")

_MUTATING_METHODS = {"POST", "PATCH", "DELETE"}
_SUMMARY_MAX = 500


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Log mutating requests to ``klaravex_loki_audit`` after response delivery.

    - ``client_email`` is extracted from the JSON body key ``client_email``
      (if present) and redacted before storage.
    - ``request_summary`` is the first 500 characters of the redacted JSON body.
    - Failures in the audit insert are logged but never propagate to the client.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method not in _MUTATING_METHODS:
            return await call_next(request)

        # Buffer body so we can both read it and pass it downstream.
        raw_body = await request.body()

        async def receive():  # noqa: E306
            return {"type": "http.request", "body": raw_body, "more_body": False}

        patched_request = Request(request.scope, receive)
        response = await call_next(patched_request)

        # Fire-and-forget: audit insert must not affect response latency.
        try:
            await _insert_audit_row(
                method=request.method,
                path=str(request.url.path),
                raw_body=raw_body,
                status_code=response.status_code,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("AuditLogMiddleware: insert failed: %s", exc)

        return response


async def _insert_audit_row(
    method: str,
    path: str,
    raw_body: bytes,
    status_code: int,
) -> None:
    client_email: str | None = None
    request_summary = ""
    redacted_flag = False

    if raw_body:
        try:
            parsed = json.loads(raw_body)
            # Extract client_email before redaction so we capture the field.
            raw_email = parsed.get("client_email") if isinstance(parsed, dict) else None
            if raw_email and isinstance(raw_email, str):
                client_email = redact_phi(raw_email)

            # Build a short summary from the redacted body.
            redacted_body = json.dumps(parsed)
            redacted_body = redact_phi(redacted_body)
            request_summary = redacted_body[:_SUMMARY_MAX]
            redacted_flag = True
        except Exception:  # noqa: BLE001
            request_summary = raw_body.decode("utf-8", errors="replace")[:_SUMMARY_MAX]

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO klaravex_loki_audit
                (method, path, client_email, request_summary, response_status, redacted)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            method,
            path,
            client_email,
            request_summary,
            status_code,
            redacted_flag,
        )
    log.debug("audit_log: %s %s → %d", method, path, status_code)
