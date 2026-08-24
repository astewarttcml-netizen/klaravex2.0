"""
app/services/autonomy_promotion_runner.py
──────────────────────────────────────────
phase19-010 — Autonomy promotion runner.

Daily sweep that:
  1. Reads today's per-agent status_color from autonomy_metrics
     (phase3-003 logic, called directly to avoid an HTTP self-loop)
  2. Updates the AutonomyStreak row for each agent
  3. When green has held for GREEN_STREAK_DAYS_REQUIRED (=14) days AND
     no promotion ApprovalRequest is already pending, emits one
     (action='autonomy.promote', risk_level=P4) for Anthony to review

Approval EXECUTION is out of scope here — that's the standard P4
approval execution pipeline. When approved, a follow-up task writes
the AutonomyPromotion ledger row and flips the agent's flag. The
runner's only job is to PROPOSE promotions.

Design notes
------------
- evaluate_streak() is a pure function: takes (current_color,
  prior_streak, now) -> StreakDecision. No I/O. Testable in isolation.
- The orchestrating async wrapper run_promotion_sweep() applies the
  decisions: upserts AutonomyStreak rows and creates the P4
  ApprovalRequest when the decision is 'promote'.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Literal, Optional
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.approval import ApprovalRequest, ApprovalStatus, RiskLevel
from klara.rarv.autonomy_streak import AutonomyStreak

logger = structlog.get_logger(__name__)


# How many continuous days of 'green' status_color before the runner proposes
# a P3 -> P2 promotion. The PRD §17 phrasing is "remain acceptable over
# time"; this constant is the operational interpretation.
GREEN_STREAK_DAYS_REQUIRED = 14

GREEN = "green"


StreakAction = Literal[
    "start_streak",    # first time we've seen this agent — record current_color
    "extend_streak",   # color unchanged, streak continues, not yet 14 days
    "reset_streak",    # color changed (green -> amber/red, or vice versa)
    "promote",         # green streak >= 14 days, no promotion in-flight
    "noop",            # green streak >= 14 days BUT promotion already pending
]


@dataclass
class StreakDecision:
    agent_name: str
    action: StreakAction
    streak_days: int
    current_color: str


def evaluate_streak(
    agent_name: str,
    current_color: str,
    prior_streak: Optional[AutonomyStreak],
    now: datetime,
) -> StreakDecision:
    """
    Pure function — decides what the runner should do for one agent based
    on today's color and the prior streak record.

    Inputs are normalised by the caller (current_color is the value from
    autonomy_metrics for this agent in this sweep).
    """
    # No prior record — start tracking
    if prior_streak is None:
        return StreakDecision(agent_name, "start_streak", 0, current_color)

    # Color changed — reset streak
    if prior_streak.current_color != current_color:
        return StreakDecision(agent_name, "reset_streak", 0, current_color)

    # Color unchanged. If not green, nothing actionable — just bump the streak.
    if current_color != GREEN:
        days = (now.date() - prior_streak.streak_started_at.date()).days
        return StreakDecision(agent_name, "extend_streak", days, current_color)

    # Green streak — count days
    days = (now.date() - prior_streak.streak_started_at.date()).days

    if days < GREEN_STREAK_DAYS_REQUIRED:
        return StreakDecision(agent_name, "extend_streak", days, current_color)

    # Eligible for promotion. Don't re-request while one is pending.
    if prior_streak.pending_promotion_approval_id is not None:
        return StreakDecision(agent_name, "noop", days, current_color)

    return StreakDecision(agent_name, "promote", days, current_color)


async def _upsert_streak(
    db: AsyncSession,
    agent_name: str,
    current_color: str,
    streak_started_at: datetime,
    now: datetime,
    pending_approval_id: Optional[str] = None,
) -> AutonomyStreak:
    """Insert or update the AutonomyStreak row for `agent_name`."""
    q = await db.execute(
        select(AutonomyStreak).where(AutonomyStreak.agent_name == agent_name)
    )
    row = q.scalar_one_or_none()
    if row is None:
        row = AutonomyStreak(
            id=str(uuid4()),
            agent_name=agent_name,
            current_color=current_color,
            streak_started_at=streak_started_at,
            last_checked_at=now,
            pending_promotion_approval_id=pending_approval_id,
        )
        db.add(row)
    else:
        row.current_color = current_color
        row.streak_started_at = streak_started_at
        row.last_checked_at = now
        if pending_approval_id is not None:
            row.pending_promotion_approval_id = pending_approval_id
    return row


async def _create_promotion_approval(
    db: AsyncSession,
    agent_name: str,
    streak_days: int,
    now: datetime,
) -> ApprovalRequest:
    """Create a P4 ApprovalRequest proposing P3 -> P2 promotion."""
    approval = ApprovalRequest(
        id=str(uuid4()),
        action_name="autonomy.promote",
        risk_level=RiskLevel.p4.value,
        payload=json.dumps({
            "agent_name":   agent_name,
            "from_level":   "P3",
            "to_level":     "P2",
            "streak_days":  streak_days,
            "reason":       "green_streak_threshold_reached",
        }, ensure_ascii=False),
        justification=(
            f"Agent {agent_name!r} has maintained status_color='green' for "
            f"{streak_days} consecutive days in autonomy_metrics. PRD §17 "
            f"threshold: promote P3 -> P2 (auto-execute without approval) "
            f"once metrics remain acceptable over time."
        ),
        requested_by_agent="autonomy_promotion_runner",
        lead_id=None,
        conversation_id=None,
        status=ApprovalStatus.pending.value,
        created_at=now,
    )
    db.add(approval)
    return approval


async def apply_decision(
    db: AsyncSession,
    decision: StreakDecision,
    prior_streak: Optional[AutonomyStreak],
    now: datetime,
) -> Optional[ApprovalRequest]:
    """
    Apply a StreakDecision to the DB. Returns the created ApprovalRequest
    when the decision is 'promote', else None.

    Side effects:
      - upserts the AutonomyStreak row
      - creates a P4 ApprovalRequest when promoting, and links its id
        back on the streak row
    """
    if decision.action == "noop":
        # Just bump last_checked_at.
        if prior_streak is not None:
            prior_streak.last_checked_at = now
        return None

    # Determine streak_started_at for the upsert:
    #   - start_streak: now
    #   - reset_streak: now (color flipped)
    #   - extend_streak / promote: keep prior streak start
    if decision.action in ("start_streak", "reset_streak"):
        started_at = now
    else:
        assert prior_streak is not None
        started_at = prior_streak.streak_started_at

    approval = None
    pending_id = None
    if decision.action == "promote":
        approval = await _create_promotion_approval(
            db, decision.agent_name, decision.streak_days, now,
        )
        pending_id = approval.id

    await _upsert_streak(
        db, decision.agent_name,
        current_color=decision.current_color,
        streak_started_at=started_at,
        now=now,
        pending_approval_id=pending_id,
    )
    return approval


async def run_promotion_sweep(
    db: AsyncSession,
    agent_status: Iterable[tuple[str, str]],
    now: Optional[datetime] = None,
) -> dict:
    """
    Run the daily promotion sweep.

    `agent_status` is an iterable of (agent_name, current_color) tuples —
    the caller is responsible for sourcing this (typically by calling
    autonomy_metrics(days=30, db) and projecting `(a.agent_name,
    a.status_color)` from the response).

    Returns a summary dict with counts of each decision type and a list
    of agents that received a fresh promotion ApprovalRequest in this
    sweep (useful for the daily_report alert).
    """
    now = now or datetime.now(timezone.utc)

    summary = {
        "checked": 0,
        "start_streak": 0,
        "extend_streak": 0,
        "reset_streak": 0,
        "promote": 0,
        "noop": 0,
        "promoted_agents": [],
    }

    for agent_name, current_color in agent_status:
        summary["checked"] += 1

        q = await db.execute(
            select(AutonomyStreak).where(AutonomyStreak.agent_name == agent_name)
        )
        prior = q.scalar_one_or_none()

        decision = evaluate_streak(agent_name, current_color, prior, now)
        summary[decision.action] += 1

        await apply_decision(db, decision, prior, now)

        if decision.action == "promote":
            summary["promoted_agents"].append({
                "agent_name":  agent_name,
                "streak_days": decision.streak_days,
            })

    logger.info("autonomy_promotion_sweep.complete", **{
        k: v for k, v in summary.items() if k != "promoted_agents"
    }, promoted_count=len(summary["promoted_agents"]))
    return summary
