"""Semantic search over klaravex.note_submissions (T-INF-09).

POST /api/v1/internal/notes/search_semantic
  Body: {"query": str, "k": int=10, "topic_slug": str?, "agent_id": str?,
         "min_score": float?}
  Returns notes ranked by cosine similarity to the query embedding.

The route is gated on ``x-loki-internal-secret`` — registered in main.py with
``dependencies=[Depends(require_internal_secret)]`` (fails closed).

Requires migration 029 (embedding column + HNSW index) and a backfill
(infra/scripts/backfill_note_embeddings.py). Rows without an embedding are
excluded from results.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .lib.db import get_pool
from .lib.embeddings import EmbeddingError, embed_text, to_pgvector

log = logging.getLogger(__name__)
router = APIRouter()


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=8000)
    k: int = Field(10, ge=1, le=100)
    topic_slug: Optional[str] = None
    agent_id: Optional[str] = None
    min_score: Optional[float] = Field(None, ge=-1.0, le=1.0)


class SemanticHit(BaseModel):
    id: int
    submission_uuid: str
    agent_id: Optional[str]
    topic_slug: Optional[str]
    note_kind: Optional[str]
    title: Optional[str]
    score: float
    created_at: Optional[str]


class SemanticSearchResponse(BaseModel):
    query: str
    count: int
    results: list[SemanticHit]


@router.post("/search_semantic", response_model=SemanticSearchResponse)
async def search_semantic(req: SemanticSearchRequest) -> SemanticSearchResponse:
    """Embed the query, then rank note_submissions by cosine similarity."""
    try:
        qvec = await embed_text(req.query)
    except EmbeddingError as exc:
        log.warning("semantic search: embedding failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"embedding backend unavailable: {exc}")

    qlit = to_pgvector(qvec)

    # $1 is always the query vector literal. Filters append positional params.
    where = ["embedding IS NOT NULL"]
    params: list = [qlit]
    if req.topic_slug:
        params.append(req.topic_slug)
        where.append(f"topic_slug = ${len(params)}")
    if req.agent_id:
        params.append(req.agent_id)
        where.append(f"agent_id = ${len(params)}")
    params.append(req.k)
    limit_pos = len(params)

    sql = (
        "SELECT id, submission_uuid, agent_id, topic_slug, note_kind, title, "
        "created_at, 1 - (embedding <=> $1::vector) AS score "
        "FROM klaravex.note_submissions "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY embedding <=> $1::vector "
        f"LIMIT ${limit_pos}"
    )

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    results: list[SemanticHit] = []
    for r in rows:
        score = float(r["score"])
        if req.min_score is not None and score < req.min_score:
            continue
        results.append(
            SemanticHit(
                id=r["id"],
                submission_uuid=str(r["submission_uuid"]),
                agent_id=r["agent_id"],
                topic_slug=r["topic_slug"],
                note_kind=r["note_kind"],
                title=r["title"],
                score=round(score, 6),
                created_at=r["created_at"].isoformat() if r["created_at"] else None,
            )
        )
    return SemanticSearchResponse(query=req.query, count=len(results), results=results)
