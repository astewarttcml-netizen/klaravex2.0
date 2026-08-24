"""
app/api/social_media_admin.py
──────────────────────────────
Admin endpoints for social media post management.

All endpoints require X-API-Key authentication (same key as other admin routes).

Routes (mounted under /api/v1/admin/social-media):
  GET  /posts      — list posts with optional filters
  POST /posts      — ingest a new social post
  POST /trigger    — manually fire the beat task
  GET  /stats      — routing statistics
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from klara.rarv.runtime import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class SocialPostIngest(BaseModel):
    platform: str
    external_post_id: Optional[str] = None
    post_url: Optional[str] = None
    author_name: Optional[str] = None
    author_handle: Optional[str] = None
    content: Optional[str] = None
    is_qualified_lead: bool = False


_VALID_PLATFORMS = {"linkedin", "twitter", "instagram", "facebook", "other"}


# ── 1. List posts ─────────────────────────────────────────────────────────────

@router.get("/posts", dependencies=[Depends(verify_api_key)])
async def list_social_posts(
    platform: Optional[str] = Query(default=None),
    is_qualified_lead: Optional[bool] = Query(default=None),
    unprocessed_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Return social media posts with optional filters."""
    from klara.rarv.social_media_post import SocialMediaPost

    stmt = select(SocialMediaPost)
    if platform:
        stmt = stmt.where(SocialMediaPost.platform == platform)
    if is_qualified_lead is not None:
        stmt = stmt.where(SocialMediaPost.is_qualified_lead == is_qualified_lead)
    if unprocessed_only:
        stmt = stmt.where(SocialMediaPost.lead_id == None)  # noqa: E711

    stmt = stmt.order_by(SocialMediaPost.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    posts = result.scalars().all()

    return {
        "count": len(posts),
        "items": [
            {
                "id": p.id,
                "platform": p.platform,
                "external_post_id": p.external_post_id,
                "post_url": p.post_url,
                "author_handle": p.author_handle,
                "content": p.content[:200] if p.content else None,
                "is_qualified_lead": p.is_qualified_lead,
                "lead_id": p.lead_id,
                "processed_at": p.processed_at.isoformat() if p.processed_at else None,
                "created_at": p.created_at.isoformat(),
            }
            for p in posts
        ],
    }


# ── 2. Ingest a post ──────────────────────────────────────────────────────────

@router.post("/posts", dependencies=[Depends(verify_api_key)], status_code=status.HTTP_201_CREATED)
async def ingest_social_post(
    payload: SocialPostIngest,
    db: AsyncSession = Depends(get_db),
):
    """Ingest a social media post for processing."""
    from klara.rarv.social_media_post import SocialMediaPost

    if payload.platform not in _VALID_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"platform must be one of: {', '.join(sorted(_VALID_PLATFORMS))}",
        )

    post = SocialMediaPost(
        id=str(uuid4()),
        platform=payload.platform,
        external_post_id=payload.external_post_id,
        post_url=payload.post_url,
        author_name=payload.author_name,
        author_handle=payload.author_handle,
        content=payload.content,
        is_qualified_lead=payload.is_qualified_lead,
    )
    db.add(post)
    await db.flush()

    logger.info(
        "social_media.post_ingested",
        post_id=post.id,
        platform=post.platform,
        is_qualified_lead=post.is_qualified_lead,
    )

    return {
        "id": post.id,
        "platform": post.platform,
        "is_qualified_lead": post.is_qualified_lead,
        "created_at": post.created_at.isoformat() if post.created_at else None,
    }


# ── 3. Manual trigger ─────────────────────────────────────────────────────────

@router.post("/trigger", dependencies=[Depends(verify_api_key)])
async def trigger_social_routing():
    """Manually fire the route_qualified_social_posts Celery task."""
    from app.tasks.social_media import route_qualified_social_posts

    task = route_qualified_social_posts.apply_async(
        kwargs={"triggered_by": "manual_admin"},
        queue="default",
    )

    logger.info("social_media.manual_trigger", task_id=task.id)

    return {
        "status": "queued",
        "task_id": task.id,
        "message": "route_qualified_social_posts queued on default queue.",
    }


# ── 4. Stats ──────────────────────────────────────────────────────────────────

@router.get("/stats", dependencies=[Depends(verify_api_key)])
async def social_media_stats(db: AsyncSession = Depends(get_db)):
    """Return routing statistics for the social media pipeline."""
    from klara.rarv.social_media_post import SocialMediaPost

    total = (
        await db.execute(select(func.count(SocialMediaPost.id)))
    ).scalar_one() or 0

    qualified = (
        await db.execute(
            select(func.count(SocialMediaPost.id)).where(
                SocialMediaPost.is_qualified_lead == True  # noqa: E712
            )
        )
    ).scalar_one() or 0

    processed = (
        await db.execute(
            select(func.count(SocialMediaPost.id)).where(
                SocialMediaPost.lead_id != None  # noqa: E711
            )
        )
    ).scalar_one() or 0

    pending = (
        await db.execute(
            select(func.count(SocialMediaPost.id)).where(
                SocialMediaPost.is_qualified_lead == True,  # noqa: E712
                SocialMediaPost.lead_id == None,  # noqa: E711
            )
        )
    ).scalar_one() or 0

    return {
        "total_posts": total,
        "qualified_posts": qualified,
        "processed_posts": processed,
        "pending_routing": pending,
    }
