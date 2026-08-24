"""Regression tests for dunning._send_resend_email.

Lock the semantics called out in iter-6 code_review (Critical finding):
  - Function name still says "resend" but transport is M365 Graph.
  - send_email() swallows Graph failures internally, so this wrapper
    returns True on the happy path. Any caller that treats True as
    "delivery confirmed" is wrong — the docstring warns of this.
  - Only path returning False is an unexpected exception from send_email
    itself (e.g. attribute error, cancellation).

These tests exist to make any future change to that contract fail loudly
so callers get audited before behavior shifts under them.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

INFRA = Path(__file__).resolve().parents[3] / "infra"
sys.path.insert(0, str(INFRA))

pytest.importorskip("asyncpg")

from klara.handlers.dunning import _send_resend_email  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class TestSendResendEmail:
    def test_returns_true_when_send_email_returns_normally(self):
        async def fake_send(*, to, subject, body):
            return None

        with patch("klara.handlers.dunning.send_email", side_effect=fake_send):
            ok = _run(_send_resend_email("a@b.com", "s", "b"))
        assert ok is True

    def test_returns_false_when_send_email_raises(self):
        async def fake_send(*, to, subject, body):
            raise RuntimeError("graph token expired")

        with patch("klara.handlers.dunning.send_email", side_effect=fake_send):
            ok = _run(_send_resend_email("a@b.com", "s", "b"))
        assert ok is False

    def test_forwards_to_send_email_with_kwargs(self):
        captured: dict = {}

        async def fake_send(*, to, subject, body):
            captured["to"] = to
            captured["subject"] = subject
            captured["body"] = body

        with patch("klara.handlers.dunning.send_email", side_effect=fake_send):
            _run(_send_resend_email("client@example.com", "Past due", "Payment failed."))
        assert captured == {
            "to": "client@example.com",
            "subject": "Past due",
            "body": "Payment failed.",
        }
