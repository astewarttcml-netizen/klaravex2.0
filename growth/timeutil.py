"""USA dual-coast Growth OS clocks.

- **Eastern** ``America/New_York`` — ops timers + B2B publish default
- **Western** ``America/Los_Angeles`` — B2C publish default (Pacific)

Override with ``GROWTH_TIMEZONE`` / ``GROWTH_TIMEZONE_WEST``.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DEFAULT_EAST = "America/New_York"
DEFAULT_WEST = "America/Los_Angeles"
DEFAULT_HOUR = 10


def east_tz_name() -> str:
    return (os.getenv("GROWTH_TIMEZONE") or DEFAULT_EAST).strip() or DEFAULT_EAST


def west_tz_name() -> str:
    return (os.getenv("GROWTH_TIMEZONE_WEST") or DEFAULT_WEST).strip() or DEFAULT_WEST


def growth_tz_name() -> str:
    """Primary/ops timezone (Eastern)."""
    return east_tz_name()


def growth_tz() -> ZoneInfo:
    return ZoneInfo(growth_tz_name())


def tz_for_coast(coast: str) -> ZoneInfo:
    c = (coast or "east").strip().lower()
    if c in {"west", "western", "pacific", "pt", "pst", "pdt", "la"}:
        return ZoneInfo(west_tz_name())
    return ZoneInfo(east_tz_name())


def coast_for_surface(surface: str) -> str:
    """B2B → Eastern morning; B2C → Western morning."""
    s = (surface or "").strip().lower()
    if s in {"consumer", "b2c", "personal"}:
        return "west"
    return "east"


def now_local(coast: str = "east") -> datetime:
    return datetime.now(tz_for_coast(coast))


def to_utc_iso(dt: datetime) -> str:
    """ISO-8601 UTC with Z suffix for Zernio APIs."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=growth_tz())
    utc = dt.astimezone(ZoneInfo("UTC"))
    return utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def next_slot(
    *,
    hour: int = DEFAULT_HOUR,
    minute: int = 0,
    coast: str = "east",
    after: datetime | None = None,
) -> datetime:
    """Next wall-clock slot on the given US coast (default 10:00 local)."""
    tz = tz_for_coast(coast)
    base = after or datetime.now(tz)
    if base.tzinfo is None:
        base = base.replace(tzinfo=tz)
    else:
        base = base.astimezone(tz)
    candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= base:
        candidate = candidate + timedelta(days=1)
    return candidate


def schedule_iso(
    *,
    hour: int = DEFAULT_HOUR,
    minute: int = 0,
    coast: str = "east",
    surface: str | None = None,
) -> str:
    """UTC ISO for next publish slot; ``surface`` maps B2C→west, B2B→east."""
    if surface:
        coast = coast_for_surface(surface)
    return to_utc_iso(next_slot(hour=hour, minute=minute, coast=coast))


def schedule_meta(surface: str | None = None, *, hour: int = DEFAULT_HOUR) -> dict[str, str]:
    coast = coast_for_surface(surface or "business")
    slot = next_slot(hour=hour, coast=coast)
    return {
        "coast": coast,
        "timezone": west_tz_name() if coast == "west" else east_tz_name(),
        "local": slot.strftime("%Y-%m-%d %H:%M %Z"),
        "utc": to_utc_iso(slot),
    }
