"""Adapter registry — probe status for Layer C / klaravex-os Growth cockpit."""

from __future__ import annotations

from typing import Any, Callable

from growth.adapters import ads, clay, freelance_sites, hunter, reddit, smartlead, wordpress, zernio
from growth.adapters.freelancer import probe_status  # Import directly to avoid circular import
from growth.adapters.freelance_pipeline import health_check_endpoint

ProbeFn = Callable[[], dict[str, Any]]

ADAPTERS: list[tuple[str, str, list[str], ProbeFn]] = [
    ("hunter", "Hunter.io email find/verify", ["leads"], hunter.enrich),
    ("clay", "Clay enrichment (optional)", ["leads"], clay.enrich),
    ("zernio", "Zernio / TikTok + YouTube Shorts", ["socials"], zernio.draft),
    ("ads", "Google / Meta / LinkedIn Ads reports", ["ads"], ads.draft),
    ("smartlead", "Smartlead sequences", ["leads", "freelance"], smartlead.enqueue),
    ("wordpress", "WordPress publish", ["seo-blog", "kb"], wordpress.publish),
    ("reddit", "Reddit forums", ["forums"], reddit.probe),
    ("guru", "Guru session", ["freelance"], freelance_sites.guru),
    ("peopleperhour", "PeoplePerHour session", ["freelance"], freelance_sites.peopleperhour),
    ("freelancer", "Freelancer.com API", ["freelance"], freelance_sites.freelancer),
    ("freelance_pipeline", "Freelance bid pipeline", ["freelance"], health_check_endpoint),
]

_ADAPTER_MAP: dict[str, ProbeFn] = {name: fn for name, _, _, fn in ADAPTERS}


def get_adapter(name: str) -> ProbeFn | None:
    return _ADAPTER_MAP.get(name)


def probe_all() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, label, streams, probe in ADAPTERS:
        result = probe()
        out.append(
            {
                "name": name,
                "label": label,
                "streams": streams,
                **result,
            }
        )
    return out


def invoke(name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    fn = get_adapter(name)
    if fn is None:
        raise KeyError(name)
    if payload is not None:
        return fn(payload=payload)
    return fn()
