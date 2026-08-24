"""Assemble charter-format leads outbox drafts from misplaced per-prospect files + research bundles."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

VOICE_REPLACEMENTS = (
    (re.compile(r"\bI hope this (?:message|email) finds you well\.?\s*", re.I), ""),
    (re.compile(r"\bI['']m reaching out from\b", re.I), "Klaravex reaches out to"),
    (re.compile(r"\bI recently (?:conducted|analyzed|reviewed)\b", re.I), "Klaravex research shows"),
    (re.compile(r"\bI'm reaching out\b", re.I), "Klaravex is reaching out"),
    (re.compile(r"\bI noticed\b", re.I), "Klaravex identified"),
    (re.compile(r"\bI'd be happy to\b", re.I), "Klaravex can"),
    (re.compile(r"\bWould you be open to\b", re.I), "Would your team be open to"),
    (re.compile(r"\bcompliance\b", re.I), "readiness"),
    (re.compile(r"\[Your Name\][^\n]*", re.I), "Klaravex Team"),
    (re.compile(r"\[Your Company Name\]", re.I), "Klaravex"),
    (re.compile(r"\[Your Title\][^\n]*", re.I), ""),
    (re.compile(r"\[Your Contact Information\][^\n]*", re.I), ""),
)

SUBJECT_RE = re.compile(r"^Subject:\s*(.+)$", re.M | re.I)
SIGNAL_TABLE_RE = re.compile(
    r"## Signals[^\n]*\n+(.*?)(?=\n## |\Z)",
    re.S | re.I,
)
OUTREACH_MSG_RE = re.compile(
    r"### Personalized Message[^\n]*\n+(.*?)(?=\n### |\n## |\Z)",
    re.S | re.I,
)


def _load_enriched(research_dir: Path) -> list[dict[str, Any]]:
    summary_path = research_dir / "summary.json"
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    enriched = data.get("enriched") or []
    if not isinstance(enriched, list):
        raise RuntimeError(f"invalid summary.json enriched list: {summary_path}")
    return enriched


def _slug_from_draft_path(path: Path, slugs: list[str]) -> str | None:
    stem = path.stem.lower()
    stem_clean = re.sub(r"^prospect[_-]\d+[_-]?", "", stem)
    tokens = [t for t in re.split(r"[^a-z0-9]+", stem_clean) if len(t) > 3]
    best: tuple[int, str] | None = None
    for slug in slugs:
        hits = sum(1 for t in tokens if t in slug)
        if hits and (best is None or hits > best[0]):
            best = (hits, slug)
    if best and best[0] >= 1:
        return best[1]

    m = re.search(r"prospect[_-](\d+)", path.name.lower())
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(slugs):
            return slugs[idx]
    return None


def _collect_draft_files(draft_dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in draft_dirs:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.md")):
            if path.name.startswith("."):
                continue
            if path.name in {"README.md", "drafts.md"}:
                continue
            files.append(path)
    return files


def _map_drafts_to_slugs(draft_files: list[Path], slugs: list[str]) -> dict[str, Path]:
    mapped: dict[str, Path] = {}
    for path in draft_files:
        slug = _slug_from_draft_path(path, slugs)
        if slug:
            mapped[slug] = path
    return mapped


_NOISE_SCRAPERS = {"social_hook", "news_mentions", "forum_mentions"}
_NOISE_EXCERPT_RE = re.compile(
    r"^(News:|HackerNews:)|banned|\b(Hetzner|Azure|Atera|Vapi|Smartlead|Apollo)\b",
    re.I,
)
_FIRST_PERSON_RE = re.compile(r"\b(I['']m|\bI\b|\bme\b|\bmy\b)\b", re.I)


def _extract_signal_table(bundle_summary: str) -> str:
    m = SIGNAL_TABLE_RE.search(bundle_summary)
    if not m:
        return ""
    return _client_safe_signal_table(m.group(1).strip())


def _client_safe_signal_table(table: str) -> str:
    """Keep web/ssl/tech rows; drop news/HN blurbs and banned-vendor names."""
    kept: list[str] = []
    header_lines: list[str] = []
    for line in table.splitlines():
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if "signal_id" in line or line.startswith("|---") or (parts and parts[0] in {"signal_id", "-----------"}):
            header_lines.append(line)
            continue
        if len(parts) < 3:
            continue
        sid, scraper, excerpt = parts[0], parts[1], parts[2]
        if scraper in _NOISE_SCRAPERS:
            continue
        if _NOISE_EXCERPT_RE.search(excerpt) or _FIRST_PERSON_RE.search(excerpt):
            continue
        kept.append(line)
    if not kept:
        return "| signal_id | scraper | excerpt |\n|-----------|---------|---------|\n| — | — | (no client-safe signals) |"
    if header_lines:
        return "\n".join(header_lines + kept)
    return (
        "| signal_id | scraper | excerpt |\n|-----------|---------|---------\n"
        + "\n".join(kept)
    )


def _apply_voice(text: str) -> str:
    out = text.strip()
    for pattern, repl in VOICE_REPLACEMENTS:
        out = pattern.sub(repl, out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    if "klaravex.com" not in out.lower():
        out = out.rstrip() + "\n\nLearn more at klaravex.com."
    return out.strip()


def _parse_loose_outreach(text: str) -> tuple[str, str]:
    msg_m = OUTREACH_MSG_RE.search(text)
    block = msg_m.group(1).strip() if msg_m else text.strip()
    subject_m = SUBJECT_RE.search(block)
    subject = subject_m.group(1).strip() if subject_m else "Security readiness for your practice"
    body = SUBJECT_RE.sub("", block, count=1).strip() if subject_m else block
    body = re.sub(r"^Hi [^\n,]+,\s*", "Dear colleague,\n\n", body, count=1, flags=re.I)
    body = _apply_voice(body)
    return subject, body


def _inject_signal_citations(body: str, signal_ids: list[str]) -> str:
    if not signal_ids:
        return body
    if re.search(r"\[[a-z]+-\d+\]", body):
        return body
    cites = " ".join(f"[{sid}]" for sid in signal_ids[:3])
    return body.rstrip() + f"\n\nKlaravex research flagged: {cites}."


def _signal_ids_from_table(table: str, limit: int = 5) -> list[str]:
    ids: list[str] = []
    for line in table.splitlines():
        if not line.startswith("|") or "signal_id" in line or line.startswith("|---"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if parts and re.match(r"^[a-z]+-\d+$", parts[0]):
            ids.append(parts[0])
    return ids[:limit]


def _research_section(*, idx: int, slug: str, research_dir: Path, confidence: float) -> str:
    bundle_path = research_dir / slug / "bundle.summary.md"
    table = ""
    if bundle_path.is_file():
        table = _extract_signal_table(bundle_path.read_text(encoding="utf-8"))
    if not table:
        table = "| signal_id | scraper | excerpt |\n|-----------|---------|---------|\n| — | — | (no bundle table) |"
    return f"""## RESEARCH — prospect-{idx}-{slug}
**Confidence Score:** {confidence:.2f}

**Signal Table:**
{table}
"""


def _outreach_section(*, idx: int, slug: str, subject: str, body: str, prospect: dict[str, Any]) -> str:
    return f"""## OUTREACH — prospect-{idx}-{slug}

**Subject Line:** {subject}

**Email Body:**

{body}
"""


def _shortlist_block(enriched: list[dict[str, Any]], drafted_slugs: set[str]) -> str:
    lines = ["## Prospect Shortlist", ""]
    for entry in enriched:
        p = entry.get("prospect") or {}
        slug = entry.get("slug") or ""
        status = "drafted" if slug in drafted_slugs else "research only (no misplaced draft found)"
        lines.append(
            f"- **{p.get('company_name', slug)}** — {p.get('vertical', '?')}, "
            f"{p.get('city', '?')}, {p.get('state', '?')}; "
            f"contact: {p.get('contact_first_name', '')} {p.get('contact_last_name', '')} "
            f"({p.get('contact_title', '')}); {status}; "
            f"source: public-web research"
        )
    lines.append("")
    return "\n".join(lines)


def _preferred_hooks(table: str, limit: int = 4) -> list[tuple[str, str]]:
    """Return (signal_id, excerpt) preferring web/ssl findings, never news blurbs."""
    preferred: list[tuple[str, str]] = []
    fallback: list[tuple[str, str]] = []
    for line in table.splitlines():
        if not line.startswith("|") or "signal_id" in line or line.startswith("|---"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 3:
            continue
        sid, scraper, excerpt = parts[0], parts[1], parts[2]
        if not re.match(r"^[a-z]+-\d+$", sid) or excerpt in {"—", "-"}:
            continue
        if scraper in _NOISE_SCRAPERS:
            continue
        if excerpt.lower().startswith("news:") or excerpt.lower().startswith("hackernews:"):
            continue
        if _NOISE_EXCERPT_RE.search(excerpt) or _FIRST_PERSON_RE.search(excerpt):
            continue
        item = (sid, excerpt)
        if scraper in {"web_scanner", "ssl_scanner"}:
            preferred.append(item)
        else:
            fallback.append(item)
    out: list[tuple[str, str]] = []
    for item in preferred + fallback:
        if item not in out:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _draft_outreach_from_signals(*, prospect: dict[str, Any], hooks: list[tuple[str, str]]) -> tuple[str, str]:
    company = (prospect.get("company_name") or "your practice").strip()
    domain = (prospect.get("domain") or "your site").strip()
    first = (prospect.get("contact_first_name") or "there").strip()
    vertical = (prospect.get("vertical") or "professional").replace("_", " ").strip()
    subject = f"{company} — public-site readiness findings"
    if hooks:
        bullets = "\n".join(f"- {excerpt} [{sid}]" for sid, excerpt in hooks)
        cites = " ".join(f"[{sid}]" for sid, _ in hooks)
        body = (
            f"Dear {first},\n\n"
            f"Klaravex reviewed the public-facing infrastructure for {company} ({domain}) "
            f"and found gaps that matter for {vertical} practices handling client data:\n\n"
            f"{bullets}\n\n"
            "These are the kinds of findings that show up on cyber-insurance questionnaires "
            "and client security reviews. Klaravex runs readiness, managed detection, and "
            "vCISO advisory for firms like yours under the Directive tier.\n\n"
            "15 minutes to walk through what we found — worth a call?\n\n"
            "Klaravex\nklaravex.com\n"
            f"\nKlaravex research flagged: {cites}."
        )
    else:
        body = (
            f"Dear {first},\n\n"
            f"Klaravex reviewed public-facing infrastructure for {company} ({domain}). "
            "A short readiness conversation would help your team see what a client or "
            "insurer would flag first.\n\n"
            "Klaravex runs readiness, managed detection, and vCISO advisory under the "
            "Directive tier. 15 minutes — worth a call?\n\n"
            "Klaravex\nklaravex.com"
        )
    return subject, _apply_voice(body)


def assemble_from_research(
    *,
    research_dir: Path,
    output_path: Path,
    run_id: str,
) -> dict[str, Any]:
    """Build a charter-format outbox file from scraper bundles (no LLM drafts)."""
    summary_path = research_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    enriched = summary.get("enriched") or []
    skipped_rows = summary.get("skipped") or []
    if not isinstance(enriched, list) or not enriched:
        raise RuntimeError(f"no enriched prospects in {summary_path}")

    parts = [
        f"# Leads Shortlist — assembled from research run `{run_id}`",
        "",
        "_Assembled from public-web research bundles (programmatic draft)._",
        "",
        _shortlist_block(enriched, {str(e.get("slug") or "") for e in enriched if e.get("slug")}),
    ]
    drafted = 0
    skipped_no_email: list[str] = []

    for idx, entry in enumerate(enriched, start=1):
        slug = str(entry.get("slug") or "")
        prospect = entry.get("prospect") or {}
        confidence = float(entry.get("research_confidence") or 0.0)
        parts.append(_research_section(idx=idx, slug=slug, research_dir=research_dir, confidence=confidence))

        email = str(prospect.get("contact_email") or "").strip()
        if not email or "@" not in email:
            skipped_no_email.append(slug)
            continue

        table = ""
        bundle_path = research_dir / slug / "bundle.summary.md"
        if bundle_path.is_file():
            table = _extract_signal_table(bundle_path.read_text(encoding="utf-8"))
        hooks = _preferred_hooks(table)
        subject, body = _draft_outreach_from_signals(prospect=prospect, hooks=hooks)
        first = str(prospect.get("contact_first_name") or "").strip()
        last = str(prospect.get("contact_last_name") or "").strip()
        contact = " ".join(p for p in (first, last) if p)
        extra_meta = (
            f"**Email:** {email}\n"
            f"**Contact:** {contact}\n"
            f"**Company:** {prospect.get('company_name') or ''}\n"
            f"**Title:** {prospect.get('contact_title') or ''}\n"
        )
        outreach = _outreach_section(
            idx=idx, slug=slug, subject=subject, body=body, prospect=prospect
        )
        outreach = outreach.replace(
            f"## OUTREACH — prospect-{idx}-{slug}\n\n",
            f"## OUTREACH — prospect-{idx}-{slug}\n\n{extra_meta}\n",
            1,
        )
        parts.append(outreach)
        parts.append("")
        drafted += 1

    skip_lines: list[str] = []
    if isinstance(skipped_rows, list):
        for row in skipped_rows:
            if isinstance(row, dict):
                skip_lines.append(
                    f"- `{row.get('slug') or row.get('domain')}` — below confidence or scraper skip"
                )
            else:
                skip_lines.append(f"- `{row}`")
    for slug in skipped_no_email:
        skip_lines.append(f"- `{slug}` — missing email after enrichment")

    if skip_lines:
        parts.append("## SKIPPED")
        parts.append("")
        parts.extend(skip_lines)
        parts.append("")

    body = "\n".join(parts).rstrip() + "\n"
    _assert_gate_ready(body)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(body, encoding="utf-8")
    return {
        "output": str(output_path),
        "prospect_count": len(enriched),
        "drafted_count": drafted,
        "skipped_no_email": skipped_no_email,
    }


def _assert_gate_ready(body: str) -> None:
    from growth.gatekeeper.adjudicate import evaluate

    verdict = evaluate(body, "leads")
    if verdict["status"] == "APPROVED":
        return
    checks = {k: v[0] for k, v in verdict["checks"].items()}
    fails = "; ".join(verdict["failures"] or [str(checks)])
    raise RuntimeError(f"assembled leads draft would be REJECTED by gatekeeper: {fails}")


def assemble(
    *,
    research_dir: Path,
    draft_dirs: list[Path],
    output_path: Path,
    run_id: str,
) -> dict[str, Any]:
    enriched = _load_enriched(research_dir)
    slugs = [str(e["slug"]) for e in enriched if e.get("slug")]
    draft_map = _map_drafts_to_slugs(_collect_draft_files(draft_dirs), slugs)

    parts = [
        f"# Leads Shortlist — assembled from research run `{run_id}`",
        "",
        f"_Assembled by `leads_assembler.py` from research bundles + misplaced charter drafts._",
        "",
    ]
    drafted: set[str] = set()

    for entry in enriched:
        slug = entry.get("slug")
        if slug and slug in draft_map:
            drafted.add(str(slug))

    parts.append(_shortlist_block(enriched, drafted))

    skipped: list[str] = []
    for idx, entry in enumerate(enriched, start=1):
        slug = str(entry.get("slug") or "")
        prospect = entry.get("prospect") or {}
        confidence = float(entry.get("research_confidence") or 0.0)
        parts.append(_research_section(idx=idx, slug=slug, research_dir=research_dir, confidence=confidence))

        draft_path = draft_map.get(slug)
        if not draft_path:
            skipped.append(slug)
            continue

        subject, body = _parse_loose_outreach(draft_path.read_text(encoding="utf-8"))
        bundle_table = ""
        bundle_path = research_dir / slug / "bundle.summary.md"
        if bundle_path.is_file():
            bundle_table = _extract_signal_table(bundle_path.read_text(encoding="utf-8"))
        body = _inject_signal_citations(body, _signal_ids_from_table(bundle_table))
        parts.append(_outreach_section(idx=idx, slug=slug, subject=subject, body=body, prospect=prospect))
        parts.append("")

    if skipped:
        parts.append("## SKIPPED")
        parts.append("")
        for slug in skipped:
            parts.append(f"- `{slug}` — no misplaced draft file found for assembler")
        parts.append("")

    body = "\n".join(parts).rstrip() + "\n"
    _assert_gate_ready(body)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(body, encoding="utf-8")

    return {
        "output": str(output_path),
        "prospect_count": len(enriched),
        "drafted_count": len(drafted),
        "skipped_slugs": skipped,
        "draft_sources": {k: str(v) for k, v in draft_map.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble charter-format leads outbox from research + misplaced drafts")
    parser.add_argument(
        "--research-dir",
        default=os.getenv(
            "GROWTH_RESEARCH_ARTIFACT_DIR",
            "/home/anthony/Klaravex2.0/growth/data/research",
        ),
    )
    parser.add_argument("--research-run-id", required=True)
    parser.add_argument(
        "--draft-dir",
        action="append",
        default=[],
        help="Directory containing misplaced prospect markdown drafts (repeatable)",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output outbox path (default: revenue-agents/outbox/leads/YYYY-MM-DD-us-vertical-shortlist.md)",
    )
    parser.add_argument(
        "--root",
        default=os.getenv("GROWTH_REVENUE_AGENTS_ROOT", "/home/anthony/Klaravex2.0/revenue-agents"),
    )
    args = parser.parse_args()

    research_dir = Path(args.research_dir) / args.research_run_id
    if not research_dir.is_dir():
        print(f"research dir not found: {research_dir}")
        return 2

    draft_dirs = [Path(d) for d in args.draft_dir] or [
        Path("/home/anthony/Klaravex2.0/growth/data/executor/misplaced/277b9b04"),
        Path("/home/anthony/Klaravex2.0/growth/outreach"),
    ]

    if args.output:
        output_path = Path(args.output)
    else:
        today = date.today().isoformat()
        output_path = Path(args.root) / "outbox" / "leads" / f"{today}-us-law-accounting-medical-shortlist.md"

    result = assemble(research_dir=research_dir, draft_dirs=draft_dirs, output_path=output_path, run_id=args.research_run_id)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
