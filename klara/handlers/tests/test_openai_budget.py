"""
Unit tests for klara.handlers.lib.openai_budget.

These tests exercise pure-Python paths (cost math, env parsing). The
DB-backed check_and_record path is verified via a stubbed get_pool so we
don't need a live Postgres connection.

Run with:
    pytest infra/klara.handlers/tests/test_openai_budget.py -v
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INFRA_DIR = PROJECT_ROOT / "infra"
sys.path.insert(0, str(INFRA_DIR))


def test_estimate_cost_embedding(monkeypatch):
    from klara.handlers.lib.openai_budget import estimate_cost_usd

    # 1M tokens of text-embedding-3-small = $0.02
    assert estimate_cost_usd(1_000_000, 0, model="text-embedding-3-small") == Decimal("0.0200")
    # No completion tokens for embeddings
    assert estimate_cost_usd(500_000, 99, model="text-embedding-3-small") == Decimal("0.0100")


def test_estimate_cost_haiku():
    from klara.handlers.lib.openai_budget import estimate_cost_usd
    # 1M input + 1M output of haiku-4-5 = $1 + $5 = $6
    assert estimate_cost_usd(1_000_000, 1_000_000, model="claude-haiku-4-5") == Decimal("6.0000")


def test_estimate_cost_unknown_model_falls_back_to_sonnet():
    from klara.handlers.lib.openai_budget import estimate_cost_usd
    # Sonnet: $3 in / $15 out per 1M
    assert estimate_cost_usd(1_000_000, 1_000_000, model="some-future-model") == Decimal("18.0000")


def test_budget_env_default(monkeypatch):
    monkeypatch.delenv("OPENAI_MONTHLY_BUDGET_USD", raising=False)
    from klara.handlers.lib import openai_budget
    assert openai_budget._budget_usd() == Decimal("50")


def test_budget_env_override(monkeypatch):
    monkeypatch.setenv("OPENAI_MONTHLY_BUDGET_USD", "5")
    from klara.handlers.lib import openai_budget
    # Reset the module-level constant since it reads at call time, not import.
    assert openai_budget._budget_usd() == Decimal("5")


def test_budget_env_garbage_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("OPENAI_MONTHLY_BUDGET_USD", "not-a-number")
    from klara.handlers.lib import openai_budget
    assert openai_budget._budget_usd() == Decimal("50")


@pytest.mark.asyncio
async def test_check_and_record_under_budget(monkeypatch):
    """When spend is under the cap, check_and_record returns True and records."""
    monkeypatch.setenv("OPENAI_MONTHLY_BUDGET_USD", "10")
    from klara.handlers.lib import openai_budget

    recorded: list[Decimal] = []

    async def fake_mtd():
        return Decimal("0.5")

    async def fake_record(day, requests, prompt_toks, completion_toks, cost_usd):
        recorded.append(cost_usd)

    monkeypatch.setattr(openai_budget, "_month_to_date_spend", fake_mtd)
    monkeypatch.setattr(openai_budget, "_record_usage", fake_record)

    ok = await openai_budget.check_and_record(1000, 0, model="text-embedding-3-small")
    assert ok is True
    # 1000 toks * $0.02 / 1M = $0.00002 → quantized to 4 decimals = 0.0000
    assert len(recorded) == 1


@pytest.mark.asyncio
async def test_check_and_record_over_budget_returns_false(monkeypatch):
    """When projected spend > budget, check_and_record returns False."""
    monkeypatch.setenv("OPENAI_MONTHLY_BUDGET_USD", "1")
    from klara.handlers.lib import openai_budget

    async def fake_mtd():
        return Decimal("0.99")

    recorded: list[Decimal] = []

    async def fake_record(day, requests, prompt_toks, completion_toks, cost_usd):
        recorded.append(cost_usd)

    monkeypatch.setattr(openai_budget, "_month_to_date_spend", fake_mtd)
    monkeypatch.setattr(openai_budget, "_record_usage", fake_record)

    # Huge call that puts us over the cap.
    ok = await openai_budget.check_and_record(10_000_000, 10_000_000, model="claude-sonnet-4-5")
    assert ok is False
    # The attempt is still recorded (with cost=0) for observability.
    assert recorded == [Decimal("0")]
