"""Taplio adapter — LinkedIn draft/schedule via official REST API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from growth.adapters import not_wired, poc_sandbox
from growth.adapters.credentials import creds_configured, creds_detail, _merged_env
from growth.poc import is_poc_mode

DEFAULT_BASE = "https://api.taplio.com"


def _api_key() -> str | None:
    key = _merged_env().get("TAPLIO_API_KEY", "").strip()
    return key or None


def _base_url() -> str:
    return os.getenv("TAPLIO_BASE_URL", DEFAULT_BASE).rstrip("/")


def _readonly() -> bool:
    raw = (_merged_env().get("TAPLIO_READONLY") or os.getenv("TAPLIO_READONLY") or "true").strip()
    return raw.lower() in {"1", "true", "yes", "on"}


def _request(method: str, path: str, *, body: dict[str, Any] | None = None, timeout: float = 20) -> dict[str, Any]:
    key = _api_key()
    if not key:
        raise RuntimeError("TAPLIO_API_KEY not configured")

    url = f"{_base_url()}{path}"
    data = None
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": os.getenv("TAPLIO_USER_AGENT", "KlaravexGrowth/2.0 (+growth-api)"),
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Taplio HTTP {exc.code}: {err_body}") from exc


def probe_account() -> dict[str, Any]:
    """Read-only identity check (GET /v1/me)."""
    payload = _request("GET", "/v1/me")
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {"ok": True, "raw_keys": list(payload.keys()) if isinstance(payload, dict) else []}
    return {
        "ok": True,
        "name": data.get("name"),
        "username": data.get("username"),
    }


def create_draft(*, content: str) -> dict[str, Any]:
    """Create a Taplio draft (POST /v1/posts/drafts)."""
    text = content.strip()
    if not text:
        raise RuntimeError("empty content")
    payload = _request("POST", "/v1/posts/drafts", body={"content": text})
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError("Taplio returned empty draft response")
    return {
        "draft_id": data.get("id"),
        "status": data.get("status"),
        "content_preview": (data.get("content") or "")[:120],
    }


def schedule_draft(*, draft_id: str, scheduled_for: str) -> dict[str, Any]:
    """Schedule a draft (POST /v1/posts/drafts/{id}/schedule).

    HARD BLOCK: Taplio must not auto-post. Scheduling is publish-adjacent and is
    disabled unless TAPLIO_ALLOW_SCHEDULE=true (operator override only).
    """
    allow = (_merged_env().get("TAPLIO_ALLOW_SCHEDULE") or os.getenv("TAPLIO_ALLOW_SCHEDULE") or "false").strip()
    if allow.lower() not in {"1", "true", "yes", "on"}:
        raise RuntimeError(
            "Taplio schedule/publish blocked — TAPLIO_ALLOW_SCHEDULE is not enabled "
            "(drafts only; human posts from Taplio UI)"
        )
    did = draft_id.strip()
    when = scheduled_for.strip()
    if not did or not when:
        raise RuntimeError("draft_id and scheduled_for required")
    payload = _request(
        "POST",
        f"/v1/posts/drafts/{did}/schedule",
        body={"scheduled_for": when},
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError("Taplio returned empty schedule response")
    return {
        "draft_id": data.get("id"),
        "status": data.get("status"),
        "scheduled_for": when,
    }


def draft(payload: dict[str, Any] | None = None, **_kwargs) -> dict[str, Any]:
    if is_poc_mode():
        return poc_sandbox(
            "taplio",
            "draft",
            {"platform": "linkedin", "account": "@poc", "draft_status": "draft"},
        )

    if not creds_configured("taplio"):
        return not_wired("taplio")

    data = dict(payload or {})
    data.update({k: v for k, v in _kwargs.items() if v is not None})

    content = str(data.get("content") or data.get("text") or "").strip()
    scheduled_for = str(data.get("scheduled_for") or os.getenv("TAPLIO_SCHEDULE_FOR") or "").strip()
    # Default: next 10:00 America/New_York when caller asks to schedule without a time
    if not scheduled_for and data.get("schedule_us_default"):
        from growth.timeutil import schedule_iso

        scheduled_for = schedule_iso(hour=10, minute=0, coast="east")

    if content:
        if _readonly():
            return {
                "adapter": "taplio",
                "status": "connected",
                "action": "draft",
                "detail": "TAPLIO_READONLY=true — set false to create live Taplio drafts (never auto-schedules)",
                "creds_configured": True,
                "sample": {
                    "content_chars": len(content),
                    "scheduled_for": None,
                    "dry_run": True,
                },
            }
        try:
            # Draft only — never call schedule_draft here. Taplio cannot/must not
            # auto-post; humans publish from the Taplio UI after review.
            result = create_draft(content=content)
            if scheduled_for:
                result["schedule_requested"] = scheduled_for
                result["schedule_skipped"] = "TAPLIO_ALLOW_SCHEDULE required; drafts stay unscheduled"
            account = probe_account()
            return {
                "adapter": "taplio",
                "status": "connected",
                "action": "draft",
                "detail": (
                    f"Taplio draft {result.get('draft_id')} "
                    f"({result.get('status')}) for @{account.get('username') or account.get('name')} "
                    "(unscheduled — human publish only)"
                ),
                "sample": result,
                "creds_configured": True,
            }
        except Exception as exc:
            return {
                "adapter": "taplio",
                "status": "error",
                "action": "draft",
                "detail": f"{creds_detail('taplio')} — draft failed: {exc}",
            }

    try:
        account = probe_account()
    except Exception as exc:
        return {
            "adapter": "taplio",
            "status": "error",
            "action": "draft",
            "detail": f"{creds_detail('taplio')} — probe failed: {exc}",
        }

    mode = "readonly_probe" if _readonly() else "draft_ready"
    return {
        "adapter": "taplio",
        "status": "connected",
        "action": "draft",
        "detail": (
            f"LinkedIn account @{account.get('username') or account.get('name')} — "
            + (
                "read-only probe OK; set TAPLIO_READONLY=false + APPROVED socials draft to push"
                if _readonly()
                else "ready for draft/schedule API"
            )
        ),
        "sample": {
            "platform": "linkedin",
            "account": account.get("username") or account.get("name"),
            "mode": mode,
        },
        "creds_configured": True,
    }
