"""
app/services/llm_cost.py
─────────────────────────
phase9-001 — LLM call cost tracking.

Public surface:
  · compute_cost_eur(model, input_tokens, output_tokens) → Decimal
  · record_llm_call(db, agent_name, model, input_tokens, output_tokens, ...) → None

The cost table is hard-coded here. When Anthropic changes prices, update
PRICING. EUR conversion uses a fixed USD→EUR rate (no live FX lookup —
the rates are stable enough at €/$ ≈ 0.92 that an off-by-2% on cost
reporting doesn't matter for budgeting).

Recording failures NEVER raise — agents should never crash because the
cost-tracking write failed.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import uuid4

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_call import LlmCall

logger = structlog.get_logger(__name__)


# Per-million-token USD pricing from Anthropic public docs. Update on each
# model change. The dict maps full model id → (input_per_million, output_per_million).
PRICING: dict[str, tuple[Decimal, Decimal]] = {
    # Claude 3.5 family
    "claude-3-5-sonnet-20241022":     (Decimal("3.00"), Decimal("15.00")),
    "claude-3-5-haiku-20241022":      (Decimal("0.80"), Decimal("4.00")),
    # Claude Haiku 4.5 (used by post_call_processor)
    "claude-haiku-4-5-20251001":      (Decimal("0.80"), Decimal("4.00")),
    # Claude 4 family — placeholder pricing matching 3.5 until official prices land
    "claude-opus-4-7":                (Decimal("15.00"), Decimal("75.00")),
    "claude-sonnet-4-6":              (Decimal("3.00"), Decimal("15.00")),
}

# Fallback for unknown models — Sonnet-class pricing.
_FALLBACK_PRICING = (Decimal("3.00"), Decimal("15.00"))

# USD → EUR conversion factor. Fixed for budgeting purposes — see module docstring.
USD_TO_EUR = Decimal("0.92")


def compute_cost_eur(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    """Compute the EUR cost of one Claude call.

    Cost formula:
      cost_usd = (input_tokens / 1e6) × input_price + (output_tokens / 1e6) × output_price
      cost_eur = cost_usd × USD_TO_EUR
    """
    input_price, output_price = PRICING.get(model, _FALLBACK_PRICING)
    input_cost = (Decimal(input_tokens) / Decimal("1000000")) * input_price
    output_cost = (Decimal(output_tokens) / Decimal("1000000")) * output_price
    total_usd = input_cost + output_cost
    return (total_usd * USD_TO_EUR).quantize(Decimal("0.000001"))


async def track_response(
    db: AsyncSession,
    *,
    agent_name: str,
    model: str,
    response,
    lead_id: Optional[str] = None,
) -> None:
    """Convenience wrapper: extract usage from an Anthropic response object
    and forward to record_llm_call. Never raises."""
    try:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        await record_llm_call(
            db,
            agent_name=agent_name,
            model=model,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            lead_id=lead_id,
        )
    except Exception as exc:
        logger.warning("llm_cost.track_response_failed", error=str(exc))


async def record_llm_call(
    db: AsyncSession,
    *,
    agent_name: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    lead_id: Optional[str] = None,
) -> None:
    """
    Record a Claude API call. Never raises — recording failures are logged.

    Caller should pass the values from the AsyncAnthropic response object:
      response.usage.input_tokens
      response.usage.output_tokens
    """
    try:
        cost = compute_cost_eur(model, input_tokens, output_tokens)
        row = LlmCall(
            id=str(uuid4()),
            agent_name=agent_name,
            model=model,
            input_tokens=int(input_tokens or 0),
            output_tokens=int(output_tokens or 0),
            cost_eur=cost,
            lead_id=lead_id,
        )
        db.add(row)
        await db.flush()
        logger.info(
            "llm_cost.recorded",
            agent_name=agent_name,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_eur=float(cost),
        )
    except Exception as exc:
        # Never propagate — cost tracking must not crash an agent.
        logger.warning(
            "llm_cost.record_failed",
            agent_name=agent_name,
            model=model,
            error=str(exc),
        )
