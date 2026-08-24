"""Zernio / Late adapter — draft TikTok + YouTube Shorts (and other platforms).

Requires ``ZERNIO_API_KEY`` (aliases ``LATE_API_KEY`` / ``POSTLY_API_KEY``) in
process env or ``~/.config/social/.env``. Posts as **drafts** by default
(``publishNow=false``) so Nadia can approve in the Zernio UI.
"""

from __future__ import annotations

import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from growth.adapters import not_wired, poc_sandbox
from growth.poc import is_poc_mode

DEFAULT_V1 = "https://getlate.dev/api/v1"
SOCIAL_ENV = Path.home() / ".config" / "social" / ".env"
SOCIAL_CONFIG = Path.home() / ".config" / "social" / "config.json"


def _readonly() -> bool:
    return os.getenv("ZERNIO_READONLY", "true").lower() in {"1", "true", "yes", "on"}


def _load_social_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if SOCIAL_ENV.is_file():
        for line in SOCIAL_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _api_key() -> str | None:
    env = {**_load_social_env(), **{k: v for k, v in os.environ.items() if v}}
    for k in ("ZERNIO_API_KEY", "LATE_API_KEY", "POSTLY_API_KEY"):
        val = (env.get(k) or "").strip()
        if val:
            return val
    return None


def _base_url() -> str:
    if SOCIAL_CONFIG.is_file():
        try:
            cfg = json.loads(SOCIAL_CONFIG.read_text(encoding="utf-8"))
            for key in ("v1Url", "baseUrl"):
                raw = (cfg.get(key) or "").rstrip("/")
                if raw.endswith("/api/v1"):
                    return raw
                if raw.endswith("/api"):
                    return raw + "/v1"
                if "getlate.dev" in raw or "zernio.com" in raw:
                    return raw if raw.endswith("/v1") else f"{raw}/api/v1"
        except json.JSONDecodeError:
            pass
    return os.getenv("ZERNIO_API_BASE", DEFAULT_V1).rstrip("/")


def _request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60,
) -> Any:
    key = _api_key()
    if not key:
        raise RuntimeError("ZERNIO_API_KEY not configured")
    url = f"{_base_url()}{path}"
    hdrs = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": "KlaravexGrowth/2.0 (+zernio-adapter)",
    }
    body = data
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return None
            if raw.lstrip().startswith("<!") or raw.lstrip().startswith("<html"):
                raise RuntimeError(f"Zernio non-JSON response for {path} (likely wrong route)")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Zernio HTTP {exc.code}: {err}") from exc


def list_accounts() -> list[dict[str, Any]]:
    data = _request("GET", "/accounts")
    if isinstance(data, dict) and isinstance(data.get("accounts"), list):
        return data["accounts"]
    if isinstance(data, list):
        return data
    return []


def account_id_for(platform: str) -> str | None:
    want = platform.lower().strip()
    for acc in list_accounts():
        p = str(acc.get("platform") or "").lower()
        if p == want or (want == "twitter" and p in {"twitter", "x"}):
            aid = acc.get("id") or acc.get("_id") or acc.get("accountId")
            if aid:
                return str(aid)
    return None


def list_accounts_summary() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for acc in list_accounts():
        out.append(
            {
                "platform": str(acc.get("platform") or ""),
                "username": str(acc.get("username") or acc.get("handle") or acc.get("name") or ""),
                "id": str(acc.get("id") or acc.get("_id") or acc.get("accountId") or ""),
            }
        )
    return out


def upload_media(path: Path) -> str:
    """Upload local media; return public URL for posts.create."""
    raw = path.read_bytes()
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    # Late/Zernio: POST /media/presign → PUT uploadUrl → use publicUrl
    try:
        presign = _request(
            "POST",
            "/media/presign",
            json_body={"filename": path.name, "contentType": ctype},
        )
    except RuntimeError:
        presign = None

    if isinstance(presign, dict) and presign.get("uploadUrl") and presign.get("publicUrl"):
        upload_url = presign["uploadUrl"]
        req = urllib.request.Request(
            upload_url,
            data=raw,
            method="PUT",
            headers={"Content-Type": ctype},
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            resp.read()
        return str(presign["publicUrl"])

    raise RuntimeError(f"media presign failed: {presign!r}"[:300])


def draft_post(
    *,
    content: str,
    platform: str,
    media_path: Path | None = None,
    title: str | None = None,
    publish_now: bool = False,
    scheduled_for: str | None = None,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    if is_poc_mode():
        return poc_sandbox(
            "zernio",
            "draft",
            {
                "platform": platform,
                "content_chars": len(content),
                "media": str(media_path) if media_path else None,
                "publish_now": publish_now,
                "scheduled_for": scheduled_for,
                "timezone": timezone_name,
            },
        )
    if not _api_key():
        return not_wired("zernio")
    if _readonly() and publish_now:
        return {
            "adapter": "zernio",
            "status": "readonly",
            "detail": "ZERNIO_READONLY=true — refusing publishNow; set false to go live",
            "platform": platform,
        }

    account_id = account_id_for(platform)
    if not account_id:
        return {
            "adapter": "zernio",
            "status": "error",
            "detail": f"no connected Zernio account for platform={platform}",
            "platform": platform,
        }

    media_urls: list[str] = []
    if media_path is not None:
        media_urls.append(upload_media(media_path))

    platform_entry: dict[str, Any] = {"platform": platform, "accountId": account_id}
    if platform == "youtube" and title:
        platform_entry["platformSpecificData"] = {
            "title": title[:100],
            "visibility": "public",
            "containsSyntheticMedia": True,
        }

    tz_name = (
        timezone_name
        or os.getenv("GROWTH_TIMEZONE", "America/New_York")
    )
    body: dict[str, Any] = {
        "content": content,
        "platforms": [platform_entry],
        "publishNow": bool(publish_now and not scheduled_for),
        "timezone": tz_name,
    }
    if scheduled_for:
        body["scheduledFor"] = scheduled_for
        body["publishNow"] = False
    if media_urls:
        body["mediaUrls"] = media_urls
        body["mediaItems"] = [{"type": "video", "url": u} for u in media_urls]

    try:
        result = _request("POST", "/posts", json_body=body)
    except RuntimeError as exc:
        return {
            "adapter": "zernio",
            "status": "error",
            "detail": str(exc),
            "platform": platform,
        }

    return {
        "adapter": "zernio",
        "status": "connected",
        "action": "publish" if body.get("publishNow") else ("scheduled" if scheduled_for else "draft"),
        "platform": platform,
        "account_id": account_id,
        "media_urls": media_urls,
        "timezone": tz_name,
        "scheduled_for": scheduled_for,
        "result": result,
        "creds_configured": True,
    }


def draft(payload: dict[str, Any] | None = None, **_kwargs) -> dict[str, Any]:
    """Probe or create a draft. Empty payload → credential/account probe only."""
    if is_poc_mode():
        return poc_sandbox("zernio", "draft", {"platforms": ["tiktok", "youtube"]})

    if not _api_key():
        return not_wired("zernio")

    data = dict(payload or {})
    data.update({k: v for k, v in _kwargs.items() if v is not None})
    content = str(data.get("content") or "").strip()
    if not content:
        try:
            accounts = list_accounts()
            platforms = sorted(
                {str(a.get("platform")) for a in accounts if a.get("platform")}
            )
            return {
                "adapter": "zernio",
                "status": "connected",
                "action": "probe",
                "detail": f"{len(accounts)} accounts · platforms={platforms}",
                "creds_configured": True,
                "sample": {"platforms": platforms},
            }
        except RuntimeError as exc:
            return {
                "adapter": "zernio",
                "status": "error",
                "detail": str(exc),
                "creds_configured": True,
            }

    media = data.get("media_path")
    return draft_post(
        content=content,
        platform=str(data.get("platform") or "tiktok"),
        media_path=Path(media) if media else None,
        title=data.get("title"),
        publish_now=bool(data.get("publish_now")),
    )
