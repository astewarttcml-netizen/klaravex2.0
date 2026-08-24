"""OpenClaw HTTP client seam for EngineerAgent.

Extracts the wire-level concerns (httpx instantiation, timeout, error mapping)
out of EngineerAgent._call_openclaw so:

  (a) Tests inject a fake implementing the OpenClawClient Protocol instead of
      patching `infra.klara.handlers.engineers.base.httpx.AsyncClient` — closes
      the test-to-module coupling flagged by architecture-strategist review
      review-20260618T175105Z-2 (Medium [3]).
  (b) The four distinct failure modes the upstream OpenClaw service can produce
      (transport down, timeout, non-2xx response, malformed JSON body) map to
      four distinct exception types so downstream consumers — retry supervisors,
      dashboards, alert pipelines — can branch on the failure class. Closes
      review-20260618T175105Z-2 (High [2]).

This is a sibling module to base.py: the consumer imports the Protocol +
exceptions; production wiring uses HttpxOpenClawClient as the default.
"""

from typing import Any, Protocol

import httpx


class OpenClawError(Exception):
    """Base class for all OpenClaw client failures."""


class OpenClawTransportError(OpenClawError):
    """The HTTP request never reached a response — DNS, refused, reset, etc."""


class OpenClawTimeoutError(OpenClawError):
    """The request was sent but no response arrived within the configured deadline."""


class OpenClawHTTPError(OpenClawError):
    """OpenClaw returned a non-2xx response."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class OpenClawDecodeError(OpenClawError):
    """The response body was not valid JSON."""


class OpenClawClient(Protocol):
    """Wire seam between EngineerAgent and the OpenClaw HTTP service.

    Implementations MUST raise one of the OpenClaw* exception types above for
    every failure mode — never leak the underlying transport's exceptions.
    """

    async def reason(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class HttpxOpenClawClient:
    """Default production implementation backed by httpx.AsyncClient."""

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def reason(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._base_url}/v1/reason",
                    json=payload,
                    timeout=self._timeout,
                )
        except httpx.TimeoutException as exc:
            raise OpenClawTimeoutError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise OpenClawTransportError(str(exc)) from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise OpenClawHTTPError(str(exc), status_code=exc.response.status_code) from exc

        try:
            return response.json()
        except ValueError as exc:
            raise OpenClawDecodeError(str(exc)) from exc
