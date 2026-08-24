"""
app/services/circuit_breaker.py
────────────────────────────────
phase12-005 — Circuit breaker for external APIs.

Standard three-state breaker:
  closed     — requests pass through
  open       — requests fail fast (no actual call)
  half_open  — single test request allowed; success → closed, failure → open

State is per-named-circuit (one breaker per service: resend, anthropic,
stripe, calendly). State lives in process memory — short-lived enough for
a daemonised api/worker process, restart-resilient via /status endpoint.

Usage:
    from klara.rarv.runtime.circuit_breaker import get_breaker, CircuitOpenError
    breaker = get_breaker("resend")
    try:
        result = await breaker.call(lambda: send_via_resend(...))
    except CircuitOpenError:
        ...handle degraded path...
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Dict, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class State(str, Enum):
    closed = "closed"
    open = "open"
    half_open = "half_open"


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is open."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Circuit '{name}' is open")


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5      # consecutive failures to open
    reset_timeout_s: float = 60.0   # seconds before half_open probe
    state: State = State.closed
    consecutive_failures: int = 0
    opened_at: float = 0.0          # monotonic timestamp

    def _now(self) -> float:
        return time.monotonic()

    def can_attempt(self) -> bool:
        """Return True if a call may proceed (or probe in half_open)."""
        if self.state == State.closed:
            return True
        if self.state == State.open:
            if self._now() - self.opened_at >= self.reset_timeout_s:
                self.state = State.half_open
                logger.info("circuit_breaker.half_open", name=self.name)
                return True
            return False
        return True   # half_open allows the single probe

    def record_success(self) -> None:
        if self.state in (State.open, State.half_open):
            logger.info("circuit_breaker.closed", name=self.name)
        self.state = State.closed
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.state == State.half_open:
            self.state = State.open
            self.opened_at = self._now()
            logger.warning("circuit_breaker.reopened", name=self.name)
            return
        if self.consecutive_failures >= self.failure_threshold:
            self.state = State.open
            self.opened_at = self._now()
            logger.warning(
                "circuit_breaker.opened",
                name=self.name,
                consecutive_failures=self.consecutive_failures,
            )

    async def call(self, func: Callable[[], Awaitable[T]]) -> T:
        if not self.can_attempt():
            raise CircuitOpenError(self.name)
        try:
            result = await func()
        except Exception:
            self.record_failure()
            raise
        else:
            self.record_success()
            return result


# Process-wide registry of named breakers
_BREAKERS: Dict[str, CircuitBreaker] = {}


def get_breaker(name: str) -> CircuitBreaker:
    if name not in _BREAKERS:
        _BREAKERS[name] = CircuitBreaker(name=name)
    return _BREAKERS[name]


def reset_breaker(name: str) -> None:
    """Force a breaker back to closed. Useful for tests."""
    if name in _BREAKERS:
        _BREAKERS[name] = CircuitBreaker(name=name)


def all_breaker_states() -> dict[str, dict]:
    """Snapshot of every named breaker — used by /status and Ops dashboard."""
    return {
        name: {
            "state": b.state.value,
            "consecutive_failures": b.consecutive_failures,
            "opened_at_monotonic": b.opened_at,
        }
        for name, b in _BREAKERS.items()
    }
