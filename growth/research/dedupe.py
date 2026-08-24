"""Dedupe prospects against recent Growth OS leads outbox history."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

_EMAIL_DOMAIN_RE = re.compile(
    r"@([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*)",
    re.IGNORECASE,
)
_DOMAIN_RE = re.compile(
    r"\b(?:domain|website)[:\s]+([a-z0-9](?:[a-z0-9.-]{0,253}[a-z0-9])?\.[a-z]{2,})\b",
    re.IGNORECASE,
)


def collect_excluded_domains(
    revenue_agents_root: Path,
    *,
    lookback_days: int = 90,
) -> set[str]:
    """Return lowercased domains seen in leads outbox within lookback window."""
    outbox = revenue_agents_root / "outbox" / "leads"
    if not outbox.is_dir():
        return set()

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    excluded: set[str] = set()

    for path in outbox.glob("*.md"):
        if path.name.startswith("."):
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime < cutoff:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in _EMAIL_DOMAIN_RE.finditer(text):
            excluded.add(match.group(1).lower().lstrip("www."))
        for match in _DOMAIN_RE.finditer(text):
            excluded.add(match.group(1).lower().lstrip("www."))

    return excluded
