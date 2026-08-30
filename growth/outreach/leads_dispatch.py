"""Dispatch gatekeeper-APPROVED leads outbox drafts to Smartlead."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from growth.adapters import smartlead as smartlead_adapter
from growth.outreach import sent_log

GATE_VERDICT_RE = re.compile(r"^## GATE VERDICT\s*$(.*)", re.M | re.S)
APPROVED_RE = re.compile(r"\*\*Status:\*\*\s*APPROVED\b")
OUTREACH_SECTION_RE = re.compile(
    r"^## OUTREACH(?:\s*[—–-]\s*(?P<slug>[^\n]+))?\s*$",
    re.M | re.I,
)
META_RE = {
    "email": re.compile(r"^\*\*Email:\*\*\s*(.+)$", re.M | re.I),
    "contact": re.compile(r"^\*\*Contact:\*\*\s*(.+)$", re.M | re.I),
    "company": re.compile(r"^\*\*Company:\*\*\s*(.+)$", re.M | re.I),
    "title": re.compile(r"^\*\*Title:\*\*\s*(.+)$", re.M | re.I),
}
SUBJECT_RE = re.compile(
    r"^(?:Subject:|\*\*Subject Line:\*\*)\s*(.+)$",
    re.M | re.I,
)
RESEARCH_RUN_RE = re.compile(
    r"assembled from research run [`'\"]?([0-9a-f-]{36})",
    re.I,
)
OUTREACH_SLUG_RE = re.compile(r"^prospect-\d+-(.+)$", re.I)


def _is_approved(text: str) -> bool:
    m = GATE_VERDICT_RE.search(text)
    if not m:
        return False
    return bool(APPROVED_RE.search(m.group(1)))


def _split_name(full: str) -> tuple[str, str]:
    parts = full.strip().split(None, 1)
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _research_slug(raw_slug: str) -> str:
    raw = raw_slug.strip()
    m = OUTREACH_SLUG_RE.match(raw)
    return m.group(1) if m else raw


def _load_prospect_index(research_run_id: str) -> dict[str, dict[str, str]]:
    research_dir = Path(os.getenv("GROWTH_RESEARCH_ARTIFACT_DIR", "/home/anthony/Klaravex2.0/growth/data/research"))
    summary_path = research_dir / research_run_id / "summary.json"
    if not summary_path.is_file():
        return {}
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    index: dict[str, dict[str, str]] = {}
    for row in summary.get("enriched") or []:
        slug = str(row.get("slug") or "").strip()
        prospect = row.get("prospect") or {}
        if not slug or not isinstance(prospect, dict):
            continue
        index[slug] = {
            "email": str(prospect.get("contact_email") or "").strip(),
            "first_name": str(prospect.get("contact_first_name") or "").strip(),
            "last_name": str(prospect.get("contact_last_name") or "").strip(),
            "company_name": str(prospect.get("company_name") or "").strip(),
            "contact_title": str(prospect.get("contact_title") or "").strip(),
        }
    return index


def _research_run_id_from_text(text: str) -> str:
    m = RESEARCH_RUN_RE.search(text)
    return m.group(1) if m else ""


def _parse_outreach_sections(
    text: str,
    *,
    prospect_index: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Extract outreach blocks from charter-shaped leads drafts."""
    sections: list[dict[str, str]] = []
    matches = list(OUTREACH_SECTION_RE.finditer(text))
    if not matches:
        return sections

    prospect_index = prospect_index or {}
    for idx, m in enumerate(matches):
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        gate_m = re.search(r"^## GATE VERDICT\s*$", block, re.M)
        if gate_m:
            block = block[: gate_m.start()].strip()
        raw_slug = (m.group("slug") or f"prospect-{idx + 1}").strip()
        slug = _research_slug(raw_slug)

        subject_m = SUBJECT_RE.search(block)
        subject = subject_m.group(1).strip() if subject_m else ""
        body = block
        if subject_m:
            body = block[subject_m.end() :].strip()
        body = re.sub(r"^\*\*Email Body:\*\*\s*", "", body, flags=re.I).strip()
        li_m = re.search(r"^\*\*LinkedIn Message:\*\*\s*$", body, re.M | re.I)
        if li_m:
            body = body[: li_m.start()].strip()

        email = ""
        first_name = ""
        last_name = ""
        company = ""
        title = ""
        prospect = prospect_index.get(slug, {})
        email = prospect.get("email", "")
        first_name = prospect.get("first_name", "")
        last_name = prospect.get("last_name", "")
        company = prospect.get("company_name", "")
        title = prospect.get("contact_title", "")

        for key, rx in META_RE.items():
            hit = rx.search(block) or rx.search(text)
            if not hit:
                continue
            val = hit.group(1).strip()
            if key == "email" and val:
                email = val
            elif key == "contact" and val:
                first_name, last_name = _split_name(val)
            elif key == "company" and val:
                company = val
            elif key == "title" and val:
                title = val

        sections.append(
            {
                "slug": slug,
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "company_name": company,
                "contact_title": title,
                "subject": subject,
                "body_text": body,
            }
        )
    return sections


def dispatch_file(path: Path, *, dry_run: bool = False) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if "## BRIDGED" in text:
        return {"file": str(path), "status": "skipped", "reason": "already bridged"}
    if not _is_approved(text):
        return {"file": str(path), "status": "skipped", "reason": "no APPROVED gate verdict"}

    research_run_id = _research_run_id_from_text(text)
    prospect_index = _load_prospect_index(research_run_id) if research_run_id else {}
    leads = _parse_outreach_sections(text, prospect_index=prospect_index)
    if not leads:
        return {"file": str(path), "status": "skipped", "reason": "no ## OUTREACH sections parsed"}

    results: list[dict[str, Any]] = []
    for lead in leads:
        if dry_run:
            results.append({"slug": lead["slug"], "status": "dry_run", "email": lead.get("email")})
            continue
        if not lead.get("email") or not lead.get("subject"):
            results.append(
                {
                    "slug": lead["slug"],
                    "status": "skipped",
                    "reason": "missing email or subject",
                }
            )
            continue
        # Per-action idempotency (gate #41): a crash mid-file must not resend
        # already-dispatched prospects on retry.
        action_key = sent_log.make_action_key("leads", path.name, "email", lead["email"])
        prior = sent_log.already_sent(action_key)
        if prior:
            results.append(
                {
                    "slug": lead["slug"],
                    "status": "skipped",
                    "reason": f"already sent {prior.get('sent_at')} (sent-log)",
                    "action_key": action_key,
                }
            )
            continue
        out = smartlead_adapter.enqueue(payload=lead)
        if out.get("status") in {"connected", "ok"}:
            sent_log.record_sent(
                action_key,
                stream="leads",
                action="email",
                target=lead["email"],
                meta={"slug": lead["slug"], "file": path.name, "via": "smartlead"},
            )
        results.append({"slug": lead["slug"], "action_key": action_key, **out})

    ok = all(r.get("status") in {"connected", "dry_run", "skipped"} for r in results)
    if not dry_run and ok:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        path.write_text(
            text.rstrip()
            + f"\n\n## BRIDGED\n\n- **Bridged:** {now}\n- **Action:** smartlead_enqueue\n"
            + f"- **Refs:** `{json.dumps(results)[:500]}`\n",
            encoding="utf-8",
        )
    return {"file": str(path), "status": "ok" if ok else "failed", "results": results}


def dispatch_outbox(root: Path, *, dry_run: bool = False) -> list[dict[str, Any]]:
    leads_dir = root / "outbox" / "leads"
    if not leads_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(leads_dir.glob("*.md")):
        if "poc" in path.name.lower():
            continue
        out.append(dispatch_file(path, dry_run=dry_run))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Enqueue APPROVED leads drafts via Smartlead")
    parser.add_argument(
        "--root",
        default=os.getenv("GROWTH_REVENUE_AGENTS_ROOT", "/home/anthony/Klaravex2.0/revenue-agents"),
        help="revenue-agents root (contains outbox/leads/)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--file", default="", help="Dispatch one leads draft only")
    args = parser.parse_args()

    if smartlead_adapter._readonly() and not args.dry_run:
        print("SMARTLEAD_READONLY=true — use --dry-run or set SMARTLEAD_READONLY=false")
        return 2

    root = Path(args.root)
    if args.file:
        results = [dispatch_file(Path(args.file), dry_run=args.dry_run)]
    else:
        results = dispatch_outbox(root, dry_run=args.dry_run)
    print(json.dumps(results, indent=2))
    failed = [r for r in results if r.get("status") == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
