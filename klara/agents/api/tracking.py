"""
app/api/tracking.py
────────────────────
Public tracking endpoints for cold-outreach engagement signals (phase3-002).

  GET /api/v1/track/open/{token}              → 1x1 GIF, marks opened_at
  GET /api/v1/track/click/{token}?u={url}     → 302 redirect to url, marks last_clicked_at

Both endpoints are intentionally PUBLIC (no auth) — they're called by
email clients on behalf of recipients. The opaque tracking_token is the
only authorization signal. Unknown tokens 404 (open) / 400 (click); we
never leak which token mapped to which prospect.
"""
from __future__ import annotations

from urllib.parse import unquote

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import get_db
from app.models.proposal import Proposal, ProposalStatus
from app.services.engagement_tracker import (
    DEDUP_SECONDS,
    TRANSPARENT_GIF,
    get_prospect_by_token,
    record_click,
    record_open,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get("/track/open/{token}", include_in_schema=False)
async def track_open(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Tracking-pixel endpoint. Always returns a 1×1 transparent GIF, even on
    unknown tokens — we don't want bot scanners to enumerate valid tokens.
    """
    prospect = await get_prospect_by_token(db, token)
    if prospect is not None:
        try:
            await record_open(db, prospect)
            await db.commit()
        except Exception as exc:
            logger.warning("track_open.persist_failed", error=str(exc))
            # Still return the pixel — the email client must not see an error.

    return Response(
        content=TRANSPARENT_GIF,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma":        "no-cache",
            "Expires":       "0",
        },
    )


@router.get("/track/click/{token}", include_in_schema=False)
async def track_click(
    token: str,
    u: str = Query(..., description="Target URL (URL-encoded)"),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """
    Click-tracking redirect. Records the click then 302's to the encoded
    target URL `u`. Unknown tokens still redirect — we never block the
    user's click, we just don't record anything.
    """
    target = unquote(u)
    if not (target.startswith("http://") or target.startswith("https://")):
        raise HTTPException(status_code=400, detail="Invalid target URL")

    prospect = await get_prospect_by_token(db, token)
    if prospect is not None:
        try:
            await record_click(db, prospect, target)
            await db.commit()
        except Exception as exc:
            logger.warning("track_click.persist_failed", error=str(exc))

    return RedirectResponse(url=target, status_code=302)


# ── Proposal tracking (phase5-002) ────────────────────────────────────────────


async def _get_proposal_by_token(db: AsyncSession, token: str) -> Proposal | None:
    if not token:
        return None
    result = await db.execute(
        select(Proposal).where(Proposal.tracking_token == token)
    )
    return result.scalar_one_or_none()


@router.get("/track/proposal/open/{token}", include_in_schema=False)
async def track_proposal_open(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Open-tracking pixel for a client-facing proposal email."""
    proposal = await _get_proposal_by_token(db, token)
    if proposal is not None:
        try:
            now = datetime.now(timezone.utc)
            last = proposal.last_opened_at
            if last is None or (now - last) >= timedelta(seconds=DEDUP_SECONDS):
                if proposal.opened_at is None:
                    proposal.opened_at = now
                proposal.last_opened_at = now
                proposal.engagement_count = (proposal.engagement_count or 0) + 1
                # Status transition: sent_to_client stays — opened just stamps the column.
                await db.commit()
        except Exception as exc:
            logger.warning("track_proposal_open.persist_failed", error=str(exc))

    return Response(
        content=TRANSPARENT_GIF,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/track/proposal/click/{token}", include_in_schema=False)
async def track_proposal_click(
    token: str,
    u: str = Query(..., description="Target URL (URL-encoded)"),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Click-tracking redirect for a client-facing proposal email."""
    target = unquote(u)
    if not (target.startswith("http://") or target.startswith("https://")):
        raise HTTPException(status_code=400, detail="Invalid target URL")

    proposal = await _get_proposal_by_token(db, token)
    if proposal is not None:
        try:
            now = datetime.now(timezone.utc)
            if proposal.first_clicked_at is None:
                proposal.first_clicked_at = now
            proposal.engagement_count = (proposal.engagement_count or 0) + 1
            await db.commit()
        except Exception as exc:
            logger.warning("track_proposal_click.persist_failed", error=str(exc))

    return RedirectResponse(url=target, status_code=302)
