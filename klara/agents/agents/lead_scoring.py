"""
app/agents/lead_scoring.py
──────────────────────────
Converts qualification data into a numeric score (0–100).

Scoring model (rule-based, no extra LLM call):
  Company size fit (max 25)
    500+     = 10  (too big, likely own IT dept)
    200-500  = 20
    50-200   = 25  ← sweet spot
    10-50    = 22
    1-10     = 12  (too small for enterprise services)

  Services fit (max 30)
    Each matched service = +10 pts, capped at 30

  Decision maker (max 15)
    true = 15, false = 5

  Urgency (max 20)
    immediate    = 20
    1-3 months   = 18
    3-6 months   = 10
    exploratory  = 5

  Confidence pass-through (max 10)
    confidence * 10

Total: 0–100.  Score >= 60 → HOT lead.
"""
from __future__ import annotations

import structlog
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.lead import Lead

logger = structlog.get_logger(__name__)

_SIZE_SCORES = {
    "500+":    10,
    "200-500": 20,
    "50-200":  25,
    "10-50":   22,
    "1-10":    12,
}
_URGENCY_SCORES = {
    "immediate":   20,
    "1-3 months":  18,
    "3-6 months":  10,
    "exploratory":  5,
}


class LeadScoringAgent(BaseAgent):
    name = "lead_scoring"
    description = (
        "Computes a 0–100 lead score from qualification data. "
        "Updates the lead's score field in the database."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        qual = input_data.get("qualification", {})
        lead_id = context.lead_id or input_data.get("lead_id")

        if not qual:
            return AgentResult.fail("lead_scoring: 'qualification' dict is required.")

        # ── Compute score ──────────────────────────────────────────────────────
        score = 0.0
        reasons: list[str] = []

        size = qual.get("company_size_est", "")
        size_pts = _SIZE_SCORES.get(size, 10)
        score += size_pts
        reasons.append(f"size({size})={size_pts}")

        services = qual.get("services_fit", [])
        svc_pts = min(len(services) * 10, 30)
        score += svc_pts
        reasons.append(f"services({len(services)})={svc_pts}")

        dm_pts = 15 if qual.get("decision_maker") else 5
        score += dm_pts
        reasons.append(f"decision_maker={dm_pts}")

        urgency = qual.get("urgency", "exploratory")
        urgency_pts = _URGENCY_SCORES.get(urgency, 5)
        score += urgency_pts
        reasons.append(f"urgency({urgency})={urgency_pts}")

        confidence_pts = round(qual.get("confidence", 0.5) * 10, 1)
        score += confidence_pts
        reasons.append(f"confidence={confidence_pts}")

        score = round(min(score, 100.0), 1)
        reason_str = " | ".join(reasons)
        tier = "HOT" if score >= 60 else "WARM" if score >= 35 else "COLD"

        # ── Persist to DB ──────────────────────────────────────────────────────
        if lead_id:
            result = await context.db.execute(select(Lead).where(Lead.id == lead_id))
            lead = result.scalar_one_or_none()
            if lead:
                lead.score = score
                lead.score_reason = reason_str
                await context.db.flush()

        logger.info(
            "lead_scoring.complete",
            lead_id=lead_id,
            score=score,
            tier=tier,
        )

        return AgentResult.ok(
            output={"score": score, "tier": tier, "score_reason": reason_str, "lead_id": lead_id}
        )
