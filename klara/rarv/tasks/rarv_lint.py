"""
app/tasks/rarv_lint.py
────────────────────────
RARV vault health check — weekly (Sunday 20:00 Berlin).

Adapted from the "second-brain" method's /lint operation, but this vault
has no wikilink graph (knowledge/context pages are topic-keyed append
logs, not free-form cross-linked wiki pages -- see README.md), so the
checks below are shaped around what's actually meaningful here instead
of a literal port of "orphan pages with no incoming links":

  - STALE topic files: no new entry in STALE_DAYS -- either a genuinely
    resolved topic, or a topic nothing is watching anymore.
  - UNCOVERED topic slugs: a topic_slug exists in the documented taxonomy
    (CLAUDE.md) but has zero knowledge/ or context/ entries ever -- the
    closest equivalent to "orphan page" for this structure.
  - OVERSIZED topic files: a single topic file has grown past
    SIZE_WARN_BYTES -- candidate for splitting or periodic compaction
    (context/infra-ops.md hit 11MB before this check existed).
  - UNPOPULATED structural folders: agents/ and topics/ are documented
    in README.md as real, in-use paths but may sit empty except
    .gitkeep -- surfaced so it's a known state, not a silent gap.
  - MONTHLY REBUILD STALENESS: topics/_monthly_rebuild.md should update
    on the 1st of each month (rarv_rebuild.run_monthly_rebuild) -- flag
    if it's missing or older than ~40 days.

This task does NOT attempt contradiction detection (would need an LLM
pass over pairs of entries -- left as a follow-up, not built here) or
wikilink-graph analysis (the vault doesn't use wikilinks).

Output: topics/_lint_report.md, write_mode=replace (point-in-time
health snapshot, not history -- same category as knowledge/agents/*.md).
"""
from __future__ import annotations

import asyncio
import base64
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog

from app.config import get_settings
from app.tasks.celery_app import celery_app
from app.tasks.rarv_heartbeat import _GH_API, _GH_COMMITTER, _gh_get_file

logger = structlog.get_logger(__name__)

STALE_DAYS = 30
MONTHLY_MARKER_STALE_DAYS = 40
SIZE_WARN_BYTES = 2_000_000  # 2MB -- infra-ops hit 11MB before this existed

# Canonical topic_slug taxonomy (CLAUDE.md / note-submit tool schema).
KNOWN_TOPIC_SLUGS = [
    "deployment", "schema-change", "config-change", "code-edit", "decision",
    "error-resolution", "observation", "directive", "audit-finding",
    "api-integration", "vault-mcp", "loki-agent", "infra-ops", "policy-edit",
    "read-finding", "sub-agent-finding",
]


@celery_app.task(
    name="app.tasks.rarv_lint.run_weekly_lint",
    bind=True,
    max_retries=1,
    default_retry_delay=600,
)
def run_weekly_lint(self) -> dict:
    """Sunday 20:00 Berlin -- vault health check, writes topics/_lint_report.md."""
    try:
        return asyncio.run(_lint())
    except Exception as exc:
        logger.error("rarv_lint.failed", error=str(exc), exc_info=True)
        try:
            raise self.retry(exc=exc)
        except Exception:
            return {"ok": False, "error": str(exc)}


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _gh_get_tree(client: httpx.AsyncClient, headers: dict, repo: str, branch: str) -> list[dict]:
    """Full recursive file listing via the git trees API (one call, not a directory walk)."""
    ref_resp = await client.get(f"{_GH_API}/repos/{repo}/git/ref/heads/{branch}", headers=headers)
    ref_resp.raise_for_status()
    commit_sha = ref_resp.json()["object"]["sha"]

    commit_resp = await client.get(f"{_GH_API}/repos/{repo}/git/commits/{commit_sha}", headers=headers)
    commit_resp.raise_for_status()
    tree_sha = commit_resp.json()["tree"]["sha"]

    tree_resp = await client.get(
        f"{_GH_API}/repos/{repo}/git/trees/{tree_sha}",
        headers=headers,
        params={"recursive": "1"},
    )
    tree_resp.raise_for_status()
    return tree_resp.json().get("tree", [])


def _extract_frontmatter_field(content: str, field: str) -> Optional[str]:
    """Cheap single-field frontmatter scrape -- avoids a full YAML parser dependency."""
    if not content.startswith("---"):
        return None
    end = content.find("\n---", 3)
    if end == -1:
        return None
    fm_block = content[3:end]
    for line in fm_block.splitlines():
        line = line.strip()
        if line.startswith(f"{field}:"):
            return line.split(":", 1)[1].strip().strip('"')
    return None


def _last_entry_created_at(content: str) -> Optional[datetime]:
    """
    For an append-mode topic file (multiple frontmatter blocks stacked),
    the LAST entry is what we care about for staleness -- find the last
    '---' frontmatter block and read its created_at.
    """
    blocks = content.split("\n---\n")
    # blocks alternate: [pre, fm1, body1_and_fm2_start, ...] -- simplest robust
    # approach: find all created_at occurrences, take the last one.
    dates = []
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("created_at:"):
            raw = line.split(":", 1)[1].strip().strip('"')
            try:
                dates.append(datetime.fromisoformat(raw.replace("Z", "+00:00")))
            except ValueError:
                continue
    return max(dates) if dates else None


async def _lint() -> dict:
    settings = get_settings()
    headers = _gh_headers(settings.github_vault_token)
    repo = settings.github_vault_repo
    branch = settings.github_vault_branch
    now = datetime.now(timezone.utc)

    findings: dict[str, list[str]] = {
        "stale": [],
        "uncovered_topics": [],
        "oversized": [],
        "unpopulated_folders": [],
        "monthly_rebuild": [],
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        tree = await _gh_get_tree(client, headers, repo, branch)

        # ── Build a map of topic_slug -> (path, size) for knowledge/ and context/ ──
        topic_files: dict[str, list[tuple[str, int]]] = {}
        folder_counts: dict[str, int] = {"agents": 0, "topics": 0}

        for entry in tree:
            if entry["type"] != "blob":
                continue
            path = entry["path"]
            size = entry.get("size", 0)

            if path.startswith("knowledge/") and path.endswith(".md") and path != "knowledge/.gitkeep":
                if path.startswith("knowledge/agents/"):
                    folder_counts["agents"] += 1
                    continue
                slug = path[len("knowledge/"):-len(".md")]
                topic_files.setdefault(slug, []).append((path, size))
            elif path.startswith("context/") and path.endswith(".md") and path != "context/.gitkeep":
                slug = path[len("context/"):-len(".md")]
                topic_files.setdefault(slug, []).append((path, size))
            elif path.startswith("topics/") and path not in ("topics/.gitkeep",):
                folder_counts["topics"] += 1

        # ── Oversized + staleness checks (read each file once) ──
        for slug, files in sorted(topic_files.items()):
            for path, size in files:
                if size > SIZE_WARN_BYTES:
                    findings["oversized"].append(
                        f"`{path}` is {size / 1_000_000:.1f}MB (warn threshold {SIZE_WARN_BYTES / 1_000_000:.0f}MB) -- candidate for splitting or periodic compaction"
                    )

                content, _ = await _gh_get_file(client, headers, repo, branch, path)
                if content is None:
                    continue
                last = _last_entry_created_at(content)
                if last is None:
                    continue
                age_days = (now - last).days
                if age_days > STALE_DAYS:
                    findings["stale"].append(
                        f"`{path}` -- last entry {last.date().isoformat()} ({age_days}d ago, threshold {STALE_DAYS}d)"
                    )

        # ── Uncovered topic slugs: in the taxonomy, zero knowledge/ or context/ entries ──
        for slug in KNOWN_TOPIC_SLUGS:
            if slug not in topic_files:
                findings["uncovered_topics"].append(
                    f"`{slug}` -- in the documented topic_slug taxonomy, zero knowledge/ or context/ entries found"
                )

        # ── Unpopulated structural folders ──
        if folder_counts["agents"] == 0:
            findings["unpopulated_folders"].append(
                "`agents/` -- documented in README.md as \"per-agent configuration and learned context\", contains no files"
            )
        if folder_counts["topics"] == 0:
            findings["unpopulated_folders"].append(
                "`topics/` -- documented in README.md as per-topic index pages, contains no files (aside from this lint report + the monthly marker)"
            )

        # ── Monthly rebuild marker staleness ──
        marker_content, _ = await _gh_get_file(client, headers, repo, branch, "topics/_monthly_rebuild.md")
        if marker_content is None:
            findings["monthly_rebuild"].append(
                "`topics/_monthly_rebuild.md` does not exist -- run_monthly_rebuild may never have run successfully"
            )
        else:
            marker_field = _extract_marker_last_rebuild(marker_content)
            if marker_field is None:
                findings["monthly_rebuild"].append(
                    "`topics/_monthly_rebuild.md` exists but its \"Last rebuild\" line could not be parsed"
                )
            else:
                age_days = (now - marker_field).days
                if age_days > MONTHLY_MARKER_STALE_DAYS:
                    findings["monthly_rebuild"].append(
                        f"Last monthly rebuild was {marker_field.date().isoformat()} ({age_days}d ago, threshold {MONTHLY_MARKER_STALE_DAYS}d)"
                    )

        # ── Compose + write report ──
        report = _compose_report(findings, topic_files, now)
        commit_sha = await _write_report(client, headers, repo, branch, report)

    total_findings = sum(len(v) for v in findings.values())
    logger.info("rarv_lint.done", total_findings=total_findings, commit_sha=commit_sha)
    return {"ok": True, "total_findings": total_findings, "commit_sha": commit_sha, "findings": findings}


def _extract_marker_last_rebuild(content: str) -> Optional[datetime]:
    for line in content.splitlines():
        if "Last rebuild:" in line:
            # "- **Last rebuild:** 2026-07-16 02:00 CEST" style, from rarv_rebuild._now_berlin_iso()
            raw = line.split("Last rebuild:", 1)[1].strip().strip("*").strip()
            for fmt in ("%Y-%m-%d %H:%M %Z", "%Y-%m-%d %H:%M"):
                try:
                    dt = datetime.strptime(raw[: len(raw)], fmt)
                    return dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
            # fallback: just the date portion
            try:
                return datetime.fromisoformat(raw[:10]).replace(tzinfo=timezone.utc)
            except ValueError:
                return None
    return None


def _compose_report(
    findings: dict[str, list[str]],
    topic_files: dict[str, list[tuple[str, int]]],
    now: datetime,
) -> str:
    when = now.strftime("%Y-%m-%d %H:%M UTC")
    total = sum(len(v) for v in findings.values())

    lines = [
        "# Vault Lint Report",
        "",
        f"> Weekly health check. Last run: **{when}** by the RARV journal team.",
        f"> Do not edit by hand -- overwritten on next run.",
        f"> {total} finding(s) across {len(topic_files)} tracked topic(s).",
        "",
    ]

    section_titles = {
        "stale": f"## Stale topics (no new entry in {STALE_DAYS}+ days)",
        "uncovered_topics": "## Uncovered topic slugs (in taxonomy, never written)",
        "oversized": "## Oversized topic files",
        "unpopulated_folders": "## Unpopulated structural folders",
        "monthly_rebuild": "## Monthly rebuild staleness",
    }

    for key, title in section_titles.items():
        items = findings[key]
        lines.append(title)
        lines.append("")
        if not items:
            lines.append("(none)")
        else:
            for item in items:
                lines.append(f"- {item}")
        lines.append("")

    lines.append("## Not covered by this check")
    lines.append("")
    lines.append(
        "- Contradiction detection between entries (would need an LLM pass over "
        "entry pairs within a topic -- not built yet)."
    )
    lines.append(
        "- Wikilink-graph orphan detection (this vault doesn't use wikilinks -- "
        "\"uncovered topic slugs\" above is the closest equivalent)."
    )
    lines.append("")

    return "\n".join(lines)


async def _write_report(client: httpx.AsyncClient, headers: dict, repo: str, branch: str, content: str) -> str:
    path = "topics/_lint_report.md"
    _, file_sha = await _gh_get_file(client, headers, repo, branch, path)
    body: dict = {
        "message": "rarv: weekly lint report",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
        "committer": _GH_COMMITTER,
    }
    if file_sha:
        body["sha"] = file_sha
    url = f"{_GH_API}/repos/{repo}/contents/{path}"
    resp = await client.put(url, headers=headers, json=body)
    resp.raise_for_status()
    return resp.json()["commit"]["sha"]
