"""Serialize ProspectResearchBundle artifacts for charter + gate consumption."""

from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from typing import Any


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "prospect").lower()).strip("-")
    return slug[:80] or "prospect"


def bundle_to_artifact(bundle: Any) -> dict[str, Any]:
    """Convert a legacy ProspectResearchBundle into a JSON-serializable artifact."""
    if is_dataclass(bundle):
        data = asdict(bundle)
    elif isinstance(bundle, dict):
        data = dict(bundle)
    else:
        raise TypeError(f"unsupported bundle type: {type(bundle)!r}")

    raw_sources: dict[str, list] = data.get("raw_sources") or {}
    signals: list[dict[str, str]] = []
    prefix_map = {
        "google_reviews_raw": "gr",
        "web_scanner_raw": "web",
        "job_postings_raw": "job",
        "social_hook_raw": "soc",
        "news_mentions_raw": "news",
        "forum_mentions_raw": "forum",
        "tech_stack_raw": "tech",
        "ssl_scanner_raw": "ssl",
        "breach_check_raw": "br",
        "linkedin_company_raw": "li",
        "employee_reviews_raw": "emp",
    }

    for raw_key, items in raw_sources.items():
        if not isinstance(items, list):
            continue
        prefix = prefix_map.get(raw_key, raw_key.replace("_raw", "")[:4])
        scraper = raw_key.replace("_raw", "")
        for idx, excerpt in enumerate(items, start=1):
            text = str(excerpt).strip()
            if not text:
                continue
            signals.append(
                {
                    "signal_id": f"{prefix}-{idx:02d}",
                    "scraper": scraper,
                    "excerpt": text,
                }
            )

    return {
        "google_review_complaints": data.get("google_review_complaints") or [],
        "web_issues": data.get("web_issues") or [],
        "job_pain_signals": data.get("job_pain_signals") or [],
        "social_hooks": data.get("social_hooks") or [],
        "research_confidence": float(data.get("research_confidence") or 0.0),
        "signals": signals,
        "raw_sources": raw_sources,
    }


def render_bundle_summary(prospect: dict[str, Any], artifact: dict[str, Any]) -> str:
    """Human-readable summary for charter prompt / operator review."""
    lines = [
        f"# Research summary — {prospect.get('company_name') or prospect.get('domain')}",
        "",
        f"**Domain:** {prospect.get('domain') or '(none)'}",
        f"**Confidence:** {artifact.get('research_confidence', 0.0):.2f}",
        f"**Contact:** {prospect.get('contact_first_name', '')} {prospect.get('contact_last_name', '')}".strip(),
        "",
        "## Signals (cite signal_id in outreach copy)",
        "",
        "| signal_id | scraper | excerpt |",
        "|-----------|---------|---------|",
    ]
    for row in artifact.get("signals") or []:
        excerpt = (row.get("excerpt") or "").replace("|", "\\|")[:200]
        lines.append(
            f"| {row.get('signal_id')} | {row.get('scraper')} | {excerpt} |"
        )
    if len(lines) == 8:
        lines.append("| — | — | _no signals returned_ |")
    lines.append("")
    return "\n".join(lines)
