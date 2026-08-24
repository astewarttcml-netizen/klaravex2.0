"""Tests for EngineerAgent OpenClaw refactor.

Covers:
- pattern-34: prompt-rendering side never emits placeholder markers (every
  _*_prompt method on EngineerAgent — Mistake 30 / Pattern 34)
- prompt structural shape: bullets in _default_playbook_prompt are well-formed
- _call_openclaw: HTTP request shape + response parsing + structured error path
  (transport, timeout, http-status, decode each map to a distinct error_type
  in the fallback dict — closes review-20260618T175105Z-2 High [2])
- matches_ticket: producer/consumer seam reads 'keywords' as concrete-engineer
  scoring expects

The HTTP client is now injected via EngineerAgent(openclaw_client=...), so
tests no longer reach across the module boundary by patching
infra.klara.handlers.engineers.base.httpx.AsyncClient — that coupling was flagged
by review-20260618T175105Z-2 Medium [3].

Run: pytest infra/klara.handlers/tests/test_engineer_openclaw.py -v
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from infra.klara.handlers.engineers.base import EngineerAgent  # noqa: E402
from infra.klara.handlers.engineers.openclaw_client import (  # noqa: E402
    OpenClawDecodeError,
    OpenClawHTTPError,
    OpenClawTimeoutError,
    OpenClawTransportError,
)


class _ConcreteEngineer(EngineerAgent):
    name = "engineer_test"
    display_name = "Test Engineer"
    pillar = "test_pillar"
    system_prompt = "You are the Test Engineer."
    specialty_keywords = ["firewall", "VLAN", "EDR"]
    secondary_keywords = ["backup", "patch"]


class _FakeOpenClawClient:
    """Minimal Protocol-shaped fake. Records the last payload it was called with.

    response_data is returned from reason() unless raises is set, in which case
    raises is raised. This is the only seam EngineerAgent uses, so the fake
    surface stays at one method.
    """

    def __init__(
        self,
        *,
        response_data: Optional[dict[str, Any]] = None,
        raises: Optional[BaseException] = None,
    ) -> None:
        self.response_data = response_data if response_data is not None else {}
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    async def reason(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(payload)
        if self.raises is not None:
            raise self.raises
        return self.response_data


def _run(coro):
    return asyncio.run(coro)


def _make_ticket(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "TKT-001",
        "severity": "P2",
        "source": "email",
        "sku": "assurance",
        "subject": "Firewall rule audit",
        "summary": "Annual UniFi audit due.",
        "created_at": "2026-06-18T00:00:00Z",
        "keywords": "firewall VLAN audit",
    }
    base.update(overrides)
    return base


class TestPromptForbidsPlaceholders(unittest.TestCase):
    """Pattern-34: every _*_prompt method that emits a string destined for an
    LLM must not leak placeholder markers, and must include the schema
    substrings the downstream consumer expects."""

    FORBIDDEN_MARKERS = ("<<", "TODO", "FIXME", "XXX", "<placeholder>")

    def _assert_no_placeholder_markers(self, prompt: str, *, where: str) -> None:
        for marker in self.FORBIDDEN_MARKERS:
            self.assertNotIn(
                marker,
                prompt,
                msg=f"placeholder marker {marker!r} leaked into {where}",
            )

    def test_rendered_prompt_contains_no_placeholder_markers(self):
        prompt = _ConcreteEngineer()._build_ticket_prompt(_make_ticket())
        self._assert_no_placeholder_markers(prompt, where="ticket prompt")

    def test_rendered_prompt_includes_consumer_expected_schema_keys(self):
        prompt = _ConcreteEngineer()._build_ticket_prompt(_make_ticket())
        for key in ("action_type", "title", "body_markdown", "proposed_payload", "reasoning"):
            self.assertIn(key, prompt, msg=f"schema key {key!r} missing from prompt")

    def test_rendered_prompt_carries_ticket_identifying_fields(self):
        prompt = _ConcreteEngineer()._build_ticket_prompt(
            _make_ticket(id="TKT-XYZ", severity="P1", subject="DR failover")
        )
        self.assertIn("TKT-XYZ", prompt)
        self.assertIn("P1", prompt)
        self.assertIn("DR failover", prompt)

    def test_rendered_prompt_includes_system_prompt_at_top(self):
        prompt = _ConcreteEngineer()._build_ticket_prompt(_make_ticket())
        self.assertTrue(
            prompt.startswith("You are the Test Engineer."),
            msg="system prompt should be rendered at the top of the ticket prompt",
        )

    def test_gap_analysis_prompt_with_copy_has_no_placeholder_markers(self):
        prompt = _ConcreteEngineer()._gap_analysis_prompt(
            "We claim 24/7 SOC, EDR-managed endpoints, NIS2 readiness."
        )
        self._assert_no_placeholder_markers(prompt, where="gap_analysis prompt (with copy)")
        self.assertIn("Test Engineer", prompt)

    def test_gap_analysis_prompt_without_copy_has_no_placeholder_markers(self):
        prompt = _ConcreteEngineer()._gap_analysis_prompt("")
        self._assert_no_placeholder_markers(prompt, where="gap_analysis prompt (no copy)")
        self.assertIn("Test Engineer", prompt)

    def test_documentation_prompt_has_no_placeholder_markers(self):
        prompt = _ConcreteEngineer()._documentation_prompt(
            doc_target="UniFi firewall hardening runbook",
            gap_context="Current runbook stops at VLAN tagging.",
        )
        self._assert_no_placeholder_markers(prompt, where="documentation prompt")
        self.assertIn("UniFi firewall hardening runbook", prompt)

    def test_documentation_prompt_empty_gap_context_has_no_placeholder_markers(self):
        prompt = _ConcreteEngineer()._documentation_prompt(
            doc_target="HIPAA risk assessment template", gap_context=""
        )
        self._assert_no_placeholder_markers(prompt, where="documentation prompt (no gap)")

    def test_default_playbook_prompt_has_no_placeholder_markers(self):
        prompt = _ConcreteEngineer()._default_playbook_prompt()
        self._assert_no_placeholder_markers(prompt, where="default playbook prompt")
        self.assertIn("Test Engineer", prompt)


class TestPromptBulletFormatting(unittest.TestCase):
    """Structural shape of bulleted lists inside prompts.

    Separated from TestPromptForbidsPlaceholders because the invariants are
    different — placeholder-forbid is a negative assertion (no forbidden
    markers), bullet-formatting is a positive structural assertion. Co-locating
    them bled two invariants into one class's name (architecture-strategist
    review-20260618T175105Z-2 Medium [4])."""

    def test_default_playbook_prompt_bullets_are_well_formed(self):
        """Regression guard: line 156 of base.py previously shipped
        'Role-specific best practices' without the leading '- ' bullet, so an
        LLM would merge it into the previous list item rather than treat it as
        a third bullet. Lock the corrected shape."""
        prompt = _ConcreteEngineer()._default_playbook_prompt()
        for bullet in ("- Common scenarios", "- Step-by-step procedures", "- Role-specific best practices"):
            self.assertIn(bullet, prompt, msg=f"bullet {bullet!r} missing or malformed in playbook prompt")


class TestCallOpenclawRequestShape(unittest.TestCase):
    def test_payload_carries_engineer_prompt_system_prompt_fallback(self):
        fake = _FakeOpenClawClient(
            response_data={
                "action_type": "client_reply",
                "title": "Re: Firewall audit",
                "body_markdown": "Body",
                "proposed_payload": {"to": "a@example.com"},
                "reasoning": "Because.",
            }
        )
        eng = _ConcreteEngineer(openclaw_client=fake)
        result = _run(eng._call_openclaw("ANALYZE THIS", fallback_title="Fallback title"))

        self.assertEqual(len(fake.calls), 1)
        payload = fake.calls[0]
        self.assertEqual(payload["engineer"], "engineer_test")
        self.assertEqual(payload["prompt"], "ANALYZE THIS")
        self.assertEqual(payload["system_prompt"], "You are the Test Engineer.")
        self.assertEqual(payload["fallback_title"], "Fallback title")

        self.assertEqual(result["action_type"], "client_reply")
        self.assertEqual(result["title"], "Re: Firewall audit")
        self.assertEqual(result["body_markdown"], "Body")
        self.assertEqual(result["proposed_payload"], {"to": "a@example.com"})
        self.assertEqual(result["reasoning"], "Because.")
        self.assertNotIn("error_type", result)

    def test_missing_response_fields_fall_back_to_defaults(self):
        fake = _FakeOpenClawClient(response_data={})
        eng = _ConcreteEngineer(openclaw_client=fake)
        result = _run(eng._call_openclaw("p", fallback_title="FB"))

        self.assertEqual(result["action_type"], "investigation_plan")
        self.assertEqual(result["title"], "FB")
        self.assertEqual(result["body_markdown"], "")
        self.assertEqual(result["proposed_payload"], {})
        self.assertEqual(result["reasoning"], "")


class TestCallOpenclawErrorPath(unittest.TestCase):
    """Each failure mode the OpenClaw client raises MUST map to a distinct
    error_type in the fallback dict, so a retry supervisor / dashboard / alert
    pipeline can branch on the failure class. The pre-iter-3 behaviour
    collapsed all four into a single shape — review-20260618T175105Z-2
    High [2] flagged the lossy collapse."""

    def _call_with_error(self, exc: BaseException, fallback_title: str) -> dict[str, Any]:
        fake = _FakeOpenClawClient(raises=exc)
        eng = _ConcreteEngineer(openclaw_client=fake)
        return _run(eng._call_openclaw("p", fallback_title=fallback_title))

    def test_transport_error_maps_to_error_type_transport(self):
        result = self._call_with_error(
            OpenClawTransportError("connection refused"), "Fallback title"
        )
        self.assertEqual(result["action_type"], "investigation_plan")
        self.assertEqual(result["title"], "Fallback title")
        self.assertEqual(result["error_type"], "transport")
        self.assertEqual(result["proposed_payload"]["error_type"], "transport")
        self.assertIn("connection refused", result["body_markdown"])
        self.assertIn("connection refused", result["reasoning"])

    def test_timeout_error_maps_to_error_type_timeout(self):
        result = self._call_with_error(
            OpenClawTimeoutError("timed out after 30s"), "Timeout FB"
        )
        self.assertEqual(result["error_type"], "timeout")
        self.assertEqual(result["proposed_payload"]["error_type"], "timeout")
        self.assertEqual(result["title"], "Timeout FB")
        self.assertIn("timed out", result["body_markdown"])
        self.assertIn("timed out", result["reasoning"])

    def test_http_status_error_maps_to_error_type_http_status_with_status_code(self):
        result = self._call_with_error(
            OpenClawHTTPError("503 Service Unavailable", status_code=503), "503 FB"
        )
        self.assertEqual(result["error_type"], "http_status")
        self.assertEqual(result["proposed_payload"]["error_type"], "http_status")
        self.assertEqual(result["proposed_payload"]["error_status"], 503)
        self.assertEqual(result["title"], "503 FB")
        self.assertIn("503", result["body_markdown"])

    def test_decode_error_maps_to_error_type_decode(self):
        result = self._call_with_error(
            OpenClawDecodeError("Expecting value: line 1 column 1"), "JSON FB"
        )
        self.assertEqual(result["error_type"], "decode")
        self.assertEqual(result["proposed_payload"]["error_type"], "decode")
        self.assertEqual(result["title"], "JSON FB")
        self.assertIn("Expecting value", result["body_markdown"])

    def test_unexpected_exception_maps_to_error_type_unknown_without_propagating(self):
        """Defensive: if the injected client raises something outside the
        OpenClawError hierarchy (e.g. an implementation bug), _call_openclaw
        must still produce a fallback dict so the engineer reasoning loop
        stays non-fatal. error_type='unknown' tells the retry supervisor
        this branch needs investigation rather than auto-retry."""
        result = self._call_with_error(RuntimeError("unexpected bug"), "Bug FB")
        self.assertEqual(result["error_type"], "unknown")
        self.assertEqual(result["proposed_payload"]["error_type"], "unknown")
        self.assertEqual(result["title"], "Bug FB")
        self.assertIn("unexpected bug", result["body_markdown"])

    def test_error_type_classes_are_disjoint(self):
        """Pattern 12 / Pattern 13 generalisation: distinct failure modes MUST
        map to distinct error_type strings. If two branches collapse onto the
        same string a retry supervisor cannot tell them apart — that was the
        pre-iter-3 regression. Lock the set."""
        emitted = set()
        for exc in (
            OpenClawTransportError("a"),
            OpenClawTimeoutError("b"),
            OpenClawHTTPError("c", status_code=500),
            OpenClawDecodeError("d"),
            RuntimeError("e"),
        ):
            result = self._call_with_error(exc, "Disjoint FB")
            emitted.add(result["error_type"])
        self.assertEqual(
            emitted, {"transport", "timeout", "http_status", "decode", "unknown"}
        )


class TestMatchesTicketScoring(unittest.TestCase):
    """matches_ticket reads ticket['keywords'] — the producer/consumer seam
    after the iter-47 schema collapse. Lock the contract."""

    def test_specialty_match_scores_five_each(self):
        eng = _ConcreteEngineer()
        self.assertEqual(eng.matches_ticket({"keywords": "firewall"}), 5)
        self.assertEqual(eng.matches_ticket({"keywords": "firewall vlan"}), 10)
        self.assertEqual(eng.matches_ticket({"keywords": "firewall vlan edr"}), 15)

    def test_secondary_match_scores_one_each(self):
        eng = _ConcreteEngineer()
        self.assertEqual(eng.matches_ticket({"keywords": "backup"}), 1)
        self.assertEqual(eng.matches_ticket({"keywords": "backup patch"}), 2)

    def test_mixed_scoring_combines_specialty_and_secondary(self):
        eng = _ConcreteEngineer()
        self.assertEqual(eng.matches_ticket({"keywords": "firewall backup"}), 6)

    def test_case_insensitive_match(self):
        eng = _ConcreteEngineer()
        self.assertEqual(eng.matches_ticket({"keywords": "FIREWALL"}), 5)
        self.assertEqual(eng.matches_ticket({"keywords": "Vlan"}), 5)

    def test_missing_keywords_field_scores_zero_without_raising(self):
        eng = _ConcreteEngineer()
        self.assertEqual(eng.matches_ticket({}), 0)
        self.assertEqual(eng.matches_ticket({"keywords": ""}), 0)

    def test_no_overlap_scores_zero(self):
        eng = _ConcreteEngineer()
        self.assertEqual(eng.matches_ticket({"keywords": "unrelated noise"}), 0)

    def test_non_string_keywords_raises_attribute_error(self):
        """Defensive lock: matches_ticket reads ticket.get('keywords', '') and
        .lower()s it. A non-string producer (list/None/int) currently raises
        AttributeError; pin that behaviour so a silent regression to
        'returns 0 on bad type' is detected, and so a future fix that adds a
        defensive cast updates this test deliberately."""
        eng = _ConcreteEngineer()
        with self.assertRaises(AttributeError):
            eng.matches_ticket({"keywords": ["firewall", "VLAN"]})
        with self.assertRaises(AttributeError):
            eng.matches_ticket({"keywords": None})


if __name__ == "__main__":
    unittest.main()
