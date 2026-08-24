"""Dispatch gatekeeper-APPROVED seo-blog / kb drafts to WordPress as drafts."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from growth.adapters import wordpress as wp_adapter
from growth.adapters.credentials import _merged_env

GATE_VERDICT_RE = re.compile(r"^## GATE VERDICT\s*$(.*)", re.M | re.S)


def _auto_publish() -> bool:
    """APPROVED drafts go live immediately when WORDPRESS_AUTO_PUBLISH is on."""
    raw = (_merged_env().get("WORDPRESS_AUTO_PUBLISH") or os.getenv("WORDPRESS_AUTO_PUBLISH") or "false").strip()
    return raw.lower() in {"1", "true", "yes", "on"}
APPROVED_RE = re.compile(r"\*\*Status:\*\*\s*APPROVED\b")
BODY_RE = re.compile(r"\n---\s*\n(.*?)(?=\n## GATE VERDICT|\Z)", re.S)


def _is_approved(text: str) -> bool:
    m = GATE_VERDICT_RE.search(text)
    if not m:
        return False
    return bool(APPROVED_RE.search(m.group(1)))


def parse_article(text: str, fname: str) -> dict[str, str] | None:
    surface = title = meta = ""
    for line in text.splitlines()[:12]:
        if line.startswith("surface:"):
            surface = line.split(":", 1)[1].strip()
        elif line.startswith("title:"):
            title = line.split(":", 1)[1].strip()
        elif line.startswith("meta-description:"):
            meta = line.split(":", 1)[1].strip()
    body_m = BODY_RE.search(text)
    if not (surface and title and body_m):
        return None
    slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", Path(fname).stem)
    return {
        "surface": surface,
        "title": title,
        "meta": meta,
        "slug": slug,
        "markdown": body_m.group(1).strip(),
    }


def dispatch_file(path: Path, *, dry_run: bool = False) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if "## BRIDGED" in text:
        return {"file": str(path), "status": "skipped", "reason": "already bridged"}
    if not _is_approved(text):
        return {"file": str(path), "status": "skipped", "reason": "no APPROVED gate verdict"}

    art = parse_article(text, path.name)
    if not art:
        return {"file": str(path), "status": "skipped", "reason": "could not parse front block/body"}

    if dry_run:
        return {
            "file": str(path),
            "status": "dry_run",
            "surface": art["surface"],
            "title": art["title"],
            "slug": art["slug"],
        }

    wp_status = "publish" if _auto_publish() else "draft"
    out = wp_adapter.publish(
        payload={
            "surface": art["surface"],
            "title": art["title"],
            "markdown": art["markdown"],
            "slug": art["slug"],
            "excerpt": art["meta"],
            "status": wp_status,
        }
    )
    ok = out.get("status") == "connected"
    if ok:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        path.write_text(
            text.rstrip()
            + f"\n\n## BRIDGED\n\n- **Bridged:** {now}\n- **Action:** wp_{wp_status}\n"
            + f"- **Refs:** `{json.dumps(out.get('sample', {}))[:500]}`\n",
            encoding="utf-8",
        )
    return {"file": str(path), "status": "ok" if ok else "failed", "result": out}


def dispatch_outbox(root: Path, streams: tuple[str, ...], *, dry_run: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for stream in streams:
        d = root / "outbox" / stream
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.md")):
            if "poc" in path.name.lower():
                continue
            out.append(dispatch_file(path, dry_run=dry_run))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Push APPROVED seo-blog/kb drafts to WordPress")
    parser.add_argument(
        "--root",
        default=os.getenv("GROWTH_REVENUE_AGENTS_ROOT", "/home/anthony/Klaravex2.0/revenue-agents"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if wp_adapter._readonly() and not args.dry_run:
        print("WORDPRESS_READONLY=true — use --dry-run or set WORDPRESS_READONLY=false")
        return 2

    results = dispatch_outbox(Path(args.root), ("seo-blog", "kb"), dry_run=args.dry_run)
    print(json.dumps(results, indent=2))
    failed = [r for r in results if r.get("status") == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
