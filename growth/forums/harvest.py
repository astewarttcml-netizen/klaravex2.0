"""Harvest forum_mentions signals from Growth research bundles for the forums agent."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from growth.digests.heads import week_theme_for

_FORUM_SCRAPERS = {"forum_mentions", "forum"}
_VENUE_HINT = re.compile(
    r"\b(r/\w+|reddit|hackernews|hn\b|spiceworks|sysadmin|msp)\b",
    re.I,
)


def _repo_roots() -> tuple[Path, Path]:
    growth_root = Path(__file__).resolve().parents[1]
    return growth_root, growth_root.parent


def iter_forum_signals(
    research_root: Path,
    *,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """Return newest-ish forum signals from bundle.json files."""
    if not research_root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    paths = sorted(research_root.rglob("bundle.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        signals = data.get("signals") or []
        prospect = path.parent.name
        run_id = path.parent.parent.name if path.parent.parent != research_root else ""
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            scraper = str(sig.get("scraper") or "")
            sid = str(sig.get("signal_id") or "")
            # More robust check: accept both "forum_mentions" and "forum" scrapers,
            # as well as any signal_id starting with "forum-"
            if scraper not in _FORUM_SCRAPERS and not sid.startswith("forum-"):
                continue
            excerpt = str(sig.get("excerpt") or "").strip()
            if not excerpt:
                continue
            rows.append(
                {
                    "signal_id": sid or "forum-??",
                    "scraper": scraper or "forum_mentions",
                    "excerpt": excerpt,
                    "prospect": prospect,
                    "research_run": run_id,
                    "bundle": str(path),
                    "venue_hint": bool(_VENUE_HINT.search(excerpt)),
                }
            )
            if len(rows) >= limit:
                return rows
    return rows


def rank_for_theme(rows: list[dict[str, Any]], theme_slug: str) -> list[dict[str, Any]]:
    """Prefer venue-looking excerpts; light keyword boost from theme slug tokens."""
    tokens = [t for t in re.split(r"[-_]+", theme_slug) if len(t) > 2]

    def score(row: dict[str, Any]) -> tuple[int, int]:
        text = row["excerpt"].lower()
        kw = sum(1 for t in tokens if t.lower() in text)
        venue = 1 if row.get("venue_hint") else 0
        return (venue + kw, kw)

    return sorted(rows, key=score, reverse=True)


def render_candidates_md(
    rows: list[dict[str, Any]],
    *,
    theme: dict[str, Any],
    day: str,
) -> str:
    lines = [
        f"# Forum harvest — {day}",
        "",
        f"- **Theme:** `{theme['slug']}` (ISO week {theme['iso_week']})",
        f"- **Business:** {theme['business']}",
        f"- **Consumer:** {theme['consumer']}",
        f"- **Candidates:** {len(rows)}",
        "",
        "| # | signal_id | excerpt | prospect |",
        "|---|---|---|---|",
    ]
    for i, row in enumerate(rows, start=1):
        excerpt = row["excerpt"].replace("|", "/").replace("\n", " ")[:140]
        lines.append(
            f"| {i} | `{row['signal_id']}` | {excerpt} | `{row['prospect'][:40]}` |"
        )
    lines += [
        "",
        "_Use these as Source: research `forum-NN` in outbox/forums drafts. "
        "Skip off-topic HN noise; prefer r/sysadmin / r/msp / healthcare IT._",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="Harvest forum_mentions for forums agent")
    p.add_argument("--date", default=None, help="YYYY-MM-DD for theme + optional write")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument(
        "--write",
        action="store_true",
        help="Write harvest md under revenue-agents/outbox/forums/_harvest/",
    )
    p.add_argument("--json", action="store_true", help="Print JSON instead of markdown")
    args = p.parse_args()
    day = args.date or date.today().isoformat()
    growth_root, repo_root = _repo_roots()
    research_root = growth_root / "data" / "research"
    theme = week_theme_for(day)
    rows = rank_for_theme(iter_forum_signals(research_root, limit=args.limit * 2), theme["slug"])[
        : args.limit
    ]
    if args.json:
        print(json.dumps({"date": day, "theme": theme, "candidates": rows}, indent=2))
        return
    body = render_candidates_md(rows, theme=theme, day=day)
    print(body)
    if args.write:
        out = repo_root / "revenue-agents" / "outbox" / "forums" / "_harvest"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{day}-harvest.md"
        path.write_text(body, encoding="utf-8")
        print(f"wrote {path}", flush=True)


if __name__ == "__main__":
    main()
