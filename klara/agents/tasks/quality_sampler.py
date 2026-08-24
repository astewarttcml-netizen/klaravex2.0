"""
app/tasks/quality_sampler.py
─────────────────────────────
phase12-003 — daily LLM-as-judge sampling.

Selects up to MAX_SAMPLES random llm_calls from the previous day. For
each, asks Haiku to score the output on a 1-5 scale with a one-sentence
reason. Persists to quality_samples.

We deliberately use Haiku (cheap, fast) for judging — not Sonnet — so
the cost of judging stays well below the cost of the calls being judged.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from uuid import uuid4

import structlog
from anthropic import AsyncAnthropic
from celery import shared_task
from sqlalchemy import func, select

from klara.rarv.runtime import get_settings
from klara.rarv.runtime import db_context
from klara.rarv.llm_call import LlmCall
from klara.rarv.prompt_quality import QualitySample

logger = structlog.get_logger(__name__)

MAX_SAMPLES = 20
JUDGE_MODEL = "claude-haiku-4-5-20251001"

JUDGE_PROMPT = """\
You are an internal quality auditor reviewing outputs from a multi-agent
sales automation system. Score the output below on a 1-5 scale.

Scoring rubric (be strict):
  5 — Excellent: accurate, on-brand, no errors, complete
  4 — Good: solid but could be sharper
  3 — Acceptable: works but has weaknesses
  2 — Poor: meaningful problems (factual error, tone-off, incomplete)
  1 — Bad: would embarrass the operator if sent

Respond ONLY with JSON: {{"score": <int 1-5>, "reason": "<one sentence>"}}

Agent: {agent_name}
Model used: {model}
Tokens: input={input_tokens}, output={output_tokens}
Output snippet (truncated to first 800 chars):
{snippet}
"""


@shared_task(
    bind=True,
    name="app.tasks.quality_sampler.run_quality_sampler",
    max_retries=2,
    default_retry_delay=600,
)
def run_quality_sampler(self):
    try:
        result = asyncio.run(_run())
        logger.info("quality_sampler.complete", **result)
        return result
    except Exception as exc:
        logger.error("quality_sampler.task_failed", error=str(exc), exc_info=True)
        raise self.retry(exc=exc)


async def _run() -> dict:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    yesterday_start = datetime.combine(now.date() - timedelta(days=1), time.min, tzinfo=timezone.utc)
    today_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

    judged = 0
    skipped_already = 0
    failed = 0

    async with db_context() as db:
        # Pull up to MAX_SAMPLES random llm_calls from yesterday
        q = await db.execute(
            select(LlmCall)
            .where(
                LlmCall.called_at >= yesterday_start,
                LlmCall.called_at < today_start,
            )
            .order_by(func.random())
            .limit(MAX_SAMPLES)
        )
        candidates = list(q.scalars().all())
        if not candidates:
            return {"judged": 0, "candidates": 0}

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        for call in candidates:
            # Skip if already judged
            existing = await db.execute(
                select(QualitySample.id).where(QualitySample.llm_call_id == call.id).limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                skipped_already += 1
                continue

            # We don't store the output text in llm_calls — only metadata.
            # So the snippet here is just metadata describing the call.
            # A future migration could persist short output snippets to
            # llm_calls; for now, the judge sees metadata only.
            snippet = (
                f"[output text not retained — metadata-only review]\n"
                f"agent={call.agent_name}\n"
                f"model={call.model}\n"
                f"in_tokens={call.input_tokens} out_tokens={call.output_tokens}"
            )
            prompt = JUDGE_PROMPT.format(
                agent_name=call.agent_name,
                model=call.model,
                input_tokens=call.input_tokens,
                output_tokens=call.output_tokens,
                snippet=snippet,
            )

            try:
                response = await client.messages.create(
                    model=JUDGE_MODEL,
                    max_tokens=200,
                    temperature=0,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.content[0].text.strip()
                parsed = json.loads(raw)
                score = int(parsed.get("score", 3))
                reason = parsed.get("reason") or None
                score = max(1, min(5, score))
            except Exception as exc:
                logger.warning(
                    "quality_sampler.judge_failed",
                    llm_call_id=call.id,
                    error=str(exc),
                )
                failed += 1
                continue

            sample = QualitySample(
                id=str(uuid4()),
                llm_call_id=call.id,
                agent_name=call.agent_name,
                score=score,
                reason=reason,
            )
            db.add(sample)
            judged += 1

    return {
        "candidates": len(candidates),
        "judged": judged,
        "skipped_already": skipped_already,
        "failed": failed,
    }
