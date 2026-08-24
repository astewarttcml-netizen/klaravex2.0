"""Regression tests for POST /api/v1/customer-helper/redeem/{token}.

Locks the production wire-in contract for G34.

Architecture: the handler depends on a `TokenStore` protocol via FastAPI
`Depends(get_token_store)`. Tests inject a `_FakeStore` returning the
exact `RedeemOutcome` the test wants — no monkeypatching of module
symbols required, so the iter-1 "import-path duality" hazard
(review-20260621T123417Z-1 Medium [5]) is no longer load-bearing here.

Contract:
- 200 + Session shape on success
- 410 on already-redeemed / expired tokens
- 402 on payment-not-confirmed tokens
- 404 on unknown tokens
- raw token NEVER appears in the response, NEVER appears in logs
- token length validated at the path layer (20..128 chars)
- note_submissions failure does not break the 200 response (best-effort)
"""
from __future__ import annotations

import datetime as dt
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

# Path A re-enabled with Sectigo + Apple signing (16.9 reopened)

from infra import main as main_module

# Import via the SAME path main.py uses (`klara.handlers.X`, not
# `infra.klara.handlers.X`). Until the package-layout duality flagged in
# review-20260621T123417Z-1 Medium [5] is properly resolved by fixing
# PYTHONPATH, the two paths are distinct sys.modules entries and
# `dependency_overrides[get_token_store]` only works when keyed by the
# function-identity main.py actually loaded.
import klara.handlers.customer_helper as ch  # noqa: E402, F401 — kept for logger fixture compat
from klara.handlers.customer_helper_schemas import Session  # noqa: E402
from klara.handlers.customer_helper_store import (  # noqa: E402
    AlreadyRedeemed,
    Expired,
    PaymentMissing,
    PgAuditLog,
    Redeemed,
    RedeemOutcome,
    Unknown,
    get_audit_log,
    get_token_store,
)

client = TestClient(main_module.app)


def _ok_session(**overrides) -> Session:
    base = {
        "customer_session_id": "123456789",
        "session_password": "pw-redacted-20chars",
        "expires_at": dt.datetime(2099, 1, 1, tzinfo=dt.timezone.utc).isoformat(),
        "display_topic": "printer trouble",
        "operator_label": "Klara (AI)",
    }
    base.update(overrides)
    return Session(**base)


class _FakeStore:
    """In-memory TokenStore for tests — returns whatever outcome was set."""

    def __init__(self, outcome: RedeemOutcome):
        self.outcome = outcome
        self.calls: list[bytes] = []

    async def try_redeem(self, token_sha: bytes) -> RedeemOutcome:
        self.calls.append(token_sha)
        return self.outcome


class _SpyAudit:
    """In-memory AuditLog for tests — records calls, never raises."""

    def __init__(self, *, raise_exc: Exception | None = None):
        self.calls: list[tuple[str, str]] = []
        self._raise = raise_exc

    async def record_redeem(self, token_h16: str, customer_session_id: str) -> None:
        self.calls.append((token_h16, customer_session_id))
        if self._raise is not None:
            raise self._raise


@pytest.fixture(autouse=True)
def _silent_audit() -> Iterator[_SpyAudit]:
    """Install a no-op AuditLog by default so no test accidentally writes
    to the live klaravex-db pool. Individual tests can override via
    `with_audit()` to inspect calls or simulate failures.
    """
    spy = _SpyAudit()
    main_module.app.dependency_overrides[get_audit_log] = lambda: spy
    yield spy
    main_module.app.dependency_overrides.pop(get_audit_log, None)


@pytest.fixture
def with_store() -> Iterator[callable]:
    """Yield a setter that installs a FakeStore for the next request.

    Cleans up `app.dependency_overrides` on test exit so tests don't leak.
    """

    def _install(outcome: RedeemOutcome) -> _FakeStore:
        store = _FakeStore(outcome)
        main_module.app.dependency_overrides[get_token_store] = lambda: store
        return store

    yield _install
    main_module.app.dependency_overrides.pop(get_token_store, None)


@pytest.fixture
def with_audit() -> Iterator[callable]:
    """Yield a setter that installs a custom AuditLog for the next request."""

    def _install(audit: _SpyAudit) -> _SpyAudit:
        main_module.app.dependency_overrides[get_audit_log] = lambda: audit
        return audit

    yield _install


def test_redeem_success_returns_session_shape(with_store):
    with_store(Redeemed(session=_ok_session()))
    token = "a" * 40
    r = client.post(f"/api/v1/customer-helper/redeem/{token}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {
        "customer_session_id",
        "session_password",
        "expires_at",
        "display_topic",
        "operator_label",
    }
    assert body["customer_session_id"] == "123456789"
    assert body["session_password"] == "pw-redacted-20chars"
    assert body["operator_label"] == "Klara (AI)"
    # Raw token must NOT echo back.
    assert token not in r.text


def test_redeem_operator_label_defaults_when_store_returns_klara(with_store):
    """The store's `_row_to_session` defaults NULL operator_label to
    'Klara (AI)' — verified at the store layer. Here we just confirm
    the handler doesn't override a present label."""
    with_store(Redeemed(session=_ok_session(operator_label="Klara (AI)")))
    r = client.post(f"/api/v1/customer-helper/redeem/{'b' * 32}")
    assert r.status_code == 200
    assert r.json()["operator_label"] == "Klara (AI)"


def test_redeem_unknown_token_returns_404(with_store):
    with_store(Unknown())
    r = client.post(f"/api/v1/customer-helper/redeem/{'c' * 32}")
    assert r.status_code == 404
    assert r.json() == {"detail": "unknown token"}


def test_redeem_already_redeemed_returns_410(with_store):
    with_store(AlreadyRedeemed())
    r = client.post(f"/api/v1/customer-helper/redeem/{'d' * 32}")
    assert r.status_code == 410
    assert "already redeemed" in r.json()["detail"]


def test_redeem_expired_returns_410(with_store):
    with_store(Expired())
    r = client.post(f"/api/v1/customer-helper/redeem/{'e' * 32}")
    assert r.status_code == 410
    assert r.json()["detail"] == "token expired"


def test_redeem_payment_not_confirmed_returns_402(with_store):
    with_store(PaymentMissing())
    r = client.post(f"/api/v1/customer-helper/redeem/{'f' * 32}")
    assert r.status_code == 402
    assert r.json()["detail"] == "payment not confirmed"


def test_redeem_rejects_too_short_token():
    # Path validation: min_length=20.
    r = client.post("/api/v1/customer-helper/redeem/short")
    assert r.status_code == 422


def test_redeem_rejects_too_long_token():
    r = client.post(f"/api/v1/customer-helper/redeem/{'g' * 129}")
    assert r.status_code == 422


def test_redeem_note_submission_swallows_pool_failure(
    with_store, with_audit, monkeypatch
):
    """Memory-policy write failure must NOT 5xx the customer.

    Drives the REAL `PgAuditLog.record_redeem` with a broken pool so the
    test locks the try/except guard inside the production implementation.
    """
    with_store(Redeemed(session=_ok_session()))

    async def _broken_pool():
        raise RuntimeError("simulated db outage")

    from klara.handlers.customer_helper_store import PgAuditLog as _PgAuditLog
    import klara.handlers.customer_helper_store as _store_mod

    # Inject the REAL PgAuditLog and break the pool underneath it so the
    # production try/except in PgAuditLog.record_redeem is exercised.
    monkeypatch.setattr(_store_mod, "get_pool", _broken_pool)
    with_audit(_PgAuditLog())  # type: ignore[arg-type]

    r = client.post(f"/api/v1/customer-helper/redeem/{'h' * 40}")
    assert r.status_code == 200, r.text


def test_redeem_emits_audit_row_with_token_hash_and_session_id(with_store, with_audit):
    """Lock the AuditLog call shape — handler passes token_h16 + session id."""
    import hashlib

    with_store(Redeemed(session=_ok_session()))
    spy = with_audit(_SpyAudit())
    token = "j" * 40
    expected_h16 = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]

    r = client.post(f"/api/v1/customer-helper/redeem/{token}")
    assert r.status_code == 200
    assert spy.calls == [(expected_h16, "123456789")]


def test_redeem_failure_outcomes_skip_audit(with_store, _silent_audit):
    """Audit row is only written on success — failure paths must not call it."""
    with_store(Unknown())
    r = client.post(f"/api/v1/customer-helper/redeem/{'k' * 40}")
    assert r.status_code == 404
    assert _silent_audit.calls == []


def test_redeem_logs_only_token_hash_prefix(with_store, caplog):
    import logging

    with_store(Redeemed(session=_ok_session()))
    token = "leak-me-if-you-dare-" + "x" * 24
    with caplog.at_level(logging.INFO, logger="klaravex.customer_helper"):
        r = client.post(f"/api/v1/customer-helper/redeem/{token}")
    assert r.status_code == 200
    # Raw token MUST NOT appear in any log message.
    for rec in caplog.records:
        assert token not in rec.getMessage(), (
            f"raw token leaked into log: {rec.getMessage()!r}"
        )


def test_redeem_passes_sha256_to_store(with_store):
    """Lock the contract that the store receives sha256(token), NOT raw."""
    import hashlib

    store = with_store(Redeemed(session=_ok_session()))
    token = "i" * 40
    expected = hashlib.sha256(token.encode("utf-8")).digest()
    r = client.post(f"/api/v1/customer-helper/redeem/{token}")
    assert r.status_code == 200
    assert store.calls == [expected]


def test_health_endpoint():
    r = client.get("/api/v1/customer-helper/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "handler": "customer_helper"}
