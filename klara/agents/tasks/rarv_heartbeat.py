"""
app/tasks/rarv_heartbeat.py
────────────────────────────
RARV journal team heartbeat — every 30 min when wired into beat.

Picks up to BATCH_SIZE pending note_submissions rows, runs each
through the 4-agent pipeline, applies the verdict (DB update +
vault file write + git commit + push), and exits.

This task is the ONLY place where vault writes happen. The 4 agents
are pure analysis — this task is the IO layer.

Scheduling
----------
Not in any beat_schedule yet. When ready, add to
app/tasks/celery_app.py beat_schedule:

    "rarv-heartbeat": {
        "task": "app.tasks.rarv_heartbeat.run_heartbeat",
        "schedule": crontab(minute="*/30"),
        "options": {"queue": "default"},
    },

Concurrency
-----------
Claim phase uses SELECT ... FOR UPDATE SKIP LOCKED so two workers
cannot grab the same row. The claim transaction commits before the
processing transaction starts, so a worker crash mid-processing
leaves the row in 'claimed' status — the recovery sweep (see
_reclaim_stale below) re-queues claimed rows older than the lock
timeout.
"""
from __future__ import annotations

import asyncio
import base64
import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentContext
from app.agents.journal import (
    RARVReasonerAgent,
    RARVReflectorAgent,
    RARVVerifierAgent,
    RARVWriterAgent,
)
from app.config import get_settings
from app.database import db_context
from app.models.note_submission import NoteSubmission, SubmissionStatus
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

BATCH_SIZE_DEFAULT = 10
CLAIM_STALE_MINUTES = 30  # claimed rows older than this are re-queued

_GH_COMMITTER = {"name": "RARV Journal Team", "email": "rarv-journal@klaravex.de"}
_GH_API = "https://api.github.com"


# ════════════════════════════════════════════════════════════════════════
# Celery entry point
# ════════════════════════════════════════════════════════════════════════


@celery_app.task(
    name="app.tasks.rarv_heartbeat.run_heartbeat",
    bind=True,
    max_retries=0,  # heartbeat tolerates partial failure; next tick retries
)
def run_heartbeat(self, batch_size: int = BATCH_SIZE_DEFAULT) -> dict:
    """Celery sync wrapper. Returns a result summary for log/inspection."""
    try:
        return asyncio.run(_heartbeat(batch_size=int(batch_size)))
    except Exception as exc:
        logger.error("rarv_heartbeat.fatal", error=str(exc), exc_info=True)
        return {"ok": False, "error": str(exc), "processed": 0}


# ════════════════════════════════════════════════════════════════════════
# Orchestration
# ════════════════════════════════════════════════════════════════════════


async def _heartbeat(batch_size: int) -> dict:
    """Reclaim stale, claim a fresh batch, process each."""
    worker_id = _worker_id()
    summary = {
        "ok": True,
        "worker_id": worker_id,
        "reclaimed": 0,
        "claimed": 0,
        "written": 0,
        "rejected": 0,
        "failed": 0,
    }

    # 1. Reclaim stale 'claimed' rows from dead workers
    async with db_context() as db:
        summary["reclaimed"] = await _reclaim_stale(db)
        await db.commit()

    # 2. Claim a fresh batch
    async with db_context() as db:
        claimed_ids = await _claim_batch(db, batch_size, worker_id)
        await db.commit()
        summary["claimed"] = len(claimed_ids)

    # 3. Process each (separate tx per row — failure isolation)
    for sub_id in claimed_ids:
        try:
            outcome = await _process_one(sub_id)
            summary[outcome] = summary.get(outcome, 0) + 1
        except Exception as exc:
            logger.error(
                "rarv_heartbeat.process_one_exception",
                submission_id=sub_id,
                error=str(exc),
                exc_info=True,
            )
            summary["failed"] += 1
            async with db_context() as db:
                await _mark_failed(db, sub_id, f"unhandled: {exc}")
                await db.commit()

    logger.info("rarv_heartbeat.done", **summary)
    return summary


async def _process_one(sub_id: int) -> str:
    """
    Run the 4-agent pipeline against a single submission.

    Returns one of: 'written', 'rejected', 'failed'.
    """
    settings = get_settings()

    # Phase 1: 4 agents (each in their own short-lived db session)
    async with db_context() as db:
        ctx = AgentContext(db=db, settings=settings, request_id=str(sub_id))

        reasoner_res = await RARVReasonerAgent().run(ctx, {"submission_id": sub_id})
        if not reasoner_res.success:
            await _mark_failed(db, sub_id, reasoner_res.error or "reasoner exception")
            await db.commit()
            return "failed"

        if reasoner_res.output["decision"] == "reject":
            await _mark_rejected(
                db,
                sub_id,
                reasoner_res.output["reject_code"],
                reasoner_res.output["reason"],
            )
            await db.commit()
            return "rejected"

        writer_res = await RARVWriterAgent().run(ctx, {"submission_id": sub_id})
        if not writer_res.success:
            await _mark_failed(db, sub_id, writer_res.error or "writer exception")
            await db.commit()
            return "failed"

        # Mark as 'processing' for visibility while we do the slow IO bits below
        await _set_status(db, sub_id, SubmissionStatus.processing)
        await db.commit()

        reflector_res = await RARVReflectorAgent().run(
            ctx,
            {"submission_id": sub_id, "writer_output": writer_res.output},
        )
        if not reflector_res.success:
            await _mark_failed(db, sub_id, reflector_res.error or "reflector exception")
            await db.commit()
            return "failed"

        verifier_res = await RARVVerifierAgent().run(
            ctx,
            {
                "submission_id": sub_id,
                "writer_output": writer_res.output,
                "reflector_output": reflector_res.output,
            },
        )
        if not verifier_res.success:
            await _mark_failed(db, sub_id, verifier_res.error or "verifier exception")
            await db.commit()
            return "failed"

        if not verifier_res.output["go"]:
            await _mark_rejected(
                db,
                sub_id,
                verifier_res.output["reject_code"],
                verifier_res.output["reason"],
            )
            await db.commit()
            return "rejected"

    # Phase 2: vault write via GitHub Contents API (no filesystem access needed)
    vault_path = verifier_res.output["vault_path"]
    write_mode = verifier_res.output["write_mode"]
    full_md = writer_res.output["full_md"]
    note_kind = writer_res.output["frontmatter"]["note_kind"]
    topic_slug = writer_res.output["frontmatter"]["topic_slug"]
    submission_uuid = writer_res.output["frontmatter"]["submission_uuid"]

    commit_sha = await _write_to_github(
        token=settings.github_vault_token,
        repo=settings.github_vault_repo,
        branch=settings.github_vault_branch,
        vault_path=vault_path,
        write_mode=write_mode,
        full_md=full_md,
        note_kind=note_kind,
        topic_slug=topic_slug,
        submission_uuid=submission_uuid,
    )

    # Phase 3: mark written (final DB tx)
    async with db_context() as db:
        await _mark_written(db, sub_id, vault_path, commit_sha)
        await db.commit()

    return "written"


# ════════════════════════════════════════════════════════════════════════
# DB helpers — all small focused mutations
# ════════════════════════════════════════════════════════════════════════


async def _reclaim_stale(db: AsyncSession) -> int:
    """Re-queue rows stuck in 'claimed' or 'processing' older than the lock timeout."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=CLAIM_STALE_MINUTES)
    stmt = (
        update(NoteSubmission)
        .where(
            NoteSubmission.status.in_(
                [SubmissionStatus.claimed, SubmissionStatus.processing]
            )
        )
        .where(NoteSubmission.claimed_at < cutoff)
        .values(
            status=SubmissionStatus.pending,
            claimed_by=None,
            claimed_at=None,
        )
    )
    result = await db.execute(stmt)
    return result.rowcount or 0


async def _claim_batch(
    db: AsyncSession, batch_size: int, worker_id: str
) -> list[int]:
    """Atomically claim up to batch_size pending rows."""
    # SELECT FOR UPDATE SKIP LOCKED so concurrent workers don't grab the same rows.
    stmt = (
        select(NoteSubmission.id)
        .where(NoteSubmission.status == SubmissionStatus.pending)
        .order_by(NoteSubmission.priority.desc(), NoteSubmission.created_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    ids = [row for row in (await db.execute(stmt)).scalars().all()]
    if not ids:
        return []

    now = datetime.now(timezone.utc)
    upd = (
        update(NoteSubmission)
        .where(NoteSubmission.id.in_(ids))
        .values(
            status=SubmissionStatus.claimed,
            claimed_by=worker_id,
            claimed_at=now,
            journal_team_attempts=NoteSubmission.journal_team_attempts + 1,
        )
    )
    await db.execute(upd)
    return ids


async def _set_status(db: AsyncSession, sub_id: int, status: str) -> None:
    stmt = (
        update(NoteSubmission)
        .where(NoteSubmission.id == sub_id)
        .values(status=status, updated_at=datetime.now(timezone.utc))
    )
    await db.execute(stmt)


async def _mark_rejected(
    db: AsyncSession, sub_id: int, reject_code: str, reason: Optional[str]
) -> None:
    stmt = (
        update(NoteSubmission)
        .where(NoteSubmission.id == sub_id)
        .values(
            status=SubmissionStatus.rejected,
            reject_code=reject_code,
            rejection_reason=reason,
            processed_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.execute(stmt)


async def _mark_failed(db: AsyncSession, sub_id: int, error: str) -> None:
    """Decide if retry-eligible or terminal-failed based on attempts."""
    # Fetch current attempts to decide whether to flip terminal
    row = (
        await db.execute(
            select(
                NoteSubmission.journal_team_attempts, NoteSubmission.max_attempts
            ).where(NoteSubmission.id == sub_id)
        )
    ).one_or_none()
    if row is None:
        return

    attempts, max_attempts = row
    terminal = attempts >= max_attempts

    stmt = (
        update(NoteSubmission)
        .where(NoteSubmission.id == sub_id)
        .values(
            status=SubmissionStatus.failed if terminal else SubmissionStatus.pending,
            rejection_reason=error[:1000],
            processed_at=datetime.now(timezone.utc) if terminal else None,
            claimed_by=None,
            claimed_at=None,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.execute(stmt)


async def _mark_written(
    db: AsyncSession, sub_id: int, vault_path: str, commit_sha: str
) -> None:
    stmt = (
        update(NoteSubmission)
        .where(NoteSubmission.id == sub_id)
        .values(
            status=SubmissionStatus.written,
            vault_path=vault_path,
            commit_sha=commit_sha,
            processed_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.execute(stmt)


# ════════════════════════════════════════════════════════════════════════
# GitHub Contents API helpers
# ════════════════════════════════════════════════════════════════════════


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


async def _gh_get_file(
    client: httpx.AsyncClient,
    headers: dict,
    repo: str,
    branch: str,
    path: str,
) -> tuple[str | None, str | None]:
    """
    Fetch an existing vault file.
    Returns (current_content_str, sha) or (None, None) if not found.
    """
    url = f"{_GH_API}/repos/{repo}/contents/{path}"
    resp = await client.get(url, headers=headers, params={"ref": branch})
    if resp.status_code == 404:
        return None, None
    resp.raise_for_status()
    data = resp.json()
    existing = base64.b64decode(data["content"]).decode("utf-8")
    return existing, data["sha"]


async def _write_to_github(
    *,
    token: str,
    repo: str,
    branch: str,
    vault_path: str,
    write_mode: str,
    full_md: str,
    note_kind: str,
    topic_slug: str,
    submission_uuid: str,
) -> str:
    """
    Create or update a file in the loki-vault GitHub repo via the Contents API.

    write_mode='replace' overwrites the file.
    write_mode='append'  appends to the existing content (or creates new).

    Returns the commit SHA.
    Raises RuntimeError on any API failure.
    """
    if not token:
        raise RuntimeError(
            "GITHUB_VAULT_TOKEN not configured — cannot write to vault"
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    commit_msg = f"rarv: {note_kind} -- {topic_slug} ({submission_uuid[:8]})"

    async with httpx.AsyncClient(timeout=30.0) as client:
        existing_content, file_sha = await _gh_get_file(
            client, headers, repo, branch, vault_path
        )

        if write_mode == "replace":
            new_content = full_md
        elif write_mode == "append":
            if existing_content:
                sep = "\n\n" if not existing_content.endswith("\n\n") else ""
                new_content = existing_content + sep + full_md
            else:
                new_content = full_md
        else:
            raise ValueError(f"unknown write_mode: {write_mode!r}")

        body: dict = {
            "message": commit_msg,
            "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
            "branch": branch,
            "committer": _GH_COMMITTER,
        }
        if file_sha:
            body["sha"] = file_sha

        url = f"{_GH_API}/repos/{repo}/contents/{vault_path}"
        resp = await client.put(url, headers=headers, json=body)

        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"GitHub API error {resp.status_code}: {resp.text[:300]}"
            )

        commit_sha: str = resp.json()["commit"]["sha"]
        logger.info(
            "rarv_heartbeat.github_write_ok",
            vault_path=vault_path,
            commit_sha=commit_sha[:12],
            write_mode=write_mode,
        )
        return commit_sha
