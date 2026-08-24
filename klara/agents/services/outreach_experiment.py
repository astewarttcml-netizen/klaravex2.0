"""
app/services/outreach_experiment.py
────────────────────────────────────
phase15-001 — wire the Phase 14 A/B framework into prospecting_outreach.

Auto-seeds an "outreach_subject_v1" experiment with two arms (control,
variant) if not present. Returns the assigned arm name for a given
prospect_id. The agent appends the arm hint to its prompt so Claude
can tailor the subject line.

Idempotent — the seeding step uses ON CONFLICT DO NOTHING so concurrent
agents racing to seed produce the same outcome.
"""
from __future__ import annotations

from typing import Optional
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.experiments import Experiment, ExperimentArm, ExperimentStatus
from klara.rarv.runtime.experiments import assign_arm

logger = structlog.get_logger(__name__)


EXPERIMENT_NAME = "outreach_subject_v1"
ARM_CONTROL = "control"
ARM_VARIANT = "punchy_question"


async def _ensure_experiment(db: AsyncSession) -> str:
    """Return the experiment_id, creating the row + arms if missing."""
    exp_q = await db.execute(
        select(Experiment).where(Experiment.name == EXPERIMENT_NAME)
    )
    exp = exp_q.scalar_one_or_none()
    if exp is not None:
        return exp.id

    # Seed experiment + 2 arms. Race-safe via ON CONFLICT DO NOTHING.
    exp_id = str(uuid4())
    await db.execute(
        pg_insert(Experiment)
        .values(
            id=exp_id,
            name=EXPERIMENT_NAME,
            description="Cold outreach subject line — control vs question-style variant.",
            status=ExperimentStatus.active,
        )
        .on_conflict_do_nothing(index_elements=["name"])
    )
    # Re-fetch the canonical id (could be ours or a racing peer's)
    exp_q = await db.execute(
        select(Experiment).where(Experiment.name == EXPERIMENT_NAME)
    )
    exp = exp_q.scalar_one_or_none()
    if exp is None:
        # Should not happen — log and return our id as best-effort
        return exp_id
    exp_id = exp.id

    # Seed arms — idempotent by (experiment_id, name)
    existing_arms_q = await db.execute(
        select(ExperimentArm).where(ExperimentArm.experiment_id == exp_id)
    )
    existing = {a.name for a in existing_arms_q.scalars()}
    for arm_name in (ARM_CONTROL, ARM_VARIANT):
        if arm_name not in existing:
            db.add(ExperimentArm(
                id=str(uuid4()),
                experiment_id=exp_id,
                name=arm_name,
                weight=1,
            ))
    await db.flush()
    return exp_id


async def variant_hint_for(
    db: AsyncSession,
    prospect_id: str,
) -> Optional[str]:
    """
    Return a one-line hint to feed Claude based on which arm the
    prospect was assigned to. None if assignment fails (caller should
    proceed with the control prompt).
    """
    try:
        exp_id = await _ensure_experiment(db)
        arm = await assign_arm(db, exp_id, prospect_id)
        if arm is None:
            return None
        if arm.name == ARM_VARIANT:
            return (
                "Subject-line variant: make the subject a punchy one-line "
                "question (no greeting, max 8 words). Example: "
                '"30 minutes to fix your Azure spend?"'
            )
        return None   # control = no hint
    except Exception as exc:
        logger.warning(
            "outreach_experiment.assignment_failed",
            prospect_id=prospect_id,
            error=str(exc),
        )
        return None
