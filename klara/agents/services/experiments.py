"""
app/services/experiments.py
────────────────────────────
phase14-001 — A/B experiment variant assignment.

Deterministic by subject_key: the same prospect/lead/whatever always
lands on the same arm. Uses a hash of (experiment_id || subject_key)
mapped into the cumulative-weight space of the experiment's arms.

assign_arm() is idempotent: looks up an existing assignment first,
falls back to compute + insert. ON CONFLICT DO NOTHING guards against
concurrent first-time assigners.
"""
from __future__ import annotations

import hashlib
from typing import Optional
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.experiments import (
    ExperimentArm,
    ExperimentAssignment,
)

logger = structlog.get_logger(__name__)


def _hash_to_unit(experiment_id: str, subject_key: str) -> float:
    """Hash (experiment_id, subject_key) → float in [0.0, 1.0)."""
    h = hashlib.sha256(f"{experiment_id}|{subject_key}".encode("utf-8")).digest()
    # First 8 bytes as unsigned int, divided by 2^64
    n = int.from_bytes(h[:8], "big")
    return n / (1 << 64)


async def assign_arm(
    db: AsyncSession,
    experiment_id: str,
    subject_key: str,
) -> Optional[ExperimentArm]:
    """
    Return the arm assigned for (experiment_id, subject_key).

    On first call for a key: compute via weighted hash, persist, return arm.
    On subsequent calls: return the same arm (idempotent).

    Returns None if the experiment has no arms.
    """
    # Existing assignment?
    existing_q = await db.execute(
        select(ExperimentAssignment).where(
            ExperimentAssignment.experiment_id == experiment_id,
            ExperimentAssignment.subject_key == subject_key,
        )
    )
    existing = existing_q.scalar_one_or_none()
    if existing is not None:
        arm_q = await db.execute(
            select(ExperimentArm).where(ExperimentArm.id == existing.arm_id)
        )
        return arm_q.scalar_one_or_none()

    # Load arms (ordered by id for determinism)
    arms_q = await db.execute(
        select(ExperimentArm)
        .where(ExperimentArm.experiment_id == experiment_id)
        .order_by(ExperimentArm.id)
    )
    arms = list(arms_q.scalars().all())
    if not arms:
        return None

    total_weight = sum(max(0, a.weight) for a in arms)
    if total_weight <= 0:
        # Fall back to equal split
        total_weight = len(arms)
        weights = [1.0 for _ in arms]
    else:
        weights = [max(0, a.weight) for a in arms]

    target = _hash_to_unit(experiment_id, subject_key) * total_weight
    cumulative = 0.0
    chosen = arms[0]
    for arm, w in zip(arms, weights):
        cumulative += w
        if target < cumulative:
            chosen = arm
            break

    # Persist — ON CONFLICT DO NOTHING handles race conditions
    stmt = (
        pg_insert(ExperimentAssignment)
        .values(
            id=str(uuid4()),
            experiment_id=experiment_id,
            arm_id=chosen.id,
            subject_key=subject_key,
        )
        .on_conflict_do_nothing(
            index_elements=["experiment_id", "subject_key"],
        )
    )
    await db.execute(stmt)
    await db.flush()

    logger.info(
        "experiments.assigned",
        experiment_id=experiment_id,
        subject_key=subject_key,
        arm=chosen.name,
    )
    return chosen
