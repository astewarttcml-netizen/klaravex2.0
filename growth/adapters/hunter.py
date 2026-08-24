"""Hunter.io adapter — email find / verify for leads enrichment."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from growth.adapters import not_wired
from growth.adapters.credentials import creds_configured, creds_detail, _merged_env

HUNTER_API = "https://api.hunter.io/v2"


def _api_key() -> str | None:
    key = _merged_env().get("HUNTER_API_KEY", "").strip()
    return key or None


def _request(path: str, *, params: dict[str, str] | None = None, timeout: float = 20) -> dict[str, Any]:
    key = _api_key()
    if not key:
        raise RuntimeError("HUNTER_API_KEY not configured")

    q = dict(params or {})
    q["api_key"] = key
    url = f"{HUNTER_API}{path}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": os.getenv("HUNTER_USER_AGENT", "KlaravexGrowth/2.0 (+growth-api)"),
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Hunter HTTP {exc.code}: {err_body}") from exc


def probe_account() -> dict[str, Any]:
    payload = _request("/account")
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {"ok": True}
    requests = data.get("requests") if isinstance(data.get("requests"), dict) else {}
    searches = requests.get("searches") if isinstance(requests.get("searches"), dict) else {}
    verifications = requests.get("verifications") if isinstance(requests.get("verifications"), dict) else {}
    return {
        "ok": True,
        "plan": data.get("plan_name"),
        "searches_remaining": searches.get("remaining"),
        "verifications_remaining": verifications.get("remaining"),
    }


def enrich(*_args, **_kwargs) -> dict[str, Any]:
    if not creds_configured("hunter"):
        return not_wired("hunter")

    readonly = os.getenv("HUNTER_READONLY", "true").lower() in {"1", "true", "yes", "on"}
    try:
        account = probe_account()
    except Exception as exc:
        return {
            "adapter": "hunter",
            "status": "error",
            "action": "enrich",
            "detail": f"{creds_detail('hunter')} — probe failed: {exc}",
        }

    sample = {
        "plan": account.get("plan"),
        "searches_remaining": account.get("searches_remaining"),
        "verifications_remaining": account.get("verifications_remaining"),
        "mode": "readonly_probe" if readonly else "enrich_ready",
    }
    return {
        "adapter": "hunter",
        "status": "connected",
        "action": "enrich",
        "detail": (
            f"Hunter {sample.get('plan') or 'account'} — "
            f"{sample.get('searches_remaining')} searches, "
            f"{sample.get('verifications_remaining')} verifications left"
            + (
                "; leads pipeline runs find/verify after Apollo (growth/research/hunter_enrich.py)"
                if readonly
                else "; direct invoke + pipeline enrich active"
            )
        ),
        "sample": sample,
        "creds_configured": True,
    }
