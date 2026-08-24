"""Pull current, real-world security problems into the KB stream's inputs.

Fetches the CISA Known Exploited Vulnerabilities catalog and writes a
markdown brief to outbox/kb/inputs/current-threats.md before each KB run.
The KB agent uses it to pick topical articles instead of only evergreen ones.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import date, timedelta
from pathlib import Path

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
DEFAULT_OUT = "/home/anthony/Klaravex2.0/revenue-agents/outbox/kb/inputs/current-threats.md"
WINDOW_DAYS = 14


def fetch_kev() -> list[dict]:
    req = urllib.request.Request(KEV_URL, headers={"User-Agent": "KlaravexGrowth/2.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    return data.get("vulnerabilities") or []


def recent(vulns: list[dict], days: int = WINDOW_DAYS) -> list[dict]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = [v for v in vulns if (v.get("dateAdded") or "") >= cutoff]
    return sorted(rows, key=lambda v: v.get("dateAdded") or "", reverse=True)


def render(rows: list[dict]) -> str:
    today = date.today().isoformat()
    lines = [
        f"# Current security problems — updated {today}",
        "",
        "Source: CISA Known Exploited Vulnerabilities catalog (actively exploited",
        f"in the wild, added in the last {WINDOW_DAYS} days). Use these to pick a",
        "TOPICAL article when one is relevant to Klaravex audiences (SMB business",
        "stacks or consumer devices). Never invent incidents beyond this list;",
        "evergreen pool topics remain valid when nothing here fits.",
        "",
        "| Added | Vendor | Product | Issue | Ransomware use |",
        "|---|---|---|---|---|",
    ]
    for v in rows[:25]:
        lines.append(
            f"| {v.get('dateAdded', '')} | {v.get('vendorProject', '')} "
            f"| {v.get('product', '')} | {v.get('vulnerabilityName', '')} "
            f"| {v.get('knownRansomwareCampaignUse', 'Unknown')} |"
        )
    if not rows:
        lines.append("| — | — | — | (no additions in window) | — |")
    lines += [
        "",
        "Angle guidance:",
        "- business surface: what a small firm should do this week about the",
        "  affected vendor/product (patch, verify exposure, ask their IT partner).",
        "- consumer surface: only when a consumer product (router, browser, phone",
        "  OS, smart device) appears above — plain-English 'update now' guidance.",
        "- Voice rules unchanged: corporate we/Klaravex, readiness not compliance,",
        "  CTA to klaravex.com or personal.klaravex.com.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    out_path = Path(os.getenv("KB_CURRENT_ISSUES_PATH", DEFAULT_OUT))
    rows = recent(fetch_kev())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(rows), encoding="utf-8")
    print(f"wrote {out_path} ({len(rows)} recent KEV entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
