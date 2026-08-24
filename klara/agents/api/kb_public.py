"""
app/api/kb_public.py
─────────────────────
Public Knowledge Base search endpoint (phase11-003).

  GET /api/v1/kb-public/search?q=...

No authentication — same surface as a public docs site. Used by:
  · the /kb landing page for self-service
  · search engines for SEO indexing
  · clients looking for known fixes before opening a ticket

Returns a sanitised subset of KnownProblem fields (product, symptom,
diagnosis, fix_steps_markdown). Internal-only fields like author/created
timestamps and any "private" entries are NOT exposed.
"""
from __future__ import annotations

from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import get_db
from klara.rarv.known_problem import KnownProblem

logger = structlog.get_logger(__name__)
router = APIRouter()


class KbEntry(BaseModel):
    id: str
    product: Optional[str]
    symptom: Optional[str]
    diagnosis: Optional[str]
    fix_steps_markdown: Optional[str]


class KbSearchResponse(BaseModel):
    query: str
    total: int
    items: List[KbEntry]


@router.get("/search", response_model=KbSearchResponse)
async def kb_search(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> KbSearchResponse:
    """Search the public KB. Uses ILIKE matching on product/symptom/diagnosis.

    We deliberately do NOT use the search_vector FTS column here — it's
    English-only and the public surface needs to match across both
    languages without surprises. ILIKE is fast enough for the KB size
    (low hundreds of rows).
    """
    pattern = f"%{q}%"
    base = select(KnownProblem).where(
        or_(
            KnownProblem.product.ilike(pattern),
            KnownProblem.symptom.ilike(pattern),
            KnownProblem.diagnosis.ilike(pattern),
        )
    ).limit(limit)

    rows = (await db.execute(base)).scalars().all()
    items = [
        KbEntry(
            id=r.id,
            product=r.product,
            symptom=r.symptom,
            diagnosis=r.diagnosis,
            fix_steps_markdown=getattr(r, "fix_steps_markdown", None) or getattr(r, "fix_steps", None),
        )
        for r in rows
    ]

    return KbSearchResponse(query=q, total=len(items), items=items)
