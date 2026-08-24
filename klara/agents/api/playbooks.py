"""
app/api/playbooks.py
────────────────────
Playbook library + suggest endpoint (prod-006).

  GET    /api/v1/playbooks/                — list, optional applies_to / q filter
  POST   /api/v1/playbooks/                — create
  GET    /api/v1/playbooks/{id}            — get one
  PUT    /api/v1/playbooks/{id}            — replace
  DELETE /api/v1/playbooks/{id}            — delete
  POST   /api/v1/playbooks/suggest         — suggest best matches for a description

The suggest endpoint takes a free-text ticket description (and optional product)
and returns ranked playbook matches scored by keyword-overlap. The PRD's other
form (`POST /api/tickets/{id}/suggest-playbook`) requires a Ticket model that
does not yet exist in this codebase; once Ticket lands the second form will
reuse the same matching helper (`_score_playbook`) so behaviour stays consistent.

All endpoints are admin-only — gated by the existing X-API-Key header.
"""
from __future__ import annotations

import re
from typing import List, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from klara.rarv.runtime import get_db
from klara.rarv.playbook import Playbook

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class PlaybookStep(BaseModel):
    description: str = Field(..., min_length=1, max_length=2_000)
    responsible_party: Optional[str] = Field(None, max_length=120)
    automation_script_ref: Optional[str] = Field(None, max_length=500)


class PlaybookBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1, max_length=10_000)
    applies_to: Optional[str] = Field(None, max_length=120)
    steps: List[PlaybookStep] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)


class PlaybookCreate(PlaybookBase):
    """Payload for POST /."""


class PlaybookUpdate(PlaybookBase):
    """Payload for PUT /{id} (full replace)."""


class PlaybookResponse(PlaybookBase):
    id: str
    created_at: str
    updated_at: str

    @classmethod
    def from_orm_row(cls, pb: Playbook) -> "PlaybookResponse":
        return cls(
            id=pb.id,
            name=pb.name,
            description=pb.description,
            applies_to=pb.applies_to,
            steps=[PlaybookStep(**s) for s in (pb.steps or [])],
            keywords=list(pb.keywords or []),
            created_at=pb.created_at.isoformat(),
            updated_at=pb.updated_at.isoformat(),
        )


class SuggestRequest(BaseModel):
    description: str = Field(
        ..., min_length=1, max_length=10_000,
        description="The free-text ticket description to match against.",
    )
    product: Optional[str] = Field(
        None, max_length=120,
        description=(
            "Optional product label. When provided, only playbooks whose "
            "applies_to matches (or is NULL — agnostic) are considered."
        ),
    )
    top_n: int = Field(5, ge=1, le=20)


class SuggestionMatch(BaseModel):
    playbook: PlaybookResponse
    score: int                       # number of keyword hits (>=1 to be returned)
    matched_keywords: List[str]      # which keywords actually fired


class SuggestResponse(BaseModel):
    matches: List[SuggestionMatch]


# ── Helpers ───────────────────────────────────────────────────────────────────

# Word-boundary tokeniser. Matches contiguous alphanumerics so "MFA" and
# "office365" stay as single tokens; "user's" splits to ["user", "s"] which
# is fine — keywords are author-controlled and won't include possessives.
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def _score_playbook(
    description_tokens: set[str], playbook: Playbook
) -> tuple[int, list[str]]:
    """
    Return (score, matched_keywords) for one playbook against a tokenised
    description. score is the count of distinct playbook.keywords that
    appear as whole tokens in the description. Case-insensitive; keywords
    are lowercased before comparison.
    """
    matched: list[str] = []
    for kw in (playbook.keywords or []):
        kw_norm = (kw or "").strip().lower()
        if not kw_norm:
            continue
        # Multi-word keywords: every token must be present (AND match).
        kw_tokens = _TOKEN_RE.findall(kw_norm)
        if not kw_tokens:
            continue
        if all(t in description_tokens for t in kw_tokens):
            matched.append(kw_norm)
    return len(matched), matched


async def _load_or_404(db: AsyncSession, playbook_id: str) -> Playbook:
    result = await db.execute(
        select(Playbook).where(Playbook.id == playbook_id)
    )
    pb = result.scalar_one_or_none()
    if pb is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playbook not found.",
        )
    return pb


# ── CRUD endpoints ────────────────────────────────────────────────────────────

@router.get(
    "/",
    response_model=List[PlaybookResponse],
    dependencies=[Depends(verify_api_key)],
    summary="List playbooks",
)
async def list_playbooks(
    applies_to: Optional[str] = Query(None, description="Exact product match."),
    q: Optional[str] = Query(
        None, min_length=1, max_length=200,
        description="Substring search on name + description.",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(Playbook).order_by(Playbook.created_at.desc())
    if applies_to:
        query = query.where(Playbook.applies_to.ilike(applies_to))
    if q:
        pattern = f"%{q}%"
        query = query.where(
            or_(Playbook.name.ilike(pattern), Playbook.description.ilike(pattern))
        )
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    rows = result.scalars().all()
    return [PlaybookResponse.from_orm_row(r) for r in rows]


@router.post(
    "/",
    response_model=PlaybookResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key)],
    summary="Create a playbook",
)
async def create_playbook(
    req: PlaybookCreate,
    db: AsyncSession = Depends(get_db),
):
    pb = Playbook(
        id=str(uuid4()),
        name=req.name,
        description=req.description,
        applies_to=req.applies_to,
        steps=[s.model_dump() for s in req.steps],
        keywords=[k.strip().lower() for k in req.keywords if k and k.strip()],
    )
    db.add(pb)
    await db.commit()
    await db.refresh(pb)
    logger.info("playbook.created", id=pb.id, name=pb.name)
    return PlaybookResponse.from_orm_row(pb)


@router.get(
    "/{playbook_id}",
    response_model=PlaybookResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Get a playbook",
)
async def get_playbook(
    playbook_id: str,
    db: AsyncSession = Depends(get_db),
):
    pb = await _load_or_404(db, playbook_id)
    return PlaybookResponse.from_orm_row(pb)


@router.put(
    "/{playbook_id}",
    response_model=PlaybookResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Replace a playbook",
)
async def update_playbook(
    playbook_id: str,
    req: PlaybookUpdate,
    db: AsyncSession = Depends(get_db),
):
    pb = await _load_or_404(db, playbook_id)
    pb.name = req.name
    pb.description = req.description
    pb.applies_to = req.applies_to
    pb.steps = [s.model_dump() for s in req.steps]
    pb.keywords = [k.strip().lower() for k in req.keywords if k and k.strip()]
    await db.commit()
    await db.refresh(pb)
    logger.info("playbook.updated", id=pb.id, name=pb.name)
    return PlaybookResponse.from_orm_row(pb)


@router.delete(
    "/{playbook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_api_key)],
    summary="Delete a playbook",
)
async def delete_playbook(
    playbook_id: str,
    db: AsyncSession = Depends(get_db),
):
    pb = await _load_or_404(db, playbook_id)
    await db.delete(pb)
    await db.commit()
    logger.info("playbook.deleted", id=playbook_id)
    return None


# ── Suggest endpoint ──────────────────────────────────────────────────────────

@router.post(
    "/suggest",
    response_model=SuggestResponse,
    dependencies=[Depends(verify_api_key)],
    summary="Suggest playbooks for a ticket description",
)
async def suggest_playbooks(
    req: SuggestRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Score every candidate playbook against the description by counting
    keyword overlaps and return the top-N matches (score >= 1, ties broken
    by name). Pure read path.

    Candidate set: when `product` is provided, only playbooks whose
    `applies_to` matches (case-insensitive) OR is NULL (product-agnostic)
    are scored. Without `product`, every playbook is a candidate.

    Slice 2 will replace this with a tsvector match score; the response
    contract (list of {playbook, score, matched_keywords}) stays the same
    so existing callers keep working.
    """
    # Build candidate query
    query = select(Playbook)
    if req.product:
        query = query.where(
            or_(
                Playbook.applies_to.is_(None),
                Playbook.applies_to.ilike(req.product),
            )
        )

    result = await db.execute(query)
    candidates: list[Playbook] = list(result.scalars().all())

    description_tokens = _tokens(req.description)

    scored: list[tuple[int, str, Playbook, list[str]]] = []
    for pb in candidates:
        score, matched = _score_playbook(description_tokens, pb)
        if score > 0:
            scored.append((score, pb.name.lower(), pb, matched))

    # Sort: score desc, then name asc (stable tie-break)
    scored.sort(key=lambda t: (-t[0], t[1]))

    matches = [
        SuggestionMatch(
            playbook=PlaybookResponse.from_orm_row(pb),
            score=score,
            matched_keywords=matched,
        )
        for (score, _name, pb, matched) in scored[: req.top_n]
    ]

    logger.info(
        "playbook.suggest",
        product=req.product,
        candidates=len(candidates),
        matches=len(matches),
        top_score=matches[0].score if matches else 0,
    )
    return SuggestResponse(matches=matches)
