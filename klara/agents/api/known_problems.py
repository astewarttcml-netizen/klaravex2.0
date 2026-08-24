"""
app/api/known_problems.py
─────────────────────────
CRUD endpoints for the Know-How Library (prod-004).

  GET    /api/v1/known-problems/                — list, optional product / q filters
  POST   /api/v1/known-problems/                — create
  POST   /api/v1/known-problems/bulk            — idempotent batch upsert
  POST   /api/v1/known-problems/bulk-delete     — batch delete by id
  GET    /api/v1/known-problems/coverage        — per-product data-quality breakdown
  GET    /api/v1/known-problems/health          — composite library data-quality scorecard
  GET    /api/v1/known-problems/products        — distinct products with counts
  GET    /api/v1/known-problems/templates       — distinct ticket templates with counts
  GET    /api/v1/known-problems/orphans         — entries flagged with data-quality issues
  GET    /api/v1/known-problems/duplicates      — clusters of rows sharing one (product, symptom)
  GET    /api/v1/known-problems/conflicts       — duplicate clusters that disagree on fix text
  GET    /api/v1/known-problems/stale           — entries not updated in the last N days
  GET    /api/v1/known-problems/recent          — entries created within the last N days
  GET    /api/v1/known-problems/timeline        — time-bucketed entry-creation counts
  GET    /api/v1/known-problems/export          — seed-compatible JSON backup snapshot
  POST   /api/v1/known-problems/import          — restore a prior /export envelope
  POST   /api/v1/known-problems/products/rename — bulk rename one product → another
  POST   /api/v1/known-problems/products/merge  — collapse N products → one canonical product
  POST   /api/v1/known-problems/products/delete — delete every entry tied to a retired product
  POST   /api/v1/known-problems/tags/rename     — bulk rename one tag → another
  POST   /api/v1/known-problems/tags/delete     — bulk drop one tag from every entry
  POST   /api/v1/known-problems/templates/rename — bulk rename one ticket template → another
  POST   /api/v1/known-problems/templates/delete — bulk drop one ticket template from every entry
  POST   /api/v1/known-problems/templates/merge  — collapse N ticket templates → one canonical template
  GET    /api/v1/known-problems/templates/autocomplete — prefix-search templates for typeahead
  GET    /api/v1/known-problems/templates/cooccurrence — templates that co-occur with a focal template
  GET    /api/v1/known-problems/tags/cooccurrence — tags that co-occur with a focal tag
  GET    /api/v1/known-problems/tags/timeline   — time-bucketed creation counts for entries carrying a focal tag
  GET    /api/v1/known-problems/products/timeline — time-bucketed creation counts for entries tied to a focal product
  GET    /api/v1/known-problems/products/tag-breakdown — tags used within a focal product's entries, ranked
  GET    /api/v1/known-problems/tags/product-breakdown — products that carry a focal tag, ranked
  GET    /api/v1/known-problems/templates/tag-breakdown — tags used within entries that reference a focal template, ranked
  GET    /api/v1/known-problems/templates/product-breakdown — products of entries that reference a focal template, ranked
  GET    /api/v1/known-problems/tags/template-breakdown — ticket templates used within entries that carry a focal tag, ranked
  GET    /api/v1/known-problems/{id}            — get one
  PUT    /api/v1/known-problems/{id}            — replace
  PATCH  /api/v1/known-problems/{id}            — partial update
  DELETE /api/v1/known-problems/{id}            — delete
  POST   /api/v1/known-problems/{id}/duplicate  — fork an entry with optional field overrides
  POST   /api/v1/known-problems/{id}/merge      — collapse a duplicate row into this one

All endpoints require the X-API-Key management header. This is internal
admin tooling — there is no public/per-client surface area here.

Symptom search: this slice ships ILIKE-based substring matching on
`symptom` + `diagnosis`. A GIN/tsvector full-text index will replace it
in a follow-up migration without changing the request/response contract.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, List, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import String, bindparam, case, func, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.audit import AuditLog
from klara.rarv.known_problem import KnownProblem
from klara.rarv.runtime.known_problem_matcher import find_matches
from klara.rarv.runtime.known_problems_seed import SeedEntry, seed_known_problems

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class KnownProblemBase(BaseModel):
    product: str = Field(..., min_length=1, max_length=120)
    symptom: str = Field(..., min_length=1, max_length=10_000)
    diagnosis: str = Field(..., min_length=1, max_length=10_000)
    fix: str = Field(..., min_length=1, max_length=10_000)
    related_ticket_templates: List[str] = Field(default_factory=list)
    tags: List[str] = Field(
        default_factory=list,
        description=(
            "Optional cross-cutting category labels — orthogonal to "
            "`product` so one entry can be both 'Intune' and tagged "
            "'auth' alongside an unrelated Microsoft 365 'auth' entry. "
            "Normalised to lowercase, trimmed, deduplicated server-side; "
            "empty strings are dropped."
        ),
    )


class KnownProblemCreate(KnownProblemBase):
    """Payload for POST /."""


class KnownProblemUpdate(KnownProblemBase):
    """Payload for PUT /{id}. All fields required (full replace)."""


class KnownProblemPatch(BaseModel):
    """
    Payload for PATCH /{id}. Every field is optional — only the fields the
    caller actually supplies in the JSON body are written to disk. Validation
    constraints (min_length, max_length) still apply to anything that *is*
    supplied, so a client can't sneak a blank product through PATCH that
    PUT would reject.

    Partial updates are useful for admin UI inline edits (rename tags on
    one row without re-sending symptom/diagnosis/fix) and for scripted
    one-off fixes (`{"product": "Microsoft 365"}` to retitle one entry).
    Field presence is detected via Pydantic v2's `model_fields_set`, so
    the contract is "missing key = leave alone", *not* "null = clear" —
    explicit nulls are rejected by the type system on every required field.
    """
    product: Optional[str] = Field(None, min_length=1, max_length=120)
    symptom: Optional[str] = Field(None, min_length=1, max_length=10_000)
    diagnosis: Optional[str] = Field(None, min_length=1, max_length=10_000)
    fix: Optional[str] = Field(None, min_length=1, max_length=10_000)
    related_ticket_templates: Optional[List[str]] = Field(
        None,
        description=(
            "When provided, replaces the row's template list outright. "
            "Send `[]` to clear all templates; omit the key to leave the "
            "existing list untouched."
        ),
    )
    tags: Optional[List[str]] = Field(
        None,
        description=(
            "When provided, replaces the row's tag list with the canonical "
            "(lowercase, trimmed, deduped) form — same normalisation PUT "
            "applies. Send `[]` to clear all tags; omit the key to leave "
            "the existing tag list untouched."
        ),
    )


class KnownProblemDuplicate(BaseModel):
    """
    Payload for POST /{id}/duplicate — fork an existing entry into a new
    row. Every field is optional; whatever the caller supplies overrides
    the source entry's value on the new row, and any field left out is
    copied verbatim from the source.

    The shape mirrors `KnownProblemPatch` (optional fields with the same
    min/max validation that PUT/POST apply) on purpose: the admin UI's
    "Duplicate" button reuses the same edit-form schema as in-place edit,
    so a single React component drives both flows. The difference is
    semantic — PATCH writes to the original row, /duplicate writes a brand
    new row with a fresh UUID and timestamps.

    A common usage pattern is to clone a Microsoft 365 auth entry into an
    Intune-flavoured variant by overriding `product` (and sometimes
    `symptom`) while leaving `diagnosis` and `fix` to be edited by hand
    afterwards through the regular PATCH endpoint.

    An empty body is accepted and produces a literal clone — no override —
    which is sometimes what an operator wants before they start editing
    the new row. There is no uniqueness constraint on (product, symptom)
    at the DB layer, so a true clone is harmless; the /related and
    /suggest endpoints will surface it as a near-duplicate so the operator
    can notice and consolidate later.
    """
    product: Optional[str] = Field(None, min_length=1, max_length=120)
    symptom: Optional[str] = Field(None, min_length=1, max_length=10_000)
    diagnosis: Optional[str] = Field(None, min_length=1, max_length=10_000)
    fix: Optional[str] = Field(None, min_length=1, max_length=10_000)
    related_ticket_templates: Optional[List[str]] = Field(
        None,
        description=(
            "When provided, replaces the source's template list on the new "
            "row. Send `[]` to start the clone with no templates; omit the "
            "key to copy the source's list verbatim."
        ),
    )
    tags: Optional[List[str]] = Field(
        None,
        description=(
            "When provided, replaces the source's tag list with the "
            "canonical (lowercase, trimmed, deduped) form on the new row. "
            "Send `[]` to start the clone untagged; omit the key to copy "
            "the source's tag list verbatim."
        ),
    )


class KnownProblemMergeRequest(BaseModel):
    """
    Payload for POST /{target_id}/merge — collapse a duplicate Know-How
    entry into another. The target row keeps its text fields (product,
    symptom, diagnosis, fix) verbatim; only `tags` and
    `related_ticket_templates` are union-merged from source into target,
    preserving the target's existing order so the admin UI's tag pills
    don't reshuffle on merge. Source tags that already exist on target
    are no-ops; source tags that don't are appended in source order.

    By default the source row is deleted once the merge succeeds — the
    canonical follow-on to /related and /{id}/duplicate, which surface
    near-duplicates that should be collapsed. Set `keep_source=true` to
    leave the source row in place (useful when consolidating templates
    from a generic entry into a more specific one without losing the
    generic entry as a separate hit).

    The endpoint refuses to merge a row into itself (422) — that would
    delete the only copy if `keep_source=false`, which is never the
    operator's intent. Both ids must exist (404 otherwise) so the merge
    is atomic: either the union write + source delete both happen, or
    neither does.
    """
    source_id: str = Field(
        ..., min_length=1, max_length=64,
        description=(
            "UUID of the duplicate row whose tags and templates will be "
            "folded into the target. Whitespace is stripped. Must differ "
            "from the path's target id or the request is rejected with 422."
        ),
    )
    keep_source: bool = Field(
        False,
        description=(
            "When false (default), the source row is deleted after its "
            "tags and templates are union-merged into the target — the "
            "common case for collapsing duplicates surfaced by /related. "
            "When true, the source row is left in place; only the target "
            "row is mutated. Useful for one-way consolidation where the "
            "source is also referenced from elsewhere and shouldn't go away."
        ),
    )


class KnownProblemResponse(KnownProblemBase):
    id: str
    created_at: str
    updated_at: str

    @classmethod
    def from_orm_row(cls, kp: KnownProblem) -> "KnownProblemResponse":
        return cls(
            id=kp.id,
            product=kp.product,
            symptom=kp.symptom,
            diagnosis=kp.diagnosis,
            fix=kp.fix,
            related_ticket_templates=list(kp.related_ticket_templates or []),
            tags=list(kp.tags or []),
            created_at=kp.created_at.isoformat(),
            updated_at=kp.updated_at.isoformat(),
        )


class KnownProblemMergeResponse(BaseModel):
    """
    Result envelope for POST /{target_id}/merge. Mirrors the merge
    audit row shape so callers can render a one-line summary
    ("3 tags added, 1 template added, source deleted") without a
    follow-up /history fetch.
    """
    target: KnownProblemResponse
    source_id: str
    source_deleted: bool
    tags_added: List[str]
    templates_added: List[str]


def _normalize_tags(raw: List[str]) -> List[str]:
    """
    Trim, lowercase, dedupe, drop empties. Order-preserving so the first
    occurrence of each tag wins — this matters for the admin UI which
    renders tags in insertion order. Centralised here so create, update,
    and bulk-upsert all produce the same canonical form on disk.
    """
    seen: set[str] = set()
    out: List[str] = []
    for t in raw or []:
        norm = (t or "").strip().lower()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


class ProductCount(BaseModel):
    product: str
    count: int


class ProductCooccurrence(BaseModel):
    """
    One co-occurring product returned by GET /products/cooccurrence.

    `product` is the neighbour product's stored-disk casing — products are
    stored case-preserved (vendor branding matters: "Microsoft 365" is
    canonical, "microsoft 365" is not), so the response keeps whatever
    case the DB holds. `shared_tag_count` is the number of distinct tags
    that the focal product (`?product=` query param) and this neighbour
    product both attach to at least one entry of theirs respectively.

    The contract differs from /tags/cooccurrence and /templates/cooccurrence
    on purpose: each Know-How entry carries exactly one `product`, so two
    products can never appear together on the same row. The closest useful
    pairing is "products that share a topic area" — and a topic area on
    this schema means a tag. Counting distinct shared tags (rather than
    summed joint-tag occurrences) keeps the score interpretable: 5 means
    "5 different overlap topics," not "a lot of activity in one topic."

    The focal product itself is never returned — a self-pairing would
    always equal that product's own distinct-tag count and would only
    crowd the dropdown without adding signal. Products with no shared
    tags with the focal are also excluded — they would always have a
    zero count, and the admin UI's "related products" panel cares about
    the non-empty intersection list.
    """
    product: str
    shared_tag_count: int


class ProductRenameRequest(BaseModel):
    from_product: str = Field(
        ..., min_length=1, max_length=120,
        description=(
            "Existing product name to replace. Matched case-insensitively "
            "(same semantics as the list endpoint's `?product=` filter). "
            "Whitespace trimmed before matching."
        ),
    )
    to_product: str = Field(
        ..., min_length=1, max_length=120,
        description=(
            "Replacement product name. Stored case-preserved — vendor "
            "branding matters ('Microsoft 365' is canonical, "
            "'microsoft 365' is not). Whitespace trimmed; no case fold."
        ),
    )


class ProductRenameResponse(BaseModel):
    from_product: str
    to_product: str
    updated_count: int


class ProductMergeRequest(BaseModel):
    from_products: List[str] = Field(
        ..., min_length=1, max_length=50,
        description=(
            "One or more existing product names to consolidate. Matched "
            "case-insensitively (same semantics as the list endpoint's "
            "`?product=` filter), whitespace trimmed, deduped server-side. "
            "Any source that collapses to `to_product` after case-fold + "
            "trim is dropped from the source list — merging X → X is a "
            "no-op for that label and would only muddy the audit trail."
        ),
    )
    to_product: str = Field(
        ..., min_length=1, max_length=120,
        description=(
            "Target product name every source occurrence will be rewritten "
            "to. Stored case-preserved — vendor branding matters "
            "('Microsoft 365' is canonical, 'microsoft 365' is not), "
            "mirroring `/products/rename`. Whitespace trimmed; no case fold."
        ),
    )


class ProductMergeResponse(BaseModel):
    from_products: List[str]
    to_product: str
    updated_count: int


class ProductDeleteRequest(BaseModel):
    product: str = Field(
        ..., min_length=1, max_length=120,
        description=(
            "Product name to scrub from the Know-How Library. Every entry "
            "whose `product` matches this value (case-insensitively, same "
            "ILIKE rule the list endpoint's `?product=` filter uses) is "
            "deleted in full — unlike /tags/delete and /templates/delete "
            "which only drop the label from rows, /products/delete drops "
            "the rows themselves, because `product` is a non-nullable "
            "scalar and a Know-How entry without one is not meaningful. "
            "Whitespace is trimmed before matching."
        ),
    )


class ProductDeleteResponse(BaseModel):
    product: str
    deleted_count: int


class KnownProblemStats(BaseModel):
    total: int
    by_product: List[ProductCount]


class ProductCoverage(BaseModel):
    """
    Per-product data-quality breakdown returned by GET /coverage.

    `total` is the entry count for the product, and the remaining counters
    decompose that total along two orthogonal data-quality axes — tags and
    related ticket templates — so the four `with_*` / `orphan` numbers
    always sum to `total`. `last_updated_at` is the freshest `updated_at`
    timestamp across the product's entries (ISO-8601 UTC string, or `None`
    if the product has zero rows — which can't currently happen, but the
    schema keeps the option open for future joins against a separate
    product catalogue).
    """
    product: str
    total: int
    with_tags: int
    with_templates: int
    with_both: int
    orphan: int
    last_updated_at: Optional[str]


class CoverageResponse(BaseModel):
    """
    Envelope for GET /coverage. `total` is the library-wide entry count
    (echoes /stats so callers don't need a second round-trip), and
    `products` is the per-product breakdown ordered by total desc,
    product asc — the same ordering rule /products and /stats use.
    """
    total: int
    products: List[ProductCoverage]


# Weight (in score points) each data-quality axis can subtract from a
# perfect 100 when every row in the library exhibits that issue. The four
# weights sum to 100 so the worst-possible library (every row orphaned,
# duplicated, conflicting, and stale) scores 0. Conflicts carry the
# heaviest weight because a row that contradicts another row actively
# misleads readers — strictly worse than a row that's merely incomplete
# or stale. Orphans (incomplete content) and stale (rotted content) are
# weighted equally — both are "this row is not pulling its weight" rather
# than "this row is wrong". Duplicates sit one notch below because pure
# redundancy is cheap to fix (one merge) and rarely misleads on its own.
_HEALTH_WEIGHT_ORPHAN = 25.0
_HEALTH_WEIGHT_DUPLICATE = 20.0
_HEALTH_WEIGHT_CONFLICT = 35.0
_HEALTH_WEIGHT_STALE = 20.0

# Letter-grade bands applied to the composite score. Standard 10-point
# scale, cutoffs inclusive on the low end (>= 90 is A, < 90 and >= 80
# is B, …) so a clean 90.0 lands in A rather than B. F is the floor
# when nothing else matches — an empty library short-circuits to A
# above this table, on the principle that "no entries" is vacuously
# healthy rather than failing.
_HEALTH_GRADE_BANDS: list[tuple[float, str]] = [
    (90.0, "A"),
    (80.0, "B"),
    (70.0, "C"),
    (60.0, "D"),
]


def _health_grade_for(score: float) -> str:
    for cutoff, letter in _HEALTH_GRADE_BANDS:
        if score >= cutoff:
            return letter
    return "F"


class HealthComponent(BaseModel):
    """
    One axis of library data quality scored independently by `/health`.

    `count` is the number of rows the axis flagged (semantics differ per
    axis — see the field documentation on `LibraryHealth`). `ratio` is
    `count / total` rounded to four decimals (a fraction in [0, 1], not
    a percent), so a caller can render either a percentage or a raw
    fraction without re-deriving it. `penalty` is the score points this
    axis subtracted from the perfect 100 — the weights are documented on
    the per-axis field of `LibraryHealth`, and `score = 100 - sum(penalty)`
    clamped to [0, 100]. Rounded to two decimals so the four penalties
    add back to the displayed `score` without rounding drift.
    """
    count: int
    ratio: float
    penalty: float


class LibraryHealth(BaseModel):
    """
    Envelope for GET /health. A composite library data-quality scorecard.

    `total` is the library-wide entry count (echoes /stats so callers
    don't need a second round-trip). `score` is a 0–100 composite,
    rounded to one decimal, computed as `100 - sum(component.penalty)`
    and clamped to the unit interval. `grade` is the standard 10-point
    letter band over `score` (A: 90+, B: 80–89.9, C: 70–79.9, D: 60–69.9,
    F: <60); an empty library short-circuits to score=100 grade=A on the
    principle that "no entries" is vacuously healthy rather than failing.

    The four `HealthComponent` fields are scored independently against
    the library total — note that `conflicts` is a strict subset of
    `duplicates` (every conflicting row also counts as duplicated) so a
    contradicting row pays both penalties. This is deliberate: a
    contradiction is worse than mere redundancy and the score should
    reflect that double weight. `last_updated_at` is the freshest
    `updated_at` across the library (ISO-8601 UTC string, or `None`
    when the library is empty) so a UI can render "library last touched
    N minutes ago" without a follow-up query.

    Per-axis semantics:
      - `orphans.count`     — rows with at least one of the five
                              /orphans issue codes (`no_tags`,
                              `no_templates`, `short_symptom`,
                              `short_diagnosis`, `short_fix`). Weight 25.
      - `duplicates.count`  — rows that are members of any cluster of
                              ≥ 2 rows sharing (LOWER(product),
                              LOWER(symptom)). The row-level count, not
                              the cluster count, so the ratio is
                              comparable to the other components.
                              Weight 20.
      - `conflicts.count`   — subset of `duplicates`: rows in clusters
                              that also carry ≥ 2 distinct
                              TRIM(LOWER(fix)) texts. Weight 35.
      - `stale.count`       — rows whose `updated_at` is strictly older
                              than `now - stale_days`. Weight 20.
    """
    total: int
    score: float
    grade: str
    orphans: HealthComponent
    duplicates: HealthComponent
    conflicts: HealthComponent
    stale: HealthComponent
    last_updated_at: Optional[str]


class TagCount(BaseModel):
    tag: str
    count: int


class TagCooccurrence(BaseModel):
    """
    One co-occurring tag returned by GET /tags/cooccurrence.

    `tag` is the canonical lowercase neighbour tag, `count` is the number
    of Know-How entries on which both the focal tag (`?tag=` query param)
    and this neighbour tag appear together. The focal tag itself is never
    returned — a self-pairing would always equal the focal tag's own
    `/tags` count and would only crowd the dropdown.
    """
    tag: str
    count: int


class TemplateCount(BaseModel):
    template: str
    count: int


class TemplateCooccurrence(BaseModel):
    """
    One co-occurring ticket-template returned by GET /templates/cooccurrence.

    `template` is the neighbour template's stored-disk casing (templates are
    opaque external runbook identifiers — never canonicalised lowercase the
    way tags are — so the response preserves whatever case the writer used).
    `count` is the number of Know-How entries on which both the focal
    template (`?template=` query param) and this neighbour template appear
    together. The focal template itself is excluded — a self-pairing would
    always equal that template's own `/templates` count and would only
    crowd the dropdown without adding signal.
    """
    template: str
    count: int


class HistoryEvent(BaseModel):
    id: str
    event_type: str
    action_name: Optional[str]
    success: bool
    details: dict[str, Any]
    created_at: str

    @classmethod
    def from_orm_row(cls, row: AuditLog) -> "HistoryEvent":
        try:
            parsed = json.loads(row.details) if row.details else {}
        except (json.JSONDecodeError, TypeError):
            parsed = {}
        return cls(
            id=row.id,
            event_type=row.event_type,
            action_name=row.action_name,
            success=row.success,
            details=parsed if isinstance(parsed, dict) else {},
            created_at=row.created_at.isoformat(),
        )


class SuggestRequest(BaseModel):
    description: str = Field(
        ..., min_length=1, max_length=10_000,
        description="Free-text ticket / symptom description to match against.",
    )
    product: Optional[str] = Field(
        None, max_length=120,
        description="Optional exact product filter (case-insensitive).",
    )
    tags: List[str] = Field(
        default_factory=list,
        description=(
            "Optional tag filter. When non-empty, candidates must carry "
            "ALL listed tags (JSONB containment) — same semantics as the "
            "list endpoint's `?tag=` query parameter, so operators have "
            "one mental model across surfaces. Tags are normalised to "
            "lowercase before matching; empty strings are dropped."
        ),
    )
    top_n: int = Field(5, ge=1, le=20)
    min_rank: float = Field(
        0.0, ge=0.0, le=1.0,
        description=(
            "Drop matches whose ts_rank falls below this threshold. "
            "Defaults to 0.0 (no filter) so admin exploration sees the "
            "long tail; intake agents apply their own stricter default."
        ),
    )
    highlight: bool = Field(
        False,
        description=(
            "When true, each match also carries `highlights`: the symptom, "
            "diagnosis, and fix fields rendered with <mark>…</mark> markup "
            "wrapped around the matched FTS terms. Useful for admin UI "
            "tooling that wants to show operators exactly *why* an entry "
            "matched. Off by default because most callers consume raw text."
        ),
    )


class HighlightSnippet(BaseModel):
    symptom: str
    diagnosis: str
    fix: str


class SuggestionMatch(BaseModel):
    problem: KnownProblemResponse
    rank: float
    highlights: Optional[HighlightSnippet] = None


class SuggestResponse(BaseModel):
    matches: List[SuggestionMatch]


# Canonical issue codes returned by /orphans. Declared as module-level
# constants so the handler, tests, and the Query() validator all agree on
# the spelling — a typo anywhere would otherwise silently filter to "no
# matches" instead of raising 422. Order is the order issues are appended
# to the per-row `issues` list, so snapshot tests stay stable.
_ORPHAN_ISSUE_NO_TAGS = "no_tags"
_ORPHAN_ISSUE_NO_TEMPLATES = "no_templates"
_ORPHAN_ISSUE_SHORT_SYMPTOM = "short_symptom"
_ORPHAN_ISSUE_SHORT_DIAGNOSIS = "short_diagnosis"
_ORPHAN_ISSUE_SHORT_FIX = "short_fix"
_ORPHAN_ISSUE_CODES: frozenset[str] = frozenset({
    _ORPHAN_ISSUE_NO_TAGS,
    _ORPHAN_ISSUE_NO_TEMPLATES,
    _ORPHAN_ISSUE_SHORT_SYMPTOM,
    _ORPHAN_ISSUE_SHORT_DIAGNOSIS,
    _ORPHAN_ISSUE_SHORT_FIX,
})


class OrphanEntry(BaseModel):
    """
    A single Know-How row flagged by `/orphans` as needing curation.
    The full `problem` row is embedded so the admin UI can render the
    entry inline without a follow-up GET, and `issues` carries the
    machine-readable list of what's wrong so the UI can render
    per-issue badges ("no tags", "fix too short", …).

    Order of issues mirrors the declaration order of `_ORPHAN_ISSUE_*`
    constants above — stable across runs so snapshot tests don't churn,
    and predictable for a human scanning the list.
    """
    problem: KnownProblemResponse
    issues: List[str]


class OrphansResponse(BaseModel):
    """
    Envelope for `/orphans`. `total` is the unpaginated count of rows
    flagged with at least one of the requested issues, so the admin UI
    can render "showing 50 of 312" without a second query. `entries` is
    the current paginated slice.
    """
    total: int
    entries: List[OrphanEntry]


class DuplicateCluster(BaseModel):
    """
    One group of Know-How rows that share an identical (product, symptom)
    pair after case-folding. `product` and `symptom` echo the original
    (case-preserved) text of the first entry in the cluster — vendor
    branding matters in admin output ("Microsoft 365" not "microsoft
    365"), and showing the verbatim text the operator typed is friendlier
    than showing the lowercased key. `size` is `len(entries)` repeated
    at the cluster level so the admin UI can render a "(3 rows)" badge
    without iterating the array.

    Entries are ordered by `created_at` ASC, so the oldest row appears
    first — that's the row an operator typically keeps when collapsing
    duplicates via /{id}/merge, and stable ordering keeps snapshot tests
    deterministic when two rows share a timestamp (tie-break on id).
    """
    product: str
    symptom: str
    size: int
    entries: List[KnownProblemResponse]


class DuplicatesResponse(BaseModel):
    """
    Envelope for `/duplicates`. `total` is the unpaginated count of
    clusters (groups of >= `min_group_size` rows that share a normalised
    product+symptom key), so the admin UI can render "showing 50 of 312
    duplicate groups" without a follow-up query. `clusters` is the
    current paginated slice.
    """
    total: int
    clusters: List[DuplicateCluster]


class ConflictCluster(BaseModel):
    """
    One group of Know-How rows that share an identical (product, symptom)
    pair after case-folding AND disagree on the `fix` text. A tighter
    subset of `DuplicateCluster`: /duplicates says "these rows are
    redundant"; /conflicts says "these rows are actively contradictory
    — two operators told a future reader to do different things for the
    same symptom". `distinct_fix_count` is the number of distinct
    case-folded, whitespace-trimmed fix strings the cluster carries — by
    construction always >= 2 (clusters with one shared fix are pure
    duplicates and are excluded). The full entries are embedded ordered
    by `created_at` ASC so the operator can pick a canonical "keep this
    one" row, same convention /duplicates uses.
    """
    product: str
    symptom: str
    size: int
    distinct_fix_count: int
    entries: List[KnownProblemResponse]


class ConflictsResponse(BaseModel):
    """
    Envelope for `/conflicts`. `total` is the unpaginated count of
    conflict clusters (groups of >= `min_group_size` rows sharing a
    normalised product+symptom AND carrying two or more distinct
    fix texts), so the admin UI can render "showing 50 of 17 conflicts"
    without a follow-up query. `clusters` is the current paginated slice
    ordered by `distinct_fix_count` DESC then `size` DESC — the worst
    contradictions first so the operator works the highest-impact
    knowledge errors before the long tail.
    """
    total: int
    clusters: List[ConflictCluster]


class StaleEntry(BaseModel):
    """
    A single Know-How row surfaced by `/stale` because its `updated_at`
    is older than the caller-supplied freshness threshold. The full
    `problem` row is embedded so the admin UI can render the entry
    inline without a follow-up GET, and `days_since_update` is the
    server-computed age in whole days at response time — saved here so
    the UI doesn't have to re-derive it from `updated_at` (and so two
    rows can't disagree about "what day is it" across a paginated page).
    """
    problem: KnownProblemResponse
    days_since_update: int


class StaleResponse(BaseModel):
    """
    Envelope for `/stale`. `total` is the unpaginated count of rows whose
    `updated_at` falls before the freshness cutoff, so the admin UI can
    render "showing 50 of 312 stale entries" without a second query.
    `entries` is the current paginated slice ordered oldest-first.
    """
    total: int
    entries: List[StaleEntry]


class RecentEntry(BaseModel):
    """
    A single Know-How row surfaced by `/recent` because its `created_at`
    falls within the caller-supplied window. The full `problem` row is
    embedded so the admin UI can render the entry inline without a
    follow-up GET, and `days_since_created` is the server-computed age
    in whole days at response time — saved here so the UI doesn't have
    to re-derive it from `created_at` and so two rows can't disagree
    about "what day is it" across a paginated page (same discipline as
    `/stale`'s `days_since_update`).
    """
    problem: KnownProblemResponse
    days_since_created: int


class RecentResponse(BaseModel):
    """
    Envelope for `/recent`. `total` is the unpaginated count of rows
    whose `created_at` falls inside the freshness window, so the admin
    UI can render "showing 50 of 312 new entries" without a second
    query. `entries` is the current paginated slice ordered newest-first
    (the natural review order — newest additions surface first).
    """
    total: int
    entries: List[RecentEntry]


class TimelineBucket(BaseModel):
    """
    One row of the `/timeline` time-series. `bucket_start` is the UTC
    date at which this bucket opens — for `bucket=day` that's the
    calendar date the row was created; for `week` it's the Monday of
    the ISO week (Postgres' `date_trunc('week', ts)` convention); for
    `month` it's the first of the month. `count` is the number of
    `created_at` timestamps that landed in the bucket.

    Only buckets that actually saw activity are returned — empty
    intervals between two non-empty buckets are *not* zero-padded.
    Pinning that responsibility on the client keeps the SQL one
    round-trip and the contract trivial; a dashboard that wants a dense
    series can interpolate gaps against its own X-axis scale knowing
    that any missing `bucket_start` in [now-days, now] is exactly zero.
    """
    bucket_start: date
    count: int


class BulkUpsertRequest(BaseModel):
    entries: List[KnownProblemBase] = Field(
        ..., min_length=1, max_length=500,
        description=(
            "Batch of entries to upsert. Idempotency is keyed on "
            "(product, symptom) — repeating an existing pair updates "
            "the row in place rather than creating a duplicate."
        ),
    )


class BulkUpsertResponse(BaseModel):
    created: int
    updated: int
    unchanged: int
    total: int


class BulkDeleteRequest(BaseModel):
    ids: List[str] = Field(
        ..., min_length=1, max_length=500,
        description=(
            "UUIDs to delete. Whitespace is stripped; duplicates within the "
            "same request are rejected with a 422 so the caller has to dedupe "
            "before sending — mirrors the /bulk upsert contract."
        ),
    )


class BulkDeleteResponse(BaseModel):
    deleted: int
    not_found: int
    total: int
    not_found_ids: List[str]


class TagRenameRequest(BaseModel):
    from_tag: str = Field(
        ..., min_length=1, max_length=120,
        description="Existing tag to replace. Normalised (lowercase, trimmed).",
    )
    to_tag: str = Field(
        ..., min_length=1, max_length=120,
        description="Replacement tag. Normalised (lowercase, trimmed).",
    )


class TagRenameResponse(BaseModel):
    from_tag: str
    to_tag: str
    updated_count: int


class TagDeleteRequest(BaseModel):
    tag: str = Field(
        ..., min_length=1, max_length=120,
        description="Tag to drop from every entry. Normalised (lowercase, trimmed).",
    )


class TagDeleteResponse(BaseModel):
    tag: str
    deleted_count: int


class TagMergeRequest(BaseModel):
    from_tags: List[str] = Field(
        ..., min_length=1, max_length=50,
        description=(
            "One or more existing tags to consolidate. Normalised "
            "(lowercase, trimmed, deduped) before matching. Any tag that "
            "collapses to `to_tag` after normalisation is dropped from "
            "the source list — merging X → X is a no-op for that label."
        ),
    )
    to_tag: str = Field(
        ..., min_length=1, max_length=120,
        description=(
            "Target tag every source occurrence will be rewritten to. "
            "Normalised (lowercase, trimmed)."
        ),
    )


class TagMergeResponse(BaseModel):
    from_tags: List[str]
    to_tag: str
    updated_count: int


class TemplateRenameRequest(BaseModel):
    from_template: str = Field(
        ..., min_length=1, max_length=200,
        description=(
            "Existing ticket-template name to replace. Matched "
            "case-insensitively against each entry's "
            "`related_ticket_templates` list (mirrors /products/rename — "
            "vendor template names like 'M365-Auth-Reset' vs "
            "'m365-auth-reset' should still match). Whitespace trimmed "
            "before matching."
        ),
    )
    to_template: str = Field(
        ..., min_length=1, max_length=200,
        description=(
            "Replacement ticket-template name. Stored case-preserved — "
            "template names are vendor / runbook identifiers where "
            "casing carries meaning ('M365-Auth-Reset' is canonical), "
            "same discipline /products/rename applies to product labels. "
            "Whitespace trimmed; no case fold."
        ),
    )


class TemplateRenameResponse(BaseModel):
    from_template: str
    to_template: str
    updated_count: int


class TemplateDeleteRequest(BaseModel):
    template: str = Field(
        ..., min_length=1, max_length=200,
        description=(
            "Ticket-template name to drop from every entry that "
            "references it. Matched case-insensitively against each "
            "row's `related_ticket_templates` list (same discipline "
            "/templates/rename applies — vendor runbook names like "
            "`M365-Auth-Reset` and `m365-auth-reset` collapse to one "
            "logical template). Whitespace is trimmed before matching."
        ),
    )


class TemplateDeleteResponse(BaseModel):
    template: str
    deleted_count: int


class TemplateMergeRequest(BaseModel):
    from_templates: List[str] = Field(
        ..., min_length=1, max_length=50,
        description=(
            "One or more existing ticket-template names to consolidate. "
            "Trimmed and deduped (case-folded) before matching, so the "
            "caller can paste raw operator input without pre-canonicalising. "
            "Matched case-insensitively against each row's "
            "`related_ticket_templates` list — runbook identifiers drift "
            "in casing the same way product names do, mirroring "
            "/templates/rename and /templates/delete. Any source that "
            "case-folds to `to_template` is dropped from the source set — "
            "merging X → X is a no-op for that label."
        ),
    )
    to_template: str = Field(
        ..., min_length=1, max_length=200,
        description=(
            "Target ticket-template name every source occurrence will be "
            "rewritten to. Stored case-preserved — template names are "
            "vendor / runbook identifiers where casing carries meaning, "
            "same discipline /templates/rename applies. Whitespace "
            "trimmed; no case fold."
        ),
    )


class TemplateMergeResponse(BaseModel):
    from_templates: List[str]
    to_template: str
    updated_count: int


class KnownProblemExportEntry(BaseModel):
    """
    One row in the `/export` payload. Shape is intentionally a strict
    subset of `KnownProblemBase` (product, symptom, diagnosis, fix,
    related_ticket_templates, tags) — the same shape the seed fixture
    and `/bulk` upsert consume. That symmetry means an export can be
    POSTed straight back to `/bulk` to restore a backup with no
    transformation step, which is the whole point of the endpoint.

    Audit-trail fields (id, timestamps) are deliberately *not* included
    — they are not portable across environments (ids regenerate on
    upsert, timestamps would be wrong on restore) and would confuse a
    caller that just wants the canonical content.
    """
    product: str
    symptom: str
    diagnosis: str
    fix: str
    related_ticket_templates: List[str]
    tags: List[str]

    @classmethod
    def from_orm_row(cls, kp: KnownProblem) -> "KnownProblemExportEntry":
        return cls(
            product=kp.product,
            symptom=kp.symptom,
            diagnosis=kp.diagnosis,
            fix=kp.fix,
            related_ticket_templates=list(kp.related_ticket_templates or []),
            tags=list(kp.tags or []),
        )


class KnownProblemExportResponse(BaseModel):
    """
    Versioned export envelope. `version` is bumped only on
    backwards-incompatible shape changes — additive fields don't bump
    it, so existing restores keep working. `exported_at` is the server
    UTC timestamp at the moment of the snapshot (informational; not
    used for change detection — that's what `/activity` is for).
    """
    version: str
    exported_at: str
    count: int
    entries: List[KnownProblemExportEntry]


# Versions of the export envelope this server is willing to import. New
# additive shape changes don't bump this — only breaking changes do, so
# old snapshots keep restoring after a server upgrade. Lives next to the
# export model so a future bump touches one literal in one file.
_SUPPORTED_IMPORT_VERSIONS: frozenset[str] = frozenset({"1.0"})


class KnownProblemImportRequest(BaseModel):
    """
    Body schema for POST /import — deliberately the same shape as the
    `/export` response envelope so an operator can pipe a snapshot
    straight back without rewriting it.

    `exported_at` is accepted but informational only — the audit row
    /activity exposes is the authoritative trail; we don't persist the
    source snapshot timestamp. `count`, if present, is cross-checked
    against `len(entries)` to catch truncated transfers; sending only
    `version` + `entries` is also accepted.

    Per-entry shape is `KnownProblemExportEntry`, the same fields
    `/bulk` accepts. The 500-entry cap mirrors `/bulk` so a single
    request can't blow past the upsert helper's bounded transaction.
    """
    version: str = Field(
        ..., min_length=1, max_length=32,
        description=(
            "Envelope version. Must be one of the server's "
            "_SUPPORTED_IMPORT_VERSIONS set or the request is rejected."
        ),
    )
    exported_at: Optional[str] = Field(
        None,
        description=(
            "Informational source timestamp from the original /export. "
            "Accepted for round-trip symmetry; not persisted."
        ),
    )
    count: Optional[int] = Field(
        None, ge=0,
        description=(
            "Optional integrity check — when provided, must equal "
            "len(entries). Catches truncated payloads before they hit "
            "the upsert pipeline. Omit to skip the check."
        ),
    )
    entries: List[KnownProblemExportEntry] = Field(
        ..., min_length=1, max_length=500,
        description=(
            "Snapshot rows to restore. Idempotency is keyed on "
            "(product, symptom) — repeating an existing pair updates "
            "the row in place rather than creating a duplicate. Same "
            "semantics as /bulk."
        ),
    )


class KnownProblemImportResponse(BaseModel):
    """
    Mirrors /bulk's response shape with the source `version` echoed so
    automated restore pipelines can log what envelope they replayed.
    """
    version: str
    created: int
    updated: int
    unchanged: int
    total: int


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _load_or_404(db: AsyncSession, problem_id: str) -> KnownProblem:
    result = await db.execute(
        select(KnownProblem).where(KnownProblem.id == problem_id)
    )
    kp = result.scalar_one_or_none()
    if kp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Known problem not found.",
        )
    return kp


def _audit(
    db: AsyncSession,
    event_type: str,
    problem_id: Optional[str],
    details: dict[str, Any],
) -> None:
    """
    Stage an AuditLog row for a known-problem mutation. Commit is the
    caller's responsibility — the audit row rides on the same transaction
    that mutated the KnownProblem, so the trail can never go out of sync
    with the data. PRD §13 requires every semi-autonomous action to leave
    an audit entry; this is the Know-How Library's contribution.
    """
    payload = {"problem_id": problem_id, **details}
    db.add(
        AuditLog(
            event_type=event_type,
            agent_name="known_problems_api",
            action_name=event_type.split(".", 1)[-1],
            details=json.dumps(payload, ensure_ascii=False),
            success=True,
        )
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "/",
    response_model=List[KnownProblemResponse],
    dependencies=[Depends(verify_api_key)],
    summary="List known problems",
)
async def list_known_problems(
    product: Optional[str] = Query(
        None, description="Exact product match (case-insensitive)."
    ),
    q: Optional[str] = Query(
        None,
        min_length=1,
        max_length=200,
        description=(
            "Substring search across symptom + diagnosis. "
            "Will become a tsvector FTS query in a future migration."
        ),
    ),
    tag: Optional[List[str]] = Query(
        None,
        description=(
            "Filter by one or more tags. Repeat the query parameter "
            "(`?tag=auth&tag=licensing`) to require ALL listed tags "
            "(JSONB containment). Tags are matched case-insensitively "
            "against the canonicalised lowercase form stored in the DB."
        ),
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(KnownProblem).order_by(KnownProblem.created_at.desc())
    if product:
        query = query.where(KnownProblem.product.ilike(product))
    if q:
        pattern = f"%{q}%"
        query = query.where(
            or_(
                KnownProblem.symptom.ilike(pattern),
                KnownProblem.diagnosis.ilike(pattern),
            )
        )
    if tag:
        # JSONB containment: tags @> '["x","y"]' is true iff every tag in
        # the right-hand array also appears in the row's `tags`. Normalise
        # the caller's input so `?tag=Auth` still hits rows that stored
        # the canonical 'auth'. Empty/whitespace tag values are dropped
        # silently — sending `?tag=` alone should not become a poison query.
        wanted = _normalize_tags(tag)
        if wanted:
            query = query.where(
                KnownProblem.tags.op("@>")(func.cast(wanted, JSONB))
            )
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    rows = result.scalars().all()
    return [KnownProblemResponse.from_orm_row(r) for r in rows]


@router.post(
    "/",
    response_model=KnownProblemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key)],
    summary="Create a known problem",
)
async def create_known_problem(
    req: KnownProblemCreate,
    db: AsyncSession = Depends(get_db),
):
    kp = KnownProblem(
        id=str(uuid4()),
        product=req.product,
        symptom=req.symptom,
        diagnosis=req.diagnosis,
        fix=req.fix,
        related_ticket_templates=list(req.related_ticket_templates),
        tags=_normalize_tags(req.tags),
    )
    db.add(kp)
    _audit(
        db,
        event_type="known_problem.created",
        problem_id=kp.id,
        details={
            "product": kp.product,
            "symptom_preview": kp.symptom[:120],
            "related_ticket_templates": list(kp.related_ticket_templates or []),
            "tags": list(kp.tags or []),
        },
    )
    await db.commit()
    await db.refresh(kp)
    logger.info("known_problem.created", id=kp.id, product=kp.product)
    return KnownProblemResponse.from_orm_row(kp)


@router.post(
    "/bulk",
    response_model=BulkUpsertResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Idempotently upsert a batch of known problems",
)
async def bulk_upsert_known_problems(
    req: BulkUpsertRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Upsert a batch of entries keyed on (product, symptom). Mirrors the
    `seed_known_problems` semantics so an operator can paste a JSON batch
    through the admin API and get the same idempotency guarantee the seed
    CLI gives. Diagnoses, fixes, and related_ticket_templates are replaced
    for existing rows; new rows are inserted. Returns counts so the caller
    can see what changed.

    A single duplicate (product, symptom) pair within the request body is
    rejected with a 422 — the caller must dedupe before sending.
    """
    seen: set[tuple[str, str]] = set()
    seed_entries: List[SeedEntry] = []
    for idx, item in enumerate(req.entries):
        key = (item.product.strip().lower(), item.symptom.strip().lower())
        if key in seen:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Bulk entry {idx} duplicates an earlier (product, symptom) "
                    "pair in the same request."
                ),
            )
        seen.add(key)
        seed_entries.append(
            SeedEntry(
                product=item.product.strip(),
                symptom=item.symptom.strip(),
                diagnosis=item.diagnosis.strip(),
                fix=item.fix.strip(),
                related_ticket_templates=[
                    t.strip() for t in item.related_ticket_templates
                ],
                tags=_normalize_tags(item.tags),
            )
        )

    created, updated, unchanged = await seed_known_problems(db, seed_entries)
    _audit(
        db,
        event_type="known_problem.bulk_upserted",
        problem_id=None,
        details={
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "total": len(seed_entries),
            "products": sorted({e.product for e in seed_entries}),
        },
    )
    await db.commit()
    logger.info(
        "known_problem.bulk_upsert",
        created=created,
        updated=updated,
        unchanged=unchanged,
        total=len(seed_entries),
    )
    return BulkUpsertResponse(
        created=created,
        updated=updated,
        unchanged=unchanged,
        total=len(seed_entries),
    )


@router.post(
    "/bulk-delete",
    response_model=BulkDeleteResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Delete a batch of known problems by id",
)
async def bulk_delete_known_problems(
    req: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Drop a batch of Know-How entries by id in a single transaction. The
    natural counterpart to /bulk upsert: bulk-upsert seeds many rows in
    one go, bulk-delete tears many rows down in one go. Useful when an
    operator imports a draft batch, finds it was wrong, and wants to roll
    the whole import back without 50 individual DELETE calls.

    Semantics:
      - IDs are stripped of whitespace before matching; intra-request
        duplicates after stripping are rejected with a 422, mirroring the
        /bulk upsert dedupe contract;
      - missing IDs do NOT 404 the whole request — the response reports
        them in `not_found_ids` so the caller can reconcile. This matters
        for idempotent retries: re-deleting an already-deleted row should
        succeed with `deleted=0, not_found=1`, not blow up the batch;
      - one summary audit row is written for the whole delete (no per-row
        rows) with the list of deleted ids and the affected products,
        mirroring /bulk upsert and /tags/* — keeps the audit table bounded
        when an operator drops hundreds of rows at once. `problem_id` on
        the summary row is null so per-entry /history is unaffected;
      - deletion uses `await db.delete(row)` per loaded ORM instance (not
        a bulk DELETE statement) so SQLAlchemy's identity map and any
        future cascade rules behave consistently with single-row DELETE.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick /stats, /tags, /tags/*, /activity, and /bulk use.
    """
    seen: set[str] = set()
    ids: List[str] = []
    for idx, raw in enumerate(req.ids):
        norm = (raw or "").strip()
        if not norm:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Bulk-delete id at position {idx} is blank after stripping.",
            )
        if norm in seen:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Bulk-delete id at position {idx} duplicates an earlier id "
                    "in the same request."
                ),
            )
        seen.add(norm)
        ids.append(norm)

    result = await db.execute(
        select(KnownProblem).where(KnownProblem.id.in_(ids))
    )
    rows = result.scalars().all()

    found_ids = {kp.id for kp in rows}
    not_found_ids = [i for i in ids if i not in found_ids]
    products = sorted({kp.product for kp in rows})

    _audit(
        db,
        event_type="known_problem.bulk_deleted",
        problem_id=None,
        details={
            "deleted": len(rows),
            "not_found": len(not_found_ids),
            "total": len(ids),
            # Cap the deleted-id list so the audit row stays bounded even
            # if someone drops the whole library in one call.
            "deleted_ids": [kp.id for kp in rows][:50],
            "not_found_ids": not_found_ids[:50],
            "products": products,
        },
    )

    for kp in rows:
        await db.delete(kp)
    await db.commit()

    logger.info(
        "known_problem.bulk_deleted",
        deleted=len(rows),
        not_found=len(not_found_ids),
        total=len(ids),
    )
    return BulkDeleteResponse(
        deleted=len(rows),
        not_found=len(not_found_ids),
        total=len(ids),
        not_found_ids=not_found_ids,
    )


@router.get(
    "/stats",
    response_model=KnownProblemStats,
    dependencies=[Depends(verify_api_key)],
    summary="Aggregate stats for the Know-How Library",
)
async def known_problem_stats(
    db: AsyncSession = Depends(get_db),
):
    """
    Total entry count plus counts grouped by product, ordered by count desc.
    Powers the admin dashboard "library coverage" tile so ops can see at a
    glance which products are well-covered and which need attention.
    Declared above /{problem_id} so the literal path wins the FastAPI match.
    """
    total_row = await db.execute(select(func.count(KnownProblem.id)))
    total = int(total_row.scalar() or 0)

    by_product_row = await db.execute(
        select(KnownProblem.product, func.count(KnownProblem.id))
        .group_by(KnownProblem.product)
        .order_by(func.count(KnownProblem.id).desc(), KnownProblem.product.asc())
    )
    by_product = [
        ProductCount(product=row[0], count=int(row[1]))
        for row in by_product_row.all()
    ]
    return KnownProblemStats(total=total, by_product=by_product)


@router.get(
    "/coverage",
    response_model=CoverageResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Per-product data-quality coverage breakdown",
)
async def known_problem_coverage(
    db: AsyncSession = Depends(get_db),
):
    """
    Per-product data-quality dashboard. For each distinct product the
    library knows about, returns the total entry count plus how many of
    those entries carry tags, related ticket templates, both, or neither.
    The four counters (`with_tags`-only, `with_templates`-only,
    `with_both`, `orphan`) partition `total` — they always sum back to
    it — so an admin UI can render a stacked bar per product without a
    second pass.

    Why this exists alongside /stats and /orphans:
      • /stats answers "how many entries do we have, and per product" —
        a single counter per product.
      • /orphans answers "which specific rows have a data-quality issue" —
        a flat list keyed by id, not grouped.
      • /coverage answers "for each product, what is the *shape* of the
        data quality" — the grouped quality cross-tab the dashboard
        needs to highlight which vendors are under-tagged vs which
        lack template links. The decomposition is cheap (one SQL
        round-trip with conditional aggregates) so the admin UI can
        re-fetch it on every page load.

    Implementation detail: the four conditional counters use Postgres's
    `count(*) FILTER (WHERE …)` syntax — cleaner and faster than `SUM`-of-
    `CASE` because the planner can skip the row entirely when the filter
    rejects it. We test "has at least one tag/template" with
    `jsonb_array_length(...) > 0` rather than `<> '[]'` so a row whose
    JSONB column is somehow NULL still reads as zero-length (defensive:
    `nullable=False` in the model means this can't happen today, but a
    future migration that relaxes that constraint won't break the
    coverage math). `last_updated_at` is rendered as the ISO-8601 string
    of the freshest `updated_at` for the product, or `None` for the
    (currently impossible) zero-row product case.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick /stats, /tags, /products, /templates,
    /orphans, /duplicates, /stale, /recent, and the various
    /products/* + /tags/* + /templates/* endpoints all use upstairs.
    """
    total_row = await db.execute(select(func.count(KnownProblem.id)))
    total = int(total_row.scalar() or 0)

    # Single grouped aggregate per product. The FILTER clauses are
    # mutually exclusive (with_tags-only / with_templates-only /
    # with_both / orphan) so the four returned counters partition the
    # row count for that product — no risk of double-counting.
    stmt = text(
        """
        SELECT
            product,
            count(*) AS total,
            count(*) FILTER (
                WHERE jsonb_array_length(tags) > 0
                  AND jsonb_array_length(related_ticket_templates) = 0
            ) AS with_tags_only,
            count(*) FILTER (
                WHERE jsonb_array_length(tags) = 0
                  AND jsonb_array_length(related_ticket_templates) > 0
            ) AS with_templates_only,
            count(*) FILTER (
                WHERE jsonb_array_length(tags) > 0
                  AND jsonb_array_length(related_ticket_templates) > 0
            ) AS with_both,
            count(*) FILTER (
                WHERE jsonb_array_length(tags) = 0
                  AND jsonb_array_length(related_ticket_templates) = 0
            ) AS orphan,
            max(updated_at) AS last_updated_at
        FROM known_problems
        GROUP BY product
        ORDER BY count(*) DESC, product ASC
        """
    )
    result = await db.execute(stmt)

    products: List[ProductCoverage] = []
    for row in result.all():
        product, p_total, tags_only, tmpl_only, both, orphan, last_upd = row
        # The /stats endpoint exposes "entries that have tags" as a
        # single number; here `with_tags` follows that same intuitive
        # contract — count of rows carrying at least one tag, whether
        # or not they also carry templates. Same for `with_templates`.
        # `with_both` is split out separately so callers don't need to
        # subtract to find the overlap, and `orphan` rounds out the
        # partition.
        products.append(
            ProductCoverage(
                product=product,
                total=int(p_total),
                with_tags=int(tags_only) + int(both),
                with_templates=int(tmpl_only) + int(both),
                with_both=int(both),
                orphan=int(orphan),
                last_updated_at=(
                    last_upd.isoformat() if last_upd is not None else None
                ),
            )
        )

    return CoverageResponse(total=total, products=products)


@router.get(
    "/health",
    response_model=LibraryHealth,
    dependencies=[Depends(verify_api_key)],
    summary="Composite library data-quality scorecard",
)
async def known_problem_health(
    stale_days: int = Query(
        90, ge=1, le=3650,
        description=(
            "Freshness threshold in whole days. Rows whose `updated_at` "
            "is strictly older than `now - stale_days` count toward the "
            "stale axis. Defaults to 90 — same default `/stale` uses, so "
            "the scorecard's stale count agrees with what an operator "
            "drilling into `/stale` will see. Range 1–3650 (1 day – 10 "
            "years) for callers that want a tighter or looser window."
        ),
    ),
    short_threshold: int = Query(
        20, ge=1, le=10_000,
        description=(
            "Character count below which `symptom`, `diagnosis`, or "
            "`fix` is considered too short to be diagnostically useful "
            "for the orphan axis. Defaults to 20 — same default "
            "`/orphans` uses, so the scorecard's orphan count agrees "
            "with what an operator drilling into `/orphans` will see."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Composite library data-quality scorecard. Rolls the four
    independent reports (`/orphans`, `/duplicates`, `/conflicts`,
    `/stale`) into a single 0–100 score plus a letter grade so an admin
    dashboard can render one "library health" tile at a glance — and
    drill into any axis via the existing per-report endpoint when the
    score is poor.

    Why this exists alongside /stats and /coverage:
      • /stats answers "how many entries do we have" — pure size.
      • /coverage answers "for each product, what's the *shape* of
        the data quality" — per-product cross-tab.
      • /health answers "is the library on the whole healthy enough to
        trust?" — a single composite that boils four independent axes
        down to one number for an at-a-glance dashboard tile. The
        per-axis breakdown is still in the response so a UI can render
        a "what's dragging the score down" bar chart without a second
        round-trip.

    Scoring math: each axis penalises the score in proportion to the
    fraction of rows it flagged, weighted by how serious that axis is
    (`conflicts` 35, `orphans` 25, `duplicates` 20, `stale` 20 — sum
    100 so the worst-possible library bottoms at zero). Conflicts is a
    strict subset of duplicates by construction, so a contradicting
    row pays both the conflict penalty AND the duplicate penalty — a
    deliberate double-count because a contradiction is strictly worse
    than mere redundancy and the score should reflect that.

    The score is clamped to [0, 100] and rounded to one decimal, and
    the letter grade follows the standard 10-point bands (A: ≥ 90,
    B: ≥ 80, C: ≥ 70, D: ≥ 60, F: < 60). An empty library
    short-circuits to score=100 grade=A on the principle that "no
    entries" is vacuously healthy — there is no flawed content to
    penalise, and a zero-row library returning "F" would mislead a
    dashboard tile during initial seeding.

    Implementation: one CTE-based round-trip aggregates all four axes
    in a single query. `base` carries the row-level totals plus orphan
    and stale counts via FILTER clauses; `dup_clusters` materialises
    the (LOWER(product), LOWER(symptom)) groups of size ≥ 2 once and
    feeds both the duplicate-row count (sum of cluster sizes) and the
    conflict-row count (sum of sizes where the cluster carries ≥ 2
    distinct TRIM(LOWER(fix)) texts). A single CROSS JOIN folds the
    two aggregates into one result row so Python only does arithmetic
    on the way out — no second round-trip even for libraries with
    hundreds of distinct duplicate clusters.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick /stats, /coverage, and every other aggregation
    endpoint upstairs use.
    """
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=stale_days)

    # One CTE-based query covers all four axes plus the library total
    # and last_updated_at marker — see docstring for the rationale.
    # `base` reads every row once for the orphan / stale / total /
    # last_updated_at numbers via FILTER clauses; `dup_clusters` is
    # the (LOWER(product), LOWER(symptom)) grouping shared by the
    # duplicate and conflict axes — materialising it once means the
    # query doesn't scan the table a third time. The final CROSS JOIN
    # collapses the two aggregates into a single result row.
    stmt = text(
        """
        WITH base AS (
            SELECT
                count(*) AS total,
                count(*) FILTER (
                    WHERE jsonb_array_length(tags) = 0
                       OR jsonb_array_length(related_ticket_templates) = 0
                       OR char_length(symptom)   < :short_threshold
                       OR char_length(diagnosis) < :short_threshold
                       OR char_length(fix)       < :short_threshold
                ) AS orphan_count,
                count(*) FILTER (
                    WHERE updated_at < :stale_cutoff
                ) AS stale_count,
                max(updated_at) AS last_updated_at
            FROM known_problems
        ),
        dup_clusters AS (
            SELECT
                count(*)                                AS cnt,
                count(DISTINCT TRIM(LOWER(fix)))        AS distinct_fixes
            FROM known_problems
            GROUP BY LOWER(product), LOWER(symptom)
            HAVING count(*) >= 2
        ),
        dup_agg AS (
            SELECT
                coalesce(sum(cnt), 0)::bigint AS duplicate_row_count,
                coalesce(sum(
                    CASE WHEN distinct_fixes >= 2 THEN cnt ELSE 0 END
                ), 0)::bigint AS conflict_row_count
            FROM dup_clusters
        )
        SELECT
            b.total,
            b.orphan_count,
            b.stale_count,
            b.last_updated_at,
            d.duplicate_row_count,
            d.conflict_row_count
        FROM base b CROSS JOIN dup_agg d
        """
    ).bindparams(short_threshold=short_threshold, stale_cutoff=stale_cutoff)
    row = (await db.execute(stmt)).first()

    # `row` is always one tuple — base has a single aggregate row even
    # for an empty table, and dup_agg's COALESCE means the cross join
    # never elides. Defensive `or` on each cell handles the
    # vanishingly-rare race where the query returns no row at all
    # (e.g. a unit-test mock that forgot to seed it) so the scorecard
    # degrades to "empty library" rather than blowing up with a None
    # subscript.
    if row is None:
        total = 0
        orphan_count = 0
        stale_count = 0
        last_upd = None
        duplicate_row_count = 0
        conflict_row_count = 0
    else:
        (
            total_raw,
            orphan_raw,
            stale_raw,
            last_upd,
            duplicate_raw,
            conflict_raw,
        ) = row
        total = int(total_raw or 0)
        orphan_count = int(orphan_raw or 0)
        stale_count = int(stale_raw or 0)
        duplicate_row_count = int(duplicate_raw or 0)
        conflict_row_count = int(conflict_raw or 0)

    # Empty library short-circuit: with zero rows there is no flawed
    # content to penalise, and dividing by zero for the ratios would
    # blow up. Surface a perfect score so the dashboard tile reads
    # "library is healthy" during initial seeding rather than failing
    # the operator before any content exists — see docstring.
    if total == 0:
        zero = HealthComponent(count=0, ratio=0.0, penalty=0.0)
        return LibraryHealth(
            total=0,
            score=100.0,
            grade="A",
            orphans=zero,
            duplicates=zero,
            conflicts=zero,
            stale=zero,
            last_updated_at=(
                last_upd.isoformat() if last_upd is not None else None
            ),
        )

    def _component(count: int, weight: float) -> HealthComponent:
        # ratio is bounded to [0, 1] in SQL by construction (count is a
        # FILTER over the same `total` table), so the clamp here is
        # defensive against a future change that introduces a JOIN.
        # Conflicts can in principle equal duplicates (every duplicate
        # cluster also conflicts), but never exceed it, so no clamp
        # needed across components.
        ratio = max(0.0, min(1.0, count / total))
        penalty = round(weight * ratio, 2)
        return HealthComponent(count=count, ratio=round(ratio, 4), penalty=penalty)

    orphans = _component(orphan_count, _HEALTH_WEIGHT_ORPHAN)
    duplicates = _component(duplicate_row_count, _HEALTH_WEIGHT_DUPLICATE)
    conflicts = _component(conflict_row_count, _HEALTH_WEIGHT_CONFLICT)
    stale = _component(stale_count, _HEALTH_WEIGHT_STALE)

    # Clamp to [0, 100] — the four weights sum to 100 and each ratio is
    # in [0, 1], so the raw sum is also in [0, 100], but the clamp is
    # cheap insurance against future weight tweaks that don't sum to
    # exactly 100. Round to one decimal so the displayed score is
    # readable at a glance.
    raw_score = 100.0 - (
        orphans.penalty + duplicates.penalty + conflicts.penalty + stale.penalty
    )
    score = round(max(0.0, min(100.0, raw_score)), 1)

    return LibraryHealth(
        total=total,
        score=score,
        grade=_health_grade_for(score),
        orphans=orphans,
        duplicates=duplicates,
        conflicts=conflicts,
        stale=stale,
        last_updated_at=(
            last_upd.isoformat() if last_upd is not None else None
        ),
    )


@router.get(
    "/tags",
    response_model=List[TagCount],
    dependencies=[Depends(verify_api_key)],
    summary="List distinct tags with usage counts",
)
async def known_problem_tags(
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregate distinct tags across the entire Know-How Library with the
    number of entries each tag is attached to. Powers the admin UI's tag
    filter dropdown — the same dropdown the `?tag=` query parameter on
    the list endpoint feeds. Empty tag arrays are skipped naturally by
    the JSONB unnest; tags are returned in the canonical lowercase form
    already stored on disk, so callers can render them verbatim.

    Sorted by count desc, then tag asc — so the most-used tags surface
    first and tied tags sort alphabetically (stable, predictable order
    for snapshot tests and humans scanning the dropdown).

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick the /stats endpoint uses one floor up.
    """
    # JSONB unnest happens in a lateral subquery rather than a column-list
    # set-returning function, because the latter behaves differently across
    # Postgres versions inside aggregates. The comma-join form is the
    # documented, version-stable way to expand a JSONB array per row.
    stmt = text(
        """
        SELECT t.tag::text AS tag, count(*) AS cnt
        FROM known_problems kp,
             jsonb_array_elements_text(kp.tags) AS t(tag)
        GROUP BY t.tag
        ORDER BY count(*) DESC, t.tag ASC
        """
    )
    result = await db.execute(stmt)
    return [TagCount(tag=row[0], count=int(row[1])) for row in result.all()]


@router.get(
    "/tags/autocomplete",
    response_model=List[TagCount],
    dependencies=[Depends(verify_api_key)],
    summary="Prefix-search tags for typeahead",
)
async def known_problem_tags_autocomplete(
    prefix: str = Query(..., min_length=1, max_length=120),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """
    Return tags whose canonical (lowercase) form starts with `prefix`,
    ordered by usage count desc then tag asc. Powers the admin UI's
    "add tag" combobox — the user types `aut` and the dropdown narrows
    to `auth`, `authentication`, etc. ranked by how widely each tag is
    used so the most familiar option surfaces first.

    Prefix matching, not substring: typeahead expects "I've typed the
    start of the word." Substring would surface `licensing` for `cens`
    which is confusing in a combobox. For broad discovery the existing
    `?q=` filter on the list endpoint already does substring search
    across symptom/diagnosis.

    Prefix is lowercased before matching because tags are stored in
    canonical lowercase on disk (see `_normalize_tags`), so `AUT` and
    `aut` are the same query. The `%` wildcard is appended server-side
    so callers never need to know about LIKE syntax — and never get the
    chance to inject one. ILIKE escape rules aren't applied to literal
    `%` / `_` in the prefix: if a caller types those characters they
    behave as wildcards, which is acceptable for an internal admin
    typeahead (no untrusted input reaches this endpoint thanks to
    `verify_api_key`).
    """
    # Stripping mirrors the canonicalisation rule in `_normalize_tags` —
    # if a tag with surrounding whitespace can never exist on disk, a
    # prefix with surrounding whitespace can never match anything, so
    # silently trim rather than 422. Empty after strip is still rejected
    # by the min_length=1 query validator above (which runs pre-strip),
    # so we additionally guard here for whitespace-only inputs.
    needle = prefix.strip().lower()
    if not needle:
        return []

    stmt = text(
        """
        SELECT t.tag::text AS tag, count(*) AS cnt
        FROM known_problems kp,
             jsonb_array_elements_text(kp.tags) AS t(tag)
        WHERE t.tag ILIKE :pattern
        GROUP BY t.tag
        ORDER BY count(*) DESC, t.tag ASC
        LIMIT :limit
        """
    ).bindparams(pattern=f"{needle}%", limit=limit)
    result = await db.execute(stmt)
    return [TagCount(tag=row[0], count=int(row[1])) for row in result.all()]


@router.get(
    "/tags/cooccurrence",
    response_model=List[TagCooccurrence],
    dependencies=[Depends(verify_api_key)],
    summary="Tags that co-occur with a focal tag",
)
async def known_problem_tags_cooccurrence(
    tag: str = Query(
        ...,
        min_length=1,
        max_length=120,
        description=(
            "Focal tag. The response lists every other tag that appears "
            "alongside this one on at least one Know-How entry, with the "
            "joint-occurrence count. Matched case-insensitively against "
            "the canonical lowercase form stored on disk — same rule the "
            "list endpoint's `?tag=` filter uses — so `Auth` and `auth` "
            "resolve to the same focal tag."
        ),
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description=(
            "Maximum number of co-occurring tags to return. Defaults to "
            "50 so the admin UI's 'related tags' panel can render a full "
            "list without pagination on a typical library, and caps at "
            "200 so a pathological library with hundreds of tag pairings "
            "still returns in one round-trip."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return tags that co-occur with the focal `tag` on at least one
    Know-How entry, ordered by joint-occurrence count desc then tag asc.
    Powers the admin UI's "related tags" panel: a user filtering by
    `auth` sees that `licensing`, `mfa`, and `intune` show up alongside
    it most often, which guides them toward a useful secondary filter
    without scanning every entry.

    The focal tag is never returned in its own list — a self-pairing
    would always equal that tag's `/tags` count and would only push the
    actually-interesting neighbours down the dropdown. Empty libraries,
    libraries where the focal tag is unused, and tags that never share a
    row with another tag all return `[]` rather than a 404; the admin UI
    should fail soft (render "no related tags") rather than hard.

    Tags are matched case-insensitively against the canonical lowercase
    form stored on disk — same rule the list endpoint's `?tag=` filter
    uses — so `?tag=Auth` and `?tag=auth` resolve to the same focal tag.
    Returned neighbour tags are in their canonical lowercase form, so
    the admin UI can render them verbatim alongside the rest of the
    `/tags` dropdown without re-normalising.

    Implementation: a single JSONB-unnest self-join. The inner clause
    locks the focal tag against rows whose `tags @> '[focal]'` (using
    the GIN index for O(log n) row filtering), then unnests each
    matched row's tag array and counts every neighbour except the focal
    itself. One round-trip, index-backed, no Python-side aggregation.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick /tags, /tags/autocomplete, and every other
    aggregation endpoint upstairs use.
    """
    focal = tag.strip().lower()
    if not focal:
        return []

    # JSONB-containment narrows to rows carrying the focal tag (GIN
    # index uses jsonb_path_ops on `tags`), then `jsonb_array_elements_text`
    # expands every tag on those rows so a single GROUP BY counts each
    # neighbour's joint occurrences with the focal. The `t.tag <> :focal`
    # predicate drops the focal's self-pairing — same reason `/tags`
    # never lists itself in its own dropdown — and the LIMIT caps the
    # response so pathological libraries still come back in one trip.
    stmt = text(
        """
        SELECT t.tag::text AS tag, count(*) AS cnt
        FROM known_problems kp,
             jsonb_array_elements_text(kp.tags) AS t(tag)
        WHERE kp.tags @> jsonb_build_array(:focal)
          AND t.tag <> :focal
        GROUP BY t.tag
        ORDER BY count(*) DESC, t.tag ASC
        LIMIT :limit
        """
    ).bindparams(focal=focal, limit=limit)
    result = await db.execute(stmt)
    return [
        TagCooccurrence(tag=row[0], count=int(row[1]))
        for row in result.all()
    ]


@router.get(
    "/tags/product-breakdown",
    response_model=List[ProductCount],
    dependencies=[Depends(verify_api_key)],
    summary="Products that carry a focal tag, ranked by count",
)
async def known_problem_tags_product_breakdown(
    tag: str = Query(
        ...,
        min_length=1,
        max_length=120,
        description=(
            "Focal tag. Only entries whose `tags` array contains this "
            "value are scanned. Matched case-insensitively against the "
            "canonical lowercase form stored on disk — same rule "
            "`/tags/cooccurrence` and `/tags/timeline` use — so "
            "`?tag=Auth` and `?tag=auth` resolve to the same focal tag."
        ),
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description=(
            "Maximum number of products to return. Defaults to 50 so the "
            "admin UI's 'products carrying this tag' panel can render a "
            "full list without pagination on a typical library, and caps "
            "at 200 so a pathologically broad tag still returns in one "
            "round-trip — same envelope `/products/tag-breakdown`, "
            "`/tags/cooccurrence`, `/products/cooccurrence`, and "
            "`/templates/cooccurrence` use."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the products carrying a focal tag, ranked by in-tag entry
    count desc then product asc. The cross-axis dual of
    `/products/tag-breakdown` (which lists *tags* attached to a focal
    product's entries) and the per-tag specialisation of `/products`
    (which lists every product library-wide): an admin browsing the
    `auth` tag sees `Microsoft 365` has 12 auth entries, `Intune` has 9,
    `Meraki` has 4 — useful for answering "which products is this topic
    actually documented under?" without scanning every row by hand or
    filtering `/products` client-side over rows it never received.

    Mirrors `/products` in response shape (`ProductCount` — same
    `product` + `count` fields) and ordering rule (count desc, product
    asc) so the admin UI can reuse the same renderer it uses for the
    library-wide product list. Product values are returned case-preserved
    (vendor branding matters — "Microsoft 365" is canonical, "microsoft
    365" is not), matching the rule the rest of the `/products/*` family
    follows. The focal tag itself is lowercased before the predicate
    runs — same case-insensitivity rule `/tags`, `/tags/cooccurrence`,
    and `/tags/timeline` apply, because tags are stored in canonical
    lowercase by `_normalize_tags` and the equality clause has to fold
    matching the on-disk form.

    The focal tag predicate is `kp.tags @> jsonb_build_array(:focal)` —
    JSONB containment, which lets Postgres use the GIN index on `tags`
    for O(log n) row filtering — same shape `/tags/cooccurrence` and
    `/tags/timeline` use. Tighter than an array-element equality check
    on purpose: containment is the canonical "row carries this tag"
    predicate the GIN index is built for.

    Empty libraries, tags that are unused, and tags whose entries cover
    no products all return `[]` rather than a 404; the admin UI's panel
    should fail soft ("no products tagged with this yet") rather than
    blow up the page — same discipline `/tags/cooccurrence`,
    `/tags/timeline`, and `/products/tag-breakdown` apply.

    A whitespace-only `tag` (slipped past the `min_length=1` validator
    because it counts raw characters) short-circuits to `[]` without a
    DB round-trip — same fail-soft rule the rest of the `/tags/*` family
    uses for the same reason.

    Implementation: a single JSONB-containment + GROUP BY query that
    filters rows whose `tags` JSONB array contains the focal value,
    groups by `kp.product`, and counts. One round-trip, GIN-index
    backed, no Python-side aggregation. The `lower()` fold lives only
    on the bind value (tags are stored canonical-lowercase by
    `_normalize_tags`, so no per-row fold is needed) — matches
    `/tags/cooccurrence`.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick `/tags`, `/tags/autocomplete`,
    `/tags/cooccurrence`, `/products/tag-breakdown`, and every other
    aggregation endpoint upstairs use.
    """
    # Strip-then-lowercase-then-short-circuit mirrors the discipline
    # `/tags/cooccurrence` and `/tags/timeline` apply: a whitespace-only
    # focal slips past the min_length=1 query validator (which counts
    # raw characters), and there is no tag stored as the empty string,
    # so the containment predicate is guaranteed empty — short-circuit
    # without a DB round-trip rather than scan for an impossible value.
    # Lowercasing here (unlike `/products/tag-breakdown`) is correct:
    # tags are stored canonical-lowercase, so the bind value has to
    # match that form for the containment operator to hit the index.
    focal = tag.strip().lower()
    if not focal:
        return []

    # JSONB-containment pattern mirrors `/tags/cooccurrence` and
    # `/tags/timeline` — the GIN index on `tags` (jsonb_path_ops) covers
    # `@> jsonb_build_array(:focal)` so row filtering is O(log n) rather
    # than a full scan. Grouping by `kp.product` directly (no unnest)
    # because each entry carries exactly one `product` scalar — same
    # shape `/products` and `/products/cooccurrence` use. Counts the
    # rows themselves (one per entry tagged with the focal), so the
    # number for `Microsoft 365` is "12 M365 entries are tagged `auth`,"
    # which is the right semantic for the "products carrying this tag"
    # admin panel.
    stmt = text(
        """
        SELECT kp.product AS product, count(*) AS cnt
        FROM known_problems kp
        WHERE kp.tags @> jsonb_build_array(:focal)
        GROUP BY kp.product
        ORDER BY count(*) DESC, kp.product ASC
        LIMIT :limit
        """
    ).bindparams(focal=focal, limit=limit)
    result = await db.execute(stmt)
    return [
        ProductCount(product=row[0], count=int(row[1]))
        for row in result.all()
    ]


@router.get(
    "/tags/template-breakdown",
    response_model=List[TemplateCount],
    dependencies=[Depends(verify_api_key)],
    summary="Ticket templates used within entries that carry a focal tag, ranked by count",
)
async def known_problem_tags_template_breakdown(
    tag: str = Query(
        ...,
        min_length=1,
        max_length=120,
        description=(
            "Focal tag. Only entries whose `tags` array contains this "
            "value are scanned. Matched case-insensitively against the "
            "canonical lowercase form stored on disk — same rule "
            "`/tags/cooccurrence`, `/tags/timeline`, and "
            "`/tags/product-breakdown` use — so `?tag=Auth` and "
            "`?tag=auth` resolve to the same focal tag."
        ),
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description=(
            "Maximum number of templates to return. Defaults to 50 so the "
            "admin UI's 'runbooks for this tag' panel can render a full "
            "list without pagination on a typical tag, and caps at 200 so "
            "a pathologically over-templated tag still returns in one "
            "round-trip — same envelope `/tags/product-breakdown`, "
            "`/products/template-breakdown`, `/templates/tag-breakdown`, "
            "and the rest of the breakdown family use."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the ticket templates referenced by entries that carry a
    focal tag, ranked by in-tag usage count desc then template asc.
    The cross-axis dual of `/tags/product-breakdown` (which lists
    *products* carrying a focal tag) and the per-tag specialisation of
    `/templates` (which lists every template library-wide): an admin
    browsing `auth` sees `TMPL-MFA-Reset` appears on 9 of its entries,
    `TMPL-Token-Refresh` on 4, `TMPL-SSO-Setup` on 2 — useful for
    answering "which runbooks cover this topic?" without scanning every
    row by hand or filtering `/templates` client-side over rows it
    never received.

    Closes the 3×3 Know-How Library breakdown matrix (products × tags
    × templates). Counterpart to `/templates/tag-breakdown` shipped in
    iter-112 — same two axes, swapped focal/output roles, and the same
    template-case-preservation discipline on the output side.

    Mirrors `/templates` in response shape (`TemplateCount` — same
    `template` + `count` fields) and ordering rule (count desc,
    template asc) so the admin UI can reuse the same renderer it uses
    for the library-wide template list and the per-product template
    breakdown. Template strings are returned **verbatim** from disk —
    there is no canonicalisation rule on the way in (template refs are
    opaque external runbook identifiers chosen by the writer, not
    free-form labels), so the output preserves whatever casing /
    punctuation the writer used. Differs deliberately from
    `/tags/product-breakdown` on the output side: products are stored
    case-preserved-and-returned-verbatim too, but tags themselves
    (the focal axis) are lowercased on the way in.

    The focal tag predicate is `kp.tags @> jsonb_build_array(:focal)` —
    JSONB containment, which lets Postgres use the GIN index on `tags`
    for O(log n) row filtering — same shape `/tags/cooccurrence`,
    `/tags/timeline`, and `/tags/product-breakdown` use. Tighter than
    an array-element equality check on purpose: containment is the
    canonical "row carries this tag" predicate the GIN index is built
    for. Cheaper than `/templates/tag-breakdown`'s EXISTS predicate
    (which has to scan because templates aren't canonicalised) — tags
    are stored lowercase canonical so the bind value already matches.

    Empty libraries, tags that are unused, and tags whose entries
    reference no templates all return `[]` rather than a 404; the
    admin UI's panel should fail soft ("no runbooks tagged with this
    yet") rather than blow up the page — same discipline
    `/tags/cooccurrence`, `/tags/timeline`, `/tags/product-breakdown`,
    `/templates/tag-breakdown`, and the rest of the breakdown family
    apply.

    A whitespace-only `tag` (slipped past the `min_length=1` validator
    because it counts raw characters) short-circuits to `[]` without a
    DB round-trip — same fail-soft rule the rest of the `/tags/*`
    family uses for the same reason.

    Implementation: a single JSONB-containment + JSONB-unnest query
    that filters rows whose `tags` JSONB array contains the focal value,
    unnests their `related_ticket_templates` arrays, groups by the
    case-preserved template (no `lower()` fold on the GROUP BY — see
    `/products/template-breakdown` for the same reasoning), and counts.
    One round-trip, GIN-index backed on the filter side, no
    Python-side aggregation.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick `/tags`, `/tags/cooccurrence`,
    `/tags/product-breakdown`, `/products/template-breakdown`,
    `/templates/tag-breakdown`, and every other aggregation endpoint
    upstairs use.
    """
    # Strip-then-lowercase-then-short-circuit mirrors the discipline
    # `/tags/cooccurrence`, `/tags/timeline`, and `/tags/product-breakdown`
    # apply: a whitespace-only focal slips past the min_length=1 query
    # validator (which counts raw characters), and there is no tag stored
    # as the empty string, so the containment predicate is guaranteed
    # empty — short-circuit without a DB round-trip rather than scan for
    # an impossible value. Lowercasing here (unlike `/products/template-breakdown`)
    # is correct: tags are stored canonical-lowercase, so the bind value
    # has to match that form for the containment operator to hit the index.
    focal = tag.strip().lower()
    if not focal:
        return []

    # JSONB-containment + unnest pattern combines `/tags/product-breakdown`'s
    # GIN-backed filter with `/products/template-breakdown`'s case-preserved
    # template unnest. The GROUP BY uses the raw `t.template` (not
    # `lower(t.template)`) on purpose — templates are stored case-preserved
    # and the response axis preserves that casing too, so folding would
    # incorrectly collapse `TMPL-MFA-Reset` and `tmpl-mfa-reset` into a
    # single count. That casing-drift mismatch is `/templates/merge`'s job
    # to clean up, not this endpoint's to silently hide.
    stmt = text(
        """
        SELECT t.template::text AS template, count(*) AS cnt
        FROM known_problems kp,
             jsonb_array_elements_text(kp.related_ticket_templates) AS t(template)
        WHERE kp.tags @> jsonb_build_array(:focal)
        GROUP BY t.template
        ORDER BY count(*) DESC, t.template ASC
        LIMIT :limit
        """
    ).bindparams(focal=focal, limit=limit)
    result = await db.execute(stmt)
    return [
        TemplateCount(template=row[0], count=int(row[1]))
        for row in result.all()
    ]


@router.get(
    "/products",
    response_model=List[ProductCount],
    dependencies=[Depends(verify_api_key)],
    summary="List distinct products with usage counts",
)
async def known_problem_products(
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregate distinct `product` values across the entire Know-How Library
    with the number of entries each product is attached to. Powers the
    admin UI's product filter dropdown — the same dropdown the `?product=`
    query parameter on the list endpoint feeds.

    This is the standalone read companion to `/products/autocomplete`,
    and mirrors `/tags` exactly: same response shape, same ordering rule,
    same purpose (populate a dropdown). `/stats` already exposes the same
    per-product counts but bundled with the total entry count; carving
    out a dedicated endpoint lets the admin UI hit one cheap query when
    it only needs the dropdown — and keeps the response model symmetric
    with `/tags` so the frontend can share a fetcher between the two.

    Sorted by count desc, then product asc — so the most-used products
    surface first and tied products sort alphabetically. Product names
    are stored case-preserved (vendor branding matters: "Microsoft 365"
    is canonical, "microsoft 365" is not), so the returned strings keep
    whatever case the DB holds — no normalisation applied.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick /stats, /tags, /tags/autocomplete, and
    /products/autocomplete use upstairs.
    """
    stmt = (
        select(KnownProblem.product, func.count(KnownProblem.id))
        .group_by(KnownProblem.product)
        .order_by(
            func.count(KnownProblem.id).desc(),
            KnownProblem.product.asc(),
        )
    )
    result = await db.execute(stmt)
    return [
        ProductCount(product=row[0], count=int(row[1]))
        for row in result.all()
    ]


@router.get(
    "/products/autocomplete",
    response_model=List[ProductCount],
    dependencies=[Depends(verify_api_key)],
    summary="Prefix-search products for typeahead",
)
async def known_problem_products_autocomplete(
    prefix: str = Query(..., min_length=1, max_length=120),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """
    Return distinct `product` values whose name starts with `prefix`,
    ordered by usage count desc then product asc. Powers the admin UI's
    product filter combobox — same dropdown the `?product=` filter on
    the list endpoint feeds — and the "product" field on the create /
    bulk-upsert form, so admins re-use the canonical casing already on
    disk instead of inventing a fresh spelling ("microsoft 365" vs the
    existing "Microsoft 365").

    Matching is case-insensitive (ILIKE) because product names are stored
    case-preserved (no `_normalize_*` rule lowercases them — vendor
    branding matters: "Microsoft 365" is correct, "microsoft 365" is
    not). The user typing "mi" must find the canonical row regardless of
    shift-key state; the returned value is whatever case the DB holds.

    Prefix-only — same reasoning as `/tags/autocomplete`: a typeahead
    expects "I've typed the start of the word," not substring discovery.
    Empty results for a whitespace-only prefix are returned without a
    DB round trip (the min_length=1 validator counts raw characters and
    so accepts a single space). LIKE wildcards (`%` / `_`) in the prefix
    are not escaped — acceptable for an internal admin endpoint behind
    `verify_api_key`.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick /stats and /tags/autocomplete use upstairs.
    """
    needle = prefix.strip()
    if not needle:
        return []

    stmt = text(
        """
        SELECT kp.product AS product, count(*) AS cnt
        FROM known_problems kp
        WHERE kp.product ILIKE :pattern
        GROUP BY kp.product
        ORDER BY count(*) DESC, kp.product ASC
        LIMIT :limit
        """
    ).bindparams(pattern=f"{needle}%", limit=limit)
    result = await db.execute(stmt)
    return [ProductCount(product=row[0], count=int(row[1])) for row in result.all()]


@router.get(
    "/products/cooccurrence",
    response_model=List[ProductCooccurrence],
    dependencies=[Depends(verify_api_key)],
    summary="Products that share tags with a focal product",
)
async def known_problem_products_cooccurrence(
    product: str = Query(
        ...,
        min_length=1,
        max_length=120,
        description=(
            "Focal product. The response lists every other product whose "
            "entries share at least one tag with this product's entries, "
            "ranked by the number of distinct shared tags. Matched "
            "case-insensitively against the value stored on disk — same "
            "rule the list endpoint's `?product=` filter uses — so "
            "`Microsoft 365` and `microsoft 365` resolve to the same "
            "focal product even though both are stored case-preserved."
        ),
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description=(
            "Maximum number of co-occurring products to return. Defaults "
            "to 50 so the admin UI's 'related products' panel can render "
            "a full list without pagination on a typical library, and caps "
            "at 200 so a pathological library with hundreds of cross-vendor "
            "pairings still returns in one round-trip — same envelope "
            "/tags/cooccurrence and /templates/cooccurrence use upstairs."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return products whose entries share at least one tag with the focal
    `product`'s entries, ordered by distinct-shared-tag count desc then
    product asc. Powers the admin UI's "related products" panel: an
    operator browsing `Microsoft 365` sees that `Intune` shares 7
    different tags and `Azure AD` shares 4 — useful cross-vendor signal
    for triaging an issue that touches multiple stacks.

    Unlike /tags/cooccurrence and /templates/cooccurrence, two products
    can never appear together on the same Know-How entry (each entry has
    exactly one `product` scalar — see the model). The closest useful
    pairing is therefore "products that share a topic area," and a topic
    area on this schema means a tag. The returned `shared_tag_count` is
    the size of the **intersection** of the two products' distinct tag
    sets — interpretable as "N different overlap topics" rather than
    summed joint-tag-occurrence volume, which would be skewed by any one
    very-busy tag.

    Mirrors /tags/cooccurrence and /templates/cooccurrence in role and
    response shape (just `count` → `shared_tag_count` to make the
    different semantic explicit at the wire level), but with two key
    contract differences:

    1. **Focal match is case-insensitive on input only** — products are
       stored case-preserved (vendor branding matters), so the response
       keeps whatever case the DB holds. `?product=microsoft 365` and
       `?product=Microsoft 365` resolve to the same focal; a row carrying
       `Microsoft 365` is returned with that exact casing.

    2. **Products with zero shared tags are dropped from the response**,
       not returned with a `shared_tag_count: 0` row. The admin UI's
       "related products" panel cares about the non-empty intersection
       list — listing every other product in the library with a zero
       would crowd the dropdown and bury the actually-related entries.

    The focal product is never returned in its own list — a self-pairing
    would always equal that product's own distinct-tag count and would
    only crowd the dropdown. Self-exclusion is case-insensitive too, so
    a casing-drift duplicate (which /products/merge would later collapse)
    does not surface its other-cased self as a "neighbour."

    Empty libraries, libraries where the focal product is unused, and
    products that share no tag with any other product all return `[]`
    rather than a 404; the admin UI should fail soft (render "no
    related products") rather than blow up the page — same discipline
    /tags/cooccurrence and /templates/cooccurrence apply.

    Implementation: a single JSONB-unnest query that builds the focal
    product's distinct lowercase tag set in a CTE, then unnests every
    other product's tags, joins on the focal set, and groups by neighbour
    product — counting distinct shared tags per neighbour in one
    round-trip with no Python-side aggregation. Tags are lowercased at
    write time (see `_normalize_tags`), so the lowercase fold here is
    a no-op for correctness and matches what the GIN index sees;
    products are case-insensitive on the focal predicate via `lower()`
    but case-preserved on the GROUP BY so the response keeps the writer's
    canonical capitalisation.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick /products, /products/autocomplete,
    /tags/cooccurrence, /templates/cooccurrence, and every other
    aggregation endpoint upstairs use.
    """
    # Strip-then-short-circuit mirrors the discipline /tags/cooccurrence
    # and /templates/cooccurrence apply: a whitespace-only focal slips
    # past the min_length=1 query validator (which counts raw characters),
    # and there is no product stored with surrounding whitespace, so the
    # response is guaranteed empty — saving an index probe per stray
    # keystroke from a typeahead wired up wrong.
    focal = product.strip()
    if not focal:
        return []

    # Two-stage CTE: `focal_tags` collects the focal product's distinct
    # lowercase tag set (one row per tag, deduped across the focal's
    # entries); the outer SELECT unnests every other product's tag arrays
    # and joins back to `focal_tags` so each surviving row represents a
    # (neighbour_product, shared_tag) pair. COUNT(DISTINCT) on the shared
    # tag collapses casing-drift duplicates of the same tag inside a
    # neighbour's entries (which /tags/merge would later clean up) so
    # the score stays an honest intersection size. `lower(kp.product) <>
    # lower(:focal)` drops the focal's self-pairing — case-insensitive
    # so a casing-drift duplicate doesn't surface its other-cased self.
    # HAVING > 0 is implicit via INNER JOIN; products with zero shared
    # tags never make it into the GROUP BY in the first place.
    stmt = text(
        """
        WITH focal_tags AS (
            SELECT DISTINCT lower(t.tag) AS tag
            FROM known_problems kp,
                 jsonb_array_elements_text(kp.tags) AS t(tag)
            WHERE lower(kp.product) = lower(:focal)
        )
        SELECT kp.product AS product,
               count(DISTINCT lower(t.tag)) AS shared_tag_count
        FROM known_problems kp,
             jsonb_array_elements_text(kp.tags) AS t(tag)
        WHERE lower(kp.product) <> lower(:focal)
          AND lower(t.tag) IN (SELECT tag FROM focal_tags)
        GROUP BY kp.product
        ORDER BY count(DISTINCT lower(t.tag)) DESC, kp.product ASC
        LIMIT :limit
        """
    ).bindparams(focal=focal, limit=limit)
    result = await db.execute(stmt)
    return [
        ProductCooccurrence(product=row[0], shared_tag_count=int(row[1]))
        for row in result.all()
    ]


@router.get(
    "/products/tag-breakdown",
    response_model=List[TagCount],
    dependencies=[Depends(verify_api_key)],
    summary="Tags used within a focal product's entries, ranked by count",
)
async def known_problem_products_tag_breakdown(
    product: str = Query(
        ...,
        min_length=1,
        max_length=120,
        description=(
            "Focal product. Only entries whose `product` scalar matches "
            "this value are scanned. Matched case-insensitively against "
            "the case-preserved form stored on disk — same rule "
            "`/products/timeline`, `/products/cooccurrence`, and "
            "`/products/autocomplete` apply — so `?product=Microsoft 365` "
            "and `?product=microsoft 365` resolve to the same focal product."
        ),
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description=(
            "Maximum number of tags to return. Defaults to 50 so the admin "
            "UI's 'topics for this product' panel can render a full list "
            "without pagination on a typical product, and caps at 200 so a "
            "pathologically over-tagged product still returns in one "
            "round-trip — same envelope `/tags/cooccurrence`, "
            "`/products/cooccurrence`, and `/templates/cooccurrence` use."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the tags attached to entries of a focal product, ranked by
    in-product usage count desc then tag asc. The cross-axis dual of
    `/products/cooccurrence` (which lists *other products* sharing tags
    with the focal) and the per-product specialisation of `/tags` (which
    lists every tag library-wide): an admin browsing `Microsoft 365`
    sees `auth` appears on 12 of its entries, `mfa` on 9, `licensing`
    on 4 — useful for answering "what topics are covered under this
    product?" without scanning every row by hand or filtering `/tags`
    client-side over rows it never received.

    Mirrors `/tags` in response shape (`TagCount` — same `tag` + `count`
    fields) and ordering rule (count desc, tag asc) so the admin UI can
    reuse the same renderer it uses for the library-wide tag list. Tag
    values are returned lowercase canonical (matching `_normalize_tags`
    write-time rule and `/tags` read-time rule) — a single canonical
    casing per tag, no surprise drift across endpoints.

    The focal product predicate is `lower(kp.product) = lower(:focal)`
    rather than ILIKE — same semantics `/products/timeline` and
    `/products/cooccurrence` use, and tighter than the list endpoint's
    ILIKE substring filter on purpose: a "breakdown for Intune" must
    not silently include rows whose product is `Intune Standalone`.
    Product names are stored case-preserved (vendor branding matters),
    so the equality predicate folds case on both sides rather than
    lowercasing the bind value — matches `/products/rename` and
    `/products/merge`.

    Empty libraries, products that have no entries, and products whose
    entries carry no tags all return `[]` rather than a 404; the admin
    UI's panel should fail soft ("no tags for this product yet") rather
    than blow up the page — same discipline `/products/cooccurrence`
    and `/products/timeline` apply.

    A whitespace-only `product` (slipped past the `min_length=1`
    validator because it counts raw characters) short-circuits to `[]`
    without a DB round-trip — same fail-soft rule the rest of the
    `/products/*` family uses for the same reason.

    Implementation: a single JSONB-unnest query that filters rows by
    the focal product predicate, unnests their tags arrays, lowercases
    each tag (defence-in-depth — `_normalize_tags` already lowercases
    on write, but a historical seed entry could in theory have skipped
    that path), groups by canonical tag and counts. One round-trip,
    no Python-side aggregation.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick `/products`, `/products/autocomplete`,
    `/products/cooccurrence`, `/products/timeline`, and every other
    aggregation endpoint upstairs use.
    """
    # Strip-then-short-circuit mirrors the discipline `/products/timeline`,
    # `/products/cooccurrence`, and the rest of the `/products/*` family
    # apply: a whitespace-only focal slips past the min_length=1 query
    # validator (which counts raw characters), and there is no product
    # stored as the empty string, so the equality predicate is guaranteed
    # empty — short-circuit without a DB round-trip rather than scan for
    # an impossible value.
    focal = product.strip()
    if not focal:
        return []

    # JSONB-unnest pattern mirrors `/tags` and `/tags/autocomplete` —
    # comma-join lateral subquery for cross-version stability, and
    # `jsonb_array_elements_text` so the output rows are plain TEXT
    # (tags are stored as JSON strings, never numbers or objects, so
    # text projection is safe). The `lower(t.tag)` fold inside the
    # GROUP BY collapses any casing-drift duplicates a hypothetical
    # historical seed entry may have introduced before `_normalize_tags`
    # was enforced — matches `/tags/cooccurrence`'s defence-in-depth.
    stmt = text(
        """
        SELECT lower(t.tag) AS tag, count(*) AS cnt
        FROM known_problems kp,
             jsonb_array_elements_text(kp.tags) AS t(tag)
        WHERE lower(kp.product) = lower(:focal)
        GROUP BY lower(t.tag)
        ORDER BY count(*) DESC, lower(t.tag) ASC
        LIMIT :limit
        """
    ).bindparams(focal=focal, limit=limit)
    result = await db.execute(stmt)
    return [
        TagCount(tag=row[0], count=int(row[1]))
        for row in result.all()
    ]


@router.get(
    "/products/template-breakdown",
    response_model=List[TemplateCount],
    dependencies=[Depends(verify_api_key)],
    summary="Ticket templates referenced within a focal product's entries, ranked",
)
async def known_problem_products_template_breakdown(
    product: str = Query(
        ...,
        min_length=1,
        max_length=120,
        description=(
            "Focal product. Only entries whose `product` scalar matches "
            "this value are scanned. Matched case-insensitively against "
            "the case-preserved form stored on disk — same rule "
            "`/products/timeline`, `/products/cooccurrence`, "
            "`/products/tag-breakdown`, and `/products/autocomplete` apply "
            "— so `?product=Microsoft 365` and `?product=microsoft 365` "
            "resolve to the same focal product."
        ),
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description=(
            "Maximum number of templates to return. Defaults to 50 so the "
            "admin UI's 'runbooks for this product' panel can render a full "
            "list without pagination on a typical product, and caps at 200 "
            "so a pathologically over-templated product still returns in "
            "one round-trip — same envelope `/products/tag-breakdown`, "
            "`/tags/cooccurrence`, `/products/cooccurrence`, and "
            "`/templates/cooccurrence` use."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the ticket templates referenced by entries of a focal product,
    ranked by in-product usage count desc then template asc. The third
    panel of the per-product drill-down page — sits alongside
    `/products/tag-breakdown` (topics under this product) and
    `/products/timeline` (growth of this product) — and the cross-axis
    dual of a future `/templates/product-breakdown` (which products
    reference a focal template). An admin browsing `Microsoft 365` sees
    `tmpl-mfa-reset` appears on 9 of its entries, `tmpl-outlook-cred` on
    4, `tmpl-licensing` on 2 — useful for answering "which runbooks
    cover this product?" without scanning every row by hand or filtering
    `/templates` client-side over rows it never received.

    Mirrors `/templates` in response shape (`TemplateCount` — same
    `template` + `count` fields) and ordering rule (count desc, template
    asc) so the admin UI can reuse the same renderer it uses for the
    library-wide template list. Template strings are returned **verbatim**
    from disk — there is no canonicalisation rule on the way in (template
    refs are opaque external runbook identifiers chosen by the writer,
    not free-form labels), so the output preserves whatever casing /
    punctuation the writer used. Differs deliberately from
    `/products/tag-breakdown` on that one axis: tags are lowercased on
    write and on read; templates are case-preserved everywhere.

    The focal product predicate is `lower(kp.product) = lower(:focal)`
    rather than ILIKE — same semantics `/products/timeline`,
    `/products/cooccurrence`, and `/products/tag-breakdown` use, and
    tighter than the list endpoint's ILIKE substring filter on purpose:
    a "breakdown for Intune" must not silently include rows whose product
    is `Intune Standalone`. Product names are stored case-preserved
    (vendor branding matters), so the equality predicate folds case on
    both sides rather than lowercasing the bind value — matches
    `/products/rename` and `/products/merge` so audit-log bind-parameter
    values preserve the writer's original casing.

    Empty libraries, products that have no entries, and products whose
    entries reference no templates all return `[]` rather than a 404; the
    admin UI's panel should fail soft ("no runbooks for this product yet")
    rather than blow up the page — same discipline
    `/products/tag-breakdown`, `/products/cooccurrence`, and
    `/products/timeline` apply.

    A whitespace-only `product` (slipped past the `min_length=1`
    validator because it counts raw characters) short-circuits to `[]`
    without a DB round-trip — same fail-soft rule the rest of the
    `/products/*` family uses for the same reason.

    Implementation: a single JSONB-unnest query that filters rows by
    the focal product predicate, unnests their `related_ticket_templates`
    arrays, groups by case-preserved template and counts. One round-trip,
    no Python-side aggregation. The GROUP BY uses the raw `t.template`
    (not `lower(t.template)`) on purpose — templates are stored case-
    preserved and the response axis preserves that casing too, so
    folding would incorrectly collapse `TMPL-MFA-Reset` and
    `tmpl-mfa-reset` into a single count (a casing-drift duplicate that
    `/templates/merge` would clean up, but is the operator's mess to
    resolve, not this endpoint's to hide).

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick `/products`, `/products/autocomplete`,
    `/products/cooccurrence`, `/products/timeline`,
    `/products/tag-breakdown`, and every other aggregation endpoint
    upstairs use.
    """
    # Strip-then-short-circuit mirrors the discipline `/products/timeline`,
    # `/products/cooccurrence`, `/products/tag-breakdown`, and the rest of
    # the `/products/*` family apply: a whitespace-only focal slips past
    # the min_length=1 query validator (which counts raw characters), and
    # there is no product stored as the empty string, so the equality
    # predicate is guaranteed empty — short-circuit without a DB round-trip
    # rather than scan for an impossible value.
    focal = product.strip()
    if not focal:
        return []

    # JSONB-unnest pattern mirrors `/templates` and
    # `/templates/autocomplete` — comma-join lateral subquery for cross-
    # version stability, and `jsonb_array_elements_text` so the output
    # rows are plain TEXT (template refs are stored as JSON strings,
    # never numbers or objects, so text projection is safe). Unlike
    # `/products/tag-breakdown`'s `lower(t.tag)` projection, this GROUP
    # BY keeps the case-preserved `t.template` — templates are not
    # canonicalised on write (see /templates and /templates/autocomplete
    # for the same reasoning) so the read-time response also preserves
    # casing. Casing-drift duplicates (a row with both `TMPL-MFA-Reset`
    # and `tmpl-mfa-reset`) surface as two separate counts here — that
    # mismatch is `/templates/merge`'s job to clean up, not this
    # endpoint's to silently fold.
    stmt = text(
        """
        SELECT t.template::text AS template, count(*) AS cnt
        FROM known_problems kp,
             jsonb_array_elements_text(kp.related_ticket_templates) AS t(template)
        WHERE lower(kp.product) = lower(:focal)
        GROUP BY t.template
        ORDER BY count(*) DESC, t.template ASC
        LIMIT :limit
        """
    ).bindparams(focal=focal, limit=limit)
    result = await db.execute(stmt)
    return [
        TemplateCount(template=row[0], count=int(row[1]))
        for row in result.all()
    ]


@router.get(
    "/templates",
    response_model=List[TemplateCount],
    dependencies=[Depends(verify_api_key)],
    summary="List distinct ticket templates with usage counts",
)
async def known_problem_templates(
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregate distinct `related_ticket_templates` references across the
    entire Know-How Library with the number of entries each template is
    attached to. Powers admin tooling that needs to answer "which ticket
    templates are referenced by which Know-How rows?" without scanning
    every row by hand — useful for detecting orphaned template ids after
    a template is renamed or retired upstream, and for finding the most
    widely-referenced template when consolidating duplicates.

    Mirrors the `/tags` contract exactly: same JSONB-unnest pattern, same
    response shape (just renamed `tag` → `template`), same ordering rule
    (count desc, template asc). Template strings are returned verbatim
    from disk — there is no canonicalisation rule on the way in (template
    refs are opaque external identifiers, not free-form labels), so the
    output preserves whatever casing/punctuation the writer used.

    Sorted by count desc, then template asc — so the most-referenced
    template surfaces first and tied templates sort alphabetically
    (stable, predictable order for snapshot tests and for humans scanning
    an admin dashboard).

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick the other aggregation endpoints upstairs use.
    """
    # Same JSONB unnest pattern /tags uses — comma-join lateral subquery
    # for cross-version stability, and `jsonb_array_elements_text` so the
    # output rows are plain TEXT (template refs are stored as JSON
    # strings, never numbers or objects, so text projection is safe).
    stmt = text(
        """
        SELECT t.template::text AS template, count(*) AS cnt
        FROM known_problems kp,
             jsonb_array_elements_text(kp.related_ticket_templates) AS t(template)
        GROUP BY t.template
        ORDER BY count(*) DESC, t.template ASC
        """
    )
    result = await db.execute(stmt)
    return [
        TemplateCount(template=row[0], count=int(row[1]))
        for row in result.all()
    ]


@router.get(
    "/templates/autocomplete",
    response_model=List[TemplateCount],
    dependencies=[Depends(verify_api_key)],
    summary="Prefix-search ticket templates for typeahead",
)
async def known_problem_templates_autocomplete(
    prefix: str = Query(..., min_length=1, max_length=120),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """
    Return distinct `related_ticket_templates` references whose name starts
    with `prefix`, ordered by usage count desc then template asc. Powers
    the admin UI's "add template" combobox on the create / bulk-upsert
    form — same role `/products/autocomplete` and `/tags/autocomplete`
    play for their respective fields. The user types `tmpl-mfa` and the
    dropdown narrows to `tmpl-mfa-reset`, `tmpl-mfa-bypass`, etc. ranked
    by how widely each template is referenced so the most familiar option
    surfaces first.

    Matching is case-insensitive (ILIKE) because template refs are stored
    case-preserved (no `_normalize_*` rule lowercases them — these are
    opaque external identifiers chosen by the writer, and the runbook
    system upstream may use mixed case like `TMPL-MFA-Reset`). The user
    typing `tmpl` must find every variant regardless of shift-key state;
    the returned value is whatever case the DB holds, so the admin UI
    re-uses canonical casing instead of inventing fresh capitalisation.

    Prefix-only — same reasoning as `/tags/autocomplete` and
    `/products/autocomplete`: a typeahead expects "I've typed the start
    of the word," not substring discovery. The `%` wildcard is appended
    server-side so callers never need to know about LIKE syntax — and
    never get the chance to inject one. LIKE wildcards (`%` / `_`) in
    the prefix are not escaped — acceptable for an internal admin
    endpoint behind `verify_api_key`. Empty results for a whitespace-only
    prefix are returned without a DB round trip (the min_length=1 validator
    counts raw characters and so accepts a single space).

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick /products/autocomplete and /tags/autocomplete use
    upstairs.
    """
    # Same strip-then-short-circuit pattern /tags/autocomplete and
    # /products/autocomplete use — a stray space keystroke from the
    # typeahead must not fire a DB query, and ILIKE'ing `' %'` would
    # match every row that happens to contain a space, which is wrong.
    needle = prefix.strip()
    if not needle:
        return []

    # Same JSONB-unnest + GROUP BY shape /templates and /tags/autocomplete
    # use — `jsonb_array_elements_text` projects to TEXT so ILIKE's pattern
    # binding is unambiguous, and the LATERAL join lets one query both
    # filter and count without a self-join.
    stmt = text(
        """
        SELECT t.template::text AS template, count(*) AS cnt
        FROM known_problems kp,
             jsonb_array_elements_text(kp.related_ticket_templates) AS t(template)
        WHERE t.template ILIKE :pattern
        GROUP BY t.template
        ORDER BY count(*) DESC, t.template ASC
        LIMIT :limit
        """
    ).bindparams(pattern=f"{needle}%", limit=limit)
    result = await db.execute(stmt)
    return [
        TemplateCount(template=row[0], count=int(row[1]))
        for row in result.all()
    ]


@router.get(
    "/templates/cooccurrence",
    response_model=List[TemplateCooccurrence],
    dependencies=[Depends(verify_api_key)],
    summary="Templates that co-occur with a focal template",
)
async def known_problem_templates_cooccurrence(
    template: str = Query(
        ...,
        min_length=1,
        max_length=120,
        description=(
            "Focal ticket template. The response lists every other template "
            "that appears alongside this one on at least one Know-How entry, "
            "with the joint-occurrence count. Matched case-insensitively "
            "against the value stored on disk — same rule "
            "/templates/autocomplete and /templates/rename apply — so "
            "`TMPL-MFA-Reset` and `tmpl-mfa-reset` resolve to the same "
            "focal template even though both are stored case-preserved."
        ),
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description=(
            "Maximum number of co-occurring templates to return. Defaults "
            "to 50 so the admin UI's 'related templates' panel can render "
            "a full list without pagination on a typical library, and caps "
            "at 200 so a pathological library with hundreds of template "
            "pairings still returns in one round-trip — same envelope "
            "/tags/cooccurrence uses one floor up."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return ticket templates that co-occur with the focal `template` on at
    least one Know-How entry, ordered by joint-occurrence count desc then
    template asc. Powers the admin UI's "related templates" panel: an
    operator filtering by `tmpl-mfa-reset` sees that `tmpl-mfa-bypass` and
    `tmpl-onboarding-reset` show up alongside it most often, which guides
    them toward a useful secondary filter without scanning every entry.

    Mirrors /tags/cooccurrence in role and response shape (just `tag` →
    `template`), but with one key contract difference: templates are
    opaque external runbook identifiers stored **case-preserved** (there
    is no `_normalize_*` lowercase fold on the way in — see
    /templates/autocomplete for the same reasoning), so the focal is
    matched case-insensitively while the returned neighbour templates
    preserve the casing the writer used. `?template=TMPL-MFA-Reset` and
    `?template=tmpl-mfa-reset` resolve to the same focal; a row carrying
    `TMPL-MFA-Reset` is returned with that exact casing so the admin UI
    re-uses canonical casing instead of inventing fresh capitalisation.

    The focal template is never returned in its own list — a self-pairing
    would always equal that template's `/templates` count and would only
    push the actually-interesting neighbours down the dropdown.
    Self-exclusion is case-insensitive too, so a row whose template list
    is `["TMPL-MFA-Reset", "tmpl-mfa-reset"]` (a casing-drift duplicate
    /templates/merge would clean up) does not surface its other-cased
    self as a "neighbour."

    Empty libraries, libraries where the focal template is unused, and
    templates that never share a row with another template all return
    `[]` rather than a 404; the admin UI should fail soft (render "no
    related templates") rather than hard — same discipline
    /tags/cooccurrence applies.

    Implementation: a single JSONB-unnest query that filters to rows
    carrying the focal template (case-insensitive EXISTS predicate on the
    unnested array, since `@>` is case-sensitive and templates are not
    canonicalised), then unnests each matched row's template array and
    counts every neighbour except the focal itself. One round-trip, no
    Python-side aggregation. Cannot use the GIN-backed `@>` containment
    operator the way /tags/cooccurrence does precisely because templates
    are case-preserved — `[TMPL-MFA-Reset]` and `[tmpl-mfa-reset]` would
    be two separate JSONB values for `@>`. The EXISTS-with-lower-fold
    predicate accepts a small cost (sequential scan of the unnested
    templates) in exchange for the right semantics; in practice the
    library is small enough (low thousands of entries) that the cost is
    invisible, and the row-count filter via the subquery still narrows
    the GROUP-BY dataset to rows that actually carry the focal.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick /tags, /tags/cooccurrence, /templates, and every
    other aggregation endpoint upstairs use.
    """
    # Strip-then-short-circuit mirrors the canonicalisation rule the rest
    # of the file applies to template inputs (see /templates/rename and
    # /templates/autocomplete): a whitespace-only focal slips past the
    # min_length=1 query validator (which counts raw characters), but
    # there is no template stored with surrounding whitespace, so
    # `lower(t.template) = lower('   ')` is guaranteed empty — saving an
    # index probe per stray keystroke from a typeahead wired up wrong.
    focal = template.strip()
    if not focal:
        return []

    # Case-insensitive focal match via lower() fold inside the EXISTS
    # subquery — cannot use the GIN-backed `@>` operator because
    # templates are stored case-preserved and `@>` is case-sensitive.
    # The unnest-twice shape (once in EXISTS, once in the outer FROM)
    # is the smallest correct expression: it lets one query both filter
    # rows to those carrying the focal and count every neighbour on
    # those rows in a single GROUP BY. The `lower(t.template) <>
    # lower(:focal)` predicate drops the focal's self-pairing —
    # case-insensitive so a casing-drift duplicate (which
    # /templates/merge would later collapse) doesn't surface its
    # other-cased self as a "neighbour."
    stmt = text(
        """
        SELECT t.template::text AS template, count(*) AS cnt
        FROM known_problems kp,
             jsonb_array_elements_text(kp.related_ticket_templates) AS t(template)
        WHERE EXISTS (
            SELECT 1
            FROM jsonb_array_elements_text(kp.related_ticket_templates) AS f(template)
            WHERE lower(f.template) = lower(:focal)
        )
          AND lower(t.template) <> lower(:focal)
        GROUP BY t.template
        ORDER BY count(*) DESC, t.template ASC
        LIMIT :limit
        """
    ).bindparams(focal=focal, limit=limit)
    result = await db.execute(stmt)
    return [
        TemplateCooccurrence(template=row[0], count=int(row[1]))
        for row in result.all()
    ]


@router.get(
    "/templates/tag-breakdown",
    response_model=List[TagCount],
    dependencies=[Depends(verify_api_key)],
    summary="Tags used within entries that reference a focal template, ranked by count",
)
async def known_problem_templates_tag_breakdown(
    template: str = Query(
        ...,
        min_length=1,
        max_length=120,
        description=(
            "Focal ticket template. Only entries whose `related_ticket_templates` "
            "array references this template (case-insensitively) are scanned. "
            "Matched the same way `/templates/cooccurrence`, "
            "`/templates/autocomplete`, and `/templates/rename` apply — so "
            "`?template=TMPL-MFA-Reset` and `?template=tmpl-mfa-reset` resolve "
            "to the same focal template even though both are stored "
            "case-preserved on disk."
        ),
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description=(
            "Maximum number of tags to return. Defaults to 50 so the admin "
            "UI's 'topics covered by this runbook' panel can render a full "
            "list without pagination on a typical template, and caps at 200 "
            "so a pathologically over-tagged template still returns in one "
            "round-trip — same envelope `/products/tag-breakdown`, "
            "`/tags/product-breakdown`, `/templates/cooccurrence`, and the "
            "rest of the breakdown family use."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the tags attached to entries that reference a focal ticket
    template, ranked by in-template usage count desc then tag asc. The
    cross-axis dual of `/products/tag-breakdown` (which lists tags
    attached to a focal product's entries) and the per-template
    specialisation of `/tags` (which lists every tag library-wide): an
    admin browsing `tmpl-mfa-reset` sees `auth` appears on 8 of its
    entries, `mfa` on 7, `licensing` on 2 — useful for answering "what
    topics does this runbook actually cover?" without scanning every
    row by hand or filtering `/tags` client-side over rows it never
    received.

    Mirrors `/products/tag-breakdown` in response shape (`TagCount` —
    same `tag` + `count` fields) and ordering rule (count desc, tag
    asc) so the admin UI can reuse the same renderer it uses for the
    library-wide tag list and the per-product tag breakdown. Tag values
    are returned lowercase canonical (matching `_normalize_tags`
    write-time rule and `/tags` read-time rule) — a single canonical
    casing per tag, no surprise drift across endpoints.

    The focal template predicate is an EXISTS-with-lower-fold over the
    unnested `related_ticket_templates` array rather than the
    GIN-backed `@>` containment operator: templates are stored
    case-preserved (vendor runbook identifiers are not folded by any
    `_normalize_*` rule — see `/templates/autocomplete` for the same
    reasoning), and `@>` is case-sensitive, so `?template=TMPL-MFA-Reset`
    would silently miss rows whose array element is `tmpl-mfa-reset`.
    Same predicate `/templates/cooccurrence` uses for the same reason.

    Empty libraries, templates that are never referenced, and templates
    whose referencing entries carry no tags all return `[]` rather than
    a 404; the admin UI's panel should fail soft ("no tags for this
    runbook yet") rather than blow up the page — same discipline
    `/templates/cooccurrence`, `/products/tag-breakdown`, and the rest
    of the breakdown family apply.

    A whitespace-only `template` (slipped past the `min_length=1`
    validator because it counts raw characters) short-circuits to `[]`
    without a DB round-trip — same fail-soft rule the rest of the
    `/templates/*` family uses for the same reason.

    Implementation: a single JSONB-unnest query that filters rows by
    the case-insensitive EXISTS predicate on the focal template, then
    unnests their `tags` arrays, lowercases each tag (defence-in-depth
    — `_normalize_tags` already lowercases on write, but a historical
    seed entry could in theory have skipped that path), groups by
    canonical tag and counts. One round-trip, no Python-side
    aggregation.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick `/products`, `/products/tag-breakdown`,
    `/tags/product-breakdown`, `/templates/cooccurrence`, and every
    other aggregation endpoint upstairs use.
    """
    # Strip-then-short-circuit mirrors the discipline `/templates/cooccurrence`
    # and the rest of the `/templates/*` family apply: a whitespace-only
    # focal slips past the min_length=1 query validator (which counts raw
    # characters), and there is no template stored as the empty string,
    # so the EXISTS predicate is guaranteed empty — short-circuit without
    # a DB round-trip rather than scan for an impossible value. Lowercasing
    # here would be incorrect (templates are case-preserved on disk), so
    # the case-insensitivity is applied inside the SQL predicate via
    # lower() folds on both sides — matches `/templates/cooccurrence`.
    focal = template.strip()
    if not focal:
        return []

    # EXISTS-with-lower-fold pattern mirrors `/templates/cooccurrence` —
    # we cannot use the GIN-backed `@>` containment operator because
    # templates are stored case-preserved, and `@>` is case-sensitive.
    # The unnest in the outer FROM is on `tags` (not templates), so the
    # outer GROUP BY counts each tag occurrence on a matched row. The
    # `lower(t.tag)` fold inside the GROUP BY collapses any casing-drift
    # duplicates a hypothetical historical seed entry may have introduced
    # before `_normalize_tags` was enforced — matches `/products/tag-breakdown`'s
    # defence-in-depth.
    stmt = text(
        """
        SELECT lower(t.tag) AS tag, count(*) AS cnt
        FROM known_problems kp,
             jsonb_array_elements_text(kp.tags) AS t(tag)
        WHERE EXISTS (
            SELECT 1
            FROM jsonb_array_elements_text(kp.related_ticket_templates) AS f(template)
            WHERE lower(f.template) = lower(:focal)
        )
        GROUP BY lower(t.tag)
        ORDER BY count(*) DESC, lower(t.tag) ASC
        LIMIT :limit
        """
    ).bindparams(focal=focal, limit=limit)
    result = await db.execute(stmt)
    return [
        TagCount(tag=row[0], count=int(row[1]))
        for row in result.all()
    ]


@router.get(
    "/templates/product-breakdown",
    response_model=List[ProductCount],
    dependencies=[Depends(verify_api_key)],
    summary="Products of entries that reference a focal template, ranked by count",
)
async def known_problem_templates_product_breakdown(
    template: str = Query(
        ...,
        min_length=1,
        max_length=120,
        description=(
            "Focal ticket template. Only entries whose `related_ticket_templates` "
            "array references this template (case-insensitively) are scanned. "
            "Matched the same way `/templates/cooccurrence`, "
            "`/templates/tag-breakdown`, `/templates/autocomplete`, and "
            "`/templates/rename` apply — so `?template=TMPL-MFA-Reset` and "
            "`?template=tmpl-mfa-reset` resolve to the same focal template "
            "even though both are stored case-preserved on disk."
        ),
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description=(
            "Maximum number of products to return. Defaults to 50 so the "
            "admin UI's 'products covered by this runbook' panel can render "
            "a full list without pagination on a typical template, and caps "
            "at 200 so a pathologically cross-product runbook still returns "
            "in one round-trip — same envelope `/products/tag-breakdown`, "
            "`/tags/product-breakdown`, `/templates/tag-breakdown`, "
            "`/templates/cooccurrence`, and the rest of the breakdown family use."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the products of entries that reference a focal ticket
    template, ranked by in-template usage count desc then product asc.
    The cross-axis dual of `/templates/tag-breakdown` (which lists
    *tags* attached to entries referencing the focal template) and the
    per-template specialisation of `/products` (which lists every
    product library-wide): an admin browsing `tmpl-mfa-reset` sees
    `Microsoft 365` has 10 entries referencing it, `Intune` has 4,
    `Meraki` has 1 — useful for answering "which products is this
    runbook actually used under?" without scanning every row by hand
    or filtering `/products` client-side over rows it never received.

    Fills the last missing cell of the 3×3 breakdown matrix
    (products × tags × templates) — the same "future" endpoint already
    named in the `/products/template-breakdown` docstring, and the
    fourth panel of the per-template drill-down page (sits alongside
    `/templates/cooccurrence`, `/templates/timeline`, and
    `/templates/tag-breakdown`).

    Mirrors `/products` in response shape (`ProductCount` — same
    `product` + `count` fields) and ordering rule (count desc, product
    asc) so the admin UI can reuse the same renderer it uses for the
    library-wide product list and the per-tag product breakdown.
    Product names are returned case-preserved (vendor branding matters
    — "Microsoft 365" is canonical, "microsoft 365" is not), matching
    the rule the rest of the `/products/*` family follows.

    The focal template predicate is an EXISTS-with-lower-fold over the
    unnested `related_ticket_templates` array rather than the
    GIN-backed `@>` containment operator: templates are stored
    case-preserved (vendor runbook identifiers are not folded by any
    `_normalize_*` rule — see `/templates/autocomplete` for the same
    reasoning), and `@>` is case-sensitive, so `?template=TMPL-MFA-Reset`
    would silently miss rows whose array element is `tmpl-mfa-reset`.
    Same predicate `/templates/cooccurrence` and `/templates/tag-breakdown`
    use for the same reason.

    Empty libraries, templates that are never referenced, and templates
    whose referencing entries cover no products (impossible in
    practice — `product` is NOT NULL — but treated defensively) all
    return `[]` rather than a 404; the admin UI's panel should fail
    soft ("no products for this runbook yet") rather than blow up the
    page — same discipline `/templates/cooccurrence`,
    `/templates/tag-breakdown`, and the rest of the breakdown family
    apply.

    A whitespace-only `template` (slipped past the `min_length=1`
    validator because it counts raw characters) short-circuits to `[]`
    without a DB round-trip — same fail-soft rule the rest of the
    `/templates/*` family uses for the same reason.

    Implementation: a single query that filters rows by the
    case-insensitive EXISTS predicate on the focal template, groups by
    `kp.product` directly (no unnest — each entry carries exactly one
    product scalar), and counts. One round-trip, no Python-side
    aggregation. Cheaper than `/templates/tag-breakdown` (no tag
    unnest) because the product side is a scalar, not an array.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick `/products`, `/products/tag-breakdown`,
    `/tags/product-breakdown`, `/templates/cooccurrence`,
    `/templates/tag-breakdown`, and every other aggregation endpoint
    upstairs use.
    """
    # Strip-then-short-circuit mirrors the discipline `/templates/cooccurrence`,
    # `/templates/tag-breakdown`, and the rest of the `/templates/*` family
    # apply: a whitespace-only focal slips past the min_length=1 query
    # validator (which counts raw characters), and there is no template
    # stored as the empty string, so the EXISTS predicate is guaranteed
    # empty — short-circuit without a DB round-trip rather than scan for
    # an impossible value. Lowercasing here would be incorrect (templates
    # are case-preserved on disk), so the case-insensitivity is applied
    # inside the SQL predicate via lower() folds on both sides — matches
    # `/templates/cooccurrence` and `/templates/tag-breakdown`.
    focal = template.strip()
    if not focal:
        return []

    # EXISTS-with-lower-fold pattern mirrors `/templates/cooccurrence`
    # and `/templates/tag-breakdown` — we cannot use the GIN-backed `@>`
    # containment operator because templates are stored case-preserved,
    # and `@>` is case-sensitive. The outer FROM has no unnest (unlike
    # /templates/tag-breakdown which unnests the tags array) — `product`
    # is a scalar on `known_problems`, so grouping directly by
    # `kp.product` counts entries (one per row referencing the focal),
    # which is the right semantic for the "products covered by this
    # runbook" admin panel.
    stmt = text(
        """
        SELECT kp.product AS product, count(*) AS cnt
        FROM known_problems kp
        WHERE EXISTS (
            SELECT 1
            FROM jsonb_array_elements_text(kp.related_ticket_templates) AS f(template)
            WHERE lower(f.template) = lower(:focal)
        )
        GROUP BY kp.product
        ORDER BY count(*) DESC, kp.product ASC
        LIMIT :limit
        """
    ).bindparams(focal=focal, limit=limit)
    result = await db.execute(stmt)
    return [
        ProductCount(product=row[0], count=int(row[1]))
        for row in result.all()
    ]


@router.get(
    "/orphans",
    response_model=OrphansResponse,
    dependencies=[Depends(verify_api_key)],
    summary="List entries flagged with data-quality issues",
)
async def known_problem_orphans(
    issue: Optional[List[str]] = Query(
        None,
        description=(
            "Filter to entries flagged with at least one of these issue "
            "codes. Repeat the parameter (`?issue=no_tags&issue=short_fix`) "
            "to broaden the filter — semantics are OR within `issue`, the "
            "opposite of the list endpoint's tag filter which is AND. "
            "Omit to return entries flagged with any issue. Unknown codes "
            "are rejected with 422 so a typo can't silently filter to "
            "zero results. Valid codes: no_tags, no_templates, "
            "short_symptom, short_diagnosis, short_fix."
        ),
    ),
    short_threshold: int = Query(
        20, ge=1, le=10_000,
        description=(
            "Character count below which `symptom`, `diagnosis`, or `fix` "
            "is considered too short to be useful and flagged as a "
            "`short_*` issue. Defaults to 20 — long enough to fit a real "
            "sentence, short enough to catch placeholder rows like 'TBD'."
        ),
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Data-quality report for the Know-How Library: rows missing tags or
    templates, or whose text fields are too short to be diagnostically
    useful. Powers an admin "needs attention" tile so operators have a
    bounded worklist for curation rather than a 1000-row trawl.

    Each row is checked against every known issue code; the response
    carries the row plus the full `issues` list, so an entry with no
    tags AND a placeholder `fix` surfaces with both codes attached.
    The caller-supplied `issue=` filter narrows the result set in SQL
    (OR-semantics) without changing what `issues` reports per row — a
    row pulled in by `?issue=no_tags` still shows its `short_fix`
    issue if it has one, so the admin UI never has to re-fetch to learn
    "what else is wrong here".

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick the other aggregation endpoints use.

    Issue codes:
      - `no_tags`         — `tags` list is empty
      - `no_templates`    — `related_ticket_templates` list is empty
      - `short_symptom`   — `symptom` shorter than `short_threshold`
      - `short_diagnosis` — `diagnosis` shorter than `short_threshold`
      - `short_fix`       — `fix` shorter than `short_threshold`
    """
    # Validate the requested issue codes up front so a typo
    # ("?issue=no-tags" with a dash) fails loudly instead of quietly
    # returning an empty page that the admin UI can't distinguish from
    # "the library is clean".
    if issue is not None:
        unknown = [code for code in issue if code not in _ORPHAN_ISSUE_CODES]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Unknown issue code(s): {', '.join(sorted(set(unknown)))}. "
                    f"Valid codes: {', '.join(sorted(_ORPHAN_ISSUE_CODES))}."
                ),
            )
        # Dedupe but preserve order so the SQL OR-list is deterministic
        # for snapshot tests and EXPLAIN plans.
        seen: set[str] = set()
        requested = [c for c in issue if not (c in seen or seen.add(c))]
    else:
        requested = sorted(_ORPHAN_ISSUE_CODES)

    # Build the per-issue predicates as plain SQL fragments. Each fragment
    # is a boolean column expression and is reused for the count query and
    # the paginated row query — keeping them in lockstep means the total
    # never disagrees with what entries can possibly come back.
    fragments: dict[str, str] = {
        _ORPHAN_ISSUE_NO_TAGS: "jsonb_array_length(tags) = 0",
        _ORPHAN_ISSUE_NO_TEMPLATES: "jsonb_array_length(related_ticket_templates) = 0",
        _ORPHAN_ISSUE_SHORT_SYMPTOM: "char_length(symptom) < :short_threshold",
        _ORPHAN_ISSUE_SHORT_DIAGNOSIS: "char_length(diagnosis) < :short_threshold",
        _ORPHAN_ISSUE_SHORT_FIX: "char_length(fix) < :short_threshold",
    }
    where_clause = " OR ".join(f"({fragments[code]})" for code in requested)
    # Only bind `:short_threshold` when at least one short_* predicate is
    # actually in the WHERE — SQLAlchemy raises if a name is bound that
    # the text() construct doesn't reference. Equally, the SQL doesn't
    # silently swallow the threshold when the caller asked only for tag
    # or template issues: the parameter simply isn't part of the query
    # in that case.
    needs_threshold = ":short_threshold" in where_clause
    binds = {"short_threshold": short_threshold} if needs_threshold else {}

    count_stmt = text(
        f"SELECT count(*) FROM known_problems WHERE {where_clause}"
    ).bindparams(**binds)
    total_row = await db.execute(count_stmt)
    total = int(total_row.scalar() or 0)

    # Order by updated_at DESC so the most recently touched orphans
    # surface first — matches the admin's mental model of "what did I
    # just half-finish?". Tie-break on id for deterministic pagination
    # when two rows share an updated_at (created in the same bulk-upsert).
    row_stmt = (
        select(KnownProblem)
        .where(text(where_clause).bindparams(**binds))
        .order_by(KnownProblem.updated_at.desc(), KnownProblem.id.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(row_stmt)).scalars().all()

    def _issues_for(kp: KnownProblem) -> List[str]:
        # Always report every issue the row exhibits, regardless of which
        # codes the caller filtered on — see docstring for the rationale.
        # Order follows the declaration order of `_ORPHAN_ISSUE_*` so
        # snapshot tests stay stable.
        out: List[str] = []
        if not (kp.tags or []):
            out.append(_ORPHAN_ISSUE_NO_TAGS)
        if not (kp.related_ticket_templates or []):
            out.append(_ORPHAN_ISSUE_NO_TEMPLATES)
        if len(kp.symptom or "") < short_threshold:
            out.append(_ORPHAN_ISSUE_SHORT_SYMPTOM)
        if len(kp.diagnosis or "") < short_threshold:
            out.append(_ORPHAN_ISSUE_SHORT_DIAGNOSIS)
        if len(kp.fix or "") < short_threshold:
            out.append(_ORPHAN_ISSUE_SHORT_FIX)
        return out

    entries = [
        OrphanEntry(
            problem=KnownProblemResponse.from_orm_row(kp),
            issues=_issues_for(kp),
        )
        for kp in rows
    ]
    return OrphansResponse(total=total, entries=entries)


@router.get(
    "/duplicates",
    response_model=DuplicatesResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Find clusters of rows sharing the same product+symptom",
)
async def known_problem_duplicates(
    product: Optional[str] = Query(
        None, max_length=120,
        description=(
            "Optional exact product filter (case-insensitive, whitespace "
            "stripped). When set, only clusters whose normalised product "
            "matches are returned — useful for triaging duplicates one "
            "vendor at a time. Omit to scan the whole library."
        ),
    ),
    min_group_size: int = Query(
        2, ge=2, le=100,
        description=(
            "Minimum number of rows a cluster must contain to surface. "
            "Defaults to 2 — the textbook 'two rows that look the same' "
            "case. Raise it to focus on the worst offenders first when "
            "the library has accumulated a long tail of small duplicates."
        ),
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Data-quality report: find groups of Know-How rows that share an
    identical (product, symptom) pair after case-folding, so an operator
    can scan and consolidate them via POST /{id}/merge. Powers an admin
    "needs consolidation" tile alongside /orphans — orphans tells you
    *which entries are incomplete*, /duplicates tells you *which entries
    are redundant*.

    Normalisation: matches are case-insensitive on both `product` and
    `symptom` (LOWER() on both sides) so "Microsoft 365 — MFA loop" and
    "microsoft 365 — mfa loop" cluster together. The response echoes the
    case-preserved text from the cluster's first row, not the lowercased
    key — vendor branding matters for the operator scanning the list.
    Whitespace inside `symptom` is *not* normalised: "MFA prompts" and
    "MFA  prompts" (two spaces) are treated as distinct, on the
    principle that one of them is probably a typo worth seeing
    separately rather than silently merging.

    Cluster ordering: by size DESC (biggest dupe-piles first — the
    highest-leverage merges for the operator), then by lowercased product
    and lowercased symptom ASC for stable pagination on ties. Within a
    cluster, entries are ordered by `created_at` ASC then `id` ASC — the
    oldest row first, which is the canonical "keep this one" pick when
    invoking /{id}/merge with the others as sources.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick the other aggregation endpoints upstairs use.
    """
    # Optional product filter — case-insensitive match against the
    # normalised key, same semantics the list endpoint's `?product=`
    # uses. Whitespace stripped before binding so " Microsoft 365 "
    # finds the same cluster as "Microsoft 365".
    product_filter = (product or "").strip() if product is not None else None
    where_clauses: list[str] = []
    binds: dict[str, Any] = {"min_group_size": min_group_size}
    if product_filter:
        where_clauses.append("LOWER(product) = :product_norm")
        binds["product_norm"] = product_filter.lower()
    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # Count of clusters: HAVING count(*) >= min_group_size is the
    # filtering predicate, and the outer SELECT count(*) wraps it so
    # the admin UI can render "showing 50 of 312" without a second pass.
    count_stmt = text(
        f"""
        SELECT count(*) FROM (
            SELECT 1 FROM known_problems
            {where_sql}
            GROUP BY LOWER(product), LOWER(symptom)
            HAVING count(*) >= :min_group_size
        ) g
        """
    ).bindparams(**binds)
    total_row = await db.execute(count_stmt)
    total = int(total_row.scalar() or 0)

    # Paginated cluster keys: pull just the normalised (product, symptom)
    # pairs and their sizes — enough to render the result envelope's
    # `size`, `product`, `symptom` echo. Order rules match the docstring:
    # size DESC for highest-leverage merges first, then lp/ls ASC so two
    # equal-size clusters paginate deterministically.
    keys_stmt = text(
        f"""
        SELECT LOWER(product) AS lp, LOWER(symptom) AS ls, count(*) AS cnt
        FROM known_problems
        {where_sql}
        GROUP BY LOWER(product), LOWER(symptom)
        HAVING count(*) >= :min_group_size
        ORDER BY count(*) DESC, LOWER(product) ASC, LOWER(symptom) ASC
        LIMIT :limit OFFSET :offset
        """
    ).bindparams(**binds, limit=limit, offset=offset)
    key_rows = (await db.execute(keys_stmt)).all()

    if not key_rows:
        return DuplicatesResponse(total=total, clusters=[])

    # Build a stable lookup so we can both
    #   (a) restrict the row-fetch to just the paginated keys, and
    #   (b) group fetched rows back into their cluster server-side.
    # The lookup key is the (lp, ls) tuple — same tuple the SQL groups by.
    cluster_keys: list[tuple[str, str, int]] = [
        (row[0], row[1], int(row[2])) for row in key_rows
    ]
    key_set = {(lp, ls) for (lp, ls, _) in cluster_keys}

    # Single batch query for every row in any of the paginated clusters.
    # We expand to OR-of-tuples because SQLAlchemy text() can't bind a
    # variable-arity tuple-IN cleanly across dialects without a custom
    # expanding bindparam — and the cluster page is capped at `limit`
    # (<= 200) so the WHERE list stays bounded.
    pair_conditions: list[str] = []
    pair_binds: dict[str, Any] = {}
    for idx, (lp, ls) in enumerate(key_set):
        lp_key = f"lp_{idx}"
        ls_key = f"ls_{idx}"
        pair_conditions.append(
            f"(LOWER(product) = :{lp_key} AND LOWER(symptom) = :{ls_key})"
        )
        pair_binds[lp_key] = lp
        pair_binds[ls_key] = ls

    rows_stmt = (
        select(KnownProblem)
        .where(text(" OR ".join(pair_conditions)).bindparams(**pair_binds))
        .order_by(KnownProblem.created_at.asc(), KnownProblem.id.asc())
    )
    rows = (await db.execute(rows_stmt)).scalars().all()

    # Group the fetched rows back into their clusters in the order the
    # `keys_stmt` returned them — that order is the response order and
    # must not be re-shuffled by the OR-list query's result ordering.
    grouped: dict[tuple[str, str], list[KnownProblem]] = {}
    for kp in rows:
        key = ((kp.product or "").lower(), (kp.symptom or "").lower())
        if key in key_set:
            grouped.setdefault(key, []).append(kp)

    clusters: list[DuplicateCluster] = []
    for lp, ls, _expected_size in cluster_keys:
        members = grouped.get((lp, ls), [])
        if not members:
            # Cluster vanished between the count and row fetch (race in
            # a concurrent delete). Skip it rather than emit a zero-row
            # cluster — `total` is already a best-effort snapshot.
            continue
        # Echo the case-preserved text from the first (oldest) member.
        first = members[0]
        clusters.append(
            DuplicateCluster(
                product=first.product,
                symptom=first.symptom,
                size=len(members),
                entries=[KnownProblemResponse.from_orm_row(kp) for kp in members],
            )
        )

    return DuplicatesResponse(total=total, clusters=clusters)


@router.get(
    "/conflicts",
    response_model=ConflictsResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Find clusters that share product+symptom but disagree on fix",
)
async def known_problem_conflicts(
    product: Optional[str] = Query(
        None, max_length=120,
        description=(
            "Optional exact product filter (case-insensitive, whitespace "
            "stripped). When set, only conflict clusters whose normalised "
            "product matches are returned — useful for triaging contradictory "
            "guidance one vendor at a time. Omit to scan the whole library."
        ),
    ),
    min_group_size: int = Query(
        2, ge=2, le=100,
        description=(
            "Minimum number of rows a cluster must contain to surface. "
            "Defaults to 2 — the textbook 'two writers disagreed' case. "
            "Raise it when the library has accumulated low-impact conflicts "
            "and the operator wants to focus on the highest-stakes ones first."
        ),
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Data-quality report: find groups of Know-How rows that share an
    identical (product, symptom) pair after case-folding AND carry two
    or more distinct `fix` texts. A strict subset of /duplicates that
    surfaces the worst kind of knowledge-base rot — two operators wrote
    contradictory remedies for the same problem, so a future reader gets
    different advice depending on which row they happen to land on.

    Why this exists alongside /duplicates:
      • /duplicates answers "which rows are redundant" — including the
        common harmless case where two writers independently wrote the
        same diagnosis and the same fix and just need to be merged.
      • /conflicts answers "which redundant rows are *also* inconsistent"
        — the active liability subset. A cluster that's pure dupes
        is annoying; a cluster that's also contradictory is wrong, and
        every minute it stays in the library is a minute the suggest
        endpoint can serve the wrong fix to a ticket.

    Fix normalisation: matches collapse to `TRIM(LOWER(fix))` so a
    trailing newline or a capitalised first word doesn't manufacture a
    false conflict between two rows that say the same thing. Two fix
    strings that differ only in whitespace or case do not count as
    distinct. Two strings that differ in punctuation or wording (the
    interesting case) do.

    Cluster ordering: by `distinct_fix_count` DESC (the worst
    contradictions surface first — three competing fixes for one symptom
    is a bigger fire than two), then size DESC (more readers exposed to
    the conflict ranks higher), then lowercased product and symptom ASC
    for stable pagination on ties. Within a cluster, entries are ordered
    by `created_at` ASC then `id` ASC — the oldest row first, matching
    /duplicates so the operator's "keep the original" muscle memory
    transfers between the two endpoints.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick the other aggregation endpoints upstairs use.
    """
    # Optional product filter — same case-insensitive, whitespace-stripped
    # contract /duplicates uses, so the two endpoints behave identically
    # when callers drill down to one vendor at a time.
    product_filter = (product or "").strip() if product is not None else None
    where_clauses: list[str] = []
    binds: dict[str, Any] = {"min_group_size": min_group_size}
    if product_filter:
        where_clauses.append("LOWER(product) = :product_norm")
        binds["product_norm"] = product_filter.lower()
    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # The HAVING clause does the heavy lifting: rows must share a
    # (lower product, lower symptom) key, hit the size floor, AND carry
    # two or more distinct fix texts after TRIM+LOWER. The DISTINCT count
    # is the conflict signal — count(*) >= 2 alone would surface pure
    # duplicates, which is /duplicates' job, not this one.
    having_sql = (
        "HAVING count(*) >= :min_group_size "
        "AND count(DISTINCT TRIM(LOWER(fix))) >= 2"
    )

    count_stmt = text(
        f"""
        SELECT count(*) FROM (
            SELECT 1 FROM known_problems
            {where_sql}
            GROUP BY LOWER(product), LOWER(symptom)
            {having_sql}
        ) g
        """
    ).bindparams(**binds)
    total_row = await db.execute(count_stmt)
    total = int(total_row.scalar() or 0)

    # Paginated cluster keys. The keys query also projects the distinct
    # fix count so the response envelope can echo it without a third
    # aggregate pass. Ordering rule documented in the docstring: worst
    # contradictions (most distinct fixes) first, then biggest, then
    # alphabetical for stable pagination on ties.
    keys_stmt = text(
        f"""
        SELECT
            LOWER(product) AS lp,
            LOWER(symptom) AS ls,
            count(*) AS cnt,
            count(DISTINCT TRIM(LOWER(fix))) AS distinct_fixes
        FROM known_problems
        {where_sql}
        GROUP BY LOWER(product), LOWER(symptom)
        {having_sql}
        ORDER BY
            count(DISTINCT TRIM(LOWER(fix))) DESC,
            count(*) DESC,
            LOWER(product) ASC,
            LOWER(symptom) ASC
        LIMIT :limit OFFSET :offset
        """
    ).bindparams(**binds, limit=limit, offset=offset)
    key_rows = (await db.execute(keys_stmt)).all()

    if not key_rows:
        return ConflictsResponse(total=total, clusters=[])

    # Stable lookup so we can both restrict the row fetch to just the
    # paginated keys AND group the fetched rows back into their cluster
    # in the response order — same pattern /duplicates uses.
    cluster_keys: list[tuple[str, str, int, int]] = [
        (row[0], row[1], int(row[2]), int(row[3])) for row in key_rows
    ]
    key_set = {(lp, ls) for (lp, ls, _, _) in cluster_keys}

    # Batch row fetch via OR-of-tuples — same shape /duplicates uses,
    # bounded by `limit` (<= 200) so the WHERE list stays manageable.
    pair_conditions: list[str] = []
    pair_binds: dict[str, Any] = {}
    for idx, (lp, ls) in enumerate(key_set):
        lp_key = f"lp_{idx}"
        ls_key = f"ls_{idx}"
        pair_conditions.append(
            f"(LOWER(product) = :{lp_key} AND LOWER(symptom) = :{ls_key})"
        )
        pair_binds[lp_key] = lp
        pair_binds[ls_key] = ls

    rows_stmt = (
        select(KnownProblem)
        .where(text(" OR ".join(pair_conditions)).bindparams(**pair_binds))
        .order_by(KnownProblem.created_at.asc(), KnownProblem.id.asc())
    )
    rows = (await db.execute(rows_stmt)).scalars().all()

    # Regroup the fetched rows in the order keys_stmt returned them —
    # the OR-list query's result ordering must not reshuffle the cluster
    # sequence. Identical pattern to /duplicates.
    grouped: dict[tuple[str, str], list[KnownProblem]] = {}
    for kp in rows:
        key = ((kp.product or "").lower(), (kp.symptom or "").lower())
        if key in key_set:
            grouped.setdefault(key, []).append(kp)

    clusters: list[ConflictCluster] = []
    for lp, ls, _expected_size, distinct_fixes in cluster_keys:
        members = grouped.get((lp, ls), [])
        if not members:
            # Concurrent-delete race: the keys query saw the cluster, but
            # the row fetch found no members. Skip rather than emit an
            # empty cluster that fails schema validation downstream.
            # `total` is already a best-effort snapshot, same as /duplicates.
            continue
        first = members[0]
        clusters.append(
            ConflictCluster(
                product=first.product,
                symptom=first.symptom,
                size=len(members),
                distinct_fix_count=distinct_fixes,
                entries=[KnownProblemResponse.from_orm_row(kp) for kp in members],
            )
        )

    return ConflictsResponse(total=total, clusters=clusters)


@router.get(
    "/stale",
    response_model=StaleResponse,
    dependencies=[Depends(verify_api_key)],
    summary="List entries not updated in the last N days",
)
async def known_problem_stale(
    days: int = Query(
        90, ge=1, le=3650,
        description=(
            "Freshness threshold in whole days. Rows whose `updated_at` "
            "is strictly older than `now - days` are returned. Defaults "
            "to 90 — a quarter is long enough that an entry not touched "
            "in that window probably needs a re-read against the vendor's "
            "current docs. Range is 1–3650 (1 day – 10 years), so a "
            "caller can audit anything from 'yesterday's edits onwards' "
            "to 'rows older than a decade' without having to roll a "
            "second query."
        ),
    ),
    product: Optional[str] = Query(
        None, max_length=120,
        description=(
            "Optional exact product filter (case-insensitive, whitespace "
            "stripped). When set, only stale entries whose product "
            "matches are returned — useful for re-validating one vendor's "
            "playbook after a major product change. Omit to scan the "
            "whole library."
        ),
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Data-quality report: surface Know-How entries that haven't been
    touched in the last `days` days, so a curator can sweep through and
    either re-validate or retire them. Rounds out the data-quality
    triad alongside /orphans (incomplete entries) and /duplicates
    (redundant entries) — /stale flags the third failure mode:
    *content that may have silently rotted as the vendor's product
    moved on*.

    The threshold is applied to `updated_at` rather than `created_at`
    on purpose: an entry that was edited last week to fix a typo is
    "fresh" by curation standards even if its first version was written
    years ago. PATCH and PUT both bump `updated_at` via the model's
    `onupdate=func.now()`, so a deliberate "I re-read this and it's
    still right" no-op edit is enough to drop a row off the stale list
    without having to invent a new "reviewed_at" column.

    `days_since_update` is computed server-side in whole days from
    `now - updated_at`, floored. The wall-clock `now` is captured once
    per request so two rows in the same response share the same
    reference point — without that, a row updated 10 seconds before
    the cutoff and a row updated 10 seconds after the cutoff could
    legitimately disagree about whether "today" is day N or day N+1.

    Ordering: `updated_at` ASC so the oldest (most stale) rows surface
    first — that's the order an operator wants for the
    highest-leverage "re-read this" worklist. Tie-break on id ASC for
    deterministic pagination when two rows share an `updated_at`
    (created in the same bulk-upsert all share `func.now()`).

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick the other aggregation endpoints use.
    """
    # Capture `now` once so the count query and the row query both
    # apply the exact same cutoff — otherwise a row whose `updated_at`
    # equals `now - days` at sub-second precision could appear in one
    # query and not the other across a slow execution.
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    where_clauses = [KnownProblem.updated_at < cutoff]
    product_filter = (product or "").strip() if product is not None else None
    if product_filter:
        where_clauses.append(func.lower(KnownProblem.product) == product_filter.lower())

    count_stmt = select(func.count()).select_from(KnownProblem).where(*where_clauses)
    total = int((await db.execute(count_stmt)).scalar() or 0)

    row_stmt = (
        select(KnownProblem)
        .where(*where_clauses)
        .order_by(KnownProblem.updated_at.asc(), KnownProblem.id.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(row_stmt)).scalars().all()

    entries: List[StaleEntry] = []
    for kp in rows:
        # Floor to whole days. `updated_at` is tz-aware (server default
        # `func.now()` returns timestamptz) so this subtraction is safe
        # even if Postgres and the API container disagree on local time.
        delta = now - kp.updated_at
        entries.append(
            StaleEntry(
                problem=KnownProblemResponse.from_orm_row(kp),
                days_since_update=max(0, delta.days),
            )
        )
    return StaleResponse(total=total, entries=entries)


@router.get(
    "/recent",
    response_model=RecentResponse,
    dependencies=[Depends(verify_api_key)],
    summary="List entries created within the last N days",
)
async def known_problem_recent(
    days: int = Query(
        30, ge=1, le=3650,
        description=(
            "Lookback window in whole days. Rows whose `created_at` is "
            "on-or-after `now - days` are returned. Defaults to 30 — "
            "the natural 'what's been added this month' review window. "
            "Range is 1–3650 (1 day – 10 years) so a caller can scope "
            "anything from 'today's adds only' to 'every entry ever "
            "ingested' without rolling a second query."
        ),
    ),
    product: Optional[str] = Query(
        None, max_length=120,
        description=(
            "Optional exact product filter (case-insensitive, whitespace "
            "stripped). When set, only fresh entries whose product matches "
            "are returned — useful for spot-checking what's been added "
            "for one vendor after a curation push. Omit to scan the whole "
            "library."
        ),
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Surface Know-How entries that were *added* within the last `days`
    days, so a curator can review fresh contributions. The natural
    counterpart to `/stale`: stale flags `updated_at < now-N` (rotted
    content); `/recent` flags `created_at >= now-N` (new content). The
    two answer different curator questions and intentionally target
    different timestamp columns — an entry edited yesterday is "fresh
    by curation standards" to /stale but only counts as "new" to
    /recent if it was *first written* recently.

    `days_since_created` is computed server-side in whole days from
    `now - created_at`, floored, and clamped to zero so clock skew
    (replica drift, tests that mock time) can't surface negative "added
    -3 days ago" rows in the admin UI. The wall-clock `now` is captured
    once per request so the count query and the row query both apply
    the exact same cutoff — same trick `/stale` uses upstairs and for
    the same reason (a row whose `created_at` straddles the sub-second
    boundary would otherwise be able to appear in one query and not
    the other).

    Ordering: `created_at` DESC so the newest additions surface first —
    that's the order a curator wants for "what's just been added"
    review. Tie-break on `id` ASC for deterministic pagination when two
    rows share a `created_at` (a bulk-upsert assigns the same
    `func.now()` to every inserted row).

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick /stale and every other aggregation endpoint
    upstairs use.
    """
    # Capture `now` once so the count query and the row query both
    # apply the exact same cutoff — same race defence `/stale` uses.
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    where_clauses = [KnownProblem.created_at >= cutoff]
    product_filter = (product or "").strip() if product is not None else None
    if product_filter:
        where_clauses.append(func.lower(KnownProblem.product) == product_filter.lower())

    count_stmt = select(func.count()).select_from(KnownProblem).where(*where_clauses)
    total = int((await db.execute(count_stmt)).scalar() or 0)

    row_stmt = (
        select(KnownProblem)
        .where(*where_clauses)
        .order_by(KnownProblem.created_at.desc(), KnownProblem.id.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(row_stmt)).scalars().all()

    entries: List[RecentEntry] = []
    for kp in rows:
        # Floor to whole days. `created_at` is tz-aware (server default
        # `func.now()` returns timestamptz) so this subtraction is safe
        # even if Postgres and the API container disagree on local time.
        # Clamp to zero so a row whose `created_at` is in the future
        # (NTP drift, mocked time in fixtures) doesn't surface as a
        # negative age — same defence /stale applies to its
        # `days_since_update`.
        delta = now - kp.created_at
        entries.append(
            RecentEntry(
                problem=KnownProblemResponse.from_orm_row(kp),
                days_since_created=max(0, delta.days),
            )
        )
    return RecentResponse(total=total, entries=entries)


@router.get(
    "/timeline",
    response_model=List[TimelineBucket],
    dependencies=[Depends(verify_api_key)],
    summary="Time-bucketed entry-creation counts for dashboard charts",
)
async def known_problem_timeline(
    days: int = Query(
        30, ge=1, le=3650,
        description=(
            "Lookback window in whole days. Only entries whose "
            "`created_at` is on-or-after `now - days` are bucketed. "
            "Defaults to 30 — the same 'what's been added this month' "
            "window /recent uses, so the dashboard's chart and the "
            "admin's 'recent additions' list agree on the same horizon. "
            "Range is 1–3650 (1 day – 10 years) so a caller can plot "
            "anything from a one-day pulse to the library's entire "
            "history without rolling a second query."
        ),
    ),
    bucket: str = Query(
        "day",
        description=(
            "Bucket granularity — one of `day`, `week`, or `month`. "
            "Forwarded directly to Postgres' `date_trunc` so `week` "
            "anchors on Monday (ISO convention) and `month` on the "
            "first of the month, both in UTC. Defaults to `day` for "
            "the highest-resolution chart; widen to `week` or `month` "
            "when a 10-year `days` window would otherwise return "
            "thousands of buckets and choke the renderer."
        ),
    ),
    product: Optional[str] = Query(
        None, max_length=120,
        description=(
            "Optional exact product filter (case-insensitive, whitespace "
            "stripped). When set, only entries for this product are "
            "bucketed — useful for plotting per-product growth on the "
            "admin coverage dashboard. Omit to chart the whole library."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return a time-series of created-entry counts so a dashboard can plot
    how the Know-How Library has grown over the window. The natural
    quantitative counterpart to `/recent` (which lists the rows
    themselves): `/recent` answers "what's new?" with rows; `/timeline`
    answers "how much, how often?" with counts per bucket — same
    `created_at >= now-days` cutoff so the two endpoints agree on the
    same horizon. `/activity` is the third axis: audit events across
    every mutation kind, not just creates.

    Only buckets that saw at least one create are returned, in
    chronological order (`bucket_start` asc) — the natural left-to-right
    order for a time-series chart. Empty intervals between two
    non-empty buckets are *not* zero-padded; a dense X-axis is the
    renderer's job (it already knows the scale). Pinning that on the
    client keeps the SQL to one round-trip and the response payload
    tight on a sparse-but-deep window (e.g. `days=3650, bucket=month`
    on a young library would otherwise return 120 mostly-empty rows).

    Bucket granularity is forwarded verbatim to Postgres' `date_trunc`
    so `week` anchors on Monday (ISO convention) and `month` on the
    first of the month, both in UTC — `created_at` is stored as
    timestamptz, and the truncation happens in the DB's timezone (UTC
    in production), so the same row always lands in the same bucket
    regardless of the caller's TZ. Validated server-side rather than
    via a Pydantic enum because we want a JSON 422 with a readable
    `detail` message ("bucket must be one of day, week, month; got
    'fortnight'") rather than FastAPI's stock regex error — easier for
    the admin UI to surface in the chart panel's error toast.

    The `now` cutoff is captured once per request so a row created at
    the exact second the request runs can't slip into one bucket query
    and not another (same race defence `/recent` and `/stale` use).
    Product filter follows the same case-insensitive lower() match the
    rest of the file uses so `?product=Microsoft 365` and
    `?product=microsoft 365` agree.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick /stale, /recent, and every other aggregation
    endpoint upstairs use.
    """
    bucket_kind = (bucket or "").strip().lower()
    if bucket_kind not in {"day", "week", "month"}:
        raise HTTPException(
            status_code=422,
            detail=(
                f"bucket must be one of day, week, month; got {bucket!r}"
            ),
        )

    # Capture `now` once so any subsequent count query sees the same
    # cutoff — same race defence /recent and /stale use upstairs.
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    where_clauses = [KnownProblem.created_at >= cutoff]
    product_filter = (product or "").strip() if product is not None else None
    if product_filter:
        where_clauses.append(
            func.lower(KnownProblem.product) == product_filter.lower()
        )

    # `date_trunc` is an immutable, index-friendly bucketer Postgres
    # ships natively. We GROUP BY the trunc expression rather than a
    # CTE/window because the result set is small (≤ `days` rows for
    # `bucket=day`, fewer for week/month) and a single GROUP BY beats
    # the planner's other options every time.
    bucket_expr = func.date_trunc(bucket_kind, KnownProblem.created_at)

    stmt = (
        select(bucket_expr.label("bucket_start"), func.count().label("cnt"))
        .where(*where_clauses)
        .group_by(bucket_expr)
        .order_by(bucket_expr.asc())
    )

    result = await db.execute(stmt)
    buckets: List[TimelineBucket] = []
    for row in result.all():
        raw = row[0]
        if raw is None:
            # `func.now()` skew or a NULL `created_at` somehow — drop
            # rather than surface a bucket with no start date.
            continue
        # Postgres returns `date_trunc` as a timestamptz; pull the
        # calendar date so the response is a clean ISO `YYYY-MM-DD`
        # rather than a `…T00:00:00+00:00` string the chart would have
        # to trim. `hasattr` guard so a mock that hands us a bare
        # `date` in tests still works.
        bucket_date = raw.date() if hasattr(raw, "date") else raw
        buckets.append(TimelineBucket(bucket_start=bucket_date, count=int(row[1])))
    return buckets


@router.get(
    "/tags/timeline",
    response_model=List[TimelineBucket],
    dependencies=[Depends(verify_api_key)],
    summary="Time-bucketed creation counts for entries carrying a focal tag",
)
async def known_problem_tags_timeline(
    tag: str = Query(
        ...,
        min_length=1,
        max_length=120,
        description=(
            "Focal tag. Only entries whose `tags` array contains this tag "
            "are bucketed. Matched case-insensitively against the canonical "
            "lowercase form stored on disk — same rule the list endpoint's "
            "`?tag=` filter and `/tags/cooccurrence` use — so `?tag=Auth` "
            "and `?tag=auth` resolve to the same focal tag."
        ),
    ),
    days: int = Query(
        30, ge=1, le=3650,
        description=(
            "Lookback window in whole days. Only entries whose `created_at` "
            "is on-or-after `now - days` are bucketed. Defaults to 30 — the "
            "same horizon `/timeline` and `/recent` use, so the dashboard's "
            "per-tag chart agrees with the library-wide chart on the same "
            "X-axis. Range is 1–3650 (1 day – 10 years)."
        ),
    ),
    bucket: str = Query(
        "day",
        description=(
            "Bucket granularity — one of `day`, `week`, or `month`. "
            "Forwarded directly to Postgres' `date_trunc` so `week` "
            "anchors on Monday (ISO convention) and `month` on the first "
            "of the month, both in UTC. Defaults to `day` for the "
            "highest-resolution chart; widen to `week`/`month` for long "
            "windows where day-resolution would choke the renderer."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return a time-series of created-entry counts, filtered to entries
    that carry the focal `tag`. The natural per-tag specialisation of
    `/timeline`: the library-wide endpoint answers "how fast is the
    library growing?"; this one answers "how fast is the `auth` body
    of knowledge growing?" — so the admin coverage dashboard can plot
    one series per tag of interest without re-fetching `/timeline` and
    filtering client-side over rows it never received.

    Mirrors `/timeline` in shape (same `TimelineBucket` response model,
    same `days`/`bucket` semantics, same `created_at` cutoff, same
    skip-empty-bucket rule) and `/tags/cooccurrence` in tag-matching
    contract (lowercased focal, `tags @> jsonb_build_array(:focal)`
    containment via the GIN index on `tags`). The reuse is deliberate:
    a dashboard that already renders `/timeline` data can re-render
    this endpoint's payload through the same chart component with
    zero adaptation, and an admin who already understands "tags are
    matched case-insensitively against the lowercase form" doesn't
    re-learn the rule for a new endpoint.

    Only buckets that saw at least one matching create are returned,
    in chronological order (`bucket_start` asc). Empty intervals are
    not zero-padded — the renderer's job (it already owns the X-axis
    scale). For a tag that has zero matching entries inside the window
    (newly-coined tag, retired tag, typo from the caller) the response
    is `[]` rather than a 404; the chart panel should fail soft ("no
    activity for this tag in the window") rather than hard.

    A whitespace-only `tag` (slipped past the `min_length=1` validator
    because it counts raw characters) short-circuits to `[]` without
    a DB round-trip — same fail-soft rule `/tags/cooccurrence` applies
    for the same reason. Bucket kind is validated server-side rather
    than via a Pydantic enum so the admin UI gets a readable
    `detail` ("bucket must be one of day, week, month; got
    'fortnight'") instead of FastAPI's stock regex error.

    The `now` cutoff is captured once per request so a row created at
    the exact second the request runs can't slip into one bucket
    query and not another (same race defence `/timeline`, `/recent`,
    and `/stale` use). The tag-containment predicate uses the GIN
    index on `tags` (jsonb_path_ops) so the row-set is narrowed
    cheaply before the `GROUP BY` runs over the surviving rows.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick /tags, /tags/cooccurrence, /timeline, and every
    other aggregation endpoint upstairs use.
    """
    bucket_kind = (bucket or "").strip().lower()
    if bucket_kind not in {"day", "week", "month"}:
        raise HTTPException(
            status_code=422,
            detail=(
                f"bucket must be one of day, week, month; got {bucket!r}"
            ),
        )

    # Tag-fold mirrors /tags/cooccurrence: tags are stored lowercase
    # (the `_normalize_tags` rule canonicalises on the way in), so a
    # `?tag=Auth` query has to lowercase to hit the row. A whitespace-
    # only focal slipped past the min_length=1 validator (which counts
    # raw characters), so short-circuit without a DB round-trip — the
    # GIN-backed `tags @> '[""]'` predicate would otherwise scan for
    # an impossible value.
    focal = tag.strip().lower()
    if not focal:
        return []

    # Capture `now` once so the cutoff matches across the request —
    # same race defence /timeline and /recent use upstairs.
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    # Raw text() SQL mirrors /tags/cooccurrence rather than the
    # SQLAlchemy-Core path /timeline uses. Two reasons:
    #   1. The `tags @> jsonb_build_array(:focal)` predicate is the
    #      same GIN-backed containment /tags/cooccurrence relies on —
    #      keeping the SQL textually identical means a future index
    #      tweak (e.g. switching from jsonb_path_ops to a partial
    #      index on `tags`) lands in both endpoints with a single
    #      change to the comment block one floor up.
    #   2. SQLAlchemy's literal-binds compiler can't render JSONB
    #      values, so a Core-style `tags.op("@>")(func.cast([...]))`
    #      makes the compiled SQL un-inspectable by unit tests. The
    #      `text()` shape keeps `stmt.compile().params` introspectable
    #      — same idiom every other tag-containment endpoint upstairs
    #      uses for the same reason.
    # `date_trunc` is parameterised via a bind so the same prepared
    # statement caches across bucket kinds (planner can reuse one plan
    # for day/week/month instead of compiling three).
    stmt = text(
        """
        SELECT date_trunc(:bucket_kind, kp.created_at) AS bucket_start,
               count(*) AS cnt
        FROM known_problems kp
        WHERE kp.created_at >= :cutoff
          AND kp.tags @> jsonb_build_array(:focal)
        GROUP BY date_trunc(:bucket_kind, kp.created_at)
        ORDER BY date_trunc(:bucket_kind, kp.created_at) ASC
        """
    ).bindparams(bucket_kind=bucket_kind, cutoff=cutoff, focal=focal)

    result = await db.execute(stmt)
    buckets: List[TimelineBucket] = []
    for row in result.all():
        raw = row[0]
        if raw is None:
            # NULL `bucket_start` (NTP-skew edge case, or a row whose
            # `created_at` was NULLed out of band) — drop rather than
            # surface a bucket with no start date. Same defence
            # /timeline applies for the same reason.
            continue
        # Postgres returns `date_trunc` as a timestamptz; pull the
        # calendar date so the response is a clean ISO `YYYY-MM-DD`
        # rather than a `…T00:00:00+00:00` string the chart would
        # otherwise have to trim. `hasattr` guard so a mock that
        # hands us a bare `date` in tests still works — same path
        # /timeline takes for the same reason.
        bucket_date = raw.date() if hasattr(raw, "date") else raw
        buckets.append(TimelineBucket(bucket_start=bucket_date, count=int(row[1])))
    return buckets


@router.get(
    "/templates/timeline",
    response_model=List[TimelineBucket],
    dependencies=[Depends(verify_api_key)],
    summary="Time-bucketed creation counts for entries carrying a focal template",
)
async def known_problem_templates_timeline(
    template: str = Query(
        ...,
        min_length=1,
        max_length=120,
        description=(
            "Focal ticket template. Only entries whose "
            "`related_ticket_templates` array contains this template "
            "are bucketed. Matched case-insensitively against the "
            "value stored on disk — same rule "
            "`/templates/cooccurrence`, `/templates/autocomplete`, and "
            "`/templates/rename` use — so `?template=TMPL-MFA-Reset` "
            "and `?template=tmpl-mfa-reset` resolve to the same focal "
            "template even though both are stored case-preserved."
        ),
    ),
    days: int = Query(
        30, ge=1, le=3650,
        description=(
            "Lookback window in whole days. Only entries whose "
            "`created_at` is on-or-after `now - days` are bucketed. "
            "Defaults to 30 — the same horizon `/timeline`, `/recent`, "
            "and `/tags/timeline` use, so the dashboard's per-template "
            "chart agrees with the library-wide chart on the same "
            "X-axis. Range is 1–3650 (1 day – 10 years)."
        ),
    ),
    bucket: str = Query(
        "day",
        description=(
            "Bucket granularity — one of `day`, `week`, or `month`. "
            "Forwarded directly to Postgres' `date_trunc` so `week` "
            "anchors on Monday (ISO convention) and `month` on the first "
            "of the month, both in UTC. Defaults to `day` for the "
            "highest-resolution chart; widen to `week`/`month` for long "
            "windows where day-resolution would choke the renderer."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return a time-series of created-entry counts, filtered to entries
    that carry the focal `template` in their `related_ticket_templates`
    array. The natural per-template specialisation of `/timeline` and
    the structural mirror of `/tags/timeline`: `/timeline` answers
    "how fast is the library growing?"; `/tags/timeline` answers "how
    fast is the `auth` body of knowledge growing?"; this one answers
    "how fast is the runbook coverage for `tmpl-mfa-reset` growing?" —
    so the admin coverage dashboard can plot one series per template
    of interest without re-fetching `/timeline` and filtering
    client-side over rows it never received.

    Mirrors `/tags/timeline` in shape (same `TimelineBucket` response
    model, same `days`/`bucket` semantics, same `created_at` cutoff,
    same skip-empty-bucket rule) and `/templates/cooccurrence` in
    template-matching contract — but with one key contract difference
    from `/tags/timeline`: templates are stored **case-preserved**
    (there is no `_normalize_*` lowercase fold on the way in — see
    `/templates/autocomplete` for the same reasoning), so the focal is
    matched case-insensitively via an `EXISTS(... lower(t.template) =
    lower(:focal))` subquery rather than the GIN-backed `@>`
    containment that `/tags/timeline` can use. The cost is a small
    sequential scan over the unnested templates inside each candidate
    row; in practice the library is small enough that the cost is
    invisible, and the same lookup shape `/templates/cooccurrence`
    relies on means a future index tweak (e.g. an expression GIN on
    `lower(template)` per element) lands in both endpoints with one
    change.

    Only buckets that saw at least one matching create are returned,
    in chronological order (`bucket_start` asc). Empty intervals are
    not zero-padded — the renderer's job (it already owns the X-axis
    scale). For a template that has zero matching entries inside the
    window (newly-coined template, retired template, typo from the
    caller) the response is `[]` rather than a 404; the chart panel
    should fail soft ("no activity for this template in the window")
    rather than hard.

    A whitespace-only `template` (slipped past the `min_length=1`
    validator because it counts raw characters) short-circuits to `[]`
    without a DB round-trip — same fail-soft rule
    `/templates/cooccurrence` and `/tags/timeline` apply for the same
    reason. Bucket kind is validated server-side rather than via a
    Pydantic enum so the admin UI gets a readable `detail`
    ("bucket must be one of day, week, month; got 'fortnight'")
    instead of FastAPI's stock regex error.

    The `now` cutoff is captured once per request so a row created at
    the exact second the request runs can't slip into one bucket
    query and not another (same race defence `/timeline`,
    `/tags/timeline`, `/recent`, and `/stale` use).

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick `/tags`, `/templates`, `/tags/timeline`,
    `/timeline`, and every other aggregation endpoint upstairs use.
    """
    bucket_kind = (bucket or "").strip().lower()
    if bucket_kind not in {"day", "week", "month"}:
        raise HTTPException(
            status_code=422,
            detail=(
                f"bucket must be one of day, week, month; got {bucket!r}"
            ),
        )

    # Strip-then-short-circuit mirrors the canonicalisation rule the rest
    # of the file applies to template inputs (see /templates/rename,
    # /templates/autocomplete, /templates/cooccurrence): a whitespace-only
    # focal slips past the min_length=1 validator (which counts raw
    # characters), but there is no template stored with surrounding
    # whitespace, so the EXISTS predicate is guaranteed empty — short-
    # circuit without a DB round-trip rather than scan for an impossible
    # value. Crucially we do NOT lowercase here (unlike /tags/timeline) —
    # the lower() fold lives inside the SQL predicate, because templates
    # are case-preserved on disk and the EXISTS clause does the fold per
    # candidate row.
    focal = template.strip()
    if not focal:
        return []

    # Capture `now` once so the cutoff matches across the request —
    # same race defence /timeline, /tags/timeline, and /recent use.
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    # Raw text() SQL mirrors /templates/cooccurrence rather than the
    # SQLAlchemy-Core path /timeline uses. Two reasons:
    #   1. The EXISTS-with-lower predicate is the same case-insensitive
    #      template match /templates/cooccurrence relies on — keeping
    #      the SQL textually identical means a future index tweak (e.g.
    #      an expression GIN on `lower(template)` per element) lands in
    #      both endpoints with a single change.
    #   2. SQLAlchemy's literal-binds compiler can't render JSONB
    #      lateral references inside EXISTS, so a Core-style expression
    #      would make the compiled SQL un-inspectable by unit tests.
    #      The `text()` shape keeps `stmt.compile().params`
    #      introspectable — same idiom every other template-containment
    #      endpoint upstairs uses for the same reason.
    # `date_trunc` is parameterised via a bind so the same prepared
    # statement caches across bucket kinds (planner can reuse one plan
    # for day/week/month instead of compiling three).
    stmt = text(
        """
        SELECT date_trunc(:bucket_kind, kp.created_at) AS bucket_start,
               count(*) AS cnt
        FROM known_problems kp
        WHERE kp.created_at >= :cutoff
          AND EXISTS (
              SELECT 1
              FROM jsonb_array_elements_text(kp.related_ticket_templates) AS f(template)
              WHERE lower(f.template) = lower(:focal)
          )
        GROUP BY date_trunc(:bucket_kind, kp.created_at)
        ORDER BY date_trunc(:bucket_kind, kp.created_at) ASC
        """
    ).bindparams(bucket_kind=bucket_kind, cutoff=cutoff, focal=focal)

    result = await db.execute(stmt)
    buckets: List[TimelineBucket] = []
    for row in result.all():
        raw = row[0]
        if raw is None:
            # NULL `bucket_start` (NTP-skew edge case, or a row whose
            # `created_at` was NULLed out of band) — drop rather than
            # surface a bucket with no start date. Same defence
            # /timeline and /tags/timeline apply for the same reason.
            continue
        # Postgres returns `date_trunc` as a timestamptz; pull the
        # calendar date so the response is a clean ISO `YYYY-MM-DD`
        # rather than a `…T00:00:00+00:00` string the chart would
        # otherwise have to trim. `hasattr` guard so a mock that
        # hands us a bare `date` in tests still works — same path
        # /timeline and /tags/timeline take for the same reason.
        bucket_date = raw.date() if hasattr(raw, "date") else raw
        buckets.append(TimelineBucket(bucket_start=bucket_date, count=int(row[1])))
    return buckets


@router.get(
    "/products/timeline",
    response_model=List[TimelineBucket],
    dependencies=[Depends(verify_api_key)],
    summary="Time-bucketed creation counts for entries tied to a focal product",
)
async def known_problem_products_timeline(
    product: str = Query(
        ...,
        min_length=1,
        max_length=120,
        description=(
            "Focal product. Only entries whose `product` scalar matches "
            "this value are bucketed. Matched case-insensitively against "
            "the case-preserved form stored on disk — same rule "
            "`/products/autocomplete` and `/products/rename` use — so "
            "`?product=Microsoft 365` and `?product=microsoft 365` "
            "resolve to the same focal product even though only the "
            "canonical casing is on disk."
        ),
    ),
    days: int = Query(
        30, ge=1, le=3650,
        description=(
            "Lookback window in whole days. Only entries whose "
            "`created_at` is on-or-after `now - days` are bucketed. "
            "Defaults to 30 — the same horizon `/timeline`, `/recent`, "
            "`/tags/timeline`, and `/templates/timeline` use, so the "
            "dashboard's per-product chart agrees with the library-wide "
            "chart on the same X-axis. Range is 1–3650 (1 day – 10 years)."
        ),
    ),
    bucket: str = Query(
        "day",
        description=(
            "Bucket granularity — one of `day`, `week`, or `month`. "
            "Forwarded directly to Postgres' `date_trunc` so `week` "
            "anchors on Monday (ISO convention) and `month` on the first "
            "of the month, both in UTC. Defaults to `day` for the "
            "highest-resolution chart; widen to `week`/`month` for long "
            "windows where day-resolution would choke the renderer."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return a time-series of created-entry counts, filtered to entries
    whose scalar `product` equals the focal value case-insensitively.
    The natural per-product specialisation of `/timeline` and the
    structural mirror of `/tags/timeline` and `/templates/timeline`:
    `/timeline` answers "how fast is the library growing?";
    `/tags/timeline` answers "how fast is the `auth` body of knowledge
    growing?"; `/templates/timeline` answers "how fast is the runbook
    coverage for `tmpl-mfa-reset` growing?"; this one answers "how
    fast is the Microsoft 365 body of knowledge growing?" — so the
    admin coverage dashboard can plot one series per product of interest
    without re-fetching `/timeline` and filtering client-side over rows
    it never received.

    Mirrors `/tags/timeline` and `/templates/timeline` in shape (same
    `TimelineBucket` response model, same `days`/`bucket` semantics,
    same `created_at` cutoff, same skip-empty-bucket rule). The key
    contract difference: `product` is a scalar string column (not a
    JSONB array like `tags` or `related_ticket_templates`), so the
    predicate is a direct `lower(kp.product) = lower(:focal)` equality
    rather than a containment / EXISTS subquery. Product names are
    stored case-preserved (vendor branding matters — "Microsoft 365"
    is canonical, "microsoft 365" is not), so case-insensitivity is
    handled SQL-side by the `lower()` fold on both sides rather than
    a Python-side lowercase at bind time — matches `/products/rename`
    and `/products/merge`.

    Only buckets that saw at least one matching create are returned,
    in chronological order (`bucket_start` asc). Empty intervals are
    not zero-padded — the renderer's job (it already owns the X-axis
    scale). For a product that has zero matching entries inside the
    window (newly-added product, retired product, typo from the caller)
    the response is `[]` rather than a 404; the chart panel should fail
    soft ("no activity for this product in the window") rather than hard.

    A whitespace-only `product` (slipped past the `min_length=1`
    validator because it counts raw characters) short-circuits to `[]`
    without a DB round-trip — same fail-soft rule `/tags/timeline` and
    `/templates/timeline` apply for the same reason. Bucket kind is
    validated server-side rather than via a Pydantic enum so the admin
    UI gets a readable `detail` ("bucket must be one of day, week,
    month; got 'fortnight'") instead of FastAPI's stock regex error.

    The `now` cutoff is captured once per request so a row created at
    the exact second the request runs can't slip into one bucket query
    and not another (same race defence `/timeline`, `/tags/timeline`,
    `/templates/timeline`, `/recent`, and `/stale` use).

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick `/products`, `/products/autocomplete`,
    `/tags/timeline`, `/templates/timeline`, and every other aggregation
    endpoint upstairs use.
    """
    bucket_kind = (bucket or "").strip().lower()
    if bucket_kind not in {"day", "week", "month"}:
        raise HTTPException(
            status_code=422,
            detail=(
                f"bucket must be one of day, week, month; got {bucket!r}"
            ),
        )

    # Strip-then-short-circuit mirrors the canonicalisation rule the
    # rest of the file applies to product inputs (see /products/rename,
    # /products/autocomplete): a whitespace-only focal slips past the
    # min_length=1 validator (which counts raw characters), but there
    # is no product stored as the empty string, so the equality
    # predicate is guaranteed empty — short-circuit without a DB
    # round-trip rather than scan for an impossible value. Crucially
    # we do NOT lowercase here (unlike /tags/timeline) — the lower()
    # fold lives inside the SQL predicate, because products are
    # case-preserved on disk and the equality clause does the fold per
    # candidate row (same idiom /products/rename and /products/merge
    # use for the same reason).
    focal = product.strip()
    if not focal:
        return []

    # Capture `now` once so the cutoff matches across the request —
    # same race defence /timeline, /tags/timeline, /templates/timeline,
    # and /recent use.
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    # Raw text() SQL mirrors /tags/timeline and /templates/timeline
    # rather than the SQLAlchemy-Core path /timeline uses, so future
    # index tweaks (e.g. a functional index on `lower(product)`) land
    # in all per-axis timeline endpoints with one consistent shape.
    # `date_trunc` is parameterised via a bind so the same prepared
    # statement caches across bucket kinds (planner can reuse one plan
    # for day/week/month instead of compiling three).
    stmt = text(
        """
        SELECT date_trunc(:bucket_kind, kp.created_at) AS bucket_start,
               count(*) AS cnt
        FROM known_problems kp
        WHERE kp.created_at >= :cutoff
          AND lower(kp.product) = lower(:focal)
        GROUP BY date_trunc(:bucket_kind, kp.created_at)
        ORDER BY date_trunc(:bucket_kind, kp.created_at) ASC
        """
    ).bindparams(bucket_kind=bucket_kind, cutoff=cutoff, focal=focal)

    result = await db.execute(stmt)
    buckets: List[TimelineBucket] = []
    for row in result.all():
        raw = row[0]
        if raw is None:
            # NULL `bucket_start` (NTP-skew edge case, or a row whose
            # `created_at` was NULLed out of band) — drop rather than
            # surface a bucket with no start date. Same defence
            # /timeline, /tags/timeline, and /templates/timeline apply
            # for the same reason.
            continue
        # Postgres returns `date_trunc` as a timestamptz; pull the
        # calendar date so the response is a clean ISO `YYYY-MM-DD`
        # rather than a `…T00:00:00+00:00` string the chart would
        # otherwise have to trim. `hasattr` guard so a mock that
        # hands us a bare `date` in tests still works — same path
        # /timeline, /tags/timeline, and /templates/timeline take.
        bucket_date = raw.date() if hasattr(raw, "date") else raw
        buckets.append(TimelineBucket(bucket_start=bucket_date, count=int(row[1])))
    return buckets


@router.post(
    "/products/rename",
    response_model=ProductRenameResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Rename a product across the Know-How Library",
)
async def rename_known_problem_product(
    req: ProductRenameRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk-rename one product label across every entry that uses it. The
    natural counterpart to /tags/rename, but for the scalar `product`
    field. Cleans up vendor-name drift (`M365` → `Microsoft 365`,
    `Office 365` → `Microsoft 365`, mis-cased `microsoft 365` →
    `Microsoft 365`) without re-editing each entry by hand.

    Semantics:
      - both names are trimmed before matching; `from_product` is
        matched case-insensitively (same ILIKE rule the list endpoint's
        `?product=` filter uses), so an operator pasting `m365` still
        hits a row stored as `M365`;
      - `to_product` is written **case-preserved** — there is no
        lowercase fold like /tags/rename, because vendor branding
        matters: `Microsoft 365` is canonical and `microsoft 365` is
        not. This is precisely why the endpoint exists: to canonicalise
        casing in one call;
      - if `from_product` and `to_product` are exactly equal after
        trimming (case included), the request is treated as a no-op —
        no DB scan, no row mutation, but still audited so the attempt
        shows up in /activity;
      - matched rows are rewritten one-by-one in Python (not a single
        bulk UPDATE) so SQLAlchemy fires the model's `onupdate=now()`
        for `updated_at` and the in-memory ORM identity map stays
        consistent — same pattern /tags/rename uses;
      - one summary audit row covers the whole rename (no per-entry
        rows). Per-entry /history won't surface the rename (problem_id
        is null on the summary row, same as /tags/rename and /bulk),
        but /activity will. The id sample is capped at 50 so the audit
        row stays a sensible size even when renaming a product attached
        to every entry in the library.

    Declared above `/{problem_id}` so the literal path wins the FastAPI
    match — same trick `/stats`, `/tags`, `/products`, and their
    autocomplete cousins all use upstairs.
    """
    from_product = (req.from_product or "").strip()
    to_product = (req.to_product or "").strip()
    if not from_product or not to_product:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Both from_product and to_product must be non-empty after "
                "trimming whitespace."
            ),
        )

    if from_product == to_product:
        _audit(
            db,
            event_type="known_problem.product_renamed",
            problem_id=None,
            details={
                "from": from_product,
                "to": to_product,
                "updated": 0,
                "no_op": True,
            },
        )
        await db.commit()
        logger.info(
            "known_problem.product_renamed",
            from_product=from_product,
            to_product=to_product,
            updated=0,
            no_op=True,
        )
        return ProductRenameResponse(
            from_product=from_product,
            to_product=to_product,
            updated_count=0,
        )

    # ILIKE narrows the SELECT to rows actually carrying the source
    # product (case-insensitive). The `product` column has a regular
    # btree index — ILIKE without a leading wildcard can use it on
    # PostgreSQL when paired with the right collation/op_class; in
    # practice the table is small enough (low thousands) that a seq
    # scan is fine either way. Same load-then-mutate pattern as
    # /tags/rename so audit semantics stay symmetric.
    query = select(KnownProblem).where(
        KnownProblem.product.ilike(from_product)
    )
    result = await db.execute(query)
    rows = result.scalars().all()

    updated_ids: List[str] = []
    for kp in rows:
        kp.product = to_product
        updated_ids.append(kp.id)

    _audit(
        db,
        event_type="known_problem.product_renamed",
        problem_id=None,
        details={
            "from": from_product,
            "to": to_product,
            "updated": len(updated_ids),
            # Cap the id list so the audit row stays a sensible size
            # even if every entry uses the renamed product.
            "problem_ids": updated_ids[:50],
        },
    )
    await db.commit()
    logger.info(
        "known_problem.product_renamed",
        from_product=from_product,
        to_product=to_product,
        updated=len(updated_ids),
    )
    return ProductRenameResponse(
        from_product=from_product,
        to_product=to_product,
        updated_count=len(updated_ids),
    )


@router.post(
    "/products/merge",
    response_model=ProductMergeResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Merge several products into a single target product",
)
async def merge_known_problem_products(
    req: ProductMergeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Consolidate N source product names into one canonical target. The
    natural generalisation of /products/rename: rename rewrites one
    source label, merge rewrites a *set* of source labels in a single
    sweep (`M365`, `Office 365`, `microsoft 365` → `Microsoft 365`).
    Saves an admin from running rename N times when retiring vendor-name
    drift after a rebrand or a bulk cleanup pass.

    Semantics:
      - every name is trimmed before matching; sources are matched
        case-insensitively (same ILIKE rule the list endpoint's
        `?product=` filter and /products/rename both use), so an
        operator pasting `m365` still hits a row stored as `M365`;
      - the source list is deduped server-side after case-folding, so
        callers can paste raw operator input (`["M365","m365","M365 "]`)
        without pre-canonicalising — the audit trail records the
        canonical (lowercased, trimmed) source set;
      - any source that collapses to `to_product` after case-fold + trim
        is dropped from the source set — merging X → X is a no-op for
        that label and would only muddy the audit row;
      - `to_product` is written **case-preserved** — same discipline as
        /products/rename, because vendor branding matters and the whole
        point of the endpoint is to canonicalise casing/spelling in one
        call;
      - if every source collapses (e.g. caller asked for [`Microsoft 365`]
        → `Microsoft 365`), the request is a no-op (updated_count=0) —
        still audited so /activity shows the attempt with `no_op=true`;
      - matched rows are rewritten one-by-one in Python (not a single
        bulk UPDATE) so SQLAlchemy fires the model's `onupdate=now()`
        for `updated_at` and the in-memory ORM identity map stays
        consistent — same pattern /products/rename and /tags/rename use;
      - one summary audit row covers the whole merge (no per-entry
        rows), mirroring /products/rename and /tags/merge. `problem_id`
        is null on the summary so per-entry /history won't surface it;
        /activity will. The id sample is capped at 50 so the audit row
        stays a sensible size even when merging a product attached to
        every entry in the library.

    Declared above `/{problem_id}` so the literal path wins the FastAPI
    match — same trick `/stats`, `/tags`, `/products`, `/products/rename`,
    and their autocomplete cousins all use upstairs.
    """
    to_product = (req.to_product or "").strip()
    if not to_product:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="to_product must be non-empty after trimming whitespace.",
        )

    # Canonicalise the source list: trim, drop empties, dedupe on the
    # case-folded form (preserving the first-seen case for the audit
    # trail), then drop any entry that collapses to `to_product` after
    # case-fold + trim — same X→X filter /tags/merge applies.
    to_norm = to_product.lower()
    sources: List[str] = []
    seen_norm: set[str] = set()
    for raw in req.from_products:
        if raw is None:
            continue
        trimmed = raw.strip()
        if not trimmed:
            continue
        norm = trimmed.lower()
        if norm == to_norm:
            continue
        if norm in seen_norm:
            continue
        seen_norm.add(norm)
        sources.append(trimmed)

    if not sources:
        _audit(
            db,
            event_type="known_problem.products_merged",
            problem_id=None,
            details={
                "from": [],
                "to": to_product,
                "updated": 0,
                "no_op": True,
            },
        )
        await db.commit()
        logger.info(
            "known_problem.products_merged",
            from_products=[],
            to_product=to_product,
            updated=0,
            no_op=True,
        )
        return ProductMergeResponse(
            from_products=[], to_product=to_product, updated_count=0
        )

    # Case-insensitive match against any source product. Loads the
    # affected rows so we can rewrite product per-row in Python — same
    # load-then-mutate pattern /products/rename and /tags/rename use,
    # keeping `updated_at` bumps and ORM identity-map state consistent.
    query = select(KnownProblem).where(
        func.lower(KnownProblem.product).in_([n for n in seen_norm])
    )
    result = await db.execute(query)
    rows = result.scalars().all()

    updated_ids: List[str] = []
    for kp in rows:
        kp.product = to_product
        updated_ids.append(kp.id)

    _audit(
        db,
        event_type="known_problem.products_merged",
        problem_id=None,
        details={
            "from": sources,
            "to": to_product,
            "updated": len(updated_ids),
            # Cap the id list so the audit row stays a sensible size
            # even when every entry uses one of the merged products.
            "problem_ids": updated_ids[:50],
        },
    )
    await db.commit()
    logger.info(
        "known_problem.products_merged",
        from_products=sources,
        to_product=to_product,
        updated=len(updated_ids),
    )
    return ProductMergeResponse(
        from_products=sources,
        to_product=to_product,
        updated_count=len(updated_ids),
    )


@router.post(
    "/products/delete",
    response_model=ProductDeleteResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Drop every Know-How entry tied to a retired product",
)
async def delete_known_problem_product(
    req: ProductDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk-delete every Know-How Library entry whose `product` matches the
    given name. The natural counterpart to /products/rename (rewrite one
    label → another) and /products/merge (collapse N labels → one): once
    a vendor is retired entirely — license dropped, hardware EoL,
    platform migration finished — the matching entries should disappear
    from the library, not linger as dead canon.

    The shape deliberately differs from /tags/delete and /templates/delete:
    tags and ticket templates live inside JSONB arrays on each row, so
    scrubbing them drops the label from rows but keeps the rows
    themselves. `product` is a non-nullable scalar column — a Know-How
    entry without a product is not meaningful, so the row goes with the
    label. Callers that want to *re-home* entries to a different product
    (rather than delete them) should use /products/rename or
    /products/merge instead.

    Semantics:
      - the product name is trimmed before matching; the empty case is
        rejected with 422 (an unbounded "drop everything" sweep is never
        what the operator meant — same guard /tags/delete, /templates/delete
        and the rename endpoints all use);
      - matching is **case-insensitive** (ILIKE, same rule the list
        endpoint's `?product=` filter uses), so a paste of `m365` still
        catches rows stored as `M365`. Vendor branding canonicalisation
        is the job of /products/rename — by the time the operator reaches
        for /products/delete they've already decided the product is
        going, casing be damned;
      - rows are deleted one-by-one with `await db.delete(row)` (not a
        bulk DELETE statement) so SQLAlchemy's identity map and any
        future cascade rules behave consistently with single-row DELETE
        — same pattern /bulk-delete uses;
      - if no row carries the product, `deleted_count` is 0 but a
        summary audit row is still written so /activity surfaces the
        attempt (mirrors /tags/delete, /templates/delete, and the rename
        endpoints — the attempt itself is auditable, hit or miss);
      - one summary audit row covers the whole delete (no per-row rows).
        `problem_id` on the summary is null so per-entry /history won't
        surface it; /activity will. The id sample is capped at 50 so the
        audit row stays a sensible size even when retiring a product
        attached to every entry in the library.

    The response echoes the trimmed `product` (not the raw input) so a
    caller logging the response gets the canonical form, same discipline
    /tags/delete and /templates/delete apply.

    Declared above `/{problem_id}` so the literal path wins the FastAPI
    match — same trick /products/rename, /products/merge, /tags/delete,
    /templates/delete, and every other aggregation endpoint upstairs use.
    """
    product = (req.product or "").strip()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="product must be non-empty after trimming whitespace.",
        )

    # ILIKE narrows the SELECT to rows actually carrying the target
    # product (case-insensitive). Same load-then-mutate pattern
    # /products/rename uses so audit semantics stay symmetric — load the
    # rows, snapshot their ids for the audit row, then DELETE.
    query = select(KnownProblem).where(KnownProblem.product.ilike(product))
    result = await db.execute(query)
    rows = result.scalars().all()

    deleted_ids: List[str] = [kp.id for kp in rows]

    _audit(
        db,
        event_type="known_problem.product_deleted",
        problem_id=None,
        details={
            "product": product,
            "deleted": len(deleted_ids),
            # Cap the id list so the audit row stays a sensible size
            # even if every entry in the library used the retired product.
            "problem_ids": deleted_ids[:50],
        },
    )

    for kp in rows:
        await db.delete(kp)
    await db.commit()

    logger.info(
        "known_problem.product_deleted",
        product=product,
        deleted=len(deleted_ids),
    )
    return ProductDeleteResponse(
        product=product,
        deleted_count=len(deleted_ids),
    )


@router.get(
    "/export",
    response_model=KnownProblemExportResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Export the Know-How Library as a seed-compatible JSON snapshot",
)
async def export_known_problems(
    product: Optional[str] = Query(
        None,
        description=(
            "Exact product match (case-insensitive) — same semantics as the "
            "list endpoint's `?product=`. Powers per-product backups (e.g. "
            "export just the Intune subtree before a vendor playbook update)."
        ),
    ),
    tag: Optional[List[str]] = Query(
        None,
        description=(
            "Filter by one or more tags (JSONB containment, ALL required) "
            "— same semantics as the list endpoint's `?tag=`. Repeatable "
            "(`?tag=auth&tag=licensing`). Empty/whitespace tags are dropped "
            "silently so `?tag=` alone is a no-op, not a poison query."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Stream a snapshot of the Know-How Library in the exact JSON shape
    the seed fixture and `/bulk` upsert consume. The whole point is
    *round-tripping*: a caller can `GET /export`, pipe the `entries`
    array into `POST /bulk`, and reproduce the library byte-for-byte
    on a fresh database.

    Use cases:
      - **Backups**: cron a daily export to object storage so the library
        is recoverable independent of the Postgres backup window.
      - **Migration**: lift the canonical knowledge from staging into a
        new production deployment without exposing Postgres directly.
      - **Out-of-band review**: hand the JSON to a SME (legal, vendor
        contact) for content review without giving them DB access.
      - **Version control**: commit periodic exports to a repo so the
        knowledge base has a human-readable diff history alongside the
        `/activity` audit feed.

    The response is an envelope (`version`, `exported_at`, `count`,
    `entries`) rather than a bare array because consumers need a stable
    way to detect format drift. `/bulk` takes the `entries` array
    directly, so the envelope is metadata that travels alongside the
    payload without polluting it.

    Ordering is `product ASC, symptom ASC` — deliberately *not* the
    list endpoint's `created_at DESC`. The export targets diff-friendly
    snapshots (file-on-disk backups, git-committed history), where
    stable, content-derived ordering matters more than recency. Two
    exports of an unchanged library produce identical bytes; an entry
    edit shows up as a localised diff instead of shuffling unrelated
    rows.

    Audit fields (id, created_at, updated_at) are intentionally omitted
    — see `KnownProblemExportEntry` for the rationale. Callers that
    need the audit trail should hit `/activity` instead, which is the
    purpose-built endpoint for that question.

    No pagination: the library is admin-curated and capped on disk by
    the `/bulk` 500-entry batch limit (cumulative over time, but in
    practice this table tops out in the low thousands). A bare `SELECT
    *` ordered scan over an admin-internal table is well within range
    for a snapshot endpoint. Streaming chunked responses can be added
    later without a contract change if growth ever warrants it.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick /stats, /tags, /products, and their autocomplete
    cousins all use upstairs.
    """
    query = select(KnownProblem).order_by(
        KnownProblem.product.asc(),
        KnownProblem.symptom.asc(),
    )
    if product:
        query = query.where(KnownProblem.product.ilike(product))
    if tag:
        wanted = _normalize_tags(tag)
        if wanted:
            query = query.where(
                KnownProblem.tags.op("@>")(func.cast(wanted, JSONB))
            )

    result = await db.execute(query)
    rows = result.scalars().all()
    entries = [KnownProblemExportEntry.from_orm_row(r) for r in rows]
    return KnownProblemExportResponse(
        version="1.0",
        exported_at=datetime.now(timezone.utc).isoformat(),
        count=len(entries),
        entries=entries,
    )


@router.post(
    "/import",
    response_model=KnownProblemImportResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Restore a prior /export snapshot into the Know-How Library",
)
async def import_known_problems(
    req: KnownProblemImportRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Consume a `/export` envelope and replay it through the same
    idempotent upsert pipeline `/bulk` uses. The whole point is
    *round-tripping*: GET `/export` → POST `/import` reproduces the
    library on a fresh database byte-for-byte (modulo audit metadata,
    which is intentionally not part of the export shape).

    Why a dedicated endpoint when `/bulk` already exists:
      - **Version gate**: snapshots carry a `version`. `/bulk` is shape-
        only and would happily accept a future envelope it can't
        actually restore correctly. `/import` validates the version
        first and returns 422 on anything outside
        `_SUPPORTED_IMPORT_VERSIONS`, so a stale operator pipeline
        fails loudly instead of silently mis-restoring;
      - **Integrity check**: when the caller sends `count`, we verify
        it matches `len(entries)` to catch truncated transfers before
        the upsert begins. `/bulk` has no such hook — its contract is
        "you sent N entries, here's what happened to them";
      - **Audit distinction**: `/activity` uses a different event_type
        (`known_problem.imported`) for snapshot restores than for
        operator-curated batches (`known_problem.bulk_upserted`). The
        admin "Recent activity" panel and on-call reviewers can tell
        a backup replay from a hand-edited import at a glance, which
        matters during incident response.

    Idempotency is identical to `/bulk`: keyed on (product, symptom),
    duplicates within the request are rejected with 422. The 500-entry
    cap is enforced by the request schema for the same reason.

    Declared above `/{problem_id}` so the literal path wins the
    FastAPI match — same trick `/stats`, `/tags`, `/products`, and
    `/export` use upstairs.
    """
    if req.version not in _SUPPORTED_IMPORT_VERSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Unsupported export version '{req.version}'. "
                f"Server accepts: {sorted(_SUPPORTED_IMPORT_VERSIONS)}."
            ),
        )

    if req.count is not None and req.count != len(req.entries):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Envelope count ({req.count}) does not match the number "
                f"of entries delivered ({len(req.entries)}). The snapshot "
                "is likely truncated or corrupted; refusing to import."
            ),
        )

    # Dedupe + canonicalise identically to /bulk so the upsert pipeline
    # sees the same SeedEntry shape regardless of which door the data
    # came through.
    seen: set[tuple[str, str]] = set()
    seed_entries: List[SeedEntry] = []
    for idx, item in enumerate(req.entries):
        key = (item.product.strip().lower(), item.symptom.strip().lower())
        if key in seen:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Import entry {idx} duplicates an earlier (product, "
                    "symptom) pair in the same snapshot."
                ),
            )
        seen.add(key)
        seed_entries.append(
            SeedEntry(
                product=item.product.strip(),
                symptom=item.symptom.strip(),
                diagnosis=item.diagnosis.strip(),
                fix=item.fix.strip(),
                related_ticket_templates=[
                    t.strip() for t in item.related_ticket_templates
                ],
                tags=_normalize_tags(item.tags),
            )
        )

    created, updated, unchanged = await seed_known_problems(db, seed_entries)
    _audit(
        db,
        event_type="known_problem.imported",
        problem_id=None,
        details={
            "version": req.version,
            "exported_at": req.exported_at,
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "total": len(seed_entries),
            "products": sorted({e.product for e in seed_entries}),
        },
    )
    await db.commit()
    logger.info(
        "known_problem.imported",
        version=req.version,
        created=created,
        updated=updated,
        unchanged=unchanged,
        total=len(seed_entries),
    )
    return KnownProblemImportResponse(
        version=req.version,
        created=created,
        updated=updated,
        unchanged=unchanged,
        total=len(seed_entries),
    )


@router.post(
    "/tags/rename",
    response_model=TagRenameResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Rename a tag across the Know-How Library",
)
async def rename_known_problem_tag(
    req: TagRenameRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk-rename a tag across every entry that carries it. Cleans up tag
    drift (typos, synonyms, retired labels) without re-editing each entry.

    Semantics:
      - both tags are normalised (lowercase, trimmed) before matching, so
        callers can paste raw operator input without pre-canonicalising;
      - if `from_tag` and `to_tag` collapse to the same canonical form,
        the request is a no-op (updated_count=0) — still audited so the
        attempt is visible in /activity;
      - in each affected row, `from_tag` is replaced by `to_tag` while
        preserving the original tag order; if `to_tag` already exists in
        the row, `from_tag` is dropped (merge semantics — the row keeps
        the first occurrence's position);
      - one summary audit row is written for the whole rename, mirroring
        the bulk-upsert pattern. Per-entry /history won't surface the
        rename (problem_id is null on the summary row, same as bulk),
        but /activity will.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick /stats and /tags and /activity use.
    """
    from_tag = (req.from_tag or "").strip().lower()
    to_tag = (req.to_tag or "").strip().lower()
    if not from_tag or not to_tag:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Both from_tag and to_tag must be non-empty after normalisation.",
        )

    if from_tag == to_tag:
        _audit(
            db,
            event_type="known_problem.tags_renamed",
            problem_id=None,
            details={
                "from": from_tag,
                "to": to_tag,
                "updated": 0,
                "no_op": True,
            },
        )
        await db.commit()
        logger.info(
            "known_problem.tags_renamed",
            from_tag=from_tag,
            to_tag=to_tag,
            updated=0,
            no_op=True,
        )
        return TagRenameResponse(
            from_tag=from_tag, to_tag=to_tag, updated_count=0
        )

    # JSONB containment narrows the SELECT to only rows actually carrying
    # the source tag — no scan-and-skip in Python, and the GIN index on
    # `tags` handles it cheaply.
    query = select(KnownProblem).where(
        KnownProblem.tags.op("@>")(func.cast([from_tag], JSONB))
    )
    result = await db.execute(query)
    rows = result.scalars().all()

    updated_ids: List[str] = []
    for kp in rows:
        new_tags: List[str] = []
        seen: set[str] = set()
        for t in (kp.tags or []):
            replacement = to_tag if t == from_tag else t
            if replacement in seen:
                continue
            seen.add(replacement)
            new_tags.append(replacement)
        kp.tags = new_tags
        updated_ids.append(kp.id)

    _audit(
        db,
        event_type="known_problem.tags_renamed",
        problem_id=None,
        details={
            "from": from_tag,
            "to": to_tag,
            "updated": len(updated_ids),
            # Cap the id list so the audit row stays a sensible size even
            # if someone renames a tag attached to every entry in the lib.
            "problem_ids": updated_ids[:50],
        },
    )
    await db.commit()
    logger.info(
        "known_problem.tags_renamed",
        from_tag=from_tag,
        to_tag=to_tag,
        updated=len(updated_ids),
    )
    return TagRenameResponse(
        from_tag=from_tag, to_tag=to_tag, updated_count=len(updated_ids)
    )


@router.post(
    "/tags/delete",
    response_model=TagDeleteResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Drop a tag from every entry in the Know-How Library",
)
async def delete_known_problem_tag(
    req: TagDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Scrub a tag from every entry that carries it. The natural counterpart
    to /tags/rename: rename rewrites one tag to another, delete drops it
    entirely. Use when a label was a typo, retired, or never useful enough
    to keep (`misc`, `todo`, `tmp`…).

    Semantics:
      - the tag is normalised (lowercase, trimmed) before matching, so
        callers can paste raw operator input without pre-canonicalising;
      - if the tag collapses to empty after normalisation, returns 422 —
        an unbounded "delete everything" sweep is never what the operator
        meant;
      - in each affected row, the tag is removed while preserving the
        order of the remaining tags — same order discipline /tags/rename
        applies, so the admin dropdown doesn't shuffle gratuitously;
      - if no row carries the tag, `deleted_count` is 0 but an audit row
        is still written so /activity shows the attempt;
      - one summary audit row covers the whole delete (no per-entry rows),
        mirroring /tags/rename and /bulk. `problem_id` is null on the
        summary so per-entry /history won't surface it; /activity will.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick /stats, /tags, /tags/rename, and /activity use.
    """
    tag = (req.tag or "").strip().lower()
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="tag must be non-empty after normalisation.",
        )

    # JSONB containment narrows the SELECT to only rows actually carrying
    # the target tag — no scan-and-skip in Python, and the GIN index on
    # `tags` handles it cheaply. Same pattern /tags/rename uses.
    query = select(KnownProblem).where(
        KnownProblem.tags.op("@>")(func.cast([tag], JSONB))
    )
    result = await db.execute(query)
    rows = result.scalars().all()

    updated_ids: List[str] = []
    for kp in rows:
        # Order-preserving filter: drop occurrences of `tag` and keep every
        # other tag in its original slot. Dedupe defensively in case a row
        # somehow carries the same tag twice (shouldn't happen given the
        # _normalize_tags filter, but the audit row is the trail of record).
        new_tags: List[str] = []
        seen: set[str] = set()
        for t in (kp.tags or []):
            if t == tag or t in seen:
                continue
            seen.add(t)
            new_tags.append(t)
        kp.tags = new_tags
        updated_ids.append(kp.id)

    _audit(
        db,
        event_type="known_problem.tag_deleted",
        problem_id=None,
        details={
            "tag": tag,
            "deleted": len(updated_ids),
            # Cap the id list so the audit row stays a sensible size even
            # if someone scrubs a tag attached to every entry in the lib.
            "problem_ids": updated_ids[:50],
        },
    )
    await db.commit()
    logger.info(
        "known_problem.tag_deleted",
        tag=tag,
        deleted=len(updated_ids),
    )
    return TagDeleteResponse(tag=tag, deleted_count=len(updated_ids))


@router.post(
    "/tags/merge",
    response_model=TagMergeResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Merge several tags into a single target tag",
)
async def merge_known_problem_tags(
    req: TagMergeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Consolidate N source tags into one target. The natural generalisation
    of /tags/rename: rename rewrites a single source label, merge rewrites
    a *set* of source labels (`azure-ad`, `aad`, `entra-id` → `entra`).
    Saves an admin from running rename N times when retiring synonyms in
    one sweep.

    Semantics:
      - every tag (sources and target) is normalised (lowercase, trimmed)
        before matching; sources are deduped server-side so callers can
        paste raw operator input without pre-canonicalising;
      - any source that collapses to `to_tag` after normalisation is
        dropped from the source set — merging X → X is a no-op for that
        label and would only confuse the audit trail;
      - if every source collapses (e.g. caller asked for `to_tag`→`to_tag`),
        the request is a no-op (updated_count=0) — still audited so
        /activity shows the attempt;
      - in each affected row, every source tag is replaced by `to_tag`
        while preserving the order of the first occurrence of any source
        tag (or `to_tag` if it was already present); duplicates that arise
        from the merge are squashed, mirroring /tags/rename's discipline;
      - one summary audit row covers the whole merge (no per-entry rows),
        following the bulk-upsert / rename / delete pattern. `problem_id`
        is null on the summary so per-entry /history won't surface it;
        /activity will.

    Declared above /{problem_id} so the literal path wins the FastAPI
    match — same trick /stats, /tags, /tags/rename, /tags/delete, and
    /activity use.
    """
    to_tag = (req.to_tag or "").strip().lower()
    if not to_tag:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="to_tag must be non-empty after normalisation.",
        )

    # Canonicalise the source list with the same filter used everywhere
    # else, then drop the target itself so we never audit X → X.
    sources = [t for t in _normalize_tags(req.from_tags) if t != to_tag]
    if not sources:
        _audit(
            db,
            event_type="known_problem.tags_merged",
            problem_id=None,
            details={
                "from": [],
                "to": to_tag,
                "updated": 0,
                "no_op": True,
            },
        )
        await db.commit()
        logger.info(
            "known_problem.tags_merged",
            from_tags=[],
            to_tag=to_tag,
            updated=0,
            no_op=True,
        )
        return TagMergeResponse(
            from_tags=[], to_tag=to_tag, updated_count=0
        )

    # JSONB ?| (any-key) picks every row carrying at least one of the
    # source tags. Generalises /tags/rename's single-element containment
    # to a many-key match — the GIN index on `tags` handles both forms.
    # The right-hand side of `?|` must be a Postgres text[] (not JSONB),
    # so the source list is bound through a typed ARRAY(String) param
    # rather than func.cast — the latter would coerce the Python list to
    # a JSONB array and the operator would reject it at plan time.
    sources_set = set(sources)
    query = select(KnownProblem).where(
        KnownProblem.tags.op("?|")(
            bindparam("sources", value=sources, type_=ARRAY(String))
        )
    )
    result = await db.execute(query)
    rows = result.scalars().all()

    updated_ids: List[str] = []
    for kp in rows:
        new_tags: List[str] = []
        seen: set[str] = set()
        for t in (kp.tags or []):
            replacement = to_tag if t in sources_set else t
            if replacement in seen:
                continue
            seen.add(replacement)
            new_tags.append(replacement)
        kp.tags = new_tags
        updated_ids.append(kp.id)

    _audit(
        db,
        event_type="known_problem.tags_merged",
        problem_id=None,
        details={
            "from": sources,
            "to": to_tag,
            "updated": len(updated_ids),
            # Cap the id list so the audit row stays a sensible size even
            # if someone merges tags attached to every entry in the lib.
            "problem_ids": updated_ids[:50],
        },
    )
    await db.commit()
    logger.info(
        "known_problem.tags_merged",
        from_tags=sources,
        to_tag=to_tag,
        updated=len(updated_ids),
    )
    return TagMergeResponse(
        from_tags=sources, to_tag=to_tag, updated_count=len(updated_ids)
    )


@router.post(
    "/templates/rename",
    response_model=TemplateRenameResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Rename a ticket template across the Know-How Library",
)
async def rename_known_problem_template(
    req: TemplateRenameRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk-rename a single ticket-template name across every entry that
    references it. The natural counterpart to /tags/rename and
    /products/rename, but for entries in the `related_ticket_templates`
    array. Cleans up template-name drift after a runbook rename
    (`M365-Auth-Reset` → `MS365-Auth-Reset`, mis-cased
    `m365-auth-reset` → `M365-Auth-Reset`) without re-editing each
    entry by hand.

    Semantics:
      - both names are trimmed before matching; `from_template` is
        matched case-insensitively (same discipline /products/rename
        applies to product labels), so an operator pasting
        `m365-auth-reset` still hits a row carrying `M365-Auth-Reset`;
      - `to_template` is written **case-preserved** — there is no
        lowercase fold like /tags/rename, because template / runbook
        identifiers carry case meaning the same way product names do.
        This is precisely why the endpoint exists: to canonicalise
        casing in one call;
      - if `from_template` and `to_template` are exactly equal after
        trimming (case included), the request is treated as a no-op —
        no DB scan, no row mutation, but still audited so the attempt
        shows up in /activity (mirrors /products/rename's no-op trail);
      - in each affected row, occurrences of `from_template` are
        rewritten to `to_template` while preserving the original
        template order — the admin UI's template pill list shouldn't
        gratuitously reshuffle on rename. If `to_template` already
        exists in the row (alongside `from_template`), the duplicate is
        dropped on the rewrite so the row keeps one canonical copy
        (merge semantics — same shape /tags/rename applies);
      - matched rows are rewritten one-by-one in Python (not a single
        bulk UPDATE) so SQLAlchemy fires the model's `onupdate=now()`
        for `updated_at` and the in-memory ORM identity map stays
        consistent — same pattern /tags/rename and /products/rename use;
      - one summary audit row covers the whole rename (no per-entry
        rows). Per-entry /history won't surface it (`problem_id` is null
        on the summary, same as /tags/rename and /products/rename), but
        /activity will. The id sample is capped at 50 so the audit row
        stays a sensible size even when renaming a template attached to
        every entry in the library.

    Database scan strategy: JSONB on PostgreSQL has no native
    case-insensitive containment operator, and `related_ticket_templates`
    is small enough per row (typically <10 entries) that a server-side
    case-fold inside the per-row rewrite loop is cheaper than building
    a custom GIN expression index. The handler loads the candidate set
    with a JSONB existence check on the *exact-case* string AND a
    case-folded scan via `func.jsonb_array_elements_text` — see the
    inline comment near the query for the trade-off — falling back to
    a full-table scan only when neither pre-filter matches anything. In
    practice the library is in the low thousands of rows, so even a
    cold seq-scan is sub-second.

    Declared above `/{problem_id}` so the literal path wins the FastAPI
    match — same trick `/tags/rename`, `/products/rename`, and every
    other aggregation endpoint upstairs use.
    """
    from_template = (req.from_template or "").strip()
    to_template = (req.to_template or "").strip()
    if not from_template or not to_template:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Both from_template and to_template must be non-empty "
                "after trimming whitespace."
            ),
        )

    if from_template == to_template:
        _audit(
            db,
            event_type="known_problem.template_renamed",
            problem_id=None,
            details={
                "from": from_template,
                "to": to_template,
                "updated": 0,
                "no_op": True,
            },
        )
        await db.commit()
        logger.info(
            "known_problem.template_renamed",
            from_template=from_template,
            to_template=to_template,
            updated=0,
            no_op=True,
        )
        return TemplateRenameResponse(
            from_template=from_template,
            to_template=to_template,
            updated_count=0,
        )

    # Load every row whose template array contains a case-insensitive
    # match for `from_template`. JSONB has no native case-insensitive
    # containment, so we unnest the array with jsonb_array_elements_text
    # and compare lower(element) to lower(from_template). The subquery
    # narrows the candidate set in the DB so we never load rows that
    # don't actually carry the source template — same load-then-mutate
    # discipline /tags/rename and /products/rename use, keeping
    # `updated_at` bumps and ORM identity-map state consistent. Tests
    # mock execute() so they don't exercise the subquery shape; an
    # integration test against real Postgres covers the path.
    from_lower = from_template.lower()
    elem_alias = func.jsonb_array_elements_text(
        KnownProblem.related_ticket_templates
    ).table_valued("elem")
    case_insensitive_match = (
        select(1)
        .select_from(elem_alias)
        .where(func.lower(elem_alias.c.elem) == from_lower)
        .exists()
    )
    query = select(KnownProblem).where(case_insensitive_match)
    result = await db.execute(query)
    rows = result.scalars().all()

    updated_ids: List[str] = []
    for kp in rows:
        # Order-preserving rewrite: walk the existing template list,
        # replace any case-insensitive match for `from_template` with
        # the canonical `to_template`, and drop duplicates so a row
        # that already had `to_template` alongside `from_template` ends
        # up with one canonical entry — same merge-on-collision rule
        # /tags/rename applies. Comparison is on the lowercased form so
        # mixed-case occurrences in a single row all collapse together.
        new_templates: List[str] = []
        seen: set[str] = set()
        for tpl in (kp.related_ticket_templates or []):
            replacement = (
                to_template if (tpl or "").lower() == from_lower else tpl
            )
            key = (replacement or "").lower()
            if key in seen:
                continue
            seen.add(key)
            new_templates.append(replacement)
        kp.related_ticket_templates = new_templates
        updated_ids.append(kp.id)

    _audit(
        db,
        event_type="known_problem.template_renamed",
        problem_id=None,
        details={
            "from": from_template,
            "to": to_template,
            "updated": len(updated_ids),
            # Cap the id list so the audit row stays a sensible size
            # even when every entry references the renamed template.
            "problem_ids": updated_ids[:50],
        },
    )
    await db.commit()
    logger.info(
        "known_problem.template_renamed",
        from_template=from_template,
        to_template=to_template,
        updated=len(updated_ids),
    )
    return TemplateRenameResponse(
        from_template=from_template,
        to_template=to_template,
        updated_count=len(updated_ids),
    )


@router.post(
    "/templates/delete",
    response_model=TemplateDeleteResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Drop a ticket template from every entry in the Know-How Library",
)
async def delete_known_problem_template(
    req: TemplateDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Scrub a ticket-template name from every entry that references it.
    The natural counterpart to /templates/rename: rename rewrites one
    template to another, delete drops it entirely. Use when a runbook
    has been retired, a template name was a typo never worth canon-
    icalising, or a vendor-specific template collapsed into a generic
    one and the obsolete pointer should disappear library-wide.

    Semantics:
      - the template name is trimmed before matching; the empty case
        is rejected with 422 (an unbounded "drop everything" sweep is
        never what the operator meant — same guard /tags/delete uses);
      - matching is **case-insensitive** (`m365-auth-reset` and
        `M365-Auth-Reset` collapse to one logical template), mirroring
        /templates/rename. Runbook identifiers drift in case the same
        way product names do, and forcing the operator to spell the
        exact casing they want to scrub would defeat the cleanup;
      - in each affected row, every case-insensitive occurrence of
        the template is removed while preserving the order of the
        remaining templates — the admin pill list shouldn't reshuffle
        on delete. Defensive dedupe (by case-folded form) also keeps
        a row that somehow carried two casing variants from leaving
        one behind;
      - rows are rewritten one-by-one in Python (not a single bulk
        UPDATE) so SQLAlchemy fires the model's `onupdate=now()` for
        `updated_at` and the ORM identity map stays consistent — same
        pattern /templates/rename and /tags/delete use;
      - if no row carries the template, `deleted_count` is 0 but a
        summary audit row is still written so /activity surfaces the
        attempt (mirrors /tags/delete and /products/rename);
      - one summary audit row covers the whole delete (no per-entry
        rows). `problem_id` is null on the summary so per-entry
        /history won't surface it; /activity will. The id sample is
        capped at 50 so the audit row stays a sensible size even when
        scrubbing a template attached to every entry in the library.

    Database scan strategy: JSONB on PostgreSQL has no native case-
    insensitive containment operator, so the candidate set is loaded
    by unnesting `related_ticket_templates` with
    `func.jsonb_array_elements_text` and comparing `lower(element)` to
    the lowercased target — same query shape /templates/rename uses.
    The Know-How Library lives in the low thousands of rows, so even
    a cold subquery scan is sub-second.

    Declared above `/{problem_id}` so the literal path wins the FastAPI
    match — same trick /templates/rename, /tags/delete, and every
    other aggregation endpoint upstairs use.
    """
    template = (req.template or "").strip()
    if not template:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="template must be non-empty after trimming whitespace.",
        )

    template_lower = template.lower()
    # Narrow the candidate set with a case-insensitive existence check
    # over the unnested template array — same subquery shape
    # /templates/rename uses. Tests mock execute() so they don't
    # exercise the subquery directly; an integration test against real
    # Postgres covers the path.
    elem_alias = func.jsonb_array_elements_text(
        KnownProblem.related_ticket_templates
    ).table_valued("elem")
    case_insensitive_match = (
        select(1)
        .select_from(elem_alias)
        .where(func.lower(elem_alias.c.elem) == template_lower)
        .exists()
    )
    query = select(KnownProblem).where(case_insensitive_match)
    result = await db.execute(query)
    rows = result.scalars().all()

    updated_ids: List[str] = []
    for kp in rows:
        # Order-preserving filter: drop any case-insensitive match for
        # `template`, keep every other template in its original slot.
        # Defensive dedupe (by case-folded form) protects a row that
        # somehow carries two casing variants of the same logical
        # template — both go in one sweep.
        new_templates: List[str] = []
        seen: set[str] = set()
        for tpl in (kp.related_ticket_templates or []):
            if (tpl or "").lower() == template_lower:
                continue
            key = (tpl or "").lower()
            if key in seen:
                continue
            seen.add(key)
            new_templates.append(tpl)
        kp.related_ticket_templates = new_templates
        updated_ids.append(kp.id)

    _audit(
        db,
        event_type="known_problem.template_deleted",
        problem_id=None,
        details={
            "template": template,
            "deleted": len(updated_ids),
            # Cap the id list so the audit row stays a sensible size
            # even if the scrubbed template was attached to every
            # entry in the library.
            "problem_ids": updated_ids[:50],
        },
    )
    await db.commit()
    logger.info(
        "known_problem.template_deleted",
        template=template,
        deleted=len(updated_ids),
    )
    return TemplateDeleteResponse(
        template=template,
        deleted_count=len(updated_ids),
    )


@router.post(
    "/templates/merge",
    response_model=TemplateMergeResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Merge several ticket templates into a single target template",
)
async def merge_known_problem_templates(
    req: TemplateMergeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Consolidate N source ticket-template names into one canonical target
    across every entry that references any of them. The natural
    generalisation of /templates/rename: rename rewrites a single source
    label, merge rewrites a *set* of source labels
    (`M365-Auth-Reset`, `m365-auth-reset`, `M365-AuthReset` → `MS365-Auth-Reset`).
    Saves an admin from running rename N times when retiring template-name
    synonyms in one sweep — same shape /tags/merge and /products/merge
    apply to their respective slots.

    Semantics:
      - both sides are trimmed before matching; sources are deduped
        server-side via case-folded keys so callers can paste raw operator
        input without pre-canonicalising (one casing variant survives, in
        first-seen order);
      - sources are matched **case-insensitively** against each row's
        `related_ticket_templates` list — runbook identifiers drift in
        case the same way product names do, mirroring /templates/rename;
      - `to_template` is written **case-preserved** — template / runbook
        identifiers carry case meaning, same discipline /templates/rename
        applies to its target. This is precisely why the endpoint exists:
        to canonicalise a set of synonyms onto one chosen spelling;
      - any source that case-folds to `to_template` is dropped from the
        source set — merging X → X is a no-op for that label and would
        only confuse the audit trail;
      - if every source collapses (e.g. caller asked for case variants of
        the target only), the request is treated as a fully no-op (no DB
        scan, no row mutation) but still audited so /activity shows the
        attempt — mirrors /tags/merge's empty-after-canonicalisation path;
      - in each affected row, every case-insensitive occurrence of any
        source template is rewritten to `to_template` while preserving
        the order of the first matched slot (or the target's slot if it
        was already present). Duplicates that arise from the merge are
        squashed on the rewrite by case-folded key, mirroring
        /tags/merge's collapse-on-collision rule and /templates/rename's
        merge semantics;
      - rows are rewritten one-by-one in Python (not a single bulk
        UPDATE) so SQLAlchemy fires the model's `onupdate=now()` for
        `updated_at` and the in-memory ORM identity map stays consistent
        — same pattern /templates/rename, /templates/delete, and
        /tags/merge use;
      - one summary audit row covers the whole merge (no per-entry rows).
        `problem_id` is null on the summary so per-entry /history won't
        surface it; /activity will. The id sample is capped at 50 so the
        audit row stays a sensible size even when merging templates
        attached to every entry in the library.

    Database scan strategy: JSONB on PostgreSQL has no native
    case-insensitive containment operator, and the source list may carry
    several casing variants of the same logical template, so the
    candidate set is loaded by unnesting `related_ticket_templates` with
    `func.jsonb_array_elements_text` and checking `lower(element) IN
    (...lowered sources...)`. Same query shape /templates/rename and
    /templates/delete use, just with a set membership instead of a
    single-element compare. The Know-How Library lives in the low
    thousands of rows, so even a cold subquery scan is sub-second.

    Declared above `/{problem_id}` so the literal path wins the FastAPI
    match — same trick /templates/rename, /templates/delete, /tags/merge,
    and every other aggregation endpoint upstairs use.
    """
    to_template = (req.to_template or "").strip()
    if not to_template:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="to_template must be non-empty after trimming whitespace.",
        )
    to_lower = to_template.lower()

    # Canonicalise the source list: trim, drop empties, dedupe by
    # case-folded key (first-seen casing survives), and drop any source
    # that case-folds to the target — merging X → X is a no-op for that
    # label. Same shape /tags/merge uses, adapted for case-preserved
    # template names.
    sources: List[str] = []
    seen_sources: set[str] = set()
    for raw in req.from_templates:
        tpl = (raw or "").strip()
        if not tpl:
            continue
        key = tpl.lower()
        if key == to_lower:
            continue
        if key in seen_sources:
            continue
        seen_sources.add(key)
        sources.append(tpl)

    if not sources:
        _audit(
            db,
            event_type="known_problem.templates_merged",
            problem_id=None,
            details={
                "from": [],
                "to": to_template,
                "updated": 0,
                "no_op": True,
            },
        )
        await db.commit()
        logger.info(
            "known_problem.templates_merged",
            from_templates=[],
            to_template=to_template,
            updated=0,
            no_op=True,
        )
        return TemplateMergeResponse(
            from_templates=[],
            to_template=to_template,
            updated_count=0,
        )

    # Set of lowercased sources drives both the DB pre-filter and the
    # in-Python rewrite. JSONB containment can't do case-insensitive
    # comparison directly, so we unnest the array with
    # jsonb_array_elements_text and use `lower(elem) IN (...)` — same
    # subquery shape /templates/rename uses, generalised to many keys.
    sources_lower = {s.lower() for s in sources}
    elem_alias = func.jsonb_array_elements_text(
        KnownProblem.related_ticket_templates
    ).table_valued("elem")
    case_insensitive_match = (
        select(1)
        .select_from(elem_alias)
        .where(func.lower(elem_alias.c.elem).in_(sources_lower))
        .exists()
    )
    query = select(KnownProblem).where(case_insensitive_match)
    result = await db.execute(query)
    rows = result.scalars().all()

    updated_ids: List[str] = []
    for kp in rows:
        # Order-preserving rewrite: walk the existing template list,
        # rewrite any case-insensitive match for any source to the
        # canonical target, and dedupe by case-folded form so a row that
        # already carried the target alongside one or more sources ends
        # up with one canonical entry in the first matched slot. Same
        # collapse-on-collision discipline /tags/merge and
        # /templates/rename apply.
        new_templates: List[str] = []
        seen: set[str] = set()
        for tpl in (kp.related_ticket_templates or []):
            tpl_lower = (tpl or "").lower()
            replacement = to_template if tpl_lower in sources_lower else tpl
            key = (replacement or "").lower()
            if key in seen:
                continue
            seen.add(key)
            new_templates.append(replacement)
        kp.related_ticket_templates = new_templates
        updated_ids.append(kp.id)

    _audit(
        db,
        event_type="known_problem.templates_merged",
        problem_id=None,
        details={
            "from": sources,
            "to": to_template,
            "updated": len(updated_ids),
            # Cap the id list so the audit row stays a sensible size
            # even when merging templates attached to every entry in
            # the library.
            "problem_ids": updated_ids[:50],
        },
    )
    await db.commit()
    logger.info(
        "known_problem.templates_merged",
        from_templates=sources,
        to_template=to_template,
        updated=len(updated_ids),
    )
    return TemplateMergeResponse(
        from_templates=sources,
        to_template=to_template,
        updated_count=len(updated_ids),
    )


@router.get(
    "/activity",
    response_model=List[HistoryEvent],
    dependencies=[Depends(verify_api_key)],
    summary="Recent audit events across the whole Know-How Library",
)
async def known_problem_activity(
    limit: int = Query(50, ge=1, le=200),
    event_type: Optional[str] = Query(
        None,
        description=(
            "Restrict to a single mutation kind — one of `created`, "
            "`updated`, `deleted`, `bulk_upserted`, `tags_renamed`, "
            "`tag_deleted`, `tags_merged`, `templates_merged`. "
            "Bare suffix is accepted "
            "and prefixed with `known_problem.` server-side so callers "
            "don't have to know the audit namespace. Unknown suffixes "
            "return an empty list rather than 422 — the admin UI's filter "
            "dropdown should fail soft, not hard."
        ),
    ),
    product: Optional[str] = Query(
        None,
        max_length=120,
        description=(
            "Restrict to events whose audit payload mentions this product "
            "(matched against the `product` key inside `details`, "
            "case-insensitive). Useful for scoping the admin 'Recent "
            "activity' panel to a single product's slice of the library."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return audit-log entries for the Know-How Library as a whole, newest first.

    Per-entry `/{id}/history` (iter-66) is fine for a detail page but useless
    for a dashboard widget that wants "what changed in the library lately?".
    This endpoint is the library-wide counterpart: it surfaces creates,
    updates, deletes, and bulk-upserts across every entry, optionally
    narrowed by event kind or product.

    Cross-agent safety mirrors `/{id}/history`: `audit_logs.details` is plain
    Text and other writers (portal auth, file feedback, …) park non-JSON
    strings in it. The handler parses each `details` payload defensively
    with the same `from_orm_row` helper, so a malformed row elsewhere in
    the table can't blow up this query.

    Declared above /{problem_id} so the literal path wins the FastAPI match
    — same trick /stats and /tags use.
    """
    stmt = select(AuditLog).where(AuditLog.event_type.like("known_problem.%"))

    if event_type:
        suffix = event_type.strip().lower()
        if suffix:
            full = (
                suffix
                if suffix.startswith("known_problem.")
                else f"known_problem.{suffix}"
            )
            stmt = stmt.where(AuditLog.event_type == full)

    if product:
        # Same defensive CASE the per-entry history uses: only cast rows
        # whose event_type matches the namespace, so JSON parsing can't
        # blow up on unrelated audit writers parking non-JSON strings here.
        stmt = stmt.where(
            case(
                (
                    AuditLog.event_type.like("known_problem.%"),
                    func.lower(
                        func.cast(AuditLog.details, JSONB).op("->>")("product")
                    ),
                ),
                else_=None,
            )
            == product.strip().lower()
        )

    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [HistoryEvent.from_orm_row(r) for r in rows]


@router.get(
    "/{problem_id}",
    response_model=KnownProblemResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Get a known problem",
)
async def get_known_problem(
    problem_id: str,
    db: AsyncSession = Depends(get_db),
):
    kp = await _load_or_404(db, problem_id)
    return KnownProblemResponse.from_orm_row(kp)


@router.put(
    "/{problem_id}",
    response_model=KnownProblemResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Replace a known problem",
)
async def update_known_problem(
    problem_id: str,
    req: KnownProblemUpdate,
    db: AsyncSession = Depends(get_db),
):
    kp = await _load_or_404(db, problem_id)
    previous = {
        "product": kp.product,
        "symptom_preview": kp.symptom[:120],
        "tags": list(kp.tags or []),
    }
    kp.product = req.product
    kp.symptom = req.symptom
    kp.diagnosis = req.diagnosis
    kp.fix = req.fix
    kp.related_ticket_templates = list(req.related_ticket_templates)
    kp.tags = _normalize_tags(req.tags)
    # updated_at is bumped by the column's onupdate=func.now()
    _audit(
        db,
        event_type="known_problem.updated",
        problem_id=kp.id,
        details={
            "previous": previous,
            "product": kp.product,
            "symptom_preview": kp.symptom[:120],
            "tags": list(kp.tags or []),
        },
    )
    await db.commit()
    await db.refresh(kp)
    logger.info("known_problem.updated", id=kp.id, product=kp.product)
    return KnownProblemResponse.from_orm_row(kp)


@router.patch(
    "/{problem_id}",
    response_model=KnownProblemResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Partially update a known problem",
)
async def patch_known_problem(
    problem_id: str,
    req: KnownProblemPatch,
    db: AsyncSession = Depends(get_db),
):
    """
    Apply a partial update — only the fields the caller actually included
    in the JSON body are written. Use this when retitling one field on an
    entry, rewriting a single row's tag list, or making a scripted one-off
    fix. PUT remains the right verb for a full replace.

    Semantics:
      - field-presence is detected via Pydantic v2's `model_fields_set`,
        so `{"tags": []}` clears tags but `{}` (or any payload missing the
        `tags` key) leaves them untouched;
      - tags are canonicalised through `_normalize_tags` exactly like PUT
        and POST, so case/whitespace/dupe drift can't sneak in via PATCH;
      - an empty body (no recognised fields) is a 422 — a no-op PATCH is
        a client bug, not a silent success, and we'd rather surface it;
      - the audit row carries `previous` snapshots of *only the fields
        that changed*, plus a `changed_fields` list, so the trail shows
        operators exactly which columns moved without dumping the whole
        row each time. Mirrors PUT's before/after discipline but bounded.
    """
    kp = await _load_or_404(db, problem_id)

    # Pydantic v2 — `model_fields_set` is the set of attributes the caller
    # explicitly supplied. `model_dump(exclude_unset=True)` likewise omits
    # anything missing from the wire payload. Together they give us the
    # "missing key = leave alone, present key = write through" semantics.
    fields_set = req.model_fields_set
    if not fields_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="PATCH body must include at least one field to update.",
        )

    previous: dict[str, Any] = {}
    changed: List[str] = []

    if "product" in fields_set and req.product != kp.product:
        previous["product"] = kp.product
        kp.product = req.product  # type: ignore[assignment]
        changed.append("product")

    if "symptom" in fields_set and req.symptom != kp.symptom:
        # Audit gets a bounded preview, same 120-char cap PUT/DELETE use.
        previous["symptom_preview"] = kp.symptom[:120]
        kp.symptom = req.symptom  # type: ignore[assignment]
        changed.append("symptom")

    if "diagnosis" in fields_set and req.diagnosis != kp.diagnosis:
        previous["diagnosis_preview"] = kp.diagnosis[:120]
        kp.diagnosis = req.diagnosis  # type: ignore[assignment]
        changed.append("diagnosis")

    if "fix" in fields_set and req.fix != kp.fix:
        previous["fix_preview"] = kp.fix[:120]
        kp.fix = req.fix  # type: ignore[assignment]
        changed.append("fix")

    if "related_ticket_templates" in fields_set:
        new_templates = list(req.related_ticket_templates or [])
        if new_templates != list(kp.related_ticket_templates or []):
            previous["related_ticket_templates"] = list(
                kp.related_ticket_templates or []
            )
            kp.related_ticket_templates = new_templates
            changed.append("related_ticket_templates")

    if "tags" in fields_set:
        new_tags = _normalize_tags(req.tags or [])
        if new_tags != list(kp.tags or []):
            previous["tags"] = list(kp.tags or [])
            kp.tags = new_tags
            changed.append("tags")

    # An empty `changed` list means the caller sent fields whose values
    # already matched the stored row — the PATCH is a structural no-op.
    # Still audit it so /activity surfaces the attempt, mirroring the
    # /tags/rename no-op pattern. The row isn't actually rewritten, so
    # updated_at stays put (onupdate only fires when a column moves).
    _audit(
        db,
        event_type="known_problem.patched",
        problem_id=kp.id,
        details={
            "product": kp.product,
            "symptom_preview": kp.symptom[:120],
            "changed_fields": changed,
            "previous": previous,
            "no_op": not changed,
        },
    )
    await db.commit()
    await db.refresh(kp)
    logger.info(
        "known_problem.patched",
        id=kp.id,
        product=kp.product,
        changed_fields=changed,
        no_op=not changed,
    )
    return KnownProblemResponse.from_orm_row(kp)


@router.delete(
    "/{problem_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_api_key)],
    summary="Delete a known problem",
)
async def delete_known_problem(
    problem_id: str,
    db: AsyncSession = Depends(get_db),
):
    kp = await _load_or_404(db, problem_id)
    _audit(
        db,
        event_type="known_problem.deleted",
        problem_id=kp.id,
        details={
            "product": kp.product,
            "symptom_preview": kp.symptom[:120],
        },
    )
    await db.delete(kp)
    await db.commit()
    logger.info("known_problem.deleted", id=problem_id)
    # 204 — no body
    return None


@router.get(
    "/{problem_id}/history",
    response_model=List[HistoryEvent],
    dependencies=[Depends(verify_api_key)],
    summary="Audit trail for a known problem",
)
async def known_problem_history(
    problem_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    Return audit-log entries for a single Know-How entry, newest first.

    iter-57 wired the mutation handlers to write audit rows on create /
    update / delete; this is the read surface — without it the trail is
    only visible via raw SQL. Powers the "Activity" tab on the admin
    entry detail page so operators can see who changed what and when.

    The entry must currently exist (404 if not) so callers can't probe
    for which IDs have audit history. Bulk-upsert rows are excluded by
    design: they carry `problem_id: null` because one summary row covers
    the whole batch, so they don't link back to any single entry.

    Cross-agent safety: `audit_logs.details` is plain Text and other
    writers (portal auth, file feedback, …) store non-JSON strings in it.
    The CASE guard makes Postgres skip the JSONB cast on those rows, so
    a malformed payload elsewhere in the table can't blow up this query.
    """
    await _load_or_404(db, problem_id)

    stmt = (
        select(AuditLog)
        .where(AuditLog.event_type.like("known_problem.%"))
        .where(
            case(
                (
                    AuditLog.event_type.like("known_problem.%"),
                    func.cast(AuditLog.details, JSONB).op("->>")("problem_id"),
                ),
                else_=None,
            )
            == problem_id
        )
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [HistoryEvent.from_orm_row(r) for r in rows]


@router.get(
    "/{problem_id}/related",
    response_model=SuggestResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Find Know-How entries similar to an existing one",
)
async def related_known_problems(
    problem_id: str,
    top_n: int = Query(5, ge=1, le=20),
    min_rank: float = Query(0.0, ge=0.0, le=1.0),
    scope_to_product: bool = Query(
        True,
        description=(
            "When true (default), only consider entries with the same product "
            "as the source. Off lets cross-product near-duplicates surface — "
            "useful when an Intune symptom mirrors a Microsoft 365 one."
        ),
    ),
    scope_to_tags: bool = Query(
        False,
        description=(
            "When true, restrict candidates to rows that carry ALL of the "
            "source entry's tags. Off by default because the tagset is the "
            "operator-supplied categorisation — forcing it on would hide "
            "untagged near-duplicates that the FTS index correctly surfaces. "
            "Turn on when an entry has a deliberate tagset (e.g. 'auth') and "
            "the sidebar should stay within that category."
        ),
    ),
    highlight: bool = Query(
        False,
        description=(
            "When true, each match carries `highlights`: the symptom, "
            "diagnosis, and fix fields rendered with <mark>…</mark> markup "
            "around the tokens that overlap with the source entry. Mirrors "
            "the /suggest endpoint so the admin 'See similar entries' "
            "sidebar can show *why* an entry is considered near-duplicate."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Find Know-How entries whose symptom/diagnosis text overlaps with the
    given entry. The source entry is always filtered out of the result so
    the caller never has to dedupe.

    Built on the same matcher as /suggest — no new ranking code — so the
    score scale, min_rank semantics, product filtering, and highlight
    markup all behave identically to free-text suggestion. The admin UI
    uses this to render a "See similar entries" sidebar on the entry
    detail page, optionally with the overlapping tokens marked up.
    """
    source = await _load_or_404(db, problem_id)

    # Compose a query from the source entry's own searchable fields so the
    # matcher hits the same weighted FTS index it always does. symptom is
    # B-weighted and the longest field — it dominates ranking, which is
    # what we want for "find near-duplicates of this entry."
    query_text = f"{source.symptom}\n{source.diagnosis}"

    matches = await find_matches(
        db,
        query_text,
        product=source.product if scope_to_product else None,
        tags=list(source.tags or []) if scope_to_tags else None,
        top_n=top_n + 1,  # +1 so we still hit top_n after dropping self
        min_rank=min_rank,
        highlight=highlight,
    )

    matches = [m for m in matches if m.problem.id != source.id][:top_n]

    return SuggestResponse(
        matches=[
            SuggestionMatch(
                problem=KnownProblemResponse.from_orm_row(m.problem),
                rank=m.rank,
                highlights=(
                    HighlightSnippet(
                        symptom=m.highlights.symptom,
                        diagnosis=m.highlights.diagnosis,
                        fix=m.highlights.fix,
                    )
                    if m.highlights is not None
                    else None
                ),
            )
            for m in matches
        ]
    )


@router.post(
    "/{problem_id}/duplicate",
    response_model=KnownProblemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key)],
    summary="Duplicate a known problem with optional field overrides",
)
async def duplicate_known_problem(
    problem_id: str,
    req: KnownProblemDuplicate,
    db: AsyncSession = Depends(get_db),
):
    """
    Fork an existing Know-How entry into a brand new row. Any field
    supplied in the body overrides the source row's value on the new
    entry; anything omitted is copied verbatim. The new row gets a fresh
    UUID and fresh created_at/updated_at — the source row is left
    untouched.

    Tags are run through `_normalize_tags` whenever they appear on the
    wire payload (same canonical form PUT/PATCH/POST produce) so
    casing/whitespace drift can't sneak in via the duplicate path. When
    the caller omits `tags`, the source's already-canonical tag list is
    copied verbatim — re-normalising a copy that's already normalised
    would be a no-op anyway, and skipping it preserves insertion order
    exactly so the admin UI tag pills render identically on the clone.

    Audit: a `known_problem.duplicated` row is staged on the same
    transaction as the insert. The `details` payload carries the source
    row's id and product alongside the new row's id and the list of
    fields the caller actually overrode — so /activity surfaces both
    rows in a way the operator can trace back to the clone action
    without having to cross-reference timestamps.

    Returns 201 with the freshly-persisted entry on success, 404 if the
    source id does not exist.
    """
    source = await _load_or_404(db, problem_id)

    # Resolve each field from the override (if supplied) or the source
    # row (if not). Pydantic v2's model_fields_set tells us which keys
    # the client actually sent, so omitted-vs-explicit-null is unambiguous.
    overrides = req.model_fields_set

    new_product = req.product if "product" in overrides else source.product
    new_symptom = req.symptom if "symptom" in overrides else source.symptom
    new_diagnosis = (
        req.diagnosis if "diagnosis" in overrides else source.diagnosis
    )
    new_fix = req.fix if "fix" in overrides else source.fix

    if "related_ticket_templates" in overrides:
        new_templates = list(req.related_ticket_templates or [])
    else:
        new_templates = list(source.related_ticket_templates or [])

    if "tags" in overrides:
        new_tags = _normalize_tags(req.tags or [])
    else:
        # Source tags are already canonical (every write path normalises),
        # so copy them as-is to preserve insertion order exactly.
        new_tags = list(source.tags or [])

    clone = KnownProblem(
        id=str(uuid4()),
        product=new_product,
        symptom=new_symptom,
        diagnosis=new_diagnosis,
        fix=new_fix,
        related_ticket_templates=new_templates,
        tags=new_tags,
    )
    db.add(clone)

    _audit(
        db,
        event_type="known_problem.duplicated",
        problem_id=clone.id,
        details={
            "source_id": source.id,
            "source_product": source.product,
            "product": clone.product,
            "symptom_preview": clone.symptom[:120],
            "overridden_fields": sorted(overrides),
            "tags": list(clone.tags or []),
        },
    )
    await db.commit()
    await db.refresh(clone)
    logger.info(
        "known_problem.duplicated",
        id=clone.id,
        source_id=source.id,
        product=clone.product,
        overridden_fields=sorted(overrides),
    )
    return KnownProblemResponse.from_orm_row(clone)


@router.post(
    "/{target_id}/merge",
    response_model=KnownProblemMergeResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Merge a duplicate Know-How entry into another",
)
async def merge_known_problems(
    target_id: str,
    req: KnownProblemMergeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Collapse a duplicate Know-How entry into the target row.

    The target keeps its text fields (product, symptom, diagnosis, fix)
    untouched — merging is intentionally non-destructive on the wording
    so operators can pre-edit the row they want to survive before
    pressing Merge. Only `tags` and `related_ticket_templates` are
    union-merged from source into target, preserving the target's
    existing insertion order (source items that already exist on target
    are dropped; novel items are appended in source order). Tags are
    already canonical on both rows so no re-normalisation is needed.

    By default the source row is removed after the union write — the
    canonical follow-on to /related and /{id}/duplicate which surface
    near-duplicates worth collapsing. Pass `keep_source=true` to leave
    the source row in place; in that case the target still gains the
    union of tags and templates, but the source is untouched.

    Refuses to merge a row into itself (422) — that would delete the
    only copy under the default `keep_source=false` and is never the
    operator's intent. Both ids must resolve (404 otherwise) so the
    write is atomic: union update + audit row + (optional) source
    delete all ride the same transaction.

    Audit: a single `known_problem.merged` row is staged on the target,
    carrying the source id and product, the lists of tags and templates
    actually added (so the trail shows what changed, not just that
    something happened), and the `source_deleted` flag. /activity
    surfaces the merge against the target row; the source row's prior
    history is reachable via /history for as long as the source remains
    (or via /activity after deletion, since audit rows survive deletes).
    """
    source_id = (req.source_id or "").strip()
    if not source_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="source_id must not be blank.",
        )
    if source_id == target_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="source_id and target_id must differ.",
        )

    target = await _load_or_404(db, target_id)
    source = await _load_or_404(db, source_id)

    # Tags on both rows are already canonical (every write path runs
    # _normalize_tags), so the union is a simple append-if-novel pass
    # that preserves target order and appends novel source tags in
    # source order. Same shape applies to templates, which are stored
    # verbatim — no normalisation, just dedupe on equality.
    target_tags = list(target.tags or [])
    target_template = list(target.related_ticket_templates or [])
    existing_tags = set(target_tags)
    existing_templates = set(target_template)

    tags_added: List[str] = []
    for t in source.tags or []:
        if t in existing_tags:
            continue
        existing_tags.add(t)
        tags_added.append(t)

    templates_added: List[str] = []
    for tpl in source.related_ticket_templates or []:
        if tpl in existing_templates:
            continue
        existing_templates.add(tpl)
        templates_added.append(tpl)

    target.tags = target_tags + tags_added
    target.related_ticket_templates = target_template + templates_added

    _audit(
        db,
        event_type="known_problem.merged",
        problem_id=target.id,
        details={
            "source_id": source.id,
            "source_product": source.product,
            "source_symptom_preview": source.symptom[:120],
            "tags_added": list(tags_added),
            "templates_added": list(templates_added),
            "source_deleted": not req.keep_source,
        },
    )

    source_deleted = False
    if not req.keep_source:
        await db.delete(source)
        source_deleted = True

    await db.commit()
    await db.refresh(target)
    logger.info(
        "known_problem.merged",
        target_id=target.id,
        source_id=source.id,
        tags_added=tags_added,
        templates_added=templates_added,
        source_deleted=source_deleted,
    )
    return KnownProblemMergeResponse(
        target=KnownProblemResponse.from_orm_row(target),
        source_id=source.id,
        source_deleted=source_deleted,
        tags_added=tags_added,
        templates_added=templates_added,
    )


@router.post(
    "/suggest",
    response_model=SuggestResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Suggest known problems for a ticket description",
)
async def suggest_known_problems(
    req: SuggestRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Run the description through the Know-How Library full-text index and
    return the top-N ranked matches. Used by ticket-creation surfaces to
    surface "have we seen this before?" links.
    """
    matches = await find_matches(
        db,
        req.description,
        product=req.product,
        tags=req.tags,
        top_n=req.top_n,
        min_rank=req.min_rank,
        highlight=req.highlight,
    )
    return SuggestResponse(
        matches=[
            SuggestionMatch(
                problem=KnownProblemResponse.from_orm_row(m.problem),
                rank=m.rank,
                highlights=(
                    HighlightSnippet(
                        symptom=m.highlights.symptom,
                        diagnosis=m.highlights.diagnosis,
                        fix=m.highlights.fix,
                    )
                    if m.highlights is not None
                    else None
                ),
            )
            for m in matches
        ]
    )
