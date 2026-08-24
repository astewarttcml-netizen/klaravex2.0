"""Minimal settings loader for legacy research scrapers (no app.config import)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_PLACEHOLDERS = {"your_key_here", "placeholder", "changeme", "xxx"}


def _is_placeholder(val: str) -> bool:
    return (val or "").strip().lower() in _PLACEHOLDERS


def _list_from_env(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default).strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


@dataclass
class LegacyResearchSettings:
    apollo_api_key: str = ""
    google_places_api_key: str = ""
    apollo_min_employees: int = 10
    apollo_max_employees: int = 200
    apollo_locations_list: list[str] = field(default_factory=lambda: ["United States"])
    apollo_titles_list: list[str] = field(default_factory=list)
    apollo_industries_list: list[str] = field(default_factory=list)
    apollo_org_ids_list: list[str] = field(default_factory=list)
    hunter_api_key: str = ""

    @property
    def apollo_configured(self) -> bool:
        return bool(self.apollo_api_key and not _is_placeholder(self.apollo_api_key))

    @property
    def hunter_configured(self) -> bool:
        return bool(self.hunter_api_key and not _is_placeholder(self.hunter_api_key))


def load_legacy_settings(klaravex_root: Path) -> LegacyResearchSettings:
    """Load API keys + Apollo filters from legacy klaravex env files."""
    candidates = [
        klaravex_root / ".env",
        klaravex_root / "infra" / "docker-services" / "worker" / ".env",
    ]
    for env_path in candidates:
        if env_path.is_file():
            load_dotenv(env_path, override=False)

    locations = _list_from_env("APOLLO_LOCATIONS", os.getenv("APOLLO_LOCATION", "United States"))
    titles = _list_from_env(
        "APOLLO_TITLES",
        "Owner,Managing Partner,Office Manager,Practice Manager,Operations Manager,IT Manager",
    )
    industries = _list_from_env(
        "APOLLO_INDUSTRIES",
        "law practice,accounting,medical practice,dental,legal services",
    )
    org_ids = _list_from_env("APOLLO_ORG_IDS", "")

    return LegacyResearchSettings(
        apollo_api_key=os.getenv("APOLLO_API_KEY", "").strip(),
        google_places_api_key=os.getenv("GOOGLE_PLACES_API_KEY", "").strip(),
        hunter_api_key=os.getenv("HUNTER_API_KEY", "").strip(),
        apollo_min_employees=int(os.getenv("APOLLO_MIN_EMPLOYEES", "10")),
        apollo_max_employees=int(os.getenv("APOLLO_MAX_EMPLOYEES", "200")),
        apollo_locations_list=locations or ["United States"],
        apollo_titles_list=titles,
        apollo_industries_list=industries,
        apollo_org_ids_list=org_ids,
    )
