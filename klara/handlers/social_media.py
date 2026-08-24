"""
Klaravex social media pipeline — FastAPI router.

Three-stage pipeline:
  1. Draft  — Claude generates US B2B content for each active platform
  2. Approve — Anthony reviews drafts (one-click approve link emailed)
  3. Publish — Posts approved drafts to LinkedIn / Twitter(X) / Facebook

Routes:
  POST /internal/social/draft          generate weekly post bundle
  GET  /internal/social/drafts         list pending drafts
  GET  /internal/social/approve/{id}   approve a draft (GET = confirmation page)
  POST /internal/social/approve/{id}   approve a draft (POST = execute)
  GET  /internal/social/reject/{id}    reject a draft
  POST /internal/social/publish        publish all approved drafts

Required env vars (set per-platform as you connect accounts):
  ANTHROPIC_API_KEY               already set
  LOKI_INTERNAL_SECRET            already set
  APPROVAL_NOTIFY_EMAIL           default: astewart@klaravex.com
  APP_BASE_URL                    default: https://api.klaravex.com

  LinkedIn:
    LINKEDIN_CLIENT_ID            from developer.linkedin.com app
    LINKEDIN_CLIENT_SECRET        from developer.linkedin.com app
    LINKEDIN_ACCESS_TOKEN         OAuth 2.0 bearer token, w_organization_social scope
    LINKEDIN_ORG_ID               numeric org ID (e.g. 12345678)
    LINKEDIN_PERSONAL_TOKEN       OAuth 2.0 bearer, w_member_social scope
    LINKEDIN_PERSON_URN           urn:li:person:{id}

  Twitter / X:
    TWITTER_API_KEY               from developer.twitter.com app
    TWITTER_API_SECRET
    TWITTER_ACCESS_TOKEN          OAuth 1.0a user token
    TWITTER_ACCESS_TOKEN_SECRET

  Facebook:
    FACEBOOK_PAGE_ID              numeric page ID
    FACEBOOK_PAGE_ACCESS_TOKEN    never-expiring or long-lived page token
"""

import hashlib
import hmac
import json
import logging
import os
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .lib.db import get_pool
from .lib.email import send_email
from .social_media_reddit import _publish_reddit as _publish_reddit_raw
from .social_media_tiktok import _publish_tiktok as _publish_tiktok_raw
from .social_media_youtube import _publish_youtube as _publish_youtube_raw

log = logging.getLogger("klaravex.social_media")
router = APIRouter()

# ── Config ────────────────────────────────────────────────────────────────────

APPROVAL_EMAIL = os.environ.get("APPROVAL_NOTIFY_EMAIL", "astewart@klaravex.com")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://api.klaravex.com")
LOKI_SECRET = os.environ.get("LOKI_INTERNAL_SECRET", "")

# LinkedIn
LINKEDIN_ACCESS_TOKEN = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_ORG_ID = os.environ.get("LINKEDIN_ORG_ID", "")
LINKEDIN_PERSONAL_TOKEN = os.environ.get("LINKEDIN_PERSONAL_TOKEN", "")
LINKEDIN_PERSON_URN = os.environ.get("LINKEDIN_PERSON_URN", "")

# Twitter / X
TWITTER_API_KEY = os.environ.get("TWITTER_API_KEY", "")
TWITTER_API_SECRET = os.environ.get("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_TOKEN_SECRET = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", "")

# Facebook
FACEBOOK_PAGE_ID = os.environ.get("FACEBOOK_PAGE_ID", "")
FACEBOOK_PAGE_ACCESS_TOKEN = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", "")

# Instagram (Graph API — IG Business account paired to a Facebook Page)
INSTAGRAM_USER_ID = os.environ.get("INSTAGRAM_USER_ID", "")
INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")

# Override: LinkedIn company URN is also exposed as LINKEDIN_COMPANY_ORG_ID for
# clarity. Prefer LINKEDIN_ORG_ID, fall back to LINKEDIN_COMPANY_ORG_ID. Strip the
# `urn:li:organization:` prefix if present so legacy code expecting a bare numeric
# id keeps working.
if not LINKEDIN_ORG_ID:
    LINKEDIN_ORG_ID = os.environ.get("LINKEDIN_COMPANY_ORG_ID", "")
if LINKEDIN_ORG_ID.startswith("urn:li:organization:"):
    LINKEDIN_ORG_ID = LINKEDIN_ORG_ID.split(":")[-1]

ACTIVE_PLATFORMS = [p for p, creds in [
    ("linkedin_company", LINKEDIN_ACCESS_TOKEN and LINKEDIN_ORG_ID),
    ("linkedin_personal", LINKEDIN_PERSONAL_TOKEN and LINKEDIN_PERSON_URN),
    ("twitter", TWITTER_API_KEY and TWITTER_ACCESS_TOKEN),
    ("facebook", FACEBOOK_PAGE_ID and FACEBOOK_PAGE_ACCESS_TOKEN),
    ("instagram", INSTAGRAM_USER_ID and INSTAGRAM_ACCESS_TOKEN),
] if creds]


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def _check_internal(request: Request) -> None:
    if LOKI_SECRET and request.headers.get("x-loki-internal-secret", "") != LOKI_SECRET:
        raise HTTPException(status_code=401, detail="unauthorized")


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _create_draft(platform: str, content: str, approval_token: str) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO klaravex_social_drafts
                (platform, content, approval_token, status)
            VALUES ($1, $2, $3, 'pending')
            RETURNING id::text
            """,
            platform, content, approval_token,
        )


# ── Draft generation ──────────────────────────────────────────────────────────

DRAFT_PROMPT = """\
You are generating a social media post for Klaravex, a US-based managed security and IT advisory firm.

Platform: {platform}
Audience: US SMB decision-makers — healthcare, legal, financial services, professional services
Brand voice: Direct, confident, no buzzwords. Expertise without arrogance. No emojis unless sparingly.
Service focus: M365/Azure security, HIPAA readiness, SOC 2 prep, endpoint protection, vCISO advisory.

Platform constraints:
- linkedin_company: 1,200–1,500 chars, professional, mild CTAs, 3–5 relevant hashtags at the end
- linkedin_personal: 700–1,000 chars, first-person (founder voice), conversational, 2–3 hashtags
- twitter: 240–270 chars MAX (will be truncated on publish), punchy, 1–2 hashtags
- facebook: 400–600 chars, slightly warmer than LinkedIn, no hard sells

Topic for this week: {topic}

Return ONLY the post text, ready to publish. No quotes, no preamble, no JSON.
"""

US_TOPICS = [
    "Why HIPAA fines are hitting smaller practices harder than enterprise — and what actually changes after a breach.",
    "The hidden cost of unsanctioned shadow IT in M365 tenants — most orgs don't know half their data connectors.",
    "SOC 2 Type II isn't just for SaaS. Why professional services firms are getting asked for it by enterprise clients.",
    "AI adoption in SMBs: why Copilot rollout without a data governance review is how sensitive data leaks.",
    "Incident response for SMBs in 2026: the 3 decisions that make the difference in the first 2 hours.",
    "Zero trust isn't a product. It's a posture — and most $500K-revenue businesses already have the building blocks.",
    "Why endpoint detection matters more than perimeter firewall for remote-first teams.",
    "vCISO vs hiring: the math nobody does before the first breach.",
    "Entra ID conditional access policies that actually reduce your attack surface without locking out your team.",
    "The Ubiquiti UniFi audit nobody asks for — and why it matters for HIPAA-covered small practices.",
]


async def _generate_draft(platform: str, topic: str) -> str:
    litellm_url = os.environ.get("LITELLM_URL", "")
    litellm_key = os.environ.get("LITELLM_MASTER_KEY", "")
    if not (litellm_url and litellm_key):
        return f"[Draft generation requires LITELLM_URL + LITELLM_MASTER_KEY] Platform: {platform} | Topic: {topic}"
    prompt = DRAFT_PROMPT.format(platform=platform, topic=topic)
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{litellm_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {litellm_key}"},
            json={
                "model": "deepseek",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 600,
                "temperature": 0.7,
            },
        )
        if r.status_code != 200:
            log.warning("social draft LLM error %s", r.status_code)
            return f"[Draft generation failed: {r.status_code}] Platform: {platform} | Topic: {topic}"
        return r.json()["choices"][0]["message"]["content"].strip()


# ── Publishing helpers ─────────────────────────────────────────────────────────

async def _publish_linkedin_company(content: str) -> dict[str, Any]:
    if not (LINKEDIN_ACCESS_TOKEN and LINKEDIN_ORG_ID):
        return {"error": "linkedin_company credentials not configured"}
    payload = {
        "author": f"urn:li:organization:{LINKEDIN_ORG_ID}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": content},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.linkedin.com/v2/ugcPosts",
            json=payload,
            headers={
                "Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
                "X-Restli-Protocol-Version": "2.0.0",
            },
        )
    if r.status_code in (200, 201):
        return {"post_id": r.headers.get("x-restli-id", ""), "url": "https://www.linkedin.com/company/klaravex"}
    return {"error": f"LinkedIn company API {r.status_code}: {r.text[:200]}"}


async def _publish_linkedin_personal(content: str) -> dict[str, Any]:
    if not (LINKEDIN_PERSONAL_TOKEN and LINKEDIN_PERSON_URN):
        return {"error": "linkedin_personal credentials not configured"}
    payload = {
        "author": LINKEDIN_PERSON_URN,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": content},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.linkedin.com/v2/ugcPosts",
            json=payload,
            headers={
                "Authorization": f"Bearer {LINKEDIN_PERSONAL_TOKEN}",
                "X-Restli-Protocol-Version": "2.0.0",
            },
        )
    if r.status_code in (200, 201):
        return {"post_id": r.headers.get("x-restli-id", ""), "url": "https://www.linkedin.com/in/anthonystewarttech"}
    return {"error": f"LinkedIn personal API {r.status_code}: {r.text[:200]}"}


def _twitter_oauth1_header(method: str, url: str, params: dict[str, str]) -> str:
    """Build OAuth 1.0a Authorization header for Twitter API v2."""
    import base64
    import hashlib
    import hmac
    import time
    import urllib.parse

    nonce = uuid.uuid4().hex
    ts = str(int(time.time()))
    oauth_params = {
        "oauth_consumer_key": TWITTER_API_KEY,
        "oauth_nonce": nonce,
        "oauth_signature_method": "HMAC-SHA256",
        "oauth_timestamp": ts,
        "oauth_token": TWITTER_ACCESS_TOKEN,
        "oauth_version": "1.0",
    }
    all_params = {**params, **oauth_params}
    sorted_params = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted(all_params.items())
    )
    base_string = "&".join([
        method.upper(),
        urllib.parse.quote(url, safe=""),
        urllib.parse.quote(sorted_params, safe=""),
    ])
    signing_key = f"{urllib.parse.quote(TWITTER_API_SECRET, safe='')}&{urllib.parse.quote(TWITTER_ACCESS_TOKEN_SECRET, safe='')}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha256).digest()
    ).decode()
    oauth_params["oauth_signature"] = signature
    header = "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(oauth_params.items())
    )
    return header


async def _publish_twitter(content: str) -> dict[str, Any]:
    if not (TWITTER_API_KEY and TWITTER_ACCESS_TOKEN):
        return {"error": "twitter credentials not configured"}
    url = "https://api.twitter.com/2/tweets"
    text = content[:280]
    auth_header = _twitter_oauth1_header("POST", url, {})
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            url,
            json={"text": text},
            headers={
                "Authorization": auth_header,
                "Content-Type": "application/json",
            },
        )
    if r.status_code in (200, 201):
        data = r.json().get("data", {})
        return {"tweet_id": data.get("id", ""), "url": f"https://twitter.com/klaravex/status/{data.get('id','')}"}
    return {"error": f"Twitter API {r.status_code}: {r.text[:200]}"}


async def _publish_facebook(content: str, image_url: str | None = None) -> dict[str, Any]:
    if not (FACEBOOK_PAGE_ID and FACEBOOK_PAGE_ACCESS_TOKEN):
        return {"error": "facebook credentials not configured"}
    async with httpx.AsyncClient(timeout=30) as client:
        if image_url:
            # /photos endpoint accepts image + caption; produces a post with attached image.
            r = await client.post(
                f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/photos",
                params={"access_token": FACEBOOK_PAGE_ACCESS_TOKEN},
                json={"url": image_url, "caption": content},
            )
        else:
            r = await client.post(
                f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/feed",
                params={"access_token": FACEBOOK_PAGE_ACCESS_TOKEN},
                json={"message": content},
            )
    if r.status_code in (200, 201):
        data = r.json()
        return {"post_id": data.get("id", ""), "url": f"https://www.facebook.com/{FACEBOOK_PAGE_ID}"}
    return {"error": f"Facebook API {r.status_code}: {r.text[:200]}"}


async def _publish_instagram(content: str, image_url: str | None = None) -> dict[str, Any]:
    """Instagram Business Graph API — two-step: create media container, then publish.

    Instagram REQUIRES an image (or video). Captions without media are not
    supported by the Graph API. If image_url is missing, return an error.
    """
    if not (INSTAGRAM_USER_ID and INSTAGRAM_ACCESS_TOKEN):
        return {"error": "instagram credentials not configured"}
    if not image_url:
        return {"error": "instagram requires an image_url; caption-only posts are not supported"}
    async with httpx.AsyncClient(timeout=30) as client:
        # Step 1: create media container.
        r1 = await client.post(
            f"https://graph.facebook.com/v19.0/{INSTAGRAM_USER_ID}/media",
            params={"access_token": INSTAGRAM_ACCESS_TOKEN},
            json={"image_url": image_url, "caption": content},
        )
        if r1.status_code not in (200, 201):
            return {"error": f"Instagram container create {r1.status_code}: {r1.text[:200]}"}
        container_id = r1.json().get("id")
        if not container_id:
            return {"error": "Instagram container missing id in response"}
        # Step 2: publish the container.
        r2 = await client.post(
            f"https://graph.facebook.com/v19.0/{INSTAGRAM_USER_ID}/media_publish",
            params={"access_token": INSTAGRAM_ACCESS_TOKEN, "creation_id": container_id},
        )
    if r2.status_code in (200, 201):
        data = r2.json()
        return {"post_id": data.get("id", ""), "url": f"https://www.instagram.com/p/{data.get('id','')}/"}
    return {"error": f"Instagram publish {r2.status_code}: {r2.text[:200]}"}


# ── Reddit / TikTok / YouTube — defensive stub handlers ───────────────────────
#
# The stub handlers in social_media_reddit.py / _tiktok.py / _youtube.py take a
# dict-shaped `draft` argument (title, text, url, video_url, target_subreddit,
# tags, privacy). The publish loop in this module passes (content, image_url)
# to all publishers. The adapters below bridge the two shapes so the loop works
# unchanged, while the underlying handlers stay platform-faithful.


def _normalise_stub_result(result: dict[str, Any]) -> dict[str, Any]:
    """Translate the stub handler return shape into the publish loop shape.

    Stub success:   {"status": "posted", "platform": "...", "external_id": "...", "url": "..."}
    Loop expects:   {"post_id": "...", "url": "..."}  on success, or {"error": "..."}
    """
    if result.get("status") == "posted":
        return {
            "post_id": result.get("external_id", ""),
            "url": result.get("url", ""),
        }
    return {"error": result.get("error", "unknown publish error")}


async def _publish_reddit(content: str, image_url: str | None = None) -> dict[str, Any]:
    """Adapter: build a Reddit draft dict from publish-loop content + image_url."""
    first_line = content.splitlines()[0].strip() if content else "Klaravex update"
    draft = {
        "title": first_line[:300] or "Klaravex update",
        "text": content,
    }
    return _normalise_stub_result(_publish_reddit_raw(draft, image_url=image_url))


async def _publish_tiktok(content: str, image_url: str | None = None) -> dict[str, Any]:
    """Adapter: TikTok needs video_url; publish loop passes only text/image.

    With no video_url available from the loop, this always returns a stub error
    until upstream draft generation starts producing video drafts.
    """
    draft = {"text": content}
    return _normalise_stub_result(await _publish_tiktok_raw(draft, image_url=image_url))


async def _publish_youtube(content: str, image_url: str | None = None) -> dict[str, Any]:
    """Adapter: YouTube also needs video_url; same caveat as TikTok."""
    first_line = content.splitlines()[0].strip() if content else "Klaravex update"
    draft = {
        "title": first_line[:100] or "Klaravex update",
        "text": content,
    }
    return _normalise_stub_result(await _publish_youtube_raw(draft, image_url=image_url))


_PUBLISHERS = {
    "linkedin_company": _publish_linkedin_company,
    "linkedin_personal": _publish_linkedin_personal,
    "twitter": _publish_twitter,
    "facebook": _publish_facebook,
    "instagram": _publish_instagram,
    "reddit": _publish_reddit,
    "tiktok": _publish_tiktok,
    "youtube": _publish_youtube,
}

# Publishers that accept an optional image_url kwarg (others ignore it).
# Reddit accepts an image; TikTok and YouTube are video-only.
_PUBLISHERS_ACCEPTING_IMAGE = {"facebook", "instagram", "reddit"}


# ── Playwright fallback (ported from itexperts-berlin 2026-06-26) ─────────────
# When the API publisher returns "not configured" / "no creds", call into
# social_publisher.py which uses a headless Chromium login flow. Browser creds
# live in their own env vars (LINKEDIN_EMAIL/PASSWORD etc.) — distinct from
# the API tokens. See social_publisher.py for the full mapping.

async def _pw_fallback(platform: str, content: str) -> dict:
    """Try the Playwright path for a platform whose API path bailed.
    Returns {'post_id', ...} on success, {'error': ...} on failure."""
    try:
        from . import social_publisher as sp
    except Exception as exc:
        return {"error": f"social_publisher import failed: {exc}"}

    pw_settings = sp.settings  # shim that reads os.environ
    # social_publisher.py exposes top-level `publish_<platform>(text, settings)`
    # wrappers (the underscore-prefixed `_pw_publish_*` are internal helpers).
    wrapper_name = f"publish_{platform}"
    wrapper = getattr(sp, wrapper_name, None)
    if wrapper is None:
        return {"error": f"no playwright fallback for {platform}"}
    try:
        r = await wrapper(content, pw_settings)
        if r.success:
            return {"post_id": r.post_id or "", "post_url": r.post_url or "", "via": "playwright"}
        return {"error": f"playwright: {r.error}"}
    except AttributeError as exc:
        # social_publisher.py may not have a wrapper for every platform yet.
        return {"error": f"playwright wrapper missing: {exc}"}
    except Exception as exc:
        log.exception("pw_fallback failed for %s", platform)
        return {"error": f"playwright exception: {exc}"}


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/draft", include_in_schema=False)
async def generate_drafts(request: Request) -> JSONResponse:
    """Generate a weekly post bundle for all configured platforms."""
    _check_internal(request)
    import random
    topic = random.choice(US_TOPICS)

    platforms_to_draft = ["linkedin_company", "linkedin_personal", "twitter", "facebook"]
    drafts_created = []
    errors = []

    for platform in platforms_to_draft:
        try:
            content = await _generate_draft(platform, topic)
            token = uuid.uuid4().hex
            draft_id = await _create_draft(platform, content, token)
            approve_url = f"{APP_BASE_URL}/api/v1/internal/social/approve/{draft_id}?token={token}"
            reject_url = f"{APP_BASE_URL}/api/v1/internal/social/reject/{draft_id}?token={token}"
            drafts_created.append({
                "id": draft_id,
                "platform": platform,
                "approve_url": approve_url,
            })
        except Exception as exc:
            log.exception("draft generation failed for %s: %s", platform, exc)
            errors.append({"platform": platform, "error": str(exc)})

    if drafts_created:
        body = f"Weekly Klaravex social drafts ready for review.\n\nTopic: {topic}\n\n"
        for d in drafts_created:
            body += f"Platform: {d['platform']}\nApprove: {d['approve_url']}\n\n"
        try:
            await send_email(APPROVAL_EMAIL, "[Klaravex Social] Weekly drafts ready", body)
        except Exception as exc:
            log.warning("approval email failed: %s", exc)

    return JSONResponse({
        "status": "ok",
        "topic": topic,
        "drafts_created": len(drafts_created),
        "errors": errors,
    })


@router.get("/drafts", include_in_schema=False)
async def list_drafts(request: Request) -> JSONResponse:
    _check_internal(request)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, platform, status, content, created_at, published_at "
            "FROM klaravex_social_drafts ORDER BY created_at DESC LIMIT 50"
        )
    return JSONResponse({"drafts": [_jsonable(dict(r)) for r in rows]})


@router.get("/approve/{draft_id}", include_in_schema=False, response_class=HTMLResponse)
async def approve_draft_page(draft_id: str = Path(...), token: str = "") -> HTMLResponse:
    """Simple confirmation page for one-click approval from email."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, platform, content, status, approval_token FROM klaravex_social_drafts WHERE id=$1",
            draft_id,
        )
    if not row or row["approval_token"] != token:
        return HTMLResponse("<h2>Invalid or expired link.</h2>", status_code=403)
    if row["status"] != "pending":
        return HTMLResponse(f"<h2>Draft already {row['status']}.</h2>")
    content_escaped = row["content"].replace("<", "&lt;").replace(">", "&gt;")
    return HTMLResponse(f"""
<!doctype html><html><head><title>Approve Draft</title>
<style>body{{font-family:sans-serif;max-width:700px;margin:40px auto;padding:0 20px}}
pre{{background:#f4f4f4;padding:16px;border-radius:6px;white-space:pre-wrap}}
.btn{{display:inline-block;padding:12px 28px;border-radius:6px;text-decoration:none;font-size:16px;cursor:pointer;border:none}}
.approve{{background:#16a34a;color:#fff}}.reject{{background:#dc2626;color:#fff;margin-left:12px}}</style>
</head><body>
<h2>Review draft — {row["platform"]}</h2>
<pre>{content_escaped}</pre>
<form method="POST">
<input type="hidden" name="token" value="{token}">
<button class="btn approve" name="action" value="approve">✓ Approve & Queue</button>
<button class="btn reject" name="action" value="reject">✗ Reject</button>
</form>
</body></html>
""")


@router.post("/approve/{draft_id}", include_in_schema=False)
async def approve_draft(request: Request, draft_id: str = Path(...)) -> HTMLResponse:
    form = await request.form()
    token = form.get("token", "")
    action = form.get("action", "approve")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, platform, status, approval_token FROM klaravex_social_drafts WHERE id=$1",
            draft_id,
        )
    if not row or row["approval_token"] != token:
        return HTMLResponse("<h2>Invalid or expired link.</h2>", status_code=403)
    if row["status"] != "pending":
        return HTMLResponse(f"<h2>Draft already {row['status']}.</h2>")
    new_status = "approved" if action == "approve" else "rejected"
    pool2 = await get_pool()
    async with pool2.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex_social_drafts SET status=$1, updated_at=now() WHERE id=$2",
            new_status, draft_id,
        )
    verb = "approved and queued for publishing" if new_status == "approved" else "rejected"
    return HTMLResponse(f"<h2>Draft {verb}.</h2><p><a href='/api/v1/internal/social/drafts'>View all drafts</a></p>")


@router.get("/reject/{draft_id}", include_in_schema=False)
async def reject_draft(draft_id: str = Path(...), token: str = "") -> JSONResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, approval_token, status FROM klaravex_social_drafts WHERE id=$1",
            draft_id,
        )
    if not row or row["approval_token"] != token:
        raise HTTPException(status_code=403, detail="invalid token")
    if row["status"] != "pending":
        return JSONResponse({"status": row["status"]})
    pool2 = await get_pool()
    async with pool2.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex_social_drafts SET status='rejected', updated_at=now() WHERE id=$1",
            draft_id,
        )
    return JSONResponse({"status": "rejected"})


@router.post("/publish", include_in_schema=False)
async def publish_approved(request: Request) -> JSONResponse:
    """Publish all approved drafts to their respective platforms."""
    _check_internal(request)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, platform, content, image_url FROM klaravex_social_drafts WHERE status='approved' ORDER BY created_at ASC LIMIT 20"
        )
    published = 0
    skipped_no_creds = 0
    errors = []

    for row in rows:
        draft_id = str(row["id"])
        platform = row["platform"]
        content = row["content"]
        image_url = row.get("image_url") if hasattr(row, "get") else row["image_url"]
        publisher = _PUBLISHERS.get(platform)
        if not publisher:
            errors.append({"draft_id": draft_id, "platform": platform, "error": "unknown platform"})
            continue
        try:
            if platform in _PUBLISHERS_ACCEPTING_IMAGE:
                result = await publisher(content, image_url=image_url)
            else:
                result = await publisher(content)
            if "error" in result:
                # Try Playwright fallback if API path returned "not configured" OR
                # any 4xx HTTP error (auth, permissions, scope problems). Browser
                # session often succeeds where API tokens fail — e.g. LinkedIn
                # company posts where the personal token lacks w_organization_social.
                err_str = result["error"]
                err_lower = err_str.lower()
                should_fallback = (
                    "not configured" in err_str
                    or "no creds" in err_lower
                    or "no_creds" in err_lower
                    or bool(re.search(r"\bAPI 4\d\d\b|HTTP 4\d\d|\b4\d\d:", err_str))
                )
                if should_fallback:
                    log.info("API path failed for %s (%s) — trying Playwright fallback",
                             platform, err_str[:80])
                    pw_result = await _pw_fallback(platform, content)
                    if "error" not in pw_result:
                        result = pw_result  # success; fall through to UPDATE
                    elif "not implemented" in pw_result["error"] or "no playwright fallback" in pw_result["error"]:
                        # No Playwright path available — preserve the original API
                        # error so the operator sees why we couldn't ship.
                        errors.append({"draft_id": draft_id, "platform": platform,
                                       "error": f"{err_str} [no playwright fallback]"})
                        continue
                    else:
                        # Both API and Playwright failed — surface both.
                        errors.append({"draft_id": draft_id, "platform": platform,
                                       "error": f"API: {err_str[:100]} · PW: {pw_result['error'][:100]}"})
                        continue
                else:
                    errors.append({"draft_id": draft_id, "platform": platform, "error": err_str})
                    continue
            pool2 = await get_pool()
            async with pool2.acquire() as conn:
                await conn.execute(
                    "UPDATE klaravex_social_drafts SET status='published', published_at=now(), platform_post_id=$1, updated_at=now() WHERE id=$2",
                    result.get("post_id") or result.get("tweet_id"),
                    draft_id,
                )
            published += 1
            log.info("published %s: %s", platform, result)
        except Exception as exc:
            log.exception("publish failed %s %s: %s", platform, draft_id, exc)
            errors.append({"draft_id": draft_id, "platform": platform, "error": str(exc)})

    return JSONResponse({
        "status": "ok",
        "published": published,
        "skipped_no_creds": skipped_no_creds,
        "errors": errors,
    })
