"""Build Nadia (Growth) and Marco (Sales) accountability digests.

Writes markdown under ``revenue-agents/outbox/digests/`` and returns structured
payloads for the Growth API / klaravex-os cockpit.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

GATE_RE = re.compile(
    r"##\s*GATE\s+VERDICT\s*\n+(.*?)(?=\n##\s|\Z)",
    re.IGNORECASE | re.DOTALL,
)
STATUS_RE = re.compile(r"\*\*Status:\*\*\s*(\w+)", re.IGNORECASE)
BRIDGED_RE = re.compile(r"##\s*BRIDGED\b", re.IGNORECASE)

# ISO week % 4 → theme (see revenue-agents/charters/social-growth.md)
SOCIAL_WEEK_THEMES: tuple[dict[str, str], ...] = (
    {
        "slug": "hipaa-habits",
        "business": "Portal access, backup retention, access reviews",
        "consumer": "Why practices skip boring controls",
    },
    {
        "slug": "mfa-edge-base",
        "business": "Layered controls before audit theater",
        "consumer": "MFA + hardened edge as first stack",
    },
    {
        "slug": "access-reviews",
        "business": "Who has PHI/systems access this month",
        "consumer": "Shared logins / orphaned home-office accounts",
    },
    {
        "slug": "incident-boring-work",
        "business": "Habits that prevent tomorrow's incident",
        "consumer": "Wi‑Fi up, MFA maybe",
    },
)

# klaravex-os people: person-nadia / person-marco
HEAD_PROFILES: dict[str, dict[str, Any]] = {
    "nadia": {
        "name": "Nadia",
        "role": "Head of Growth & Marketing",
        "person_id": "person-nadia",
        "department_id": "dept-marketing-growth",
        "streams": ("socials", "seo-blog", "kb", "backlinks", "ads", "forums", "gatekeeper"),
        "outbox_streams": ("socials", "seo-blog", "kb", "backlinks", "ads", "forums"),
        "focus": (
            "Content strategy, social growth KPIs (charters/social-growth.md), "
            "forums replies (outbox/forums), Zernio routing, gate health."
        ),
    },
    "marco": {
        "name": "Marco",
        "role": "Head of Sales",
        "person_id": "person-marco",
        "department_id": "dept-sales",
        "streams": ("leads", "freelance", "gatekeeper"),
        "outbox_streams": ("leads", "freelance"),
        "focus": "Pipeline drafts, lead dispatch, outreach readiness.",
    },
}


def week_theme_for(day: str | date | None = None) -> dict[str, Any]:
    """Return current social theme from ISO week rotation."""
    if isinstance(day, str):
        d = date.fromisoformat(day)
    elif isinstance(day, date):
        d = day
    else:
        d = date.today()
    iso_week = d.isocalendar().week
    theme = SOCIAL_WEEK_THEMES[iso_week % len(SOCIAL_WEEK_THEMES)]
    return {
        "iso_week": iso_week,
        "year": d.isocalendar().year,
        **theme,
    }


def _social_gate_stats(drafts: list[DraftRow]) -> dict[str, int]:
    socials = [d for d in drafts if d.stream == "socials"]
    return {
        "total": len(socials),
        "approved": sum(1 for d in socials if d.gate == "APPROVED"),
        "bridged": sum(1 for d in socials if d.bridged),
        "approved_unbridged": sum(
            1 for d in socials if d.gate == "APPROVED" and not d.bridged
        ),
        "rejected": sum(1 for d in socials if d.gate == "REJECTED"),
        "ungated": sum(1 for d in socials if d.gate == "UNGATED"),
    }


@dataclass
class DraftRow:
    stream: str
    path: str
    gate: str  # APPROVED | REJECTED | UNGATED | unknown
    bridged: bool = False


@dataclass
class HeadDigest:
    head_id: str
    name: str
    role: str
    date: str
    focus: str
    run_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    drafts: list[DraftRow] = field(default_factory=list)
    escalations: list[str] = field(default_factory=list)
    path: str | None = None
    week_theme: dict[str, Any] | None = None
    social_kpis: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "head_id": self.head_id,
            "name": self.name,
            "role": self.role,
            "date": self.date,
            "focus": self.focus,
            "run_counts": self.run_counts,
            "drafts": [
                {
                    "stream": d.stream,
                    "path": d.path,
                    "gate": d.gate,
                    "bridged": d.bridged,
                }
                for d in self.drafts
            ],
            "escalations": self.escalations,
            "path": self.path,
            "week_theme": self.week_theme,
            "social_kpis": self.social_kpis,
        }


def _repo_roots() -> tuple[Path, Path]:
    growth_root = Path(__file__).resolve().parents[1]
    repo_root = growth_root.parent
    return growth_root, repo_root


def _load_runs(runs_path: Path) -> list[dict[str, Any]]:
    if not runs_path.is_file():
        return []
    out: list[dict[str, Any]] = []
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
        out.append(rec)
    # latest status per id
    by_id: dict[str, dict[str, Any]] = {}
    for rec in out:
        rid = rec.get("id")
        if rid:
            by_id[rid] = rec
    return list(by_id.values())


def _counts_for_streams(
    runs: list[dict[str, Any]], streams: tuple[str, ...]
) -> dict[str, dict[str, int]]:
    by_stream: dict[str, dict[str, int]] = {}
    for r in runs:
        stream = str(r.get("stream") or "unknown")
        if stream not in streams:
            continue
        st = str(r.get("status") or "unknown")
        bucket = by_stream.setdefault(stream, {})
        bucket[st] = bucket.get(st, 0) + 1
    return by_stream


def _parse_gate(text: str) -> str:
    m = GATE_RE.search(text)
    if not m:
        return "UNGATED"
    block = m.group(1)
    sm = STATUS_RE.search(block)
    if sm:
        return sm.group(1).upper()
    if re.search(r"\bAPPROVED\b", block, re.I):
        return "APPROVED"
    if re.search(r"\bREJECTED\b", block, re.I):
        return "REJECTED"
    return "unknown"


def _scan_outbox(outbox_root: Path, streams: tuple[str, ...]) -> list[DraftRow]:
    rows: list[DraftRow] = []
    for stream in streams:
        d = outbox_root / stream
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.md")):
            if path.name.startswith("."):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            rows.append(
                DraftRow(
                    stream=stream,
                    path=str(path),
                    gate=_parse_gate(text),
                    bridged=bool(BRIDGED_RE.search(text)),
                )
            )
    return rows


def _escalations(digest: HeadDigest) -> list[str]:
    notes: list[str] = []
    for stream, counts in digest.run_counts.items():
        failed = counts.get("failed", 0)
        if failed >= 2:
            notes.append(f"{stream}: {failed} failed runs in ledger — review executor logs")
        running = counts.get("running", 0)
        completed = counts.get("completed", 0)
        if running and not completed and failed:
            notes.append(f"{stream}: runs stuck/failed with no clean completion")
    rejected = [d for d in digest.drafts if d.gate == "REJECTED"]
    if len(rejected) >= 2:
        notes.append(f"{len(rejected)} REJECTED drafts still in outbox — originating agents should regenerate")
    ungated = [d for d in digest.drafts if d.gate == "UNGATED"]
    if ungated:
        notes.append(f"{len(ungated)} ungated draft(s) awaiting gatekeeper")
    approved_unbridged = [
        d for d in digest.drafts if d.gate == "APPROVED" and not d.bridged and d.stream in ("socials", "leads", "seo-blog", "kb", "forums")
    ]
    if approved_unbridged:
        notes.append(
            f"{len(approved_unbridged)} APPROVED draft(s) not yet BRIDGED — check dispatch"
        )
    return notes


def _render_nadia_kpis(d: HeadDigest) -> list[str]:
    theme = d.week_theme or week_theme_for(d.date)
    kpis = d.social_kpis or {}
    gate = kpis.get("gate") or {}
    approved = gate.get("approved", 0)
    bridged = gate.get("bridged", 0)
    rate = f"{(100 * bridged / approved):.0f}%" if approved else "n/a"
    return [
        "## Growth KPIs (social)",
        "",
        f"- **Week theme:** `{theme['slug']}` (ISO week {theme['iso_week']})",
        f"- **Business angle:** {theme['business']}",
        f"- **Consumer angle:** {theme['consumer']}",
        "- **Targets (week):** B2C LI (Zernio) 4–5 · B2B LI page 2–3 · TikTok 4–7 · YT Shorts 3–5",
        f"- **Outbox socials:** total={gate.get('total', 0)} · APPROVED={approved} · "
        f"BRIDGED={bridged} · APPROVED-unbridged={gate.get('approved_unbridged', 0)} · "
        f"REJECTED={gate.get('rejected', 0)} · ungated={gate.get('ungated', 0)}",
        f"- **APPROVED→BRIDGED rate:** {rate} (target ≥70%)",
        "- **Timezone:** dual-coast USA — B2B 10:00 ET · B2C 10:00 PT "
        "(`America/New_York` / `America/Los_Angeles`)",
        "- **Routing:** B2B/klaravex.com → Zernio page · B2C/personal.klaravex.com → Zernio · "
        "TikTok/YT → Zernio (`@klararavex` / `@klaravex`)",
        "- **Forums:** 3–5 theme-aligned Reddit/MSP replies/week (answer-first; "
        "`utm_source=reddit`); see charter Forums section",
        "- **Manual check:** comments + profile clicks + UTM site visits "
        "(prefer over follower vanity)",
        "- **Charter:** `revenue-agents/charters/social-growth.md`",
        "",
    ]


def render_digest(d: HeadDigest) -> str:
    lines = [
        f"# Daily digest — {d.name} ({d.role})",
        "",
        f"- **Date:** {d.date}",
        f"- **Head:** {d.name} / `{d.head_id}`",
        f"- **Focus:** {d.focus}",
        "",
    ]
    if d.head_id == "nadia":
        lines += _render_nadia_kpis(d)
    lines += [
        "## Run ledger (Growth API)",
        "",
    ]
    if not d.run_counts:
        lines.append("_No runs for owned streams yet._")
    else:
        lines.append("| Stream | Status counts |")
        lines.append("|---|---|")
        for stream in sorted(d.run_counts):
            parts = ", ".join(f"{k}={v}" for k, v in sorted(d.run_counts[stream].items()))
            lines.append(f"| `{stream}` | {parts} |")
    lines += ["", "## Outbox drafts", ""]
    if not d.drafts:
        lines.append("_No markdown drafts in owned outbox streams._")
    else:
        lines.append("| Stream | Gate | Bridged | File |")
        lines.append("|---|---|---|---|")
        for row in d.drafts:
            name = Path(row.path).name
            lines.append(
                f"| `{row.stream}` | {row.gate} | {'yes' if row.bridged else 'no'} | `{name}` |"
            )
    lines += ["", "## Escalations (for Anthony if non-empty)", ""]
    if d.escalations:
        for e in d.escalations:
            lines.append(f"- {e}")
    else:
        lines.append("- None — heads review dashboard only; no exec escalation.")
    lines += [
        "",
        "## Suggested actions",
        "",
    ]
    if d.head_id == "nadia":
        theme = (d.week_theme or {}).get("slug", "this week's theme")
        lines += [
            f"1. Ship drafts on theme `{theme}` — unique TikTok + YT media; no cross-reuse.",
            "2. Bridge APPROVED socials: Zernio (B2C personal.klaravex.com + B2B page, TikTok, YT).",
            "3. 15–20 min LinkedIn: B2B on clinic/MSP threads; B2C on home/SMB tech for personal.klaravex.com.",
            "4. Forums: ship paste-ready replies from `outbox/forums/` (answer-first; soft CTA ≤1/3).",
            "5. Kill or rewrite REJECTED / ungated; double down on formats with comments/saves.",
        ]
    else:
        lines += [
            "1. Review leads shortlists that are APPROVED + BRIDGED (campaign ready).",
            "2. Chase any APPROVED-but-not-bridged outreach.",
            "3. Prep call briefs from the latest shortlist before discovery.",
        ]
    lines += ["", f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} UTC_", ""]
    return "\n".join(lines)


def build_head_digest(
    head_id: str,
    *,
    runs: list[dict[str, Any]],
    outbox_root: Path,
    day: str | None = None,
) -> HeadDigest:
    profile = HEAD_PROFILES[head_id]
    day = day or date.today().isoformat()
    drafts = _scan_outbox(outbox_root, tuple(profile["outbox_streams"]))
    digest = HeadDigest(
        head_id=head_id,
        name=profile["name"],
        role=profile["role"],
        date=day,
        focus=profile["focus"],
        run_counts=_counts_for_streams(runs, tuple(profile["streams"])),
        drafts=drafts,
    )
    if head_id == "nadia":
        digest.week_theme = week_theme_for(day)
        digest.social_kpis = {"gate": _social_gate_stats(drafts)}
    digest.escalations = _escalations(digest)
    return digest


def generate_digests(
    *,
    day: str | None = None,
    write: bool = True,
    revenue_agents_root: Path | None = None,
    runs_path: Path | None = None,
) -> dict[str, Any]:
    growth_root, repo_root = _repo_roots()
    ra = Path(
        revenue_agents_root
        or (repo_root / "revenue-agents")
    ).resolve()
    runs_file = Path(runs_path or (growth_root / "data" / "runs.jsonl")).resolve()
    outbox = ra / "outbox"
    digests_dir = outbox / "digests"
    day = day or date.today().isoformat()
    runs = _load_runs(runs_file)

    results: list[HeadDigest] = []
    for head_id in ("nadia", "marco"):
        digest = build_head_digest(head_id, runs=runs, outbox_root=outbox, day=day)
        body = render_digest(digest)
        if write:
            digests_dir.mkdir(parents=True, exist_ok=True)
            path = digests_dir / f"{day}-{head_id}.md"
            path.write_text(body, encoding="utf-8")
            digest.path = str(path)
        results.append(digest)

    return {
        "date": day,
        "digests": [d.to_dict() for d in results],
        "dir": str(digests_dir) if write else None,
    }


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Generate Nadia/Marco daily digests")
    p.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    p.add_argument("--dry-run", action="store_true", help="Print only; do not write files")
    args = p.parse_args()
    payload = generate_digests(day=args.date, write=not args.dry_run)
    print(json.dumps(payload, indent=2))
    if not args.dry_run:
        for d in payload["digests"]:
            print(d.get("path"))


if __name__ == "__main__":
    main()
