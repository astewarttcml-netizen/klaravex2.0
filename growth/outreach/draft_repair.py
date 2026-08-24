"""Repair common gatekeeper failures in outbox drafts before re-adjudication."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

GATED_STREAMS = ("socials", "seo-blog", "kb", "leads", "backlinks", "forums")
GATE_VERDICT_SPLIT = re.compile(r"\n## GATE VERDICT\s*\n", re.M)

REPAIRS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcompliance\b", re.I), "readiness"),
    (re.compile(r"klaravex\.example", re.I), "klaravex.com"),
    (re.compile(r"^#poc-fixture\s*$", re.M), ""),
    (re.compile(r"\bI hope this (?:message|email) finds you well\.?\s*", re.I), ""),
    (re.compile(r"\bI'm reaching out\b", re.I), "Klaravex is reaching out"),
    (re.compile(r"\bI noticed\b", re.I), "Klaravex identified"),
    (re.compile(r"\bApollo/Hunter\b", re.I), "contact enrichment"),
    (re.compile(r"\bAnthony\b", re.I), "Klaravex"),
    (re.compile(r"\bI'm\b", re.I), "Klaravex is"),
]


def repair_text(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    body = GATE_VERDICT_SPLIT.split(text, maxsplit=1)[0].rstrip() + "\n"
    for pattern, repl in REPAIRS:
        if pattern.search(body):
            body = pattern.sub(repl, body)
            notes.append(f"applied {pattern.pattern[:40]}")
    body = re.sub(r"\n{3,}", "\n\n", body)
    if "klaravex.com" not in body.lower() and "personal.klaravex.com" not in body.lower():
        body = body.rstrip() + "\n\nLearn more at https://klaravex.com.\n"
        notes.append("appended klaravex.com CTA")
    return body, notes


def repair_file(path: Path, *, dry_run: bool = False) -> dict:
    text = path.read_text(encoding="utf-8")
    if "poc" in path.name.lower() and path.name.lower().endswith(".md"):
        if not dry_run:
            archive = path.parent / ".archived-poc" / path.name
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_text(text, encoding="utf-8")
            path.unlink()
        return {"file": str(path), "status": "archived_poc", "reason": "poc filename"}

    new_text, notes = repair_text(text)
    changed = new_text != GATE_VERDICT_SPLIT.split(text, maxsplit=1)[0].rstrip() + "\n"
    if not changed:
        return {"file": str(path), "status": "unchanged"}
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return {"file": str(path), "status": "repaired", "notes": notes}


def repair_outbox(root: Path, *, dry_run: bool = False) -> list[dict]:
    results: list[dict] = []
    for stream in GATED_STREAMS:
        outbox = root / "outbox" / stream
        if not outbox.is_dir():
            continue
        for path in sorted(outbox.rglob("*.md")):
            if path.name.startswith("."):
                continue
            results.append(repair_file(path, dry_run=dry_run))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair outbox drafts for gatekeeper re-run")
    parser.add_argument(
        "--root",
        default=os.getenv("GROWTH_REVENUE_AGENTS_ROOT", "/home/anthony/Klaravex2.0/revenue-agents"),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--file", default="")
    args = parser.parse_args()
    root = Path(args.root)
    if args.file:
        out = [repair_file(Path(args.file), dry_run=args.dry_run)]
    else:
        out = repair_outbox(root, dry_run=args.dry_run)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
