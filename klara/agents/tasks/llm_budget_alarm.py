"""
app/tasks/llm_budget_alarm.py
──────────────────────────────
phase9-003 — daily LLM cost budget alarm.

Runs at 23:00 CET. Sums today's llm_calls.cost_eur. If above
LLM_DAILY_BUDGET_EUR (env or default), writes an AuditLog row that
the existing approval_notifier sweep will surface to Anthony.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, time, timezone
from decimal import Decimal
from uuid import uuid4

import structlog
from celery import shared_task
from sqlalchemy import func, select

from klara.rarv.runtime import db_context
from klara.rarv.audit import AuditLog
from klara.rarv.llm_call import LlmCall

logger = structlog.get_logger(__name__)


def _budget_eur() -> Decimal:
    raw = os.environ.get("LLM_DAILY_BUDGET_EUR", "10.00")
    try:
        return Decimal(raw)
    except Exception:
        return Decimal("10.00")


@shared_task(
    bind=True,
    name="app.tasks.llm_budget_alarm.run_budget_check",
    max_retries=2,
    default_retry_delay=300,
)
def run_budget_check(self):
    try:
        result = asyncio.run(_check())
        logger.info("llm_budget_alarm.complete", **result)
        return result
    except Exception as exc:
        logger.error("llm_budget_alarm.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _check() -> dict:
    budget = _budget_eur()
    now = datetime.now(timezone.utc)
    start_of_day = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

    async with db_context() as db:
        total_q = await db.execute(
            select(func.coalesce(func.sum(LlmCall.cost_eur), 0))
            .where(LlmCall.called_at >= start_of_day)
        )
        total = Decimal(str(total_q.scalar() or "0"))

        exceeded = total > budget
        if exceeded:
            row = AuditLog(
                id=str(uuid4()),
                event_type="llm.budget_exceeded",
                action_name="daily_budget_check",
                details=json.dumps({
                    "total_cost_eur": float(total),
                    "budget_eur": float(budget),
                    "date": now.date().isoformat(),
                }),
            )
            db.add(row)
            logger.warning(
                "llm_budget_alarm.exceeded",
                total_cost_eur=float(total),
                budget_eur=float(budget),
            )

    return {
        "total_cost_eur": float(total),
        "budget_eur": float(budget),
        "exceeded": exceeded,
    }
