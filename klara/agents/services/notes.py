"""
app/services/notes.py
─────────────────────
Read-only helper for the loki-vault.

The vault is the canonical shared-memory store for every Klara AI agent.
This module provides cached file reads against the local Hetzner clone at
/opt/loki-vault (kept fresh by the 15-min git pull cron in /etc/cron.d/loki-vault-pull).

Writes are NEVER exposed here — only the RARV journal team has write access,
via a separate submission queue. See CLAUDE.md "Single write path".

Cache strategy:
- File contents cached with 60s TTL to avoid disk hammering during a burst of
  agent calls within the same minute.
- Cache key includes the file's mtime — if the cron pulls fresh content, mtime
  changes and the cache invalidates automatically on next read.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import get_settings

# Module-level cache: { (path_str, mtime): (read_at, content) }
_cache: dict[tuple[str, float], tuple[float, str]] = {}
_TTL_SEC = 60.0


def _vault_root() -> Path:
    """Resolve the vault root from settings (default /opt/loki-vault)."""
    settings = get_settings()
    return Path(getattr(settings, "vault_path", "/opt/loki-vault"))


def _read_file(rel_path: str) -> Optional[str]:
    """
    Cached read of a file inside the vault.

    Returns None when the file doesn't exist — agents should gracefully
    degrade when a topic file is missing rather than raise.
    """
    full = _vault_root() / rel_path
    if not full.is_file():
        return None

    try:
        mtime = full.stat().st_mtime
    except OSError:
        return None

    key = (str(full), mtime)
    now = time.time()
    cached = _cache.get(key)
    if cached and (now - cached[0]) < _TTL_SEC:
        return cached[1]

    try:
        content = full.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    # Evict previous mtime entries for this path (single live entry per path)
    for k in list(_cache.keys()):
        if k[0] == str(full) and k != key:
            _cache.pop(k, None)
    _cache[key] = (now, content)
    return content


# ── Top-level readers ─────────────────────────────────────────────────────

def read_memory() -> Optional[str]:
    """Long-term durable facts (MEMORY.md). Rebuilt nightly at 02:00 Berlin."""
    return _read_file("MEMORY.md")


def read_context() -> Optional[str]:
    """Working memory — current tasks, in-flight items. Refreshed every 30 min."""
    return _read_file("CONTEXT.md")


def read_goals() -> Optional[str]:
    """Strategic goals (manually maintained by Anthony — agents only read)."""
    return _read_file("GOALS.md")


# ── Topic-organized knowledge ─────────────────────────────────────────────

def read_topic(slug: str) -> Optional[str]:
    """
    Read knowledge/<slug>.md — consolidated knowledge for a topic.

    Slugs are lowercase-with-dashes (e.g. 'apollo-auth', 'freelancermap').
    Returns None if the topic file doesn't exist.
    """
    return _read_file(f"knowledge/{_normalize_slug(slug)}.md")


def read_topic_index(slug: str) -> Optional[str]:
    """
    Read topics/<slug>.md — per-topic index page with Obsidian wikilinks.

    Useful when you want a curated entry point into all notes about a topic.
    """
    return _read_file(f"topics/{_normalize_slug(slug)}.md")


def list_topics() -> list[str]:
    """All slugs that have a knowledge/<slug>.md file."""
    root = _vault_root() / "knowledge"
    if not root.is_dir():
        return []
    return sorted(
        p.stem for p in root.iterdir()
        if p.is_file() and p.suffix == ".md" and not p.name.startswith(".")
    )


# ── Daily notes ───────────────────────────────────────────────────────────

def read_daily(day: Optional[date] = None) -> Optional[str]:
    """
    Read daily/YYYY-MM-DD.md.

    Defaults to today in Europe/Berlin — the canonical timezone for the
    journal team's daily-note filenames.
    """
    if day is None:
        day = _today_berlin()
    return _read_file(f"daily/{day.isoformat()}.md")


def list_daily_notes(since: Optional[date] = None) -> list[date]:
    """List all daily-note dates (sorted ascending). Optionally filter to >= since."""
    root = _vault_root() / "daily"
    if not root.is_dir():
        return []
    dates = []
    for p in root.iterdir():
        if not p.is_file() or p.suffix != ".md":
            continue
        try:
            d = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if since is None or d >= since:
            dates.append(d)
    return sorted(dates)


# ── Helpers ───────────────────────────────────────────────────────────────

def _normalize_slug(slug: str) -> str:
    """Lowercase, dashes-not-spaces, no leading/trailing dashes."""
    return (
        slug.strip()
        .lower()
        .replace(" ", "-")
        .replace("_", "-")
        .strip("-")
    )


def _today_berlin() -> date:
    """Today in Europe/Berlin — agents' canonical timezone for daily-note naming."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Berlin")).date()
    except Exception:
        return datetime.now(timezone.utc).date()


# ── Cache control (for tests + admin tools) ───────────────────────────────

def clear_cache() -> None:
    """Drop the in-memory file cache. Use sparingly — TTL handles invalidation."""
    _cache.clear()


def cache_stats() -> dict:
    """Diagnostic — current cache state."""
    return {
        "entries": len(_cache),
        "vault_root": str(_vault_root()),
        "ttl_sec": _TTL_SEC,
    }
