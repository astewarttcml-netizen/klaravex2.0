"""Tests for Phase 12 V7 — B2B lead pre-brief dispatcher.

Coverage:
  - _lead_to_ticket: combined keyword payload, company field, stub fields
  - _top_engineers: top-N selection by score, fallback when no match
  - _engineer_brief: success path, exception → graceful markdown section
  - dispatch_lead_pre_brief: email built with lead data, DB status updated
    to awaiting_approval; failure path sets status=skipped
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infra.klara.handlers.vapi.pre_brief import (
    _engineer_brief,
    _lead_to_ticket,
    _top_engineers,
    dispatch_lead_pre_brief,
)


# ── _lead_to_ticket ───────────────────────────────────────────────────────────

class TestLeadToTicket(unittest.TestCase):
    def test_combines_pain_current_urgency_into_keywords(self):
        lead = {
            "company": "Acme Corp",
            "pain_points": "ransomware hit last year",
            "current_it_setup": "on-prem Windows Server 2012",
            "urgency": "need audit by Q3",
        }
        ticket = _lead_to_ticket(lead)
        assert "ransomware" in ticket["keywords"]
        assert "Windows Server 2012" in ticket["keywords"]
        assert "audit" in ticket["keywords"]
        assert ticket["keywords"] == ticket["summary"]

    def test_subject_includes_company(self):
        ticket = _lead_to_ticket({"company": "Globex"})
        assert "Globex" in ticket["subject"]

    def test_missing_fields_produce_valid_ticket(self):
        ticket = _lead_to_ticket({})
        assert isinstance(ticket["keywords"], str)
        assert ticket["sku"] == ""
        assert ticket["archetype"] == "b2b_intake"

    def test_none_values_not_included_in_keywords(self):
        lead = {"pain_points": None, "current_it_setup": None, "urgency": None}
        ticket = _lead_to_ticket(lead)
        assert ticket["keywords"] == ""

    def test_partial_fields(self):
        lead = {"pain_points": "HIPAA compliance gap", "company": "HealthCo"}
        ticket = _lead_to_ticket(lead)
        assert "HIPAA" in ticket["keywords"]
        assert "HealthCo" in ticket["subject"]


# ── _top_engineers ────────────────────────────────────────────────────────────

class TestTopEngineers(unittest.TestCase):
    def test_returns_list_length_at_most_n(self):
        ticket = _lead_to_ticket({"pain_points": "HIPAA SOC 2 audit compliance"})
        result = _top_engineers(ticket, n=2)
        assert len(result) <= 2

    def test_fallback_to_strategic_advisory_on_no_match(self):
        # Use empty string so combined keyword string is also empty.
        # With no keywords, every engineer scores 0 and the fallback kicks in.
        # Check by class name rather than isinstance to avoid import-path duality
        # (mistake-34: pre_brief uses relative import; test uses absolute import).
        ticket = {"subject": "", "summary": "", "sku": "", "keywords": "", "archetype": "b2b_intake"}
        result = _top_engineers(ticket, n=2)
        assert len(result) >= 1
        assert any(type(e).__name__ == "StrategicAdvisoryEngineer" for e in result)

    def test_security_keywords_surface_managed_security(self):
        ticket = _lead_to_ticket({
            "pain_points": "EDR firewall security monitoring managed security"
        })
        result = _top_engineers(ticket, n=2)
        assert any(type(e).__name__ == "ManagedSecurityEngineer" for e in result)

    def test_compliance_keywords_surface_regulatory(self):
        ticket = _lead_to_ticket({
            "pain_points": "HIPAA SOC 2 compliance audit regulatory readiness"
        })
        result = _top_engineers(ticket, n=2)
        assert any(type(e).__name__ == "RegulatoryReadinessEngineer" for e in result)


# ── _engineer_brief ───────────────────────────────────────────────────────────

class TestEngineerBrief(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_success_returns_markdown_with_display_name(self):
        eng = MagicMock()
        eng.display_name = "Managed Security"
        eng.name = "managed_security"
        eng.reason_about_ticket = AsyncMock(return_value={
            "title": "Security Brief",
            "body_markdown": "EDR coverage recommended.",
        })
        result = self._run(_engineer_brief(eng, {"subject": "test", "summary": ""}))
        assert "Managed Security" in result
        assert "Security Brief" in result
        assert "EDR coverage" in result

    def test_exception_returns_graceful_section(self):
        eng = MagicMock()
        eng.display_name = "AI Adoption"
        eng.name = "ai_adoption"
        eng.reason_about_ticket = AsyncMock(side_effect=RuntimeError("OpenClaw timeout"))
        result = self._run(_engineer_brief(eng, {"subject": "test", "summary": ""}))
        assert "AI Adoption" in result
        assert "unavailable" in result
        assert "RuntimeError" in result

    def test_body_fallback_from_body_key(self):
        eng = MagicMock()
        eng.display_name = "Infrastructure"
        eng.name = "infrastructure"
        eng.reason_about_ticket = AsyncMock(return_value={
            "title": "Infra Brief",
            "body": "Server migration plan.",
        })
        result = self._run(_engineer_brief(eng, {}))
        assert "Server migration plan" in result


# ── dispatch_lead_pre_brief ───────────────────────────────────────────────────

SAMPLE_LEAD = {
    "company": "Acme Corp",
    "caller_name": "Jane Smith",
    "seat_count": 45,
    "pain_points": "ransomware + HIPAA compliance",
    "current_it_setup": "on-prem Windows Server",
    "urgency": "Q3 audit",
    "phone": "+15551234567",
    "email": "jane@acme.com",
}


class TestDispatchLeadPreBrief(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def _fake_engineer(self, name: str, display: str, brief_text: str, score: int = 5):
        eng = MagicMock()
        eng.name = name
        eng.display_name = display
        eng.reason_about_ticket = AsyncMock(return_value={
            "title": f"{display} Analysis",
            "body_markdown": brief_text,
        })
        eng.matches_ticket = MagicMock(return_value=score)
        return eng

    @patch("infra.klara.handlers.vapi.pre_brief.ENGINEERS")
    @patch("infra.klara.handlers.vapi.pre_brief._set_status", new_callable=AsyncMock)
    @patch("infra.klara.handlers.vapi.pre_brief.send_email", new_callable=AsyncMock)
    def test_email_contains_company_and_briefs(self, mock_send, mock_set_status, mock_engineers):
        eng1 = self._fake_engineer("managed_security", "Managed Security", "EDR recommended.")
        eng2 = self._fake_engineer("regulatory", "Regulatory Readiness", "HIPAA gap analysis.")
        mock_engineers.__iter__ = MagicMock(return_value=iter([eng1, eng2]))

        self._run(dispatch_lead_pre_brief("lead-abc-123", SAMPLE_LEAD))

        mock_send.assert_awaited_once()
        call_kwargs = mock_send.call_args
        subject = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("subject", "")
        body = call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs.get("body", "")
        # Accept both positional and keyword
        all_args = " ".join(str(a) for a in call_kwargs.args) + " ".join(str(v) for v in call_kwargs.kwargs.values())
        assert "Acme Corp" in all_args
        assert "Pre-Brief" in all_args

    @patch("infra.klara.handlers.vapi.pre_brief.ENGINEERS")
    @patch("infra.klara.handlers.vapi.pre_brief._set_status", new_callable=AsyncMock)
    @patch("infra.klara.handlers.vapi.pre_brief.send_email", new_callable=AsyncMock)
    def test_status_set_to_awaiting_approval_on_success(self, mock_send, mock_set_status, mock_engineers):
        eng = self._fake_engineer("managed_security", "Managed Security", "EDR plan.")
        mock_engineers.__iter__ = MagicMock(return_value=iter([eng]))

        self._run(dispatch_lead_pre_brief("lead-xyz", SAMPLE_LEAD))

        status_calls = [c.args[1] for c in mock_set_status.await_args_list]
        assert "drafting" in status_calls
        assert "awaiting_approval" in status_calls

    @patch("infra.klara.handlers.vapi.pre_brief.ENGINEERS")
    @patch("infra.klara.handlers.vapi.pre_brief._set_status", new_callable=AsyncMock)
    @patch("infra.klara.handlers.vapi.pre_brief.send_email", new_callable=AsyncMock)
    def test_failure_path_sets_status_skipped(self, mock_send, mock_set_status, mock_engineers):
        eng = self._fake_engineer("managed_security", "Managed Security", "Brief.", score=5)
        mock_engineers.__iter__ = MagicMock(return_value=iter([eng]))
        mock_send.side_effect = RuntimeError("SMTP down")

        self._run(dispatch_lead_pre_brief("lead-fail-99", SAMPLE_LEAD))

        status_calls = [c.args[1] for c in mock_set_status.await_args_list]
        assert "skipped" in status_calls

    @patch("infra.klara.handlers.vapi.pre_brief.ENGINEERS")
    @patch("infra.klara.handlers.vapi.pre_brief._set_status", new_callable=AsyncMock)
    @patch("infra.klara.handlers.vapi.pre_brief.send_email", new_callable=AsyncMock)
    def test_lead_id_appears_in_email(self, mock_send, mock_set_status, mock_engineers):
        eng = self._fake_engineer("infra", "Infrastructure", "Server plan.")
        mock_engineers.__iter__ = MagicMock(return_value=iter([eng]))

        self._run(dispatch_lead_pre_brief("lead-id-42", SAMPLE_LEAD))

        all_call_str = str(mock_send.call_args)
        assert "lead-id-42" in all_call_str
