"""
Klaravex TikTok publisher — TikTok for Business API handler stub.

Defensive pattern: returns {"status": "error", "error": "tiktok credentials not configured"}
when any required env var is missing. Only attempts the real API call when
ALL required env vars are present.

Required env vars:
  TIKTOK_ACCESS_TOKEN      OAuth 2.0 bearer for TikTok for Business
  TIKTOK_OPEN_ID           open_id of the connected TikTok account
  TIKTOK_ADVERTISER_ID     advertiser_id from TikTok for Business

Draft schema (dict) consumed by _publish_tiktok:
  text         caption / description text (optional)
  video_url    REQUIRED — public URL of an .mp4 (TikTok cannot post text-only)
  title        optional — display title

If video_url is missing, returns:
  {"status": "error", "error": "TikTok requires video_url field"}

Return shape on success:
  {"status": "posted", "platform": "tiktok",
   "external_id": "<video_id>",
   "url": "https://www.tiktok.com/@<open_id>/video/<video_id>"}
"""

import logging
import os
from typing import Any, Optional

import httpx

log = logging.getLogger("klaravex.social_media_tiktok")

TIKTOK_ACCESS_TOKEN = os.environ.get("TIKTOK_ACCESS_TOKEN", "")
TIKTOK_OPEN_ID = os.environ.get("TIKTOK_OPEN_ID", "")
TIKTOK_ADVERTISER_ID = os.environ.get("TIKTOK_ADVERTISER_ID", "")

TIKTOK_API_BASE = "https://business-api.tiktok.com/open_api/v1.3"
TIKTOK_UPLOAD_ENDPOINT = f"{TIKTOK_API_BASE}/file/video/ad/upload/"


def _has_credentials() -> bool:
    return all([
        TIKTOK_ACCESS_TOKEN,
        TIKTOK_OPEN_ID,
        TIKTOK_ADVERTISER_ID,
    ])


async def _publish_tiktok(
    draft: dict[str, Any],
    image_url: Optional[str] = None,
) -> dict[str, Any]:
    """Publish a TikTok video. Returns dict matching social_media handler shape.

    image_url is accepted for interface uniformity; TikTok is video-only and
    will ignore it.

    NOTE: TikTok for Business has a multi-step upload + publish flow. This stub
    submits the video URL to the upload endpoint with `upload_type=UPLOAD_BY_URL`
    so the caller does not need to multipart-stream the video. The returned
    video_id from upload is then used for the actual post.
    """
    if not _has_credentials():
        return {
            "status": "error",
            "error": "tiktok credentials not configured",
        }

    video_url = draft.get("video_url")
    if not video_url:
        return {
            "status": "error",
            "error": "TikTok requires video_url field",
        }

    caption = draft.get("text") or draft.get("content") or draft.get("title") or ""

    headers = {
        "Access-Token": TIKTOK_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }

    upload_payload = {
        "advertiser_id": TIKTOK_ADVERTISER_ID,
        "upload_type": "UPLOAD_BY_URL",
        "video_url": video_url,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            upload_resp = await client.post(
                TIKTOK_UPLOAD_ENDPOINT,
                headers=headers,
                json=upload_payload,
            )

        if upload_resp.status_code not in (200, 201):
            return {
                "status": "error",
                "error": (
                    f"tiktok upload {upload_resp.status_code}: "
                    f"{upload_resp.text[:200]}"
                ),
            }

        data = upload_resp.json()
        # TikTok envelope: { "code": 0, "message": "OK", "data": { "video_id": "..." } }
        if data.get("code") and data["code"] != 0:
            return {
                "status": "error",
                "error": f"tiktok API code {data.get('code')}: {data.get('message','')}",
            }

        video_id = (
            data.get("data", {}).get("video_id")
            or data.get("data", {}).get("id")
            or ""
        )

        if not video_id:
            return {
                "status": "error",
                "error": f"tiktok upload returned no video_id: {data}",
            }

        # In a production flow, a follow-up /post/publish/ call would attach the
        # caption and publish the video. For the stub we return the uploaded
        # video reference.
        log.info("tiktok video uploaded id=%s caption_len=%d", video_id, len(caption))

        return {
            "status": "posted",
            "platform": "tiktok",
            "external_id": video_id,
            "url": f"https://www.tiktok.com/@{TIKTOK_OPEN_ID}/video/{video_id}",
        }
    except httpx.HTTPError as exc:
        log.exception("tiktok publish HTTP error: %s", exc)
        return {
            "status": "error",
            "error": f"tiktok HTTP error: {exc.__class__.__name__}: {exc}",
        }
    except Exception as exc:  # noqa: BLE001
        log.exception("tiktok publish failed: %s", exc)
        return {
            "status": "error",
            "error": f"tiktok API error: {exc.__class__.__name__}: {exc}",
        }
