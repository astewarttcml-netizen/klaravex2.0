"""Dispatch APPROVED socials short-form (TikTok / YouTube Shorts) via Zernio."""

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

PLATFORM_SPECS = (
    ("tiktok", "TikTok", "tiktok", None),
    ("youtube", "YouTube Shorts", "youtube", True),  # True = use title from first line
)


def _already_zernio(text: str) -> bool:
    m = re.search(r"^## ZERNIO\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        return False
    return bool(re.search(r"\*\*Bridged:\*\*", m.group(1)))


def _is_approved(text: str) -> bool:
    m = GATE_VERDICT_RE.search(text)
    if not m:
        return False
    return bool(APPROVED_RE.search(m.group(1)))


def _parse_platform_copy(text: str, heading: str) -> list[dict[str, str]]:
    posts: list[dict[str, str]] = []
    for header, surface in (
        (r"##\s*BUSINESS\s*POST", "business"),
        (r"##\s*CONSUMER\s*POST", "consumer"),
    ):
        m = re.search(header + r"[^\n]*\n(.*?)(?=\n## |\n---\s*\n## |\Z)", text, re.S | re.I)
        if not m:
            continue
        body = m.group(1)
        pm = re.search(
            rf"^###\s*{re.escape(heading)}\s*\n(.*?)(?=\n### |\Z)",
            body,
            re.M | re.S | re.I,
        )
        if not pm:
            continue
        copy = pm.group(1).strip()
        if copy:
            posts.append({"surface": surface, "content": copy})
    return posts


def _asset_for(assets_dir: Path, surface: str, platform_key: str) -> Path | None:
    # business-tiktok-9x16.mp4 / business-youtube-shorts-9x16.mp4
    candidates = [
        assets_dir / f"{surface}-{platform_key}-9x16.mp4",
        assets_dir / f"{surface}-youtube-shorts-9x16.mp4" if platform_key == "youtube" else None,
    ]
    for c in candidates:
        if c and c.is_file():
            return c
    return None


def dispatch_file(
    path: Path,
    *,
    dry_run: bool = False,
    publish_now: bool = False,
    scheduled_for: str | None = None,
) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not _is_approved(text):
        return {"file": str(path), "status": "skipped", "reason": "no APPROVED gate verdict"}

    assets_dir = path.parent / "assets" / path.stem
    results: list[dict[str, Any]] = []
    use_us_default = (
        not publish_now
        and not scheduled_for
        and os.getenv("ZERNIO_SCHEDULE_US_DEFAULT", "true").lower()
        in {"1", "true", "yes", "on"}
    )

    for platform_key, heading, z_platform, want_title in PLATFORM_SPECS:
        for post in _parse_platform_copy(text, heading):
            media = _asset_for(assets_dir, post["surface"], platform_key)
            label = f"{path.name} — {post['surface']} {heading}"
            when = scheduled_for
            meta: dict[str, str] = {}
            if use_us_default:
                from growth.timeutil import schedule_meta

                meta = schedule_meta(post["surface"], hour=10)
                when = meta["utc"]
            if dry_run:
                results.append(
                    {
                        "label": label,
                        "status": "dry_run",
                        "platform": z_platform,
                        "media": str(media) if media else None,
                        "content_chars": len(post["content"]),
                        "scheduled_for": when,
                        "timezone": meta.get("timezone") or "America/New_York",
                        "local": meta.get("local"),
                    }
                )
                continue
            title = None
            if want_title:
                first = post["content"].splitlines()[0].strip()
                title = first[:100] if first else f"Klaravex — {post['surface']}"
            out = zernio_adapter.draft_post(
                content=post["content"],
                platform=z_platform,
                media_path=media,
                title=title,
                publish_now=publish_now,
                scheduled_for=None if publish_now else when,
                timezone_name=meta.get("timezone"),
            )
            out["label"] = label
            if meta:
                out["local"] = meta["local"]
            results.append(out)

    if not results:
        return {"file": str(path), "status": "skipped", "reason": "no TikTok/YouTube Shorts sections"}

    # Append bridge note only when at least one live draft succeeded
    ok = [r for r in results if r.get("status") in {"connected", "dry_run"}]
    if ok and not dry_run and not _already_zernio(text):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        path.write_text(
            text
            + f"\n\n## ZERNIO\n\n- **Bridged:** {now}\n- **Action:** zernio_draft\n"
            + "- **Timezone:** dual-coast (B2B 10:00 ET / B2C 10:00 PT)\n"
            + f"- **Refs:** `{json.dumps(ok)[:1500]}`\n",
            encoding="utf-8",
        )

    return {"file": str(path), "status": "ok", "results": results}


def dispatch_outbox(
    root: Path,
    *,
    dry_run: bool = False,
    publish_now: bool = False,
    scheduled_for: str | None = None,
) -> list[dict[str, Any]]:
    socials_dir = root / "outbox" / "socials"
    if not socials_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(socials_dir.glob("*.md")):
        out.append(
            dispatch_file(
                path,
                dry_run=dry_run,
                publish_now=publish_now,
                scheduled_for=scheduled_for,
            )
        )
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Draft TikTok/YouTube via Zernio from APPROVED socials")
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2] / "revenue-agents")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--publish-now", action="store_true", help="Live publish immediately (ignore US slot)")
    p.add_argument(
        "--schedule-for",
        default="",
        help="UTC ISO schedule; default next 10:00 America/New_York",
    )
    args = p.parse_args()
    if not args.publish_now:
        os.environ.setdefault("ZERNIO_READONLY", "true")
    print(
        json.dumps(
            dispatch_outbox(
                args.root,
                dry_run=args.dry_run,
                publish_now=args.publish_now,
                scheduled_for=args.schedule_for or None,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
