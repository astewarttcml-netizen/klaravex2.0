"""Daily accountability digests for department heads (Nadia / Marco)."""

from __future__ import annotations

from typing import Any

__all__ = [
    "HEAD_PROFILES",
    "SOCIAL_WEEK_THEMES",
    "generate_digests",
    "render_digest",
    "week_theme_for",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from growth.digests import heads

        return getattr(heads, name)
    raise AttributeError(name)
