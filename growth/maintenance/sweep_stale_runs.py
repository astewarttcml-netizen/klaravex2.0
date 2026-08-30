"""Sweep abandoned Growth runs stuck in accepted/running."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def sweep_runs(
    runs_path: Path,
    *,
    max_age_hours: float = 2.0,
    dry_run: bool = False,
    enabled: bool = True,
) -> dict[str, Any]:
    if not enabled:
        return {"ok": True, "disabled": True, "swept": [], "dry_run": dry_run}
    if not runs_path.is_file():
        return {"ok": False, "error": f"missing {runs_path}", "swept": []}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    # latest record per id
    by_id: dict[str, dict[str, Any]] = {}
    for line in runs_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("kind") == "gate_verdict":
            continue
        rid = rec.get("id")
        if not rid:
            continue
        prev = by_id.get(rid)
        if prev is None:
            by_id[rid] = rec
        else:
            prev.update(rec)

    swept: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    for rid, rec in by_id.items():
        st = rec.get("status")
        if st not in {"accepted", "running"}:
            continue
        # Key on last_heartbeat when present (long healthy runs emit
        # heartbeats and must never be swept); fall back to started_at for
        # runs that predate the heartbeat emitter.
        last_sign = (
            _parse_ts(rec.get("last_heartbeat"))
            or _parse_ts(rec.get("started_at"))
            or _parse_ts(rec.get("finished_at"))
        )
        if last_sign is None or last_sign > cutoff:
            continue
        patch = {
            "id": rid,
            "stream": rec.get("stream"),
            "kind": rec.get("kind", "stream_run"),
            "started_at": rec.get("started_at"),
            "status": "lost",
            "finished_at": now,
            "swept_at": now,
            "detail": (
                f"swept: no heartbeat since {last_sign.isoformat()} "
                f"(>{max_age_hours:g}h, was: {rec.get('detail') or st})"
            ),
        }
        swept.append(patch)
        if not dry_run:
            with runs_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(patch, ensure_ascii=False) + "\n")

    return {
        "ok": True,
        "cutoff": cutoff.isoformat(),
        "swept_count": len(swept),
        "swept": swept,
        "dry_run": dry_run,
    }


def main() -> None:
    growth_root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description="Mark stale Growth runs as lost")
    p.add_argument("--hours", type=float, default=float(os.getenv("GROWTH_SWEEPER_HOURS", "2")))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--runs", type=Path, default=growth_root / "data" / "runs.jsonl")
    args = p.parse_args()
    enabled = os.getenv("GROWTH_SWEEPER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    print(json.dumps(sweep_runs(
        args.runs, max_age_hours=args.hours, dry_run=args.dry_run, enabled=enabled,
    ), indent=2))


if __name__ == "__main__":
    main()
