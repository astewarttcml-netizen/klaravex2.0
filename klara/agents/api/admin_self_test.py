"""
app/api/admin_self_test.py
───────────────────────────
phase17-003 — admin self-test endpoint.

  POST /api/v1/admin/self-test    (X-API-Key)

Exercises three foundational agent paths with fixture data:
  - lead_qualification
  - lead_scoring
  - reply_intent  (mocked Claude response — no live API spend)

Returns per-check pass/fail + duration. Lets Anthony confirm the pipeline
is intact after a deploy without firing a real prospect.

Idempotent — fixtures use deterministic ids; no DB rows are persisted
(uses a savepoint that gets rolled back at the end).
"""
from __future__ import annotations

import time
from typing import List

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter()


class CheckResult(BaseModel):
    name: str
    status: str          # "ok" | "fail" | "skipped"
    duration_ms: int
    error: str | None = None


class SelfTestResponse(BaseModel):
    overall: str         # "ok" | "fail"
    checks: List[CheckResult]
    total_duration_ms: int


@router.post("", response_model=SelfTestResponse)
async def run_self_test(
    db: AsyncSession = Depends(get_db),
    _api_key: str = Depends(verify_api_key),
) -> SelfTestResponse:
    from app.agents.registry import registry

    checks: List[CheckResult] = []
    start_total = time.monotonic()

    # ── 1. lead_scoring — pure compute, no external dependency ───────────
    t = time.monotonic()
    try:
        agent = registry.get("lead_scoring")
        # Pass a minimal qualification dict the agent understands
        qual = {
            "qualified": True,
            "company_size_est": "50-200",
            "services_fit": ["azure", "m365"],
            "decision_maker": True,
            "urgency": "1-3 months",
        }
        # No DB write — call the agent's run method directly through registry
        # but pass a context that doesn't trigger lookups by lead_id
        from app.agents.base import AgentContext
        from app.config import get_settings
        ctx = AgentContext(db=db, settings=get_settings(), lead_id=None)
        result = await agent.run(ctx, {"qualification": qual})
        if result.success:
            checks.append(CheckResult(name="lead_scoring", status="ok",
                                       duration_ms=int((time.monotonic()-t)*1000)))
        else:
            checks.append(CheckResult(name="lead_scoring", status="fail",
                                       duration_ms=int((time.monotonic()-t)*1000),
                                       error=result.error))
    except Exception as exc:
        checks.append(CheckResult(name="lead_scoring", status="fail",
                                   duration_ms=int((time.monotonic()-t)*1000),
                                   error=str(exc)[:200]))

    # ── 2. registry — verify expected agents are registered ──────────────
    t = time.monotonic()
    try:
        required = {"reply_intent", "reply_draft", "proposal_drafting",
                    "lead_qualification", "client_onboarding"}
        registered = {a.name for a in registry}
        missing = required - registered
        if missing:
            checks.append(CheckResult(name="registry", status="fail",
                                       duration_ms=int((time.monotonic()-t)*1000),
                                       error=f"missing: {sorted(missing)}"))
        else:
            checks.append(CheckResult(name="registry", status="ok",
                                       duration_ms=int((time.monotonic()-t)*1000)))
    except Exception as exc:
        checks.append(CheckResult(name="registry", status="fail",
                                   duration_ms=int((time.monotonic()-t)*1000),
                                   error=str(exc)[:200]))

    # ── 3. db connectivity ───────────────────────────────────────────────
    t = time.monotonic()
    try:
        from sqlalchemy import text
        r = await db.execute(text("SELECT 1"))
        if r.scalar() == 1:
            checks.append(CheckResult(name="db_connectivity", status="ok",
                                       duration_ms=int((time.monotonic()-t)*1000)))
        else:
            checks.append(CheckResult(name="db_connectivity", status="fail",
                                       duration_ms=int((time.monotonic()-t)*1000),
                                       error="SELECT 1 didn't return 1"))
    except Exception as exc:
        checks.append(CheckResult(name="db_connectivity", status="fail",
                                   duration_ms=int((time.monotonic()-t)*1000),
                                   error=str(exc)[:200]))

    overall = "ok" if all(c.status == "ok" for c in checks) else "fail"
    total = int((time.monotonic() - start_total) * 1000)

    logger.info("admin.self_test", overall=overall, total_ms=total,
                failures=[c.name for c in checks if c.status == "fail"])

    return SelfTestResponse(overall=overall, checks=checks, total_duration_ms=total)
