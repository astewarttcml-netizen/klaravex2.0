"""
app/services/prompt_registry.py
────────────────────────────────
phase12-002 — capture each unique agent prompt with SHA-256 checksum.

Idempotent INSERT — same (agent, prompt_name, checksum) triple is a no-op.
First time we see a new checksum, we record it with first_seen_at = now.
Useful for: drift detection, A/B comparisons, prompt audits.

Never raises — registration failures should not break agents.
"""
from __future__ import annotations

import hashlib
from uuid import uuid4

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.prompt_quality import PromptVersion

logger = structlog.get_logger(__name__)


def compute_checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def register_prompt(
    db: AsyncSession,
    *,
    agent_name: str,
    prompt_name: str,
    content: str,
) -> None:
    if not content:
        return
    try:
        checksum = compute_checksum(content)
        stmt = (
            pg_insert(PromptVersion)
            .values(
                id=str(uuid4()),
                agent_name=agent_name,
                prompt_name=prompt_name,
                checksum=checksum,
                content=content,
            )
            .on_conflict_do_nothing(
                index_elements=["agent_name", "prompt_name", "checksum"],
            )
        )
        async with db.begin_nested():
            await db.execute(stmt)
    except Exception as exc:
        logger.warning(
            "prompt_registry.register_failed",
            agent_name=agent_name,
            prompt_name=prompt_name,
            error=str(exc),
        )
