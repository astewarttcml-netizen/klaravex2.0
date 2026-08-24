"""Regression tests for email_agent.py auto-reply guards.

Locks in the 2026-06-10 fix: the agent must NEVER auto-reply to banks,
card issuers, payment processors, transactional local-parts, or
transactional subject lines. Auto-replying to a credit card company
asks them to pay us $79 for a fix — looks like a scam, burns merchant
trust, and triggers compliance complaints.

Run: pytest infra/klara.handlers/tests/test_email_agent_guards.py -v
Or:  python -m unittest infra.klara.handlers.tests.test_email_agent_guards
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Make `infra` importable when this file is run directly.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from infra.klara.handlers.agents.email_agent import (
    _is_internal_sender,
    _is_financial_sender,
    _is_transactional_sender,
    _is_transactional_subject,
    _should_skip_autoreply,
)


class TestInternalSender(unittest.TestCase):
    def test_klaravex_addresses_are_internal(self):
        for addr in (
            "astewart@klaravex.com",
            "support@klaravex.com",
            "ops@klaravex.eu",
            "ANYTHING@klaravex.io",
        ):
            self.assertTrue(_is_internal_sender(addr), addr)

    def test_noreply_patterns(self):
        for addr in (
            "noreply@example.com",
            "no-reply@example.com",
            "do-not-reply@example.com",
            "mailer-daemon@example.com",
            "postmaster@example.com",
            "bounce-notification@example.com",
        ):
            self.assertTrue(_is_internal_sender(addr), addr)

    def test_real_consumer_not_internal(self):
        for addr in (
            "anthony@gmail.com",
            "marie.dupont@outlook.com",
            "joe.smith@yahoo.de",
        ):
            self.assertFalse(_is_internal_sender(addr), addr)


class TestFinancialSender(unittest.TestCase):
    def test_us_card_issuers(self):
        for addr in (
            "billing@chase.com",
            "service@amex.com",
            "alerts@discover.com",
            "statements@capitalone.com",
            "alerts@notifications.chase.com",     # subdomain
            "fraud@alerts.americanexpress.com",   # subdomain
            "customerservice@wellsfargo.com",
            "support@bofa.com",
        ):
            self.assertTrue(_is_financial_sender(addr), addr)

    def test_payment_processors_and_fintech(self):
        for addr in (
            "merchantservices@stripe.com",
            "support@mercury.com",
            "alerts@brex.com",
            "billing@ramp.com",
            "service@paypal.com",
            "alerts@squareup.com",
        ):
            self.assertTrue(_is_financial_sender(addr), addr)

    def test_eu_banks(self):
        for addr in (
            "service@deutsche-bank.de",
            "alerts@n26.com",
            "noreply@revolut.com",
            "support@wise.com",
        ):
            self.assertTrue(_is_financial_sender(addr), addr)

    def test_non_financial(self):
        for addr in (
            "anthony@gmail.com",
            "marie@outlook.com",
            "client@somecompany.com",
        ):
            self.assertFalse(_is_financial_sender(addr), addr)


class TestTransactionalSender(unittest.TestCase):
    def test_known_local_parts(self):
        for addr in (
            "billing@randomvendor.com",
            "statements@somebank.org",
            "alerts@saaspay.io",
            "merchantservices@payments.example.com",
            "fraud@alerts.example.com",
            "disputes@example.com",
            "cardservices@example.com",
            "receipt@example.com",
            "invoice@example.com",
            "no_reply@example.com",
            "donotreply@example.com",
        ):
            self.assertTrue(_is_transactional_sender(addr), addr)

    def test_with_separators(self):
        for addr in (
            "billing.no-reply@example.com",
            "statements-alerts@example.com",
            "fraud_alerts@example.com",
            "merchant-services@example.com",
        ):
            self.assertTrue(_is_transactional_sender(addr), addr)

    def test_real_addresses_not_flagged(self):
        for addr in (
            "anthony@gmail.com",
            "billy.statements@personal.com",  # name 'billy' starts with 'bill' but not 'billing'
            "alex.merchant@personal.com",     # name 'alex' is fine; full local 'alex.merchant'
        ):
            # NOTE: 'billy.statements' would NOT match because we require 'billing.', 'billing-', etc.
            # and 'alex.merchant' would NOT match because 'merchant' isn't in our list (only
            # 'merchantservices' / 'merchant-services').
            self.assertFalse(_is_transactional_sender(addr), addr)


class TestTransactionalSubject(unittest.TestCase):
    def test_known_subjects(self):
        for subject in (
            "Your statement is ready",
            "Fraud alert on your account",
            "Transaction notification — Visa ending in 1234",
            "Your balance is below $100",
            "Payment received: thank you",
            "Verify your account",
            "Your invoice from Acme Corp",
            "Auto-renewal confirmation",
        ):
            self.assertTrue(_is_transactional_subject(subject), subject)

    def test_real_consumer_subjects_not_flagged(self):
        for subject in (
            "my printer is broken",
            "wifi not working",
            "need help with email setup",
            "is the office open Monday",
        ):
            self.assertFalse(_is_transactional_subject(subject), subject)


class TestShouldSkipAutoreply(unittest.TestCase):
    """The composed gate used by the process loop."""

    def test_skip_real_world_credit_card_emails(self):
        """The actual scenarios Anthony reported on 2026-06-10."""
        cases = [
            ("billing@chase.com", "Your statement is ready"),
            ("service@amex.com", "Account alert"),
            ("alerts@discover.com", "Transaction notification"),
            ("merchantservices@stripe.com", "Payment received"),
            ("noreply@mercury.com", "Card alert: $1,234.56 at AMAZON.COM"),
            ("statements@capitalone.com", "Your June statement"),
        ]
        for from_addr, subject in cases:
            skip, reason = _should_skip_autoreply(from_addr, subject)
            self.assertTrue(skip, f"{from_addr} | {subject} → reason={reason}")
            self.assertNotEqual(reason, "", f"{from_addr}: skip=True but no reason")

    def test_allow_real_consumer_support(self):
        cases = [
            ("anthony.smith@gmail.com", "my printer is broken"),
            ("marie@outlook.com", "wifi not working"),
            ("client@somecompany.com", "need help with M365 migration"),
        ]
        for from_addr, subject in cases:
            skip, reason = _should_skip_autoreply(from_addr, subject)
            self.assertFalse(skip, f"{from_addr} | {subject} → skipped with reason={reason}")

    def test_safe_when_subject_is_transactional_even_from_consumer_domain(self):
        """A consumer Gmail address with subject 'Your invoice from X' is most
        likely a forwarded vendor email — still skip to be safe."""
        skip, reason = _should_skip_autoreply(
            "anthony@gmail.com", "Your invoice from Acme Corp"
        )
        self.assertTrue(skip)
        self.assertEqual(reason, "transactional_subject")


if __name__ == "__main__":
    unittest.main(verbosity=2)
