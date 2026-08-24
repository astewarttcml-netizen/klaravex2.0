"""Phase 12 V1-V4 unit tests.

Exercises:
  - Pure helpers in vapi.lookup_client (phone normalization, phone match,
    6-digit code regex).
  - Pydantic schemas for create_b2b_lead and send_booking_link.
  - Router wiring (lookup_client / create_b2b_lead / send_booking_link
    routers exist and are mounted on the aggregator).
  - Tool dispatcher recognises the three new tool names.

We avoid actually opening a Postgres connection here — those are covered
by the integration suite. These tests are db-free and import-safe so
test_handler_imports stays green even when asyncpg/httpx are unavailable.
"""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Optional-dep shims — only installed if the real package is missing so a
# bare `bun test` / `pytest` environment doesn't blow up at import time.
# ---------------------------------------------------------------------------
def _ensure_stub(name: str, attrs: dict | None = None) -> None:
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    for k, v in (attrs or {}).items():
        setattr(mod, k, v)
    sys.modules[name] = mod


def _install_optional_stubs() -> None:
    try:  # pragma: no cover
        import fastapi  # noqa: F401
    except Exception:
        class _Router:
            def __init__(self, *_, **__):
                self.routes = []

            def post(self, path, **_):
                def deco(fn):
                    self.routes.append(("POST", path, fn))
                    return fn
                return deco

            def include_router(self, other):
                self.routes.extend(getattr(other, "routes", []))

        def _depends(_fn):  # noqa: ARG001
            return None

        async def _req_json(self):  # noqa: ARG001
            return {}

        class _Request:
            async def json(self):
                return {}

        _ensure_stub(
            "fastapi",
            {"APIRouter": _Router, "Depends": _depends, "Request": _Request},
        )

    try:  # pragma: no cover
        import pydantic  # noqa: F401
    except Exception:
        class _Model:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

            @classmethod
            def __init_subclass__(cls, **_):
                pass

        def _field(default=None, **_):
            return default

        _ensure_stub(
            "pydantic",
            {"BaseModel": _Model, "Field": _field},
        )

    try:  # pragma: no cover
        import httpx  # noqa: F401
    except Exception:
        class _Client:
            def __init__(self, **_):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, *a, **k):
                class _R:
                    status_code = 200

                    def json(self):
                        return {}

                return _R()

        _ensure_stub("httpx", {"AsyncClient": _Client})


_install_optional_stubs()


# ---------------------------------------------------------------------------
# Pure helper tests (no async, no db)
# ---------------------------------------------------------------------------
from infra.klara.handlers.vapi import lookup_client as lc_mod  # noqa: E402


def test_normalize_phone_strips_punctuation():
    assert lc_mod._normalize_phone("(424) 348-6010") == "4243486010"
    assert lc_mod._normalize_phone("+1 424 348 6010") == "+14243486010"
    assert lc_mod._normalize_phone("") == ""
    # Multiple plus signs collapse to one leading +.
    assert lc_mod._normalize_phone("+1+424+348+6010") == "+14243486010"


def test_phones_match_handles_e164_and_us_local():
    assert lc_mod._phones_match("+14243486010", "4243486010") is True
    assert lc_mod._phones_match("(424) 348-6010", "+1-424-348-6010") is True
    assert lc_mod._phones_match("4243486010", "4243486011") is False
    assert lc_mod._phones_match("", "+14243486010") is False
    assert lc_mod._phones_match("+14243486010", "") is False
    # Both must be at least 10 digits.
    assert lc_mod._phones_match("12345", "12345") is False


def test_customer_code_accepts_six_to_eight_digits():
    # Customer codes were expanded from strict 6 digits to 6–8 digits on
    # 2026-06-26 (observation 13487) so existing 6-digit codes still work
    # while leaving room for a longer namespace as the client base grows.
    assert lc_mod._CODE_RE.match("123456") is not None
    assert lc_mod._CODE_RE.match("1234567") is not None
    assert lc_mod._CODE_RE.match("12345678") is not None
    assert lc_mod._CODE_RE.match("12345") is None
    assert lc_mod._CODE_RE.match("123456789") is None
    assert lc_mod._CODE_RE.match("12a456") is None
    assert lc_mod._CODE_RE.match("") is None


def test_bundle_verify_never_leaks_stored_contact_data():
    client_row = {
        "id": "11111111-2222-3333-4444-555555555555",
        "name": "Acme Mittelstand GmbH",
        "email": "owner@acme.de",
        "phone": "+493012345678",
        "segment": "directive",
        "plan_tier": "directive",
    }
    bundle = lc_mod._bundle_verify(client_row)
    assert bundle["trust_level"] == "verify"
    assert bundle["authorized"] is True
    # Critical: the verify-trust bundle MUST NOT include company name,
    # email, phone, plan_tier, or ticket counts.
    forbidden = {"company", "email_on_file", "phone_on_file", "open_tickets", "plan_tier"}
    assert forbidden.isdisjoint(bundle["client"].keys()), (
        f"verify-trust bundle leaked: {sorted(set(bundle['client'].keys()) & forbidden)}"
    )


def test_bundle_full_includes_actionable_fields_only():
    client_row = {
        "id": "11111111-2222-3333-4444-555555555555",
        "name": "Acme",
        "email": "ops@acme.com",
        "phone": "+14245550100",
        "segment": "foundation",
        "plan_tier": "foundation",
    }
    bundle = lc_mod._bundle_full(client_row, open_tickets=3)
    assert bundle["trust_level"] == "full"
    c = bundle["client"]
    assert c["company"] == "Acme"
    assert c["plan_tier"] == "foundation"
    assert c["open_tickets"] == 3


# ---------------------------------------------------------------------------
# Router wiring
# ---------------------------------------------------------------------------
def test_router_includes_phase12_routes():
    # Re-import the aggregator so we pick up the post-edit registry.
    router_mod = importlib.import_module("infra.klara.handlers.vapi.router")
    importlib.reload(router_mod)
    router = router_mod.router
    routes = getattr(router, "routes", [])
    # FastAPI's real router stores APIRoute objects (or, on newer FastAPI,
    # lazy `_IncludedRouter` wrappers around nested sub-routers that must be
    # resolved via effective_candidates()); the stub above stores
    # (method, path, fn) tuples. Normalise to a path-string list.
    paths: list[str] = []

    def _collect(route_list):
        for r in route_list:
            if isinstance(r, tuple):
                paths.append(r[1])
            elif hasattr(r, "effective_candidates"):
                _collect(r.effective_candidates())
            else:
                paths.append(getattr(r, "path", ""))

    _collect(routes)
    assert any("/lookup_client" in p for p in paths), paths
    assert any("/create_b2b_lead" in p for p in paths), paths
    assert any("/send_booking_link" in p for p in paths), paths
    assert any("/advise_client" in p for p in paths), paths


# ---------------------------------------------------------------------------
# V5 advise_client — prompt assembly + trust-aware redaction
# ---------------------------------------------------------------------------
from infra.klara.handlers.vapi import advise_client as ac_mod  # noqa: E402


def test_advise_client_verify_prompt_excludes_company_and_plan_tier():
    prompt = ac_mod._build_engineer_prompt(
        engineer_system_prompt="You are the test engineer.",
        engineer_display_name="Test Engineer",
        pillar="managed_security",
        question="What's the right backup retention for a 25-seat law firm?",
        trust_level=ac_mod.TRUST_VERIFY,
        client_company="Acme Mittelstand GmbH",
        plan_tier="directive",
        kb_grounding="[Backup Architecture] 90-day retention is the floor for Assurance tier.",
    )
    # The verify-trust prompt must NOT leak the stored company name or plan tier
    # even when the caller passed both into the helper.
    assert "Acme Mittelstand GmbH" not in prompt
    assert "directive" not in prompt
    # And the prompt must include the explicit "hidden by trust gate" directive.
    assert "verify trust" in prompt
    assert "do NOT name a company" in prompt.lower() or "hidden by trust gate" in prompt


def test_advise_client_full_prompt_includes_company_and_plan_tier():
    prompt = ac_mod._build_engineer_prompt(
        engineer_system_prompt="You are the test engineer.",
        engineer_display_name="Test Engineer",
        pillar="managed_security",
        question="Backup retention?",
        trust_level=ac_mod.TRUST_FULL,
        client_company="Acme",
        plan_tier="foundation",
        kb_grounding="",
    )
    assert "Acme" in prompt
    assert "foundation" in prompt


def test_advise_client_strip_stored_data_removes_known_placeholders():
    raw = "Hello {company}, your plan is {plan_tier} ({open_tickets} tickets)."
    out = ac_mod._strip_stored_data_for_verify(raw)
    assert "{company}" not in out
    assert "{plan_tier}" not in out
    assert "{open_tickets}" not in out


def test_advise_client_routes_security_question_to_managed_security():
    name, pillar = ac_mod._route_question_to_pillar(
        "Should we deploy Huntress MDR across the UniFi network?"
    )
    assert pillar == "managed_security"
    assert name == "engineer_managed_security"


def test_advise_client_routes_compliance_question_to_regulatory():
    name, pillar = ac_mod._route_question_to_pillar(
        "What HIPAA controls do we need before our SOC 2 readiness audit?"
    )
    assert pillar == "regulatory_readiness"
    assert name == "engineer_regulatory_readiness"


def test_advise_client_routes_unknown_question_to_strategic_advisory():
    # Deliberately devoid of any pillar keyword — must fall back to advisory.
    # Verified locally: no token here trips any engineer's scoring keywords.
    name, pillar = ac_mod._route_question_to_pillar("zzqx wibble?")
    assert pillar == "strategic_advisory"
    assert name == "engineer_strategic_advisory"


def test_advise_client_voice_safe_reply_flattens_json():
    reply = {
        "answer": "Backup retention should be 90 days minimum for HIPAA-scoped data.",
        "follow_up_question": "Are any of these systems handling ePHI?",
        "next_action": "open a ticket",
        "citations": ["Veeam backup architecture"],
    }
    text = ac_mod._voice_safe_reply(reply, "Managed Security Engineer")
    assert "Backup retention" in text
    assert "ePHI" in text
    assert "Suggested next step: open a ticket." in text


def test_advise_client_voice_safe_reply_skips_no_further_action():
    reply = {
        "answer": "Generic guidance.",
        "follow_up_question": "",
        "next_action": "no further action",
    }
    text = ac_mod._voice_safe_reply(reply, "Test Engineer")
    assert "Suggested next step" not in text


def test_advise_client_kb_grounding_respects_char_budget():
    long_body = "x" * 5000
    hits = [
        {"source_title": "Doc 1", "content": long_body},
        {"source_title": "Doc 2", "content": long_body},
        {"source_title": "Doc 3", "content": long_body},
    ]
    out = ac_mod._format_kb_grounding(hits)
    # The function uses a soft cap; ensure it didn't pull in all 15k chars.
    assert len(out) < 5000


def test_advise_client_dispatch_recognised():
    src = (
        PROJECT_ROOT
        / "infra"
        / "klara.handlers"
        / "vapi"
        / "tool_call.py"
    ).read_text(encoding="utf-8")
    assert 'name == "advise_client"' in src


# ---------------------------------------------------------------------------
# Migration sanity
# ---------------------------------------------------------------------------
def test_migration_021_present_and_idempotent_markers():
    mig = PROJECT_ROOT / "infra" / "migrations" / "021_b2b_customer_codes.sql"
    text = mig.read_text(encoding="utf-8")
    # Schema additions.
    assert "ALTER TABLE klaravex_clients" in text
    assert "customer_code CHAR(6)" in text
    assert "CREATE TABLE IF NOT EXISTS klaravex_b2b_leads" in text
    assert "CREATE TABLE IF NOT EXISTS klaravex_voice_auth_attempts" in text
    # Idempotency markers — every CREATE INDEX / ADD COLUMN uses IF NOT EXISTS.
    assert "ADD COLUMN IF NOT EXISTS customer_code" in text
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_clients_customer_code" in text
    # Transactional safety.
    assert text.strip().startswith("-- Phase 12 V1") or text.strip().startswith("-- Phase 12")
    assert "BEGIN;" in text
    assert "COMMIT;" in text


# ---------------------------------------------------------------------------
# Dispatcher recognises the new tool names
# ---------------------------------------------------------------------------
def test_dispatch_lists_phase12_tool_names():
    src = (
        PROJECT_ROOT
        / "infra"
        / "klara.handlers"
        / "vapi"
        / "tool_call.py"
    ).read_text(encoding="utf-8")
    for tool in ("lookup_client", "create_b2b_lead", "send_booking_link"):
        assert f'name == "{tool}"' in src, f"dispatcher missing {tool}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
