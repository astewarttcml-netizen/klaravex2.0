"""G34.4 tests — RemoteSession is wired to the transport factory.

These tests guard the integration seam between session.py and factory.py:

    - __post_init__ chooses the stub by default (no env, no opt-in).
    - SessionManager.start_remote() without prefer_shim keeps the stub
      and refreshes selection (audit-visible no-op for stub-stub).
    - SessionManager.start_remote(prefer_shim=False) is a stub no-op.
    - attach_transport() swaps the transport AND emits an audit row.

We deliberately do NOT spawn the real klx-rdshim binary here; the
spawn path is covered by test_factory.py. This file's job is to prove
the SEAM is reachable, not to retest the factory's plumbing.

Run: `python3 -m pytest infra/rustdesk_controller/tests/test_session_factory_wiring.py -q`
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra"))

from rustdesk_controller import factory, protocol, session  # noqa: E402


# ── __post_init__ chooses stub by default ──────────────────────────────────


def test_remote_session_defaults_to_stub_transport(monkeypatch):
    """No env opt-in -> stub transport, kind=='stub', binary is None."""
    monkeypatch.delenv(factory.SHIM_ENV_VAR, raising=False)
    mgr = session.SessionManager()
    sess = mgr.create_session(
        customer_email="cust@example.com",
        customer_region="us",
        goal="fix wifi",
    )
    assert sess.transport_selection.kind == "stub"
    assert sess.transport_selection.binary is None
    assert isinstance(sess.transport, protocol.RustDeskClient)


def test_remote_session_post_init_does_not_consult_env(monkeypatch):
    """Even with $KLX_RDSHIM_BIN set, __post_init__ stays sync + stub.

    The shim path is async (spawns subprocess); G34.4 reserves that for
    SessionManager.start_remote(). __post_init__ MUST stay synchronous
    so RemoteSession() remains a normal dataclass constructor.
    """
    monkeypatch.setenv(factory.SHIM_ENV_VAR, "/nonexistent/klx-rdshim")
    mgr = session.SessionManager()
    sess = mgr.create_session(
        customer_email="cust@example.com",
        customer_region="us",
        goal="fix wifi",
    )
    assert sess.transport_selection.kind == "stub", (
        "__post_init__ must not spawn the shim — that's start_remote's job"
    )


# ── attach_transport swaps + audits ────────────────────────────────────────


def test_attach_transport_swaps_transport_and_audits(monkeypatch):
    monkeypatch.delenv(factory.SHIM_ENV_VAR, raising=False)
    mgr = session.SessionManager()
    sess = mgr.create_session(
        customer_email="cust@example.com",
        customer_region="us",
        goal="fix wifi",
    )
    prior_transport = sess.transport

    # Build a fake shim transport — any object that satisfies the
    # RustDeskTransport protocol surface is fine for the swap.
    class _FakeShim:
        async def connect(self, cfg): ...
        async def frames(self): ...
        async def send_event(self, event): ...
        async def close(self): ...

    fake = _FakeShim()
    new_sel = factory.TransportSelection(
        kind="shim", reason="test swap", binary="/fake/klx-rdshim",
    )

    audit_len_before = len(sess.audit.entries)
    sess.attach_transport(fake, new_sel)
    audit_after = list(sess.audit.entries)

    assert sess.transport is fake
    assert sess.transport is not prior_transport
    assert sess.transport_selection.kind == "shim"
    assert sess.transport_selection.binary == "/fake/klx-rdshim"

    # Newest audit entry is the transport_attached event.
    new_rows = audit_after[audit_len_before:]
    assert len(new_rows) == 1
    row = new_rows[0]
    assert row.event_type == "transport_attached"
    assert row.payload["kind"] == "shim"
    assert row.payload["prior"] == "stub"
    assert sess.audit.verify(), "hash chain must remain intact after attach"


# ── SessionManager.start_remote ─────────────────────────────────────────────


def test_start_remote_with_prefer_shim_false_is_stub_noop(monkeypatch):
    """prefer_shim=False keeps the stub already wired in __post_init__."""
    monkeypatch.delenv(factory.SHIM_ENV_VAR, raising=False)
    mgr = session.SessionManager()
    sess = mgr.create_session(
        customer_email="cust@example.com",
        customer_region="us",
        goal="fix wifi",
    )
    prior_transport = sess.transport

    selection = asyncio.run(mgr.start_remote(sess, prefer_shim=False))

    assert selection.kind == "stub"
    # Stub-to-stub: the transport object is allowed to be replaced (the
    # factory always returns a fresh one) but selection must reflect it.
    assert sess.transport_selection.kind == "stub"
    # The audit log should NOT have a transport_attached event for the
    # stub-stub path — attach_transport is only called on a real swap.
    rows = list(sess.audit.entries)
    assert not any(r.event_type == "transport_attached" for r in rows), (
        "stub-to-stub start_remote must not emit transport_attached"
    )


def test_start_remote_without_env_defaults_to_stub(monkeypatch):
    """prefer_shim=None + no env var -> stub branch."""
    monkeypatch.delenv(factory.SHIM_ENV_VAR, raising=False)
    mgr = session.SessionManager()
    sess = mgr.create_session(
        customer_email="cust@example.com",
        customer_region="us",
        goal="fix wifi",
    )
    selection = asyncio.run(mgr.start_remote(sess))
    assert selection.kind == "stub"
    assert sess.transport_selection.kind == "stub"


def test_start_remote_propagates_shim_spawn_failure(monkeypatch):
    """prefer_shim=True with a missing binary raises FileNotFoundError.

    This guards the loud-fail contract: silent fallback to the stub on
    a misconfigured production env is the wrong default.
    """
    monkeypatch.delenv(factory.SHIM_ENV_VAR, raising=False)
    mgr = session.SessionManager()
    sess = mgr.create_session(
        customer_email="cust@example.com",
        customer_region="us",
        goal="fix wifi",
    )
    with pytest.raises(FileNotFoundError):
        asyncio.run(
            mgr.start_remote(
                sess,
                prefer_shim=True,
                binary="/definitely/does/not/exist/klx-rdshim",
            )
        )
