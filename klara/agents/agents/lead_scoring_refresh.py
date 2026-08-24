"""
app/agents/lead_scoring_refresh.py
────────────────────────────────────
LeadScoringRefreshAgent — nightly batch agent that re-runs lead scoring over
all active leads to keep scores current.

"Active" is defined as status in: new, qualified, discovery_done, proposal_sent.
Callers may override this via ``status_filter`` in input_data.

The agent reconstructs a ``qualification`` dict from each lead's persisted fields
and delegates to the ``lead_scoring`` agent (which owns the scoring algorithm and
writes the result to DB).  This agent never duplicates scoring logic.

Score change tracking:
  - old_score is captured before calling lead_scoring
  - new_score is read from result.output["score"] after the call
  - A result entry is appended for every lead regardless of success/failure

dry_run mode:
  In dry_run mode the agent computes scores but does NOT call lead_scoring at all
  (to guarantee zero DB writes).  It reconstructs the qualification dict and
  reports what would have been scored, but returns new_score=None to signal that
  no write occurred.
"""
from __future__ import annotations

import json
from typing import Any

import structlog
from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.lead import Lead

logger = structlog.get_logger(__name__)

# Default set of statuses that represent "active" leads worth re-scoring.
_DEFAULT_ACTIVE_STATUSES: list[str] = [
    "new",
    "qualified",
    "discovery_done",
    "proposal_sent",
]

# Map lead.timeline values to urgency keys understood by lead_scoring.
_TIMELINE_TO_URGENCY: dict[str, str] = {
    "immediate":   "immediate",
    "sofort":      "immediate",
    "1-3 months":  "1-3 months",
    "1-3 monate":  "1-3 months",
    "3-6 months":  "3-6 months",
    "3-6 monate":  "3-6 months",
    "exploratory": "exploratory",
    "explorativ":  "exploratory",
}

# Map lead.company_size (enriched text) to the size bucket keys in lead_scoring.
# lead_scoring expects: "500+", "200-500", "50-200", "10-50", "1-10"
_SIZE_KEYWORDS: list[tuple[str, str]] = [
    ("500",    "500+"),
    ("200",    "200-500"),
    ("50-200", "50-200"),
    ("51",     "50-200"),
    ("50",     "50-200"),
    ("10-50",  "10-50"),
    ("11",     "10-50"),
    ("1-10",   "1-10"),
]


def _infer_company_size_bucket(company_size: str | None) -> str:
    """
    Map the free-text ``company_size`` field (e.g. "50-200 employees (inferred)")
    to the bucket key expected by lead_scoring.  Falls back to "" (unknown) so
    lead_scoring uses its own default of 10 pts.
    """
    if not company_size:
        return ""
    lower = company_size.lower()
    for keyword, bucket in _SIZE_KEYWORDS:
        if keyword in lower:
            return bucket
    return ""


def _infer_urgency(timeline: str | None) -> str:
    """
    Map the lead's timeline field to an urgency string understood by lead_scoring.
    Falls back to "exploratory" (lowest urgency, 5 pts) when no match.
    """
    if not timeline:
        return "exploratory"
    return _TIMELINE_TO_URGENCY.get(timeline.strip().lower(), "exploratory")


def _parse_services_fit(services_interest: str | None) -> list[str]:
    """
    Parse the JSON-encoded services_interest text column into a list of strings
    compatible with the ``services_fit`` field in lead_scoring's qualification dict.
    Returns an empty list on any parse failure.
    """
    if not services_interest:
        return []
    try:
        parsed = json.loads(services_interest)
        if isinstance(parsed, list):
            return [str(s) for s in parsed if s]
        # Sometimes stored as a comma-separated string
        if isinstance(parsed, str):
            return [s.strip() for s in parsed.split(",") if s.strip()]
    except (json.JSONDecodeError, TypeError):
        # Plain comma-separated fallback
        return [s.strip() for s in services_interest.split(",") if s.strip()]
    return []


def _build_qualification(lead: Lead) -> dict[str, Any]:
    """
    Reconstruct a qualification dict from a Lead's persisted fields.

    lead_scoring expects:
      company_size_est: str   — size bucket
      services_fit:     list  — matched service names
      decision_maker:   bool  — not available from lead fields; default True
                                (conservative: we have no contrary evidence)
      urgency:          str   — derived from timeline
      confidence:       float — not stored post-qualification; default 0.7
                                (represents baseline confidence for active leads)
    """
    return {
        "company_size_est": _infer_company_size_bucket(lead.company_size),
        "services_fit":     _parse_services_fit(lead.services_interest),
        "decision_maker":   True,   # conservative default — no stored value
        "urgency":          _infer_urgency(lead.timeline),
        "confidence":       0.7,    # baseline for active leads that already passed intake
    }


class LeadScoringRefreshAgent(BaseAgent):
    """
    Nightly batch agent that re-runs lead scoring over all active leads.

    Designed to be triggered by the Celery beat schedule (e.g. 03:00 CET nightly)
    or called ad-hoc with a ``lead_ids`` override for admin correction runs.

    input_data keys
    ---------------
    lead_ids      : list[str]   optional — if provided, score only these leads
    dry_run       : bool        default False — compute scores but skip DB writes
    status_filter : list[str]   optional — override active status set

    output keys
    -----------
    total_leads   : int
    refreshed     : int         leads successfully re-scored (and written if not dry_run)
    failed        : int         leads that raised an exception during scoring
    dry_run       : bool
    results       : list[dict]  per-lead: lead_id, old_score, new_score, success
    """

    name = "lead_scoring_refresh"
    description = (
        "Nightly batch agent that re-runs lead scoring over all active leads "
        "to keep scores current. Active = status in "
        "[new, qualified, discovery_done, proposal_sent]."
    )
    permission_level = PermissionLevel.P1

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        dry_run: bool = bool(input_data.get("dry_run", False))
        active_statuses: list[str] = input_data.get(
            "status_filter", _DEFAULT_ACTIVE_STATUSES
        )
        requested_ids: list[str] | None = input_data.get("lead_ids") or None

        # ── 1. Resolve target leads ───────────────────────────────────────────
        db = context.db

        if requested_ids:
            result = await db.execute(
                select(Lead).where(Lead.id.in_(requested_ids))
            )
        else:
            result = await db.execute(
                select(Lead).where(Lead.status.in_(active_statuses))
            )
        leads: list[Lead] = result.scalars().all()

        total = len(leads)
        log.info(
            "lead_scoring_refresh.start",
            total_leads=total,
            dry_run=dry_run,
            status_filter=active_statuses,
            lead_ids_override=bool(requested_ids),
        )

        if total == 0:
            log.info("lead_scoring_refresh.no_leads")
            return AgentResult.ok(
                output={
                    "total_leads": 0,
                    "refreshed": 0,
                    "failed": 0,
                    "dry_run": dry_run,
                    "results": [],
                }
            )

        # ── 2. Local import — avoids circular import at module load ───────────
        from app.agents.registry import registry  # noqa: PLC0415

        scoring_agent = registry.get("lead_scoring")

        # ── 3. Score each lead ────────────────────────────────────────────────
        refreshed = 0
        failed = 0
        results: list[dict] = []

        for lead in leads:
            lead_id = lead.id
            old_score = lead.score

            if dry_run:
                # In dry_run mode we build the qualification dict and report
                # what lead_scoring would receive, but do not invoke the agent
                # and make no DB changes.
                qual = _build_qualification(lead)
                log.debug(
                    "lead_scoring_refresh.dry_run_skip",
                    lead_id=lead_id,
                    qualification=qual,
                )
                refreshed += 1
                results.append(
                    {
                        "lead_id": lead_id,
                        "old_score": old_score,
                        "new_score": None,  # not computed — dry_run
                        "success": True,
                        "dry_run": True,
                    }
                )
                continue

            # Live run — delegate to lead_scoring agent.
            try:
                qual = _build_qualification(lead)
                scoring_result = await scoring_agent(
                    context,
                    {
                        "lead_id": lead_id,
                        "qualification": qual,
                    },
                )

                if scoring_result.success:
                    new_score: float | None = None
                    if isinstance(scoring_result.output, dict):
                        new_score = scoring_result.output.get("score")

                    log.debug(
                        "lead_scoring_refresh.scored",
                        lead_id=lead_id,
                        old_score=old_score,
                        new_score=new_score,
                    )
                    refreshed += 1
                    results.append(
                        {
                            "lead_id": lead_id,
                            "old_score": old_score,
                            "new_score": new_score,
                            "success": True,
                        }
                    )
                else:
                    log.warning(
                        "lead_scoring_refresh.agent_failure",
                        lead_id=lead_id,
                        error=scoring_result.error,
                    )
                    failed += 1
                    results.append(
                        {
                            "lead_id": lead_id,
                            "old_score": old_score,
                            "new_score": None,
                            "success": False,
                            "error": scoring_result.error,
                        }
                    )

            except Exception as exc:  # noqa: BLE001
                log.error(
                    "lead_scoring_refresh.exception",
                    lead_id=lead_id,
                    error=str(exc),
                    exc_info=True,
                )
                failed += 1
                results.append(
                    {
                        "lead_id": lead_id,
                        "old_score": old_score,
                        "new_score": None,
                        "success": False,
                        "error": str(exc),
                    }
                )

        # ── 4. Summary log ────────────────────────────────────────────────────
        log.info(
            "lead_scoring_refresh.complete",
            total_leads=total,
            refreshed=refreshed,
            failed=failed,
            dry_run=dry_run,
        )

        return AgentResult.ok(
            output={
                "total_leads": total,
                "refreshed": refreshed,
                "failed": failed,
                "dry_run": dry_run,
                "results": results,
            }
        )
