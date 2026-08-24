"""Stream name allowlist — must match revenue-agents/charters/*.md basenames."""

from __future__ import annotations

ALLOWED_STREAMS: frozenset[str] = frozenset(
    {
        "leads",
        "socials",
        "seo-blog",
        "kb",
        "backlinks",
        "ads",
        "freelance",
        "forums",
        "gatekeeper",
    }
)


def is_allowed_stream(name: str) -> bool:
    return name in ALLOWED_STREAMS
