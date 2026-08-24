"""POC / sandbox mode — fixture data instead of live Apollo, scrapers, and adapters."""

from __future__ import annotations

import os
from pathlib import Path

_GROWTH_ROOT = Path(__file__).resolve().parents[1]

POC_MODE = os.getenv("GROWTH_POC_MODE", "false").lower() in {"1", "true", "yes", "on"}
POC_FIXTURES_DIR = Path(
    os.getenv("GROWTH_POC_FIXTURES_DIR", str(_GROWTH_ROOT / "data" / "poc"))
).resolve()


def is_poc_mode() -> bool:
    return os.getenv("GROWTH_POC_MODE", "false").lower() in {"1", "true", "yes", "on"}


def stream_fixture_path(stream: str) -> Path | None:
    """Return stream context fixture if present (non-leads streams)."""
    path = POC_FIXTURES_DIR / "streams" / stream / "context.md"
    return path if path.is_file() else None


def leads_fixture_dir() -> Path:
    return POC_FIXTURES_DIR / "leads"
