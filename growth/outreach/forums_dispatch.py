"""Dispatch gatekeeper-APPROVED forums replies to Reddit as comments.

Only replies whose THREAD block carries a real reddit.com/comments/ URL are
auto-posted (live-harvest threads). Search-query targets and non-Reddit
boards stay manual. Adapter enforces readonly, dedupe, daily cap, and
minimum interval.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from growth.adapters import reddit as reddit_adapter

GATE_VERDICT_RE = re.compile(r"^## GATE VERDICT\s*$(.*)", re.M | re.S)
APPROVED_RE = re.compile(r"\*\*Status:\*\*\s*APPROVED\b")
REPLY_SPLIT_RE = re.compile(r"^## Reply \d+\s*[—–-]?\s*(?P<title>[^\n]*)$", re.M)
URL_RE = re.compile(r"^\-\s*\*\*URL:\*\*\s*(.+)$", re.M | re.I)
REPLY_BODY_RE = re.compile(r"^### REPLY\s*$(.*?)(?=^### META|\Z)", re.M | re.S)


def _is_approved(text: str) -> bool:
    m = GATE_VERDICT_RE.search(text)
    return bool(m and APPROVED_RE.search(m.group(1)))


def parse_replies(text: str) -> list[dict[str, str]]:
    matches = list(REPLY_SPLIT_RE.finditer(text))
    out: list[dict[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[m.end():end]
        gate = re.search(r"^## GATE VERDICT\s*$", block, re.M)
        if gate:
            block = block[: gate.start()]
        url_m = URL_RE.search(block)
        body_m = REPLY_BODY_RE.search(block)
        if not url_m or not body_m:
            continue
        out.append({
            "title": m.group("title").strip(),
            "url": url_m.group(1).strip(),
            "body": body_m.group(1).strip(),
        })
    return out


def dispatch_file(path: Path, *, dry_run: bool = False) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if "## BRIDGED" in text:
        return {"file": str(path), "status": "skipped", "reason": "already bridged"}
    if not _is_approved(text):
        return {"file": str(path), "status": "skipped", "reason": "no APPROVED gate verdict"}

    replies = parse_replies(text)
    if not replies:
        return {"file": str(path), "status": "skipped", "reason": "no parseable replies"}

    results: list[dict[str, Any]] = []
    posted = 0
    for reply in replies:
        url = reply["url"]
        if not reddit_adapter.thread_id(url):
            results.append({"title": reply["title"], "status": "manual", "reason": "not a live reddit URL"})
            continue
        if dry_run:
            results.append({"title": reply["title"], "status": "dry_run", "url": url})
            continue
        out = reddit_adapter.post_comment(thread_url=url, body_markdown=reply["body"])
        if out.get("ok"):
            posted += 1
            results.append({"title": reply["title"], "status": "posted", "permalink": out.get("permalink")})
        elif out.get("skipped"):
            results.append({"title": reply["title"], "status": "skipped", "reason": out.get("detail")})
        else:
            results.append({"title": reply["title"], "status": "failed", "reason": out.get("detail")})

    failed = [r for r in results if r.get("status") == "failed"]
    # Mark bridged once at least one reply posted and nothing hard-failed —
    # skipped-manual entries stay in the file for human pasting.
    if not dry_run and posted and not failed:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        path.write_text(
            text.rstrip()
            + f"\n\n## BRIDGED\n\n- **Bridged:** {now}\n- **Action:** reddit_comment\n"
            + f"- **Refs:** `{json.dumps(results)[:500]}`\n",
            encoding="utf-8",
        )
    status = "ok" if posted and not failed else ("failed" if failed else "skipped")
    return {"file": str(path), "status": status, "posted": posted, "results": results}


def dispatch_outbox(root: Path, *, dry_run: bool = False) -> list[dict[str, Any]]:
    d = root / "outbox" / "forums"
    if not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(d.glob("*.md")):
        if "poc" in path.name.lower():
            continue
        out.append(dispatch_file(path, dry_run=dry_run))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Post APPROVED forums replies to Reddit")
    parser.add_argument(
        "--root",
        default=os.getenv("GROWTH_REVENUE_AGENTS_ROOT", "/home/anthony/Klaravex2.0/revenue-agents"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    results = dispatch_outbox(Path(args.root), dry_run=args.dry_run)
    print(json.dumps(results, indent=2))
    return 1 if any(r.get("status") == "failed" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
