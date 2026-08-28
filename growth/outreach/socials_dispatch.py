"""Dispatch gatekeeper-APPROVED socials LinkedIn drafts to Zernio (LinkedIn)."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from growth.adapters import zernio as zernio_adapter

GATE_VERDICT_RE = re.compile(r"^## GATE VERDICT\s*$(.*)", re.M | re.S)
APPROVED_RE = re.compile(r"\*\*Status:\*\*\s*APPROVED\b")


def _already_bridged(text: str) -> bool:
    m = re.search(r"^## BRIDGED\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        return False
    body = m.group(1)
    return bool(re.search(r"\*\*Bridged:\*\*", body))


def _is_approved(text: str) -> bool:
    m = GATE_VERDICT_RE.search(text)
    if not m:
        return False
    return bool(APPROVED_RE.search(m.group(1)))


def _strip_md_blockquotes(copy: str) -> str:
    """Remove leading markdown '>' carrots so LinkedIn never sees literal >."""
    lines: list[str] = []
    for line in copy.splitlines():
        if line.startswith("> "):
            lines.append(line[2:])
        elif line.strip() == ">":
            lines.append("")
        else:
            lines.append(line)
    return "\n".join(lines).strip()


def parse_linkedin_posts(text: str, fname: str) -> list[dict[str, str]]:
    """Extract ### LinkedIn copy from BUSINESS/CONSUMER post sections."""
    posts: list[dict[str, str]] = []
    for header, surface in (
        (r"##\s*BUSINESS\s*POST", "business"),
        (r"##\s*CONSUMER\s*POST", "consumer"),
    ):
        m = re.search(
            header + r"[^\n]*\n(.*?)(?=\n## |\n---\s*\n## |\Z)",
            text,
            re.S | re.I,
        )
        if not m:
            continue
        body = m.group(1)
        lm = re.search(r"^###\s*LinkedIn[^\n]*\n(.*?)(?=\n### |\Z)", body, re.M | re.S | re.I)
        if not lm:
            continue
        copy = _strip_md_blockquotes(lm.group(1).strip())
        if copy:
            posts.append(
                {
                    "surface": surface,
                    "platform": "linkedin",
                    "content": copy,
                    "label": f"{fname} — {surface} LinkedIn",
                }
            )
    return posts


def _has_real_media_asset(path: Path, text: str) -> bool:
    """True only when a real image/video file exists (prompts alone do not count)."""
    if re.search(r"No assets generated|prompts-only draft", text, re.I):
        return False
    for d in (path.parent / "assets", path.parent / path.stem, path.parent):
        if not d.is_dir():
            continue
        for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.gif", "*.mp4", "*.mov", "*.webm"):
            if any(d.glob(pattern)):
                return True
    return False


def dispatch_file(path: Path, *, dry_run: bool = False, scheduled_for: str = "") -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if _already_bridged(text):
        return {"file": str(path), "status": "skipped", "reason": "already bridged"}
    if not _is_approved(text):
        return {"file": str(path), "status": "skipped", "reason": "no APPROVED gate verdict"}
    if not _has_real_media_asset(path, text):
        return {
            "file": str(path),
            "status": "skipped",
            "reason": "no real media on disk (image or video) — refuse text-only bridge",
        }

    posts = parse_linkedin_posts(text, path.name)
    if not posts:
        return {"file": str(path), "status": "skipped", "reason": "no ### LinkedIn sections parsed"}

    results: list[dict[str, Any]] = []
    for post in posts:
        # B2B + B2C LinkedIn both route to Zernio (LinkedIn).
        # 2026-08-25 per Anthony directive; adapter fully removed (account deleted, adapter file deleted).
        surfaces = {
            s.strip()
            for s in os.getenv("GROWTH_SOCIALS_SURFACES", "business,consumer").split(",")
            if s.strip()
        } or {"business", "consumer"}
        if post["surface"] not in surfaces:
            continue
        post_schedule = scheduled_for.strip()
        meta: dict[str, str] = {}
        if post_schedule:
            from growth.timeutil import schedule_meta

            # B2C Zernio → 10:00 PT; B2B Zernio page → 10:00 ET
            meta = schedule_meta(post["surface"], hour=10)
            post_schedule = meta["utc"]
        if dry_run:
            results.append(
                {
                    "label": post["label"],
                    "status": "dry_run",
                    "surface": post["surface"],
                    "content_chars": len(post["content"]),
                    "scheduled_for": post_schedule or None,
                    **({"timezone": meta["timezone"], "local": meta["local"]} if meta else {}),
                }
            )
            continue
        payload: dict[str, Any] = {"content": post["content"], "platform": "linkedin"}
        if post_schedule:
            payload["scheduled_for"] = post_schedule
        out = zernio_adapter.draft(payload=payload)
        if meta:
            out["timezone"] = meta["timezone"]
            out["local"] = meta["local"]
        results.append({"label": post["label"], **out})

    if not results:
        return {"file": str(path), "status": "skipped", "reason": "no LinkedIn posts after surface filter"}

    ok = all(r.get("status") in {"connected", "dry_run"} for r in results)
    if not dry_run and ok:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        path.write_text(
            text.rstrip()
            + f"\n\n## BRIDGED\n\n- **Bridged:** {now}\n- **Action:** zernio_draft\n"
            + "- **Timezone:** dual-coast (B2B ET / B2C PT)\n"
            + f"- **Refs:** `{json.dumps(results)[:500]}`\n",
            encoding="utf-8",
        )
    return {"file": str(path), "status": "ok" if ok else "failed", "results": results}


def dispatch_outbox(root: Path, *, dry_run: bool = False, scheduled_for: str = "") -> list[dict[str, Any]]:
    socials_dir = root / "outbox" / "socials"
    if not socials_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(socials_dir.glob("*.md")):
        if "poc" in path.name.lower():
            continue
        out.append(dispatch_file(path, dry_run=dry_run, scheduled_for=scheduled_for))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Push APPROVED socials LinkedIn copy to Zernio")
    parser.add_argument(
        "--root",
        default=os.getenv("GROWTH_REVENUE_AGENTS_ROOT", "/home/anthony/Klaravex2.0/revenue-agents"),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--schedule-for",
        default="",
        help="ISO-8601 UTC schedule time (passed to Zernio; otherwise draft-only)",
    )
    args = parser.parse_args()

    if zernio_adapter._readonly() and not args.dry_run:
        print("ZERNIO_READONLY=true — use --dry-run or set ZERNIO_READONLY=false")
        return 2

    results = dispatch_outbox(
        Path(args.root),
        dry_run=args.dry_run,
        scheduled_for=args.schedule_for,
    )
    print(json.dumps(results, indent=2))
    failed = [r for r in results if r.get("status") == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
