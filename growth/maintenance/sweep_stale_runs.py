"""Sweep abandoned Growth runs stuck in accepted/running."""

from __future__ import annotations

import argparse
import json
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
) -> dict[str, Any]:
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
        started = _parse_ts(rec.get("started_at")) or _parse_ts(rec.get("finished_at"))
        if started is None or started > cutoff:
            continue
        patch = {
            "id": rid,
            "stream": rec.get("stream"),
            "kind": rec.get("kind", "stream_run"),
            "started_at": rec.get("started_at"),
            "status": "failed",
            "finished_at": now,
            "detail": (
                f"swept: abandoned {st} older than {max_age_hours:g}h "
                f"(was: {rec.get('detail') or 'n/a'})"
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
    p = argparse.ArgumentParser(description="Mark stale Growth runs as failed")
    p.add_argument("--hours", type=float, default=2.0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--runs", type=Path, default=growth_root / "data" / "runs.jsonl")
    args = p.parse_args()
    print(json.dumps(sweep_runs(args.runs, max_age_hours=args.hours, dry_run=args.dry_run), indent=2))


if __name__ == "__main__":
    main()
