"""
Klaravex OpenAI / Anthropic cost kill-switch.

Goal
====
Bound monthly LLM + embedding spend so an attacker (or a runaway bot) cannot
drain the OPENAI_API_KEY budget overnight. The kill-switch is consulted by
every cost-incurring path (KB embeddings, chat reply LLM, etc.) BEFORE the
upstream API call is dispatched.

Behaviour
---------
- Reads OPENAI_MONTHLY_BUDGET_USD from the environment (default: $50).
- Each successful upstream call adds its estimated cost to klaravex_openai_usage
  for the UTC day. The day row is upserted on every record.
- ``check_and_record(prompt_toks, completion_toks, *, model="text-embedding-3-small")``
  computes estimated USD spend, sums month-to-date spend, and returns:
    - True  → under budget; usage is recorded and the caller may proceed.
    - False → over budget; the caller MUST fall back (e.g. KB-only reply,
              "Sorry, our AI is paused — please call +1 (424) 348-6010").
- Module is import-safe even when the migration has not been applied. A missing
  table is logged once and treated as "budget unavailable → allow" so the chat
  path keeps working during the migration window; cost is still capped by the
  app-level rate limit (H13/H2 SlowAPI).
- DB writes use the shared get_pool() — no new connections.

Pricing constants
-----------------
text-embedding-3-small  : $0.02 per 1M input tokens
claude-haiku-4-5        : $1.00 per 1M input,  $5.00 per 1M output
claude-sonnet-4-5       : $3.00 per 1M input, $15.00 per 1M output
gpt-4o-mini             : $0.15 per 1M input,  $0.60 per 1M output (fallback)

Numbers are *estimates*, not invoiced cost. We deliberately round UP rather
than down so the kill-switch is conservative.
"""

import logging
import os
from datetime import date
from decimal import Decimal

from .db import get_pool

log = logging.getLogger("klaravex.openai_budget")

# ── pricing table (USD per 1M tokens) ─────────────────────────────────────────
# (input_per_1m, output_per_1m)
_PRICING: dict[str, tuple[float, float]] = {
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
    "claude-haiku-4-5":       (1.0, 5.0),
    "claude-sonnet-4-5":      (3.0, 15.0),
    "claude-opus-4-5":        (15.0, 75.0),
    "gpt-4o-mini":            (0.15, 0.60),
    "gpt-4o":                 (2.50, 10.00),
}

# Treat anything we don't recognize as expensive so we don't accidentally
# undercount: use Sonnet pricing as the fallback bucket.
_FALLBACK_MODEL = "claude-sonnet-4-5"


def _budget_usd() -> Decimal:
    """Read OPENAI_MONTHLY_BUDGET_USD from env, default $50.

    Despite the name, this budget covers both OpenAI and Anthropic spend so
    one knob controls the total LLM + embedding outlay per month.
    """
    raw = os.environ.get("OPENAI_MONTHLY_BUDGET_USD", "50")
    try:
        v = Decimal(str(raw))
        if v < 0:
            return Decimal("50")
        return v
    except Exception:  # noqa: BLE001
        return Decimal("50")


def estimate_cost_usd(prompt_toks: int, completion_toks: int, *, model: str) -> Decimal:
    """Return estimated cost in USD for a single call.

    Both token counts are clamped at 0. Unknown model falls back to Sonnet
    pricing — conservative so the kill-switch errs on the side of caution.
    """
    p_in, p_out = _PRICING.get(model, _PRICING[_FALLBACK_MODEL])
    prompt_toks = max(int(prompt_toks or 0), 0)
    completion_toks = max(int(completion_toks or 0), 0)
    cost_in = Decimal(str(p_in)) * Decimal(prompt_toks) / Decimal(1_000_000)
    cost_out = Decimal(str(p_out)) * Decimal(completion_toks) / Decimal(1_000_000)
    # Quantize to 4 decimal places to match the NUMERIC(10,4) column.
    return (cost_in + cost_out).quantize(Decimal("0.0001"))


# Module-level flag so we only log the "table missing" warning once.
_table_missing_warned = False


async def _month_to_date_spend() -> Decimal:
    """SUM(est_cost_usd) for the current UTC calendar month.

    Returns Decimal('0') if the table doesn't exist yet (migration not run).
    """
    global _table_missing_warned
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COALESCE(SUM(est_cost_usd), 0) AS total
                  FROM klaravex_openai_usage
                 WHERE day >= date_trunc('month', (now() AT TIME ZONE 'UTC')::date)::date
                """
            )
        return Decimal(str(row["total"] or 0))
    except Exception as exc:  # noqa: BLE001
        # Most common cause: migration 020 not applied yet. Fail-OPEN here
        # because the rate limiter is still in front; we don't want the chat
        # widget to fall over the moment someone forgets to run the migration.
        if not _table_missing_warned:
            log.warning(
                "klaravex_openai_usage unavailable, treating budget as 0 spent: %s", exc,
            )
            _table_missing_warned = True
        return Decimal("0")


async def _record_usage(
    day: date, requests: int, prompt_toks: int, completion_toks: int, cost_usd: Decimal,
) -> None:
    """Upsert today's row, incrementing counters by the given deltas."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO klaravex_openai_usage
                    (day, requests, prompt_tokens, completion_tokens, est_cost_usd)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (day) DO UPDATE
                   SET requests          = klaravex_openai_usage.requests          + EXCLUDED.requests,
                       prompt_tokens     = klaravex_openai_usage.prompt_tokens     + EXCLUDED.prompt_tokens,
                       completion_tokens = klaravex_openai_usage.completion_tokens + EXCLUDED.completion_tokens,
                       est_cost_usd      = klaravex_openai_usage.est_cost_usd      + EXCLUDED.est_cost_usd
                """,
                day, requests, prompt_toks, completion_toks, cost_usd,
            )
    except Exception as exc:  # noqa: BLE001
        # Same fail-OPEN rationale as _month_to_date_spend.
        log.warning("openai_budget: failed to record usage: %s", exc)


async def check_and_record(
    prompt_toks: int,
    completion_toks: int = 0,
    *,
    model: str = "text-embedding-3-small",
) -> bool:
    """Top-level helper used by callers.

    Returns True when the call may proceed (and records the cost). Returns
    False when the monthly budget has been exhausted — caller MUST handle the
    fall-back path (KB-only reply / human-call-back message).

    NOTE: we record BEFORE the call so a parallel surge can't all sneak under
    the cap at the same moment. The cost may be a slight overestimate (we
    don't subtract on upstream failure) — that is by design; this is a kill
    switch, not an accounting ledger.
    """
    today = date.today()  # date.today() is OS-local; cron containers run UTC.
    cost = estimate_cost_usd(prompt_toks, completion_toks, model=model)
    spend = await _month_to_date_spend()
    budget = _budget_usd()
    projected = spend + cost
    if projected > budget:
        log.warning(
            "openai budget exceeded: month_to_date=%.4f projected=%.4f budget=%.2f model=%s",
            spend, projected, budget, model,
        )
        # Still record the *attempt* so observability shows the cap firing.
        # Cost is 0 because the caller WON'T make the upstream call.
        await _record_usage(today, requests=1, prompt_toks=0, completion_toks=0, cost_usd=Decimal("0"))
        return False
    await _record_usage(today, requests=1, prompt_toks=prompt_toks, completion_toks=completion_toks, cost_usd=cost)
    return True


async def month_to_date_summary() -> dict[str, object]:
    """Convenience accessor for /health/deep or future dashboards."""
    spend = await _month_to_date_spend()
    budget = _budget_usd()
    remaining = max(budget - spend, Decimal("0"))
    return {
        "month_to_date_usd": float(spend),
        "monthly_budget_usd": float(budget),
        "remaining_usd": float(remaining),
        "over_budget": spend >= budget,
    }
