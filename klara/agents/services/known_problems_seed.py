"""
app/services/known_problems_seed.py
───────────────────────────────────
Idempotent seeder for the Know-How Library (prod-004).

Loads the bundled JSON fixture at `app/data/known_problems_seed.json` and
upserts entries into the `known_problems` table. Idempotency is keyed on
`(product, symptom)` — re-running the seed against an already-populated
table updates `diagnosis`, `fix`, and `related_ticket_templates` in place
rather than creating duplicates. This lets the fixture file evolve as
internal playbooks improve without operators having to clean rows by hand.

Two callable surfaces:

  - `load_seed_entries()` — parses + validates the JSON fixture into
    plain dicts. Pure, no DB. Used by tests.
  - `seed_known_problems(db)` — async; upserts the parsed entries into
    the given AsyncSession. Returns a (created, updated, unchanged) tuple
    so the CLI / operator can see what actually changed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field as dataclasses_field
from pathlib import Path
from typing import List, Tuple
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.known_problem import KnownProblem

logger = structlog.get_logger(__name__)

SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "known_problems_seed.json"

REQUIRED_FIELDS = ("product", "symptom", "diagnosis", "fix")


@dataclass(frozen=True)
class SeedEntry:
    product: str
    symptom: str
    diagnosis: str
    fix: str
    related_ticket_templates: List[str]
    # Lowercase, deduped, trimmed cross-cutting category tags. Optional —
    # defaults to [] so seed JSONs predating the tags column still load.
    tags: List[str] = dataclasses_field(default_factory=list)


def load_seed_entries(path: Path = SEED_PATH) -> List[SeedEntry]:
    """Parse and validate the seed JSON. Raises ValueError on malformed input."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Seed file must be a JSON array of objects.")

    entries: List[SeedEntry] = []
    seen: set[tuple[str, str]] = set()
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Seed entry {idx} is not an object.")
        for field in REQUIRED_FIELDS:
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Seed entry {idx} has invalid '{field}' (must be non-empty string)."
                )
        templates = item.get("related_ticket_templates", [])
        if not isinstance(templates, list) or not all(
            isinstance(t, str) and t.strip() for t in templates
        ):
            raise ValueError(
                f"Seed entry {idx} has invalid 'related_ticket_templates' "
                "(must be a list of non-empty strings)."
            )

        tags_raw = item.get("tags", [])
        if not isinstance(tags_raw, list) or not all(
            isinstance(t, str) for t in tags_raw
        ):
            raise ValueError(
                f"Seed entry {idx} has invalid 'tags' "
                "(must be a list of strings)."
            )

        key = (item["product"].strip().lower(), item["symptom"].strip().lower())
        if key in seen:
            raise ValueError(
                f"Seed entry {idx} duplicates an earlier (product, symptom) pair."
            )
        seen.add(key)

        # Canonicalise tags up-front: lowercase, trim, dedupe, drop empties.
        # Keeps the (product, symptom) seed semantics intact while letting
        # operators paste raw human-curated tag lists into the fixture.
        seen_tags: set[str] = set()
        normalised_tags: List[str] = []
        for t in tags_raw:
            norm = t.strip().lower()
            if not norm or norm in seen_tags:
                continue
            seen_tags.add(norm)
            normalised_tags.append(norm)

        entries.append(
            SeedEntry(
                product=item["product"].strip(),
                symptom=item["symptom"].strip(),
                diagnosis=item["diagnosis"].strip(),
                fix=item["fix"].strip(),
                related_ticket_templates=[t.strip() for t in templates],
                tags=normalised_tags,
            )
        )
    return entries


async def seed_known_problems(
    db: AsyncSession, entries: List[SeedEntry] | None = None
) -> Tuple[int, int, int]:
    """
    Upsert seed entries into the known_problems table.

    Returns (created, updated, unchanged).
    """
    if entries is None:
        entries = load_seed_entries()

    created = 0
    updated = 0
    unchanged = 0

    for entry in entries:
        result = await db.execute(
            select(KnownProblem).where(
                KnownProblem.product == entry.product,
                KnownProblem.symptom == entry.symptom,
            )
        )
        existing = result.scalar_one_or_none()

        if existing is None:
            kp = KnownProblem(
                id=str(uuid4()),
                product=entry.product,
                symptom=entry.symptom,
                diagnosis=entry.diagnosis,
                fix=entry.fix,
                related_ticket_templates=list(entry.related_ticket_templates),
                tags=list(entry.tags),
            )
            db.add(kp)
            created += 1
            continue

        changed = (
            existing.diagnosis != entry.diagnosis
            or existing.fix != entry.fix
            or list(existing.related_ticket_templates or [])
            != list(entry.related_ticket_templates)
            or list(existing.tags or []) != list(entry.tags)
        )
        if changed:
            existing.diagnosis = entry.diagnosis
            existing.fix = entry.fix
            existing.related_ticket_templates = list(entry.related_ticket_templates)
            existing.tags = list(entry.tags)
            updated += 1
        else:
            unchanged += 1

    await db.commit()
    logger.info(
        "known_problems.seed",
        created=created,
        updated=updated,
        unchanged=unchanged,
        total=len(entries),
    )
    return created, updated, unchanged
