"""
app/api/social_media.py
───────────────────────
Social media inbound routes — webhook ingestion and post routing.

Endpoints (mounted at /api/v1/social):
  POST /webhook/{platform}   — ingest a social post event (LinkedIn, Twitter, etc.)
  POST /route                — manually route a specific post through SocialMediaManagerAgent
  GET  /posts                — list recent ingested posts (requires X-API-Key)

For admin routes (list/ingest/trigger/stats) see app/api/social_media_admin.py
mounted at /api/v1/admin/social-media.
"""
from typing import Optional
from datetime import datetime, timezone
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class WebhookPayload(BaseModel):
    """Generic social media webhook payload."""
    external_post_id: Optional[str] = Field(None, description="Platform post/comment ID")
    post_url: Optional[str] = Field(None, max_length=2000)
    author_name: Optional[str] = Field(None, max_length=200)
    author_handle: Optional[str] = Field(None, max_length=200)
    content: Optional[str] = Field(None, max_length=5000)
    is_qualified_lead: bool = False


class RoutePostRequest(BaseModel):
    post_id: str = Field(..., description="UUID of the SocialMediaPost to route")


_VALID_PLATFORMS = {"linkedin", "twitter", "instagram", "facebook", "other"}


# ── POST /webhook/{platform} ──────────────────────────────────────────────────

@router.post("/webhook/{platform}", status_code=status.HTTP_201_CREATED)
async def ingest_webhook(
    platform: str,
    payload: WebhookPayload,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive a social media post/mention event from a webhook.

    Creates a SocialMediaPost record. Qualified leads are picked up by the
    route_qualified_social_posts Celery beat task every 5 minutes.

    Authentication: none (webhook endpoint — caller authenticates via platform
    signature header verification, to be implemented per-platform).
    """
    if platform not in _VALID_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown platform '{platform}'. Allowed: {', '.join(sorted(_VALID_PLATFORMS))}",
        )

    from app.models.social_media_post import SocialMediaPost

    post = SocialMediaPost(
        id=str(uuid4()),
        platform=platform,
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
        "social_media.webhook_ingested",
        post_id=post.id,
        platform=platform,
        is_qualified_lead=post.is_qualified_lead,
    )

    return {
        "ok": True,
        "post_id": post.id,
        "platform": platform,
        "queued_for_routing": post.is_qualified_lead,
    }


# ── POST /route ───────────────────────────────────────────────────────────────

@router.post("/route", dependencies=[Depends(verify_api_key)])
async def route_post(
    req: RoutePostRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Manually route a specific SocialMediaPost through SocialMediaManagerAgent (P2).

    Requires X-API-Key. Used for re-processing posts or triggering routing
    outside the scheduled beat window.
    """
    from app.models.social_media_post import SocialMediaPost
    from app.agents.registry import registry
    from app.agents.base import AgentContext
    from app.config import get_settings

    result = await db.execute(select(SocialMediaPost).where(SocialMediaPost.id == req.post_id))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail=f"Post {req.post_id} not found.")

    settings = get_settings()
    context = AgentContext(db=db, settings=settings)
    agent = registry.get("social_media_manager")

    agent_result = await agent(context, {
        "post_id": str(post.id),
        "platform": post.platform,
        "author_handle": post.author_handle,
        "content": post.content,
        "is_qualified_lead": post.is_qualified_lead,
    })

    if not agent_result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=agent_result.error or "SocialMediaManagerAgent failed.",
        )

    logger.info(
        "social_media.manual_route_complete",
        post_id=req.post_id,
        output=agent_result.output,
    )

    return {
        "ok": True,
        "post_id": req.post_id,
        "result": agent_result.output,
    }


# ── GET /posts ────────────────────────────────────────────────────────────────

@router.get("/posts", dependencies=[Depends(verify_api_key)])
async def list_posts(
    platform: Optional[str] = Query(default=None),
    is_qualified_lead: Optional[bool] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List recently ingested social media posts. Requires X-API-Key."""
    from app.models.social_media_post import SocialMediaPost

    stmt = select(SocialMediaPost)
    if platform:
        stmt = stmt.where(SocialMediaPost.platform == platform)
    if is_qualified_lead is not None:
        stmt = stmt.where(SocialMediaPost.is_qualified_lead == is_qualified_lead)

    stmt = stmt.order_by(SocialMediaPost.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    posts = result.scalars().all()

    return {
        "count": len(posts),
        "items": [
            {
                "id": p.id,
                "platform": p.platform,
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
