"""
Klaravex Reddit publisher — PRAW-based handler stub.

Defensive pattern: returns {"status": "error", "error": "reddit credentials not configured"}
when any required env var is missing. Only attempts the real Reddit submission when
ALL required env vars are present.

Required env vars:
  REDDIT_CLIENT_ID         from https://www.reddit.com/prefs/apps "script" app
  REDDIT_CLIENT_SECRET     from same app
  REDDIT_USERNAME          account that owns/moderates the target subreddit
  REDDIT_PASSWORD          account password (PRAW script-flow requirement)
  REDDIT_USER_AGENT        default "klaravex-loki/1.0" — Reddit requires unique UA

Draft schema (dict) consumed by _publish_reddit:
  title              required — submission title
  text               optional — selftext body for a text post
  url                optional — if present, makes a link post (overrides text)
  target_subreddit   optional — default "klaravex" (without leading r/)

Return shape on success:
  {"status": "posted", "platform": "reddit",
   "external_id": "<submission_id>",
   "url": "https://www.reddit.com/r/<sub>/comments/<id>/"}

Return shape on failure:
  {"status": "error", "error": "<message>"}
"""

import logging
import os
from typing import Any, Optional

log = logging.getLogger("klaravex.social_media_reddit")

REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USERNAME = os.environ.get("REDDIT_USERNAME", "")
REDDIT_PASSWORD = os.environ.get("REDDIT_PASSWORD", "")
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "klaravex-loki/1.0")

DEFAULT_SUBREDDIT = "klaravex"


def _has_credentials() -> bool:
    return all([
        REDDIT_CLIENT_ID,
        REDDIT_CLIENT_SECRET,
        REDDIT_USERNAME,
        REDDIT_PASSWORD,
    ])


def _publish_reddit(draft: dict[str, Any], image_url: Optional[str] = None) -> dict[str, Any]:
    """Publish a Reddit submission. Returns dict matching social_media handler shape.

    image_url is accepted for interface uniformity; Reddit image uploads require
    media-uploading via PRAW (submit_image) which is not yet implemented in the
    stub. Image-bearing drafts fall back to a link post if draft["url"] is set,
    or a text post otherwise.
    """
    if not _has_credentials():
        return {
            "status": "error",
            "error": "reddit credentials not configured",
        }

    title = (draft.get("title") or "").strip()
    if not title:
        # Some social drafts in this schema only carry "content"/"text"; use first
        # line of content as a fallback title.
        body = (draft.get("text") or draft.get("content") or "").strip()
        if body:
            first_line = body.splitlines()[0].strip()
            title = first_line[:300] if first_line else "Klaravex update"
        else:
            return {"status": "error", "error": "reddit submission requires a title"}

    body_text = draft.get("text") or draft.get("content") or ""
    link_url = draft.get("url")
    subreddit_name = (draft.get("target_subreddit") or DEFAULT_SUBREDDIT).lstrip("r/").lstrip("/")

    try:
        import praw  # type: ignore
    except ImportError:
        return {
            "status": "error",
            "error": "reddit handler requires praw (pip install praw>=7.0)",
        }

    try:
        reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            username=REDDIT_USERNAME,
            password=REDDIT_PASSWORD,
            user_agent=REDDIT_USER_AGENT,
            check_for_async=False,
        )
        subreddit = reddit.subreddit(subreddit_name)

        if link_url:
            submission = subreddit.submit(title=title, url=link_url)
        else:
            submission = subreddit.submit(title=title, selftext=body_text or title)

        submission_id = getattr(submission, "id", "")
        permalink = getattr(submission, "permalink", "")
        if permalink and not permalink.startswith("http"):
            published_url = f"https://www.reddit.com{permalink}"
        else:
            published_url = permalink or (
                f"https://www.reddit.com/r/{subreddit_name}/comments/{submission_id}/"
            )

        return {
            "status": "posted",
            "platform": "reddit",
            "external_id": submission_id,
            "url": published_url,
        }
    except Exception as exc:  # noqa: BLE001 — surface any PRAW exception
        log.exception("reddit publish failed: %s", exc)
        return {
            "status": "error",
            "error": f"reddit API error: {exc.__class__.__name__}: {exc}",
        }
