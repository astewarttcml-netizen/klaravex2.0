"""Programmatic gatekeeper — append ## GATE VERDICT to ungated outbox drafts."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

GATED_STREAMS = ("socials", "seo-blog", "kb", "leads", "backlinks", "forums")

VOICE_FAIL_RE = re.compile(
    r"\b(I['']m|\bI\b|\bme\b|\bmy\b|our founder|\bAnthony\b|\bLoki\b|\[Your Name\])",
    re.I,
)
COMPLIANCE_RE = re.compile(r"\bcompliance\b", re.I)
BANNED_VENDOR_RE = re.compile(r"\b(Hetzner|Azure|Atera|Vapi|Smartlead|Apollo)\b", re.I)
SIGNAL_CITE_RE = re.compile(r"\[[a-z]+-\d+\]")
RESEARCH_SECTION_RE = re.compile(r"^## RESEARCH\s*[—–-]\s*prospect-\d+-", re.M)
OUTREACH_SECTION_RE = re.compile(r"^## OUTREACH\s*[—–-]\s*prospect-\d+-", re.M)
CTA_RE = re.compile(r"klaravex\.com|personal\.klaravex\.com", re.I)


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_ungated(text: str) -> bool:
    return "## GATE VERDICT" not in text


OUTREACH_BLOCK_RE = re.compile(r"^## OUTREACH\s*[—–-].*?(?=^## |\Z)", re.M | re.S)


def _outreach_and_shortlist_text(text: str) -> str:
    parts: list[str] = []
    m = re.search(r"^## Prospect Shortlist\s*$", text, re.M)
    if m:
        end = re.search(r"^## RESEARCH\s*[—–-]", text[m.end() :], re.M)
        chunk = text[m.end() : m.end() + end.start()] if end else text[m.end() : m.end() + 2000]
        parts.append(chunk)
    parts.extend(OUTREACH_BLOCK_RE.findall(text))
    return "\n".join(parts) if parts else text


FAQ_SECTION_RE = re.compile(
    r"^## (?:FAQ|Frequently Asked Questions)\s*$.*?(?=^## |\Z)",
    re.M | re.S,
)


def _voice_scope(text: str, stream: str) -> str:
    if stream in {"leads"}:
        return _outreach_and_shortlist_text(text)
    scope = text
    faq = FAQ_SECTION_RE.search(scope)
    if faq:
        scope = scope[: faq.start()] + scope[faq.end() :]
    return scope


def _check_voice(text: str, stream: str = "") -> tuple[str, str]:
    scope = _voice_scope(text, stream)
    hits = VOICE_FAIL_RE.findall(scope)
    if hits:
        sample = ", ".join(sorted(set(hits))[:5])
        return "FAIL", f"first-person or banned voice tokens: {sample}"
    if stream == "forums":
        # Soft CTA optional: allow answer-only replies marked CTA: none
        if CTA_RE.search(text) or re.search(r"\*\*CTA:\*\*\s*none\b", text, re.I):
            return "PASS", "corporate voice; forums CTA optional when marked none"
        return "FAIL", "forums draft needs klaravex.com CTA or **CTA:** none on replies"
    if not CTA_RE.search(text):
        return "FAIL", "missing klaravex.com or personal.klaravex.com CTA"
    return "PASS", "corporate voice + CTA present"


_URL_RE = re.compile(r"https?://\S+")


def _strip_urls(text: str) -> str:
    """URLs are addresses, not copy — slugs may legitimately contain keywords like 'compliance'."""
    return _URL_RE.sub(" ", text)


def _check_language(text: str) -> tuple[str, str]:
    # Charter: no vendor names / "compliance" anywhere in the draft copy (URLs exempt).
    scope = _strip_urls(text)
    if COMPLIANCE_RE.search(scope):
        return "FAIL", 'contains banned word "compliance"'
    if BANNED_VENDOR_RE.search(scope):
        return "FAIL", "contains banned infrastructure vendor name"
    return "PASS", "language clean"


def _check_claims(text: str, stream: str = "") -> tuple[str, str]:
    # Organic social must not dump hard pricing CTAs ($49/user/month etc.)
    if stream == "socials" and re.search(r"\$\s*\d+", text):
        return "FAIL", "hard pricing ($…) in organic social — wrong surface"
    return "PASS", "no untraceable pricing claims detected (basic scan)"


_NO_ASSETS_RE = re.compile(
    r"No assets generated|prompts-only draft|assets?\s+not\s+generated|TODO:?\s*generate",
    re.I,
)
_ASSET_FILE_RE = re.compile(
    r"(?i)(?:^|\s)(?:File|Path|Asset):\s*(\S+\.(?:png|jpe?g|webp|gif|mp4|mov|webm))",
    re.M,
)
_MEDIA_GLOBS = ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.gif", "*.mp4", "*.mov", "*.webm")


def _on_disk_media(draft_path: Path | None) -> list[Path]:
    if draft_path is None:
        return []
    found: list[Path] = []
    for d in (draft_path.parent / "assets", draft_path.parent / draft_path.stem, draft_path.parent):
        if not d.is_dir():
            continue
        for pattern in _MEDIA_GLOBS:
            found.extend(d.glob(pattern))
    return found


def _check_media(stream: str, text: str, draft_path: Path | None = None) -> tuple[str, str]:
    if stream != "socials":
        return "PASS", "not applicable"
    if "IMAGE_PROMPT" not in text or "VIDEO_BRIEF" not in text:
        return "FAIL", "missing IMAGE_PROMPT or VIDEO_BRIEF"
    if _NO_ASSETS_RE.search(text):
        return "FAIL", "ASSETS section is prompts-only — real media file required (image or video)"
    on_disk = _on_disk_media(draft_path)
    if on_disk:
        return "PASS", f"media on disk ({on_disk[0].name})"
    named = _ASSET_FILE_RE.findall(text)
    if not named:
        return "FAIL", "no media File/Path under ASSETS (png/jpg/webp/mp4/… required — text-only never ships)"
    # Filenames listed but nothing on disk yet → still fail (charter: generate in same run)
    return "FAIL", f"ASSETS names listed ({len(named)}) but no media file on disk yet"


def _check_outreach(stream: str, text: str) -> tuple[str, str]:
    if stream != "leads":
        return "N-A", "not applicable"
    if not RESEARCH_SECTION_RE.search(text) or not OUTREACH_SECTION_RE.search(text):
        return "FAIL", "missing ## RESEARCH / ## OUTREACH prospect sections"
    if not SIGNAL_CITE_RE.search(text):
        return "FAIL", "outreach missing [signal_id] citations"
    return "PASS", "research sections and signal citations present"


def _check_forums(stream: str, text: str) -> tuple[str, str]:
    if stream != "forums":
        return "N-A", "not applicable"
    if "### THREAD" not in text or "### REPLY" not in text:
        return "FAIL", "missing ### THREAD / ### REPLY sections"
    soft = len(re.findall(r"\*\*CTA:\*\*\s*soft\b", text, re.I))
    none = len(re.findall(r"\*\*CTA:\*\*\s*none\b", text, re.I))
    if soft + none == 0 and not CTA_RE.search(text):
        return "FAIL", "each reply needs META CTA none|soft (or draft-level klaravex link)"
    if soft > 0 and none + soft > 0 and soft > max(1, (soft + none + 2) // 3):
        return "FAIL", "soft CTA rate too high (max ~1 of 3 replies)"
    return "PASS", "thread/reply structure + CTA discipline ok"


def evaluate(text: str, stream: str, draft_path: Path | None = None) -> dict:
    """Rubric only — does not write a GATE VERDICT."""
    checks = {
        "Voice": _check_voice(text, stream),
        "Language": _check_language(text),
        "Claims": _check_claims(text, stream),
        "Media": _check_media(stream, text, draft_path),
        "Outreach": _check_outreach(stream, text),
        "Forums": _check_forums(stream, text),
    }
    approved = all(r in {"PASS", "N-A"} for r, _ in checks.values())
    status = "APPROVED" if approved else "REJECTED"
    return {
        "status": status,
        "stream": stream,
        "checks": checks,
        "failures": _failure_lines(text, stream, checks) if not approved else [],
    }


def _failure_lines(text: str, stream: str, checks: dict[str, tuple[str, str]]) -> list[str]:
    failures: list[str] = []
    voice_scope = _voice_scope(text, stream)
    if checks.get("Voice", ("PASS", ""))[0] == "FAIL":
        for i, line in enumerate(text.splitlines(), start=1):
            if line not in voice_scope:
                continue
            if VOICE_FAIL_RE.search(line):
                failures.append(f'L{i}: "{line.strip()[:120]}" — rewrite in corporate Klaravex/we voice')
    if checks.get("Language", ("PASS", ""))[0] == "FAIL":
        for i, line in enumerate(text.splitlines(), start=1):
            bare = _strip_urls(line)
            if COMPLIANCE_RE.search(bare) or BANNED_VENDOR_RE.search(bare):
                failures.append(f'L{i}: "{line.strip()[:120]}" — remove banned vendor / compliance wording')
    if stream == "leads" and not SIGNAL_CITE_RE.search(text):
        failures.append("Outreach body — add [signal_id] citations from RESEARCH tables in every email")
    if not CTA_RE.search(text):
        failures.append("Draft — add CTA link to klaravex.com or personal.klaravex.com")
    return failures[:8]


def adjudicate_file(path: Path, *, run_date: str, dry_run: bool = False) -> dict:
    text = path.read_text(encoding="utf-8")
    if not _is_ungated(text):
        return {"file": str(path), "status": "skipped", "reason": "already gated"}

    stream = path.parts[path.parts.index("outbox") + 1] if "outbox" in path.parts else "unknown"
    verdict = evaluate(text, stream, draft_path=path)
    checks = verdict["checks"]
    status = verdict["status"]

    verdict_lines = [
        "",
        "## GATE VERDICT",
        "",
        f"- **Status:** {status}",
        f"- **Timestamp:** {_utcnow()}",
        f"- **Gatekeeper run:** {run_date}",
        "",
        "| Check | Result | Notes |",
        "|---|---|---|",
    ]
    for name, (result, notes) in checks.items():
        verdict_lines.append(f"| {name} | {result} | {notes} |")

    if status == "REJECTED":
        verdict_lines.extend(["", "### Failures (REJECTED only)"])
        for item in verdict["failures"] or ["See rubric table above — regenerate per charter."]:
            verdict_lines.append(f"- {item}")

    verdict_block = "\n".join(verdict_lines) + "\n"
    if not dry_run:
        path.write_text(text.rstrip() + "\n" + verdict_block, encoding="utf-8")

    return {
        "file": str(path),
        "status": status.lower(),
        "stream": stream,
        "checks": {k: v[0] for k, v in checks.items()},
    }


def adjudicate_outbox(root: Path, *, run_date: str | None = None, dry_run: bool = False) -> list[dict]:
    run_date = run_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    results: list[dict] = []
    for stream in GATED_STREAMS:
        outbox = root / "outbox" / stream
        if not outbox.is_dir():
            continue
        for path in sorted(outbox.rglob("*.md")):
            if "poc" in path.name.lower():
                continue
            if path.name.startswith("."):
                continue
            results.append(adjudicate_file(path, run_date=run_date, dry_run=dry_run))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Append gate verdicts to ungated revenue-agent drafts")
    parser.add_argument(
        "--root",
        default=os.getenv("GROWTH_REVENUE_AGENTS_ROOT", "/home/anthony/Klaravex2.0/revenue-agents"),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--file", default="", help="Adjudicate one file only")
    args = parser.parse_args()
    root = Path(args.root)

    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if args.file:
        out = [adjudicate_file(Path(args.file), run_date=run_date, dry_run=args.dry_run)]
    else:
        out = adjudicate_outbox(root, run_date=run_date, dry_run=args.dry_run)

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
