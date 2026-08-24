"""Full Growth pull — ads performance, adapter probes, outbox brand audit."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUTBOX = ROOT / "revenue-agents" / "outbox"
AUDIT_DIR = OUTBOX / "_audit"

COMPLIANCE_RE = re.compile(r"\bcompliance\b", re.I)
UNIFI_RE = re.compile(r"\bunifi\b", re.I)
WRONG_TIER_RE = re.compile(
    r"\b(Operate|Governed|\$65|\$125|\$185|\$29\s*/\s*user|\$39\s*/\s*user)\b", re.I
)
OFFICIAL_TIER_RE = re.compile(
    r"\b(Foundation|Assurance|Directive|\$49|\$79|\$129)\b", re.I
)
PRIMARY_VENDOR_RE = re.compile(r"\b(Palo Alto|FortiGate|Fortinet|Cisco)\b", re.I)
BANNED_VENDOR_RE = re.compile(r"\b(Hetzner|Atera|Vapi|Smartlead|Apollo)\b", re.I)
GATE_STATUS_RE = re.compile(r"\*\*Status:\*\*\s*(\S+)", re.I)
CTA_B2B = re.compile(r"klaravex\.com", re.I)
CTA_B2C = re.compile(r"personal\.klaravex\.com", re.I)

STREAMS = (
    "socials",
    "seo-blog",
    "kb",
    "leads",
    "forums",
    "backlinks",
    "ads",
    "digests",
    "gatekeeper",
    "freelance",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _api(secret: str, path: str, method: str = "GET", body: dict | None = None) -> dict:
    url = f"http://127.0.0.1:4210{path}"
    headers = {"X-Growth-Secret": secret}
    with httpx.Client(timeout=30.0) as client:
        if method == "POST":
            r = client.post(url, headers=headers, json=body or {})
        else:
            r = client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()


def _probe_adapters(secret: str) -> list[dict]:
    adapters = ["hunter", "taplio", "smartlead", "wordpress", "ads"]
    rows: list[dict] = []
    for name in adapters:
        try:
            out = _api(
                secret,
                f"/v1/adapters/{name}/invoke",
                method="POST",
                body={"action": "probe"},
            )
            rows.append({"name": name, "ok": out.get("ok", True), "detail": out.get("detail", str(out)[:120])})
        except Exception as exc:  # noqa: BLE001
            rows.append({"name": name, "ok": False, "detail": str(exc)[:120]})
    return rows


def _run_ads_pull(days: int) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "growth.outreach.ads_pull",
        "--days",
        str(days),
    ]
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        return {"ok": False, "stderr": proc.stderr[-500:]}
    try:
        return {"ok": True, **json.loads(proc.stdout)}
    except json.JSONDecodeError:
        return {"ok": True, "raw": proc.stdout[-500:]}


def _gate_status(text: str) -> str:
    m = GATE_STATUS_RE.search(text)
    if m:
        return m.group(1).upper()
    if "## GATE VERDICT" in text:
        return "GATED-UNKNOWN"
    return "UNGATED"


def _brand_findings(path: Path, text: str) -> list[str]:
    findings: list[str] = []
    rel = path.relative_to(OUTBOX)
    name = path.name.lower()

    if "compliance" in name:
        findings.append("filename contains banned word compliance")

    compliance_hits = COMPLIANCE_RE.findall(text)
    if compliance_hits:
        findings.append(f'body contains "compliance" ×{len(compliance_hits)}')

    unifi = len(UNIFI_RE.findall(text))
    if unifi > 0:
        words = len(re.findall(r"\w+", text))
        pct = (unifi / max(words, 1)) * 100
        if unifi >= 3 or pct > 0.5:
            findings.append(f"UniFi overweight: {unifi} mentions ({pct:.2f}% of words; cap ≤5% mentions)")

    if WRONG_TIER_RE.search(text):
        findings.append("wrong tier or consumer price in B2B context")

    if path.parts[path.parts.index("outbox") + 1] in {"socials", "seo-blog", "kb", "ads"}:
        if not PRIMARY_VENDOR_RE.search(text) and unifi >= 2:
            findings.append("UniFi-led copy without Palo/Forti/Cisco anchor (B2B streams)")

    if BANNED_VENDOR_RE.search(text):
        findings.append("banned infrastructure vendor name")

    return findings


def _b2b_b2c_dup(text: str) -> list[str]:
    """Detect near-duplicate Business vs Consumer blocks in socials."""
    findings: list[str] = []
    biz = re.search(r"## Business Post\s*(.*?)(?=## Consumer Post|\Z)", text, re.S)
    con = re.search(r"## Consumer Post\s*(.*?)(?=## IMAGE|\Z)", text, re.S)
    if not biz or not con:
        return findings
    biz_text = re.sub(r"^###.*$", "", biz.group(1), flags=re.M)
    con_text = re.sub(r"^###.*$", "", con.group(1), flags=re.M)
    ratio = SequenceMatcher(None, biz_text[:800], con_text[:800]).ratio()
    if ratio > 0.55:
        findings.append(f"B2B/B2C near-duplicate copy (similarity {ratio:.0%})")
    # Same CTA pattern across tracks pointing wrong domain
    if CTA_B2B.search(con.group(1)) and not CTA_B2C.search(con.group(1)):
        findings.append("Consumer block links klaravex.com without personal.klaravex.com")
    return findings


def audit_outbox() -> list[dict]:
    rows: list[dict] = []
    for stream in STREAMS:
        stream_dir = OUTBOX / stream
        if not stream_dir.is_dir():
            continue
        for path in sorted(stream_dir.rglob("*.md")):
            if ".archived-poc" in path.parts or "poc" in path.name.lower():
                if "poc" in path.name.lower():
                    pass  # include poc in inventory but flag
            text = path.read_text(encoding="utf-8", errors="replace")
            rel = str(path.relative_to(ROOT))
            findings = _brand_findings(path, text)
            if stream == "socials":
                findings.extend(_b2b_b2c_dup(text))
            rows.append(
                {
                    "stream": stream,
                    "file": rel,
                    "gate": _gate_status(text),
                    "findings": findings,
                    "chars": len(text),
                }
            )
    return rows


def _summarize_gate(rows: list[dict]) -> Counter:
    c: Counter = Counter()
    for r in rows:
        if r["stream"] in {"ads", "digests", "_audit"}:
            continue
        c[r["gate"]] += 1
    return c


def write_report(
    *,
    audit_rows: list[dict],
    ads_pull: dict,
    adapters: list[dict],
    scorecard: dict,
    runs: list,
) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = AUDIT_DIR / f"{date}-full-pull.md"

    gate_counts = _summarize_gate(audit_rows)
    flagged = [r for r in audit_rows if r["findings"]]
    by_stream: dict[str, list] = defaultdict(list)
    for r in audit_rows:
        by_stream[r["stream"]].append(r)

    lines = [
        f"# Full Growth pull — { _utcnow() }",
        "",
        "Comprehensive pull: live ads performance, adapter probes, scorecard, and CLAUDE.md brand audit across all outbox streams.",
        "",
        "## Executive summary",
        "",
        f"- **Outbox files scanned:** {len(audit_rows)}",
        f"- **Brand flags:** {len(flagged)} file(s)",
        f"- **Gate status:** {dict(gate_counts)}",
        f"- **Growth runs:** {scorecard.get('total_runs', '?')} total",
        f"- **POC mode:** {scorecard.get('poc_mode')}",
        "",
        "## Live adapters",
        "",
        "| Adapter | Status | Detail |",
        "|---|---|---|",
    ]
    for a in adapters:
        status = "connected" if a.get("ok") else "FAIL"
        lines.append(f"| {a['name']} | {status} | {a.get('detail', '')[:80]} |")

    lines.extend(
        [
            "",
            "## Ads performance (last pull)",
            "",
        ]
    )
    if ads_pull.get("ok"):
        paths = ads_pull.get("paths", {})
        lines.append(f"- Markdown: `{paths.get('markdown', 'n/a')}`")
        lines.append(f"- Platforms: {', '.join(ads_pull.get('platforms', []))}")
        if ads_pull.get("errors"):
            lines.append(f"- Errors: `{ads_pull['errors']}`")
    else:
        lines.append(f"- Ads pull failed: `{ads_pull.get('stderr', ads_pull)}`")

    lines.extend(["", "## Scorecard by stream", "", "| Stream | Counts |", "|---|---|"])
    for stream, counts in sorted(scorecard.get("by_stream", {}).items()):
        parts = [f"{k}={v}" for k, v in sorted(counts.items())]
        lines.append(f"| `{stream}` | {', '.join(parts)} |")

    lines.extend(["", "## Outbox inventory", ""])
    for stream in STREAMS:
        items = by_stream.get(stream, [])
        if not items:
            continue
        lines.append(f"### `{stream}` ({len(items)} files)")
        lines.append("")
        lines.append("| File | Gate | Flags |")
        lines.append("|---|---|---|")
        for r in items:
            flags = "; ".join(r["findings"][:3]) if r["findings"] else "—"
            short = Path(r["file"]).name
            lines.append(f"| `{short}` | {r['gate']} | {flags} |")
        lines.append("")

    if flagged:
        lines.extend(["## Brand violations (action required)", ""])
        for r in flagged:
            lines.append(f"### `{Path(r['file']).name}` ({r['stream']})")
            lines.append(f"- Gate: **{r['gate']}**")
            for f in r["findings"]:
                lines.append(f"- {f}")
            lines.append("")

    lines.extend(
        [
            "## Recommended fixes",
            "",
            "1. **Rename + rewrite** seo-blog/kb HIPAA files — replace `compliance` in slug/title with `readiness`.",
            "2. **Regenerate** `socials/2026-08-23-hipaa-habits.md` — demote UniFi in consumer track; anchor B2B on Palo/Forti/Cisco + tier proof ($49/$79/$129).",
            "3. **Re-run gatekeeper** on files stuck at `DRAFT` status (not APPROVED/REJECTED).",
            "4. **Forums harvest** rejected — fix THREAD/REPLY structure before bridge.",
            "5. **Enable Google Search campaign** when ready to burn €436.80 promo match; LinkedIn T-AC-16/17 still ACTIVE at $10/day.",
            "",
            f"_Generated by `growth.outreach.full_pull` at {_utcnow()}_",
            "",
        ]
    )

    out.write_text("\n".join(lines), encoding="utf-8")
    json_path = AUDIT_DIR / f"{date}-full-pull.json"
    json_path.write_text(
        json.dumps(
            {
                "generated": _utcnow(),
                "ads_pull": ads_pull,
                "adapters": adapters,
                "scorecard": scorecard,
                "audit": audit_rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Full Growth pull + brand audit")
    parser.add_argument("--days", type=int, default=7, help="Ads performance window")
    parser.add_argument("--skip-ads", action="store_true")
    args = parser.parse_args()

    env_path = ROOT / "growth" / ".env"
    secret = ""
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            if line.startswith("GROWTH_INTERNAL_SECRET="):
                secret = line.split("=", 1)[1].strip()
                break

    ads_pull: dict = {"ok": False, "skipped": True}
    if not args.skip_ads:
        ads_pull = _run_ads_pull(args.days)

    adapters: list[dict] = []
    scorecard: dict = {}
    runs: list = []
    if secret:
        try:
            adapters = _probe_adapters(secret)
            scorecard = _api(secret, "/v1/scorecard")
            runs_raw = _api(secret, "/v1/runs?limit=100")
            runs = runs_raw if isinstance(runs_raw, list) else runs_raw.get("runs", runs_raw.get("items", []))
        except Exception as exc:  # noqa: BLE001
            scorecard = {"error": str(exc)}

    audit_rows = audit_outbox()
    report = write_report(
        audit_rows=audit_rows,
        ads_pull=ads_pull,
        adapters=adapters,
        scorecard=scorecard,
        runs=runs,
    )
    print(json.dumps({"report": str(report), "flagged": len([r for r in audit_rows if r["findings"]]), "files": len(audit_rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
