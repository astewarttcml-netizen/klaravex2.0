"""
app/agents/kb_lookup.py
────────────────────────
KbLookupAgent — P1 read-only knowledge base search agent.

Queries the known_problems table for entries matching an optional product
filter, then uses Claude to semantically rank the candidates by relevance to
the caller's symptom description.  Returns the top N matches with symptom,
diagnosis, fix, and related ticket templates.

Can be called directly via API or composed into other agents (e.g. chat_intake
to suggest a fix before creating a ticket).

Trigger:  POST /api/v1/admin/kb/lookup
          OR called directly from other agents:
            result = await kb_lookup_agent(context, {
                "symptom": "Users cannot sign in to SharePoint",
                "product": "Microsoft 365",
                "max_results": 3,
            })

Input data:
  symptom      (str)           — free-text problem description (required)
  product      (str, optional) — product filter, e.g. "Microsoft 365", "Meraki"
  max_results  (int, default 3) — maximum ranked results to return

Flow:
  1. Validate input.
  2. Query known_problems using full-text search (tsvector GIN index) with
     optional product filter.  Fall back to ILIKE if FTS returns nothing.
  3. If candidates found, call Claude to semantically rank by relevance.
  4. Return top max_results matches.

Permission: P1 — read-only.  No approval gate. No DB writes.

───────────────────────────────────────────────────────────────────────────────
known_problems schema (already deployed via migrations 0011 + 0016 + 0027/0028):

  id                      UUID, PK
  product                 VARCHAR(120), indexed
  symptom                 TEXT
  diagnosis               TEXT
  fix                     TEXT
  related_ticket_templates JSONB  (array of template reference strings)
  tags                    JSONB  (array of lowercase tag strings)
  search_vector           TSVECTOR GENERATED STORED
                          setweight(to_tsvector('english', product),   'A')
                       || setweight(to_tsvector('english', symptom),   'B')
                       || setweight(to_tsvector('english', diagnosis),  'C')
  created_at              TIMESTAMPTZ
  updated_at              TIMESTAMPTZ

Relevant indexes (from 0016_known_problems_fts.py):
  GIN(search_vector)      — fast FTS queries
  GIN(tags jsonb_path_ops) — tag containment queries
  B-tree(product)         — product filter
───────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import func, select, text

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.known_problem import KnownProblem

logger = structlog.get_logger(__name__)

_DEFAULT_MAX_RESULTS = 3
_CANDIDATE_POOL = 20   # rows fetched from DB before Claude re-ranks

# ── Ranking prompt ────────────────────────────────────────────────────────────

_RANKING_PROMPT = """\
You are an IT support engineer at Klaravex.
A technician has described a problem. You have a list of known-problem records
from the internal knowledge base. Rank the records by how closely they match
the described symptom.

Symptom described by the technician:
{symptom}

Known-problem candidates (JSON array, index 0 = first):
{candidates_json}

Output a JSON array of objects in this format — ordered best match first,
include at most {max_results} items:
[
  {{
    "index": <original index in candidates array>,
    "relevance_score": <float 0.0–1.0>,
    "relevance_reason": "<one sentence why this matches>"
  }},
  ...
]

Rules:
- Only include records that are genuinely relevant (relevance_score >= 0.3).
- If none are relevant, return an empty array [].
- Respond ONLY with valid JSON. No markdown fences, no explanation.
"""


class KbLookupAgent(BaseAgent):
    name = "kb_lookup"
    description = (
        "Searches the internal KnownProblem knowledge base by symptom (semantic "
        "re-ranking via Claude) and optional product filter. Returns top N ranked "
        "matches with diagnosis, fix, and related ticket templates. "
        "P1 read-only — no approval gate. "
        "Trigger: POST /api/v1/admin/kb/lookup or composed from other agents."
    )
    permission_level = PermissionLevel.P1

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        db = context.db
        log = logger.bind(
            agent=self.name,
            conversation_id=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        # ── Validate input ────────────────────────────────────────────────────
        symptom: str = (input_data.get("symptom") or "").strip()
        product_filter: str = (input_data.get("product") or "").strip()
        try:
            max_results: int = int(input_data.get("max_results") or _DEFAULT_MAX_RESULTS)
            max_results = max(1, min(max_results, 10))  # clamp to [1, 10]
        except (TypeError, ValueError):
            max_results = _DEFAULT_MAX_RESULTS

        if not symptom:
            return AgentResult.fail(
                "kb_lookup: 'symptom' is required.",
                agent=self.name,
            )

        log.info(
            "kb_lookup.searching",
            symptom_preview=symptom[:80],
            product_filter=product_filter or "(none)",
            max_results=max_results,
        )

        # ── Query known_problems — FTS first, ILIKE fallback ──────────────────
        candidates: list[KnownProblem] = await self._fetch_candidates(
            db=db,
            symptom=symptom,
            product_filter=product_filter,
            log=log,
        )

        if not candidates:
            log.info("kb_lookup.no_candidates", symptom_preview=symptom[:80])
            return AgentResult.ok(
                output={"matches": [], "total_candidates": 0},
                agent=self.name,
            )

        log.info("kb_lookup.candidates_found", count=len(candidates))

        # ── Semantic ranking via Claude ───────────────────────────────────────
        ranked_matches = await self._rank_candidates(
            context=context,
            symptom=symptom,
            candidates=candidates,
            max_results=max_results,
            log=log,
        )

        log.info(
            "kb_lookup.complete",
            ranked_count=len(ranked_matches),
            symptom_preview=symptom[:80],
        )

        return AgentResult.ok(
            output={
                "matches": ranked_matches,
                "total_candidates": len(candidates),
                "product_filter": product_filter or None,
            },
            agent=self.name,
        )

    # ── DB query helpers ──────────────────────────────────────────────────────

    async def _fetch_candidates(
        self,
        *,
        db,
        symptom: str,
        product_filter: str,
        log,
    ) -> list[KnownProblem]:
        """
        Try FTS first (search_vector GIN index).  Fall back to ILIKE on symptom
        if FTS returns zero results (handles short or stop-word-only queries).
        Apply product ILIKE filter when provided.
        """
        results: list[KnownProblem] = []

        # ── FTS query ─────────────────────────────────────────────────────────
        try:
            tsquery = func.plainto_tsquery("english", symptom)
            stmt = (
                select(KnownProblem)
                .where(KnownProblem.search_vector.op("@@")(tsquery))
                .order_by(
                    func.ts_rank_cd(KnownProblem.search_vector, tsquery).desc()
                )
                .limit(_CANDIDATE_POOL)
            )
            if product_filter:
                stmt = stmt.where(
                    KnownProblem.product.ilike(f"%{product_filter}%")
                )

            rows = await db.execute(stmt)
            results = list(rows.scalars().all())
        except Exception as exc:
            log.warning("kb_lookup.fts_error", error=str(exc))
            results = []

        # ── ILIKE fallback ────────────────────────────────────────────────────
        if not results:
            try:
                # Split symptom into first few meaningful words for ILIKE
                words = [w for w in symptom.split() if len(w) > 3][:5]
                ilike_pattern = f"%{' '.join(words[:3])}%" if words else f"%{symptom[:40]}%"

                stmt = (
                    select(KnownProblem)
                    .where(KnownProblem.symptom.ilike(ilike_pattern))
                    .limit(_CANDIDATE_POOL)
                )
                if product_filter:
                    stmt = stmt.where(
                        KnownProblem.product.ilike(f"%{product_filter}%")
                    )

                rows = await db.execute(stmt)
                results = list(rows.scalars().all())
                if results:
                    log.info("kb_lookup.ilike_fallback_used", count=len(results))
            except Exception as exc:
                log.warning("kb_lookup.ilike_error", error=str(exc))
                results = []

        return results

    # ── Claude ranking ────────────────────────────────────────────────────────

    async def _rank_candidates(
        self,
        *,
        context: AgentContext,
        symptom: str,
        candidates: list[KnownProblem],
        max_results: int,
        log,
    ) -> list[dict]:
        """
        Ask Claude to rank the candidate KnownProblem records by relevance to
        the symptom.  Returns a list of match dicts ready to return to the caller.
        """
        # Serialise candidates for the prompt (exclude search_vector)
        candidates_for_prompt = [
            {
                "index": i,
                "product": c.product,
                "symptom": c.symptom,
                "diagnosis": c.diagnosis[:300],  # truncate for token economy
            }
            for i, c in enumerate(candidates)
        ]

        anthropic_client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            from klara.rarv.runtime.prompt_registry import register_prompt
            await register_prompt(
                context.db, agent_name=self.name,
                prompt_name="_PROMPT",
                content=str(_PROMPT),
            )
        except Exception:
            pass

        try:
            response = await anthropic_client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": _RANKING_PROMPT.format(
                            symptom=symptom,
                            candidates_json=json.dumps(candidates_for_prompt, indent=2),
                            max_results=max_results,
                        ),
                    }
                ],
            )
            try:
                from klara.rarv.runtime.llm_cost import track_response
                await track_response(
                    context.db, agent_name=self.name,
                    model=context.settings.anthropic_model,
                    response=response, lead_id=getattr(context, 'lead_id', None),
                )
            except Exception:
                pass
            raw = response.content[0].text.strip()
        except Exception as exc:
            log.error("kb_lookup.claude_ranking_error", error=str(exc), exc_info=True)
            # Degrade gracefully: return candidates in DB order, unranked
            return self._format_matches(
                candidates[:max_results],
                relevance_scores=[None] * max_results,
                relevance_reasons=["(ranking unavailable — LLM error)"] * max_results,
            )

        # ── Parse Claude's JSON ranking ───────────────────────────────────────
        try:
            ranking: list[dict] = json.loads(raw)
            if not isinstance(ranking, list):
                raise ValueError("Expected a JSON array")
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("kb_lookup.ranking_parse_error", error=str(exc), raw=raw[:200])
            return self._format_matches(
                candidates[:max_results],
                relevance_scores=[None] * max_results,
                relevance_reasons=["(ranking parse error — results in DB order)"] * max_results,
            )

        # ── Build final match list ────────────────────────────────────────────
        matches: list[dict] = []
        seen_indices: set[int] = set()

        for rank_item in ranking[:max_results]:
            idx = rank_item.get("index")
            if idx is None or not isinstance(idx, int):
                continue
            if idx < 0 or idx >= len(candidates):
                continue
            if idx in seen_indices:
                continue
            seen_indices.add(idx)

            kp = candidates[idx]
            matches.append({
                "id": kp.id,
                "product": kp.product,
                "symptom": kp.symptom,
                "diagnosis": kp.diagnosis,
                "fix": kp.fix,
                "related_ticket_templates": kp.related_ticket_templates,
                "tags": kp.tags,
                "relevance_score": rank_item.get("relevance_score"),
                "relevance_reason": rank_item.get("relevance_reason"),
            })

        return matches

    @staticmethod
    def _format_matches(
        candidates: list[KnownProblem],
        relevance_scores: list,
        relevance_reasons: list,
    ) -> list[dict]:
        """Format candidates into the standard match dict without ranking data."""
        return [
            {
                "id": kp.id,
                "product": kp.product,
                "symptom": kp.symptom,
                "diagnosis": kp.diagnosis,
                "fix": kp.fix,
                "related_ticket_templates": kp.related_ticket_templates,
                "tags": kp.tags,
                "relevance_score": relevance_scores[i],
                "relevance_reason": relevance_reasons[i],
            }
            for i, kp in enumerate(candidates)
        ]
