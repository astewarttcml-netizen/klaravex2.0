"""Pull live ads performance into revenue-agents/outbox/ads/inputs/."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from growth.adapters import ads as ads_adapter


def main() -> int:
    p = argparse.ArgumentParser(description="Pull Google/Meta/LinkedIn ads reports into outbox/ads/inputs")
    p.add_argument("--days", type=int, default=7)
    p.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "revenue-agents",
    )
    p.add_argument("--probe-only", action="store_true")
    args = p.parse_args()

    if args.probe_only:
        print(json.dumps(ads_adapter.probe_platforms(), indent=2))
        return 0

    result = ads_adapter.write_inputs(days=args.days, revenue_agents_root=args.root)
    print(json.dumps({"paths": result.get("paths"), "errors": result.get("errors"), "platforms": list((result.get("reports") or {}).keys())}, indent=2))
    return 0 if not result.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
