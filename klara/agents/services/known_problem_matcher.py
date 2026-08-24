"""
app/services/known_problem_matcher.py
─────────────────────────────────────
Know-How Library matcher (prod-004 slice 2).

Given a free-text ticket description and an optional product label, this
module returns the highest-ranked KnownProblem rows using PostgreSQL
full-text search over the `search_vector` tsvector column added in
migration 0016.

It is the single source of truth for "given this user complaint, what do
we already know?" — used by:

  - POST /api/v1/known-problems/suggest          (admin tooling)
  - form_intake / chat_intake agent output       (so the ticket creation
    surface sees suggested matches without re-implementing scoring)

Ranking
───────
`ts_rank` over a `plainto_tsquery('english', q)` query against the
weighted search_vector (product=A, symptom=B, diagnosis=C). Higher
ts_rank → better match. When a product filter is supplied, candidates are
restricted to rows whose `product` matches case-insensitively. Empty or
whitespace-only descriptions short-circuit to `[]` — `plainto_tsquery('')`
returns an empty query that matches nothing anyway, but bailing early
saves a round-trip and avoids surfacing nonsense ranks.

Quality threshold
─────────────────
Callers can pass `min_rank` to drop low-confidence FTS hits. Default is
`DEFAULT_AGENT_MIN_RANK` for the intake agents, which would otherwise feed
noisy near-zero-rank matches into Claude's system prompt and pollute the
operator inbox. The admin /suggest endpoint defaults to 0.0 so manual
exploration can still see the long tail.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.known_problem import KnownProblem

logger = structlog.get_logger(__name__)

# Intake agents inject Know-How matches straight into Claude's system prompt
# or the operator inbox. ts_rank on plainto_tsquery typically returns values
# in [0.0, ~0.6] for relevant hits; anything below ~0.05 is usually a single
# stopword-adjacent token match and adds noise rather than signal. Tuned
# conservatively — picked low enough that genuine short-symptom matches still
# pass, high enough that "hello there" against an unrelated symptom does not.
DEFAULT_AGENT_MIN_RANK: float = 0.05


# ts_headline options. StartSel/StopSel control the markup wrapped around each
# matched token; <mark>…</mark> is HTML5-safe, requires no client-side parsing
# beyond a CSS rule, and round-trips through JSON without escaping. MaxFragments=1
# + MaxWords keep the snippet short enough to render inline in a dashboard list
# without truncating the parent layout. ShortWord=2 stops postgres from inserting
# ellipses around two-letter words (which produces ugly "…to…" fragments).
_HEADLINE_OPTIONS: str = (
    "StartSel=<mark>, StopSel=</mark>, "
    "MaxFragments=1, MaxWords=24, MinWords=8, ShortWord=2"
)


@dataclass(frozen=True)
class MatchHighlights:
    """ts_headline output for the human-readable fields of one match."""
    symptom: str
    diagnosis: str
    fix: str


@dataclass(frozen=True)
class KnownProblemMatch:
    """One ranked match from the Know-How Library."""
    problem: KnownProblem
    rank: float
    highlights: Optional[MatchHighlights] = None

    def to_summary(self) -> dict:
        """Compact dict shape suitable for agent output / structlog."""
        return {
            "id": self.problem.id,
            "product": self.problem.product,
            "symptom": self.problem.symptom,
            "diagnosis": self.problem.diagnosis,
            "fix": self.problem.fix,
            "related_ticket_templates": list(
                self.problem.related_ticket_templates or []
            ),
            "rank": round(float(self.rank), 4),
        }


async def find_matches(
    db: AsyncSession,
    description: str,
    *,
    product: Optional[str] = None,
    tags: Optional[List[str]] = None,
    top_n: int = 5,
    min_rank: float = 0.0,
    highlight: bool = False,
) -> List[KnownProblemMatch]:
    """
    Return up to `top_n` KnownProblem rows ranked by FTS relevance to
    `description`. Empty/whitespace descriptions return `[]`.

    The query uses `plainto_tsquery('english', :q)` which is forgiving of
    punctuation and stopwords — the same input that a user pastes from
    their email or chat message can be passed through directly.

    `min_rank` filters out hits whose ts_rank is below the threshold. Use
    `DEFAULT_AGENT_MIN_RANK` for agent-facing callers; pass 0.0 for admin
    exploration where you want the full tail.

    `tags` narrows candidates to rows whose JSONB `tags` array contains
    *every* listed tag (AND semantics — same as the list endpoint, so
    operators get one mental model across surfaces). Tags are trimmed +
    lowercased before matching, mirroring the canonical on-disk form;
    empty strings are dropped silently. Pass None or [] to skip the
    filter entirely.

    `highlight=True` adds `ts_headline` output to every returned match,
    exposing which terms of symptom/diagnosis/fix actually hit the query.
    Off by default because the headline call is non-trivial work the
    intake agents don't need — they consume raw text, not markup.
    """
    q = (description or "").strip()
    if not q:
        return []

    wanted_tags: List[str] = []
    if tags:
        seen: set[str] = set()
        for t in tags:
            norm = (t or "").strip().lower()
            if not norm or norm in seen:
                continue
            seen.add(norm)
            wanted_tags.append(norm)

    ts_query = func.plainto_tsquery("english", q)
    rank_expr = func.ts_rank(KnownProblem.search_vector, ts_query)
    rank = rank_expr.label("rank")

    select_cols: list = [KnownProblem, rank]
    if highlight:
        # ts_headline runs on the source text (not the tsvector), so we
        # call it once per displayable field. Each call returns the
        # original text with <mark> wrappers around matched tokens.
        select_cols.extend([
            func.ts_headline(
                "english", KnownProblem.symptom, ts_query, _HEADLINE_OPTIONS
            ).label("hl_symptom"),
            func.ts_headline(
                "english", KnownProblem.diagnosis, ts_query, _HEADLINE_OPTIONS
            ).label("hl_diagnosis"),
            func.ts_headline(
                "english", KnownProblem.fix, ts_query, _HEADLINE_OPTIONS
            ).label("hl_fix"),
        ])

    stmt = (
        select(*select_cols)
        .where(KnownProblem.search_vector.op("@@")(ts_query))
    )
    if product:
        stmt = stmt.where(KnownProblem.product.ilike(product))
    if wanted_tags:
        # Same JSONB containment shape as the list endpoint: a row qualifies
        # iff its `tags` array contains every tag in `wanted_tags`. Pushed
        # into SQL so the FTS index can intersect with the tag filter inside
        # the planner rather than us paging through FTS hits in Python.
        stmt = stmt.where(
            KnownProblem.tags.op("@>")(func.cast(wanted_tags, JSONB))
        )
    if min_rank > 0.0:
        # Apply the threshold in SQL so the LIMIT clause sees only qualified
        # rows — otherwise we'd silently fetch top_n rows and drop noise in
        # Python, hiding genuine matches that ranked below the noise.
        stmt = stmt.where(rank_expr >= min_rank)

    stmt = stmt.order_by(rank.desc(), KnownProblem.created_at.desc()).limit(top_n)

    result = await db.execute(stmt)
    rows = result.all()

    matches: List[KnownProblemMatch] = []
    for row in rows:
        problem = row[0]
        row_rank = float(row[1] or 0.0)
        if highlight:
            highlights = MatchHighlights(
                symptom=row[2] or problem.symptom,
                diagnosis=row[3] or problem.diagnosis,
                fix=row[4] or problem.fix,
            )
        else:
            highlights = None
        matches.append(
            KnownProblemMatch(problem=problem, rank=row_rank, highlights=highlights)
        )

    logger.info(
        "known_problem.match",
        product=product,
        tags=wanted_tags or None,
        min_rank=min_rank,
        highlight=highlight,
        candidates=len(matches),
        top_rank=matches[0].rank if matches else 0.0,
    )
    return matches
