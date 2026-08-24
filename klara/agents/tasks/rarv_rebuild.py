"""
app/tasks/rarv_rebuild.py
──────────────────────────
RARV knowledge-base rebuilds: nightly + monthly.

NIGHTLY (02:00 Berlin every day)
    Reads daily/*.md from klaravex-vault (GitHub Contents API), composes
    a refreshed MEMORY.md, and writes it back via the same API.

MONTHLY (04:00 Berlin on the 1st of each month)
    Full re-derivation: reads the entire daily/ history and rebuilds
    MEMORY.md plus a topics/_monthly_rebuild.md marker.

Both tasks are idempotent — they skip the GitHub write when content is
unchanged, and produce no commit if there is no diff.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog

from klara.rarv.runtime import get_settings
from klara.rarv.runtime import celery_app
from klara.rarv.tasks.rarv_heartbeat import _GH_API, _GH_COMMITTER, _gh_get_file

logger = structlog.get_logger(__name__)

NIGHTLY_WINDOW_DAYS = 30


# ════════════════════════════════════════════════════════════════════════
# Celery entry points
# ════════════════════════════════════════════════════════════════════════


@celery_app.task(
    name="klara.rarv.tasks.rarv_rebuild.run_nightly_rebuild",
    bind=True,
    max_retries=1,
    default_retry_delay=600,  # 10 min retry
)
def run_nightly_rebuild(self) -> dict:
    """02:00 Berlin -- rebuild MEMORY.md from trailing 30 days of dailies."""
    try:
        return asyncio.run(_nightly())
    except Exception as exc:
        logger.error("rarv_rebuild.nightly.failed", error=str(exc), exc_info=True)
        try:
            raise self.retry(exc=exc)
        except Exception:
            return {"ok": False, "error": str(exc)}


@celery_app.task(
    name="klara.rarv.tasks.rarv_rebuild.run_monthly_rebuild",
    bind=True,
    max_retries=1,
    default_retry_delay=900,  # 15 min retry
)
def run_monthly_rebuild(self) -> dict:
    """04:00 Berlin day 1 -- full re-derivation of knowledge/ tree."""
    try:
        return asyncio.run(_monthly())
    except Exception as exc:
        logger.error("rarv_rebuild.monthly.failed", error=str(exc), exc_info=True)
        try:
            raise self.retry(exc=exc)
        except Exception:
            return {"ok": False, "error": str(exc)}


# ════════════════════════════════════════════════════════════════════════
# Async implementations
# ════════════════════════════════════════════════════════════════════════


async def _nightly() -> dict:
    settings = get_settings()
    cutoff = date.today() - timedelta(days=NIGHTLY_WINDOW_DAYS)

    days_content = await _gh_list_and_read_dailies(
        token=settings.github_vault_token,
        repo=settings.github_vault_repo,
        branch=settings.github_vault_branch,
        since=cutoff,
    )

    body = _compose_memory_md(days_content)
    commit_sha = await _gh_write_if_changed(
        token=settings.github_vault_token,
        repo=settings.github_vault_repo,
        branch=settings.github_vault_branch,
        path="MEMORY.md",
        new_content=body,
        message=f"rarv: nightly rebuild -- MEMORY.md ({len(days_content)} day(s))",
    )

    if commit_sha is None:
        logger.info("rarv_rebuild.nightly.no_diff", days=len(days_content))
        return {"ok": True, "wrote": False, "days_considered": len(days_content)}

    logger.info("rarv_rebuild.nightly.done", days=len(days_content), commit_sha=commit_sha)
    return {
        "ok": True,
        "wrote": True,
        "days_considered": len(days_content),
        "commit_sha": commit_sha,
    }


async def _monthly() -> dict:
    settings = get_settings()

    all_days_content = await _gh_list_and_read_dailies(
        token=settings.github_vault_token,
        repo=settings.github_vault_repo,
        branch=settings.github_vault_branch,
        since=None,
    )

    body = _compose_memory_md(all_days_content, header_suffix=" (monthly full)")
    memory_sha = await _gh_write_if_changed(
        token=settings.github_vault_token,
        repo=settings.github_vault_repo,
        branch=settings.github_vault_branch,
        path="MEMORY.md",
        new_content=body,
        message=f"rarv: monthly rebuild ({len(all_days_content)} day(s) re-derived)",
    )

    marker_body = _monthly_marker(all_days_content)
    marker_sha = await _gh_write_if_changed(
        token=settings.github_vault_token,
        repo=settings.github_vault_repo,
        branch=settings.github_vault_branch,
        path="topics/_monthly_rebuild.md",
        new_content=marker_body,
        message=f"rarv: monthly rebuild marker ({len(all_days_content)} day(s))",
    )

    commit_sha = memory_sha or marker_sha
    logger.info("rarv_rebuild.monthly.done", days=len(all_days_content), commit_sha=commit_sha)
    return {
        "ok": True,
        "days_considered": len(all_days_content),
        "commit_sha": commit_sha,
    }


# ════════════════════════════════════════════════════════════════════════
# GitHub API helpers
# ════════════════════════════════════════════════════════════════════════


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _gh_list_and_read_dailies(
    *,
    token: str,
    repo: str,
    branch: str,
    since: Optional[date],
) -> list[tuple[date, str]]:
    """
    List daily/*.md from GitHub, filter by date, return [(date, content), ...] sorted ascending.
    """
    headers = _gh_headers(token)
    results: list[tuple[date, str]] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{_GH_API}/repos/{repo}/contents/daily"
        resp = await client.get(url, headers=headers, params={"ref": branch})
        if resp.status_code == 404:
            return []
        resp.raise_for_status()

        for entry in resp.json():
            name = entry.get("name", "")
            if not name.endswith(".md"):
                continue
            try:
                d = date.fromisoformat(name[:-3])
            except ValueError:
                continue
            if since and d < since:
                continue

            content, _ = await _gh_get_file(client, headers, repo, branch, f"daily/{name}")
            if content is not None:
                results.append((d, content))

    results.sort(key=lambda x: x[0])
    return results


async def _gh_write_if_changed(
    *,
    token: str,
    repo: str,
    branch: str,
    path: str,
    new_content: str,
    message: str,
) -> Optional[str]:
    """Write to GitHub only if content differs. Returns commit SHA or None."""
    headers = _gh_headers(token)

    async with httpx.AsyncClient(timeout=30.0) as client:
        existing_content, file_sha = await _gh_get_file(
            client, headers, repo, branch, path
        )
        if existing_content == new_content:
            return None

        body: dict = {
            "message": message,
            "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
            "branch": branch,
            "committer": _GH_COMMITTER,
        }
        if file_sha:
            body["sha"] = file_sha

        url = f"{_GH_API}/repos/{repo}/contents/{path}"
        resp = await client.put(url, headers=headers, json=body)
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"GitHub API error {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json()["commit"]["sha"]


# ════════════════════════════════════════════════════════════════════════
# Composition helpers
# ════════════════════════════════════════════════════════════════════════


def _compose_memory_md(
    days_content: list[tuple[date, str]],
    header_suffix: str = "",
) -> str:
    when = _now_berlin_iso()
    header = (
        f"# Memory -- Long-Term Knowledge{header_suffix}\n\n"
        f"> Curated, durable facts extracted from `daily/` notes.\n"
        f"> Last rebuilt: **{when}** by the RARV journal team.\n"
        f"> Source span: {len(days_content)} daily note(s).\n"
        f"> Do not edit by hand -- manual changes will be overwritten on next rebuild.\n\n"
    )

    if not days_content:
        return header + "## Topics\n\n(empty -- no daily notes in window)\n"

    parts = ["## Daily-note source span\n"]
    for d, _ in days_content:
        parts.append(f"- {d.isoformat()}")
    parts.append("")
    parts.append("## Aggregated content\n")
    for d, content in days_content:
        parts.append(f"### {d.isoformat()}\n")
        parts.append(content.strip())
        parts.append("")
    return header + "\n".join(parts) + "\n"


def _monthly_marker(all_days_content: list[tuple[date, str]]) -> str:
    when = _now_berlin_iso()
    first = all_days_content[0][0].isoformat() if all_days_content else "(none)"
    last = all_days_content[-1][0].isoformat() if all_days_content else "(none)"
    return (
        f"# Monthly Rebuild Marker\n\n"
        f"> Records the last full monthly re-derivation pass.\n"
        f"> Updated by app/tasks/rarv_rebuild.run_monthly_rebuild.\n\n"
        f"- **Last rebuild:** {when}\n"
        f"- **Daily notes considered:** {len(all_days_content)}\n"
        f"- **Span:** {first} -> {last}\n"
    )


def _now_berlin_iso() -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
