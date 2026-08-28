"""Bridge APPROVED outbox drafts to live adapters (Smartlead, WordPress)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from growth.outreach import content_dispatch, forums_dispatch, leads_dispatch, socials_dispatch

logger = logging.getLogger("growth.dispatch_bridge")


def dispatch_approved(root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Run all stream dispatchers; skip already-bridged files."""
    root = root.resolve()
    results: dict[str, Any] = {
        "root": str(root),
        "dry_run": dry_run,
        "leads": leads_dispatch.dispatch_outbox(root, dry_run=dry_run),
        "socials": socials_dispatch.dispatch_outbox(root, dry_run=dry_run),
        "content": content_dispatch.dispatch_outbox(root, ("seo-blog", "kb"), dry_run=dry_run),
        "forums": forums_dispatch.dispatch_outbox(root, dry_run=dry_run),
    }
    ok = 0
    skipped = 0
    failed = 0
    for stream, rows in results.items():
        if stream in {"root", "dry_run"}:
            continue
        for row in rows:
            st = row.get("status", "")
            if st in {"ok", "dry_run"}:
                ok += 1
            elif st == "skipped":
                skipped += 1
            elif st == "failed":
                failed += 1
    results["summary"] = {"ok": ok, "skipped": skipped, "failed": failed}
    return results


def maybe_dispatch_after_gatekeeper(revenue_agents_root: Path) -> dict[str, Any] | None:
    if os.getenv("GROWTH_DISPATCH_ON_GATE", "true").lower() not in {"1", "true", "yes", "on"}:
        return None
    dry_run = os.getenv("GROWTH_DISPATCH_DRY_RUN", "false").lower() in {"1", "true", "yes", "on"}
    try:
        out = dispatch_approved(revenue_agents_root, dry_run=dry_run)
        logger.info(
            "post-gatekeeper dispatch ok=%s skipped=%s failed=%s dry_run=%s",
            out["summary"]["ok"],
            out["summary"]["skipped"],
            out["summary"]["failed"],
            dry_run,
        )
        return out
    except Exception as exc:
        logger.exception("post-gatekeeper dispatch failed: %s", exc)
        return {"error": str(exc)}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Dispatch all APPROVED outbox drafts")
    parser.add_argument(
        "--root",
        default=os.getenv("GROWTH_REVENUE_AGENTS_ROOT", "/home/anthony/Klaravex2.0/revenue-agents"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    out = dispatch_approved(Path(args.root), dry_run=args.dry_run)
    print(json.dumps(out, indent=2))
    return 1 if out["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
