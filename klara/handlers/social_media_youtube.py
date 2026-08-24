"""
Klaravex YouTube publisher — YouTube Data API v3 handler stub.

Defensive pattern: returns {"status": "error", "error": "youtube credentials not configured"}
when any required env var is missing. Only attempts the real API call when
ALL required env vars are present.

Required env vars:
  YOUTUBE_REFRESH_TOKEN    OAuth 2.0 refresh token with youtube.upload scope
  YOUTUBE_CLIENT_ID        OAuth client id from Google Cloud console
  YOUTUBE_CLIENT_SECRET    OAuth client secret
  YOUTUBE_CHANNEL_ID       channel UC… id for the @Klaravex channel

Draft schema (dict) consumed by _publish_youtube:
  text         description text
  video_url    REQUIRED — public URL of an .mp4 (YouTube cannot post text-only)
  title        REQUIRED — video title
  tags         optional list[str]
  privacy      optional one of "public", "unlisted", "private" (default "public")

If video_url is missing, returns:
  {"status": "error", "error": "YouTube requires video_url field"}

Return shape on success:
  {"status": "posted", "platform": "youtube",
   "external_id": "<video_id>",
   "url": "https://www.youtube.com/watch?v=<video_id>"}
"""

import logging
import os
from typing import Any, Optional

import httpx

log = logging.getLogger("klaravex.social_media_youtube")

YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")

GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_VIDEOS_INSERT = (
    "https://www.googleapis.com/upload/youtube/v3/videos"
    "?uploadType=resumable&part=snippet,status"
)


def _has_credentials() -> bool:
    return all([
        YOUTUBE_REFRESH_TOKEN,
        YOUTUBE_CLIENT_ID,
        YOUTUBE_CLIENT_SECRET,
        YOUTUBE_CHANNEL_ID,
    ])


async def _refresh_access_token(client: httpx.AsyncClient) -> Optional[str]:
    """Exchange the refresh token for a short-lived bearer access token."""
    r = await client.post(
        GOOGLE_OAUTH_TOKEN_URL,
        data={
            "client_id": YOUTUBE_CLIENT_ID,
            "client_secret": YOUTUBE_CLIENT_SECRET,
            "refresh_token": YOUTUBE_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
    )
    if r.status_code != 200:
        log.error("youtube token refresh failed %d: %s", r.status_code, r.text[:200])
        return None
    return r.json().get("access_token")


async def _publish_youtube(
    draft: dict[str, Any],
    image_url: Optional[str] = None,
) -> dict[str, Any]:
    """Publish a YouTube video. Returns dict matching social_media handler shape.

    image_url is accepted for interface uniformity; YouTube is video-only and
    will ignore it (thumbnails are uploaded separately via videos.thumbnails.set).

    Implementation note: The Data API v3 upload flow requires the video bytes,
    not a URL. This stub initiates a resumable upload session and downloads
    the video_url then streams it to the resumable endpoint. For very large
    videos consider chunked upload in a follow-up iteration.
    """
    if not _has_credentials():
        return {
            "status": "error",
            "error": "youtube credentials not configured",
        }

    video_url = draft.get("video_url")
    if not video_url:
        return {
            "status": "error",
            "error": "YouTube requires video_url field",
        }

    title = (draft.get("title") or "").strip() or "Klaravex update"
    description = draft.get("text") or draft.get("content") or ""
    tags = draft.get("tags") or []
    privacy = (draft.get("privacy") or "public").lower()
    if privacy not in {"public", "unlisted", "private"}:
        privacy = "public"

    snippet = {
        "snippet": {
            "title": title[:100],  # YouTube hard cap
            "description": description[:5000],
            "tags": tags[:500] if isinstance(tags, list) else [],
            "categoryId": "22",  # People & Blogs — safe default for B2B brand
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            access_token = await _refresh_access_token(client)
            if not access_token:
                return {
                    "status": "error",
                    "error": "youtube refresh-token exchange failed",
                }

            # Step 1 — initiate resumable upload session.
            init = await client.post(
                YOUTUBE_VIDEOS_INSERT,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Type": "video/*",
                },
                json=snippet,
            )
            if init.status_code not in (200, 201):
                return {
                    "status": "error",
                    "error": (
                        f"youtube resumable init {init.status_code}: "
                        f"{init.text[:200]}"
                    ),
                }
            upload_location = init.headers.get("location")
            if not upload_location:
                return {
                    "status": "error",
                    "error": "youtube resumable init missing Location header",
                }

            # Step 2 — fetch the video bytes from video_url.
            video_resp = await client.get(video_url, follow_redirects=True)
            if video_resp.status_code != 200:
                return {
                    "status": "error",
                    "error": (
                        f"failed to fetch video_url {video_resp.status_code}"
                    ),
                }
            video_bytes = video_resp.content

            # Step 3 — PUT the video bytes to the resumable session.
            upload = await client.put(
                upload_location,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "video/*",
                },
                content=video_bytes,
            )
            if upload.status_code not in (200, 201):
                return {
                    "status": "error",
                    "error": (
                        f"youtube upload {upload.status_code}: "
                        f"{upload.text[:200]}"
                    ),
                }

            data = upload.json()
            video_id = data.get("id") or ""
            if not video_id:
                return {
                    "status": "error",
                    "error": f"youtube upload returned no id: {data}",
                }

            return {
                "status": "posted",
                "platform": "youtube",
                "external_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
    except httpx.HTTPError as exc:
        log.exception("youtube publish HTTP error: %s", exc)
        return {
            "status": "error",
            "error": f"youtube HTTP error: {exc.__class__.__name__}: {exc}",
        }
    except Exception as exc:  # noqa: BLE001
        log.exception("youtube publish failed: %s", exc)
        return {
            "status": "error",
            "error": f"youtube API error: {exc.__class__.__name__}: {exc}",
        }
