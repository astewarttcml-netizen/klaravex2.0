"""Reddit adapter — post approved forum replies as comments via OAuth.

Script-app password grant on the KlaravexAi account. Hard rails:
- REDDIT_READONLY defaults true; nothing posts until it is explicitly false.
- Daily comment cap and minimum interval between posts (anti-spam).
- Only ever comments on existing threads — never submits posts, never
  creates accounts, never DMs.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

from growth.adapters.credentials import _merged_env

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
COMMENT_URL = "https://oauth.reddit.com/api/comment"
ME_URL = "https://oauth.reddit.com/api/v1/me"

THREAD_ID_RE = re.compile(r"reddit\.com/r/[^/]+/comments/([a-z0-9]+)", re.I)

POSTED_LOG = Path("/home/anthony/Klaravex2.0/growth/data/reddit_posted.jsonl")
MAX_COMMENTS_PER_DAY = 5
MIN_INTERVAL_S = 600  # 10 minutes between comments


def _env(key: str, default: str = "") -> str:
    return (_merged_env().get(key) or os.getenv(key) or default).strip()


def _readonly() -> bool:
    return _env("REDDIT_READONLY", "true").lower() in {"1", "true", "yes", "on"}


def configured() -> bool:
    return bool(
        _env("REDDIT_CLIENT_ID")
        and _env("REDDIT_CLIENT_SECRET")
        and _env("REDDIT_USERNAME")
        and _env("REDDIT_PASSWORD")
    )


def _user_agent() -> str:
    return _env(
        "REDDIT_USER_AGENT",
        f"web:com.klaravex.forums:v1.0 (by /u/{_env('REDDIT_USERNAME', 'KlaravexAi')})",
    )


def _token() -> str:
    creds = f"{_env('REDDIT_CLIENT_ID')}:{_env('REDDIT_CLIENT_SECRET')}"
    import base64

    auth = base64.b64encode(creds.encode()).decode()
    data = urllib.parse.urlencode({
        "grant_type": "password",
        "username": _env("REDDIT_USERNAME"),
        "password": _env("REDDIT_PASSWORD"),
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=data,
        headers={"Authorization": f"Basic {auth}", "User-Agent": _user_agent()},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode())
    token = body.get("access_token")
    if not token:
        raise RuntimeError(f"Reddit token failed: {str(body)[:200]}")
    return token


def _posted_rows() -> list[dict]:
    if not POSTED_LOG.is_file():
        return []
    rows = []
    for line in POSTED_LOG.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def already_posted(thread_url: str) -> bool:
    tid = thread_id(thread_url)
    return any(r.get("thread_id") == tid for r in _posted_rows())


def _rate_limited() -> str | None:
    rows = _posted_rows()
    today = date.today().isoformat()
    today_rows = [r for r in rows if str(r.get("posted_at", "")).startswith(today)]
    if len(today_rows) >= MAX_COMMENTS_PER_DAY:
        return f"daily cap reached ({MAX_COMMENTS_PER_DAY})"
    if rows:
        last = max(float(r.get("ts", 0)) for r in rows)
        wait = MIN_INTERVAL_S - (time.time() - last)
        if wait > 0:
            return f"min interval — retry in {int(wait)}s"
    return None


def thread_id(url: str) -> str:
    m = THREAD_ID_RE.search(url)
    return m.group(1).lower() if m else ""


def probe() -> dict[str, Any]:
    if not configured():
        return {
            "adapter": "reddit",
            "ok": False,
            "detail": "missing REDDIT_CLIENT_ID/SECRET/USERNAME/PASSWORD in growth/.env",
        }
    token = _token()
    req = urllib.request.Request(
        ME_URL,
        headers={"Authorization": f"Bearer {token}", "User-Agent": _user_agent()},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        me = json.loads(resp.read().decode())
    return {
        "adapter": "reddit",
        "ok": True,
        "user": me.get("name"),
        "comment_karma": me.get("comment_karma"),
        "readonly": _readonly(),
    }


def post_comment(*, thread_url: str, body_markdown: str) -> dict[str, Any]:
    """Comment on an existing thread. Respects readonly, dedupe, and rate caps."""
    tid = thread_id(thread_url)
    if not tid:
        return {"ok": False, "detail": f"not a reddit thread URL: {thread_url[:80]}"}
    if not configured():
        return {"ok": False, "detail": "reddit creds not configured"}
    if already_posted(thread_url):
        return {"ok": False, "skipped": True, "detail": "already commented on this thread"}
    if _readonly():
        return {"ok": False, "skipped": True, "detail": "REDDIT_READONLY=true — set false to post"}
    limited = _rate_limited()
    if limited:
        return {"ok": False, "skipped": True, "detail": limited}

    token = _token()
    data = urllib.parse.urlencode({
        "api_type": "json",
        "thing_id": f"t3_{tid}",
        "text": body_markdown,
    }).encode()
    req = urllib.request.Request(
        COMMENT_URL,
        data=data,
        headers={"Authorization": f"Bearer {token}", "User-Agent": _user_agent()},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            out = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return {"ok": False, "detail": f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:200]}"}

    errors = (out.get("json") or {}).get("errors") or []
    if errors:
        return {"ok": False, "detail": f"reddit errors: {errors}"}

    things = ((out.get("json") or {}).get("data") or {}).get("things") or []
    comment_id = ""
    permalink = ""
    if things:
        d = things[0].get("data") or {}
        comment_id = d.get("id") or ""
        permalink = d.get("permalink") or ""

    POSTED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with POSTED_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "thread_id": tid,
            "thread_url": thread_url,
            "comment_id": comment_id,
            "permalink": permalink,
            "posted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ts": time.time(),
        }) + "\n")

    return {"ok": True, "comment_id": comment_id, "permalink": permalink}
