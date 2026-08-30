"""Hermai.ai client — schema registry lookup + hosted fetch.

Hermai turns websites into schema-defined APIs. We use it as a structured
fallback fetch layer behind the hand-rolled scouts: where a verified schema
exists for a site, `fetch()` returns structured JSON instead of us parsing
HTML. Authenticated endpoints (session-required) still run through our own
session vault — hermai's cloud has no access to our cookies.

Env: HERMAI_API_KEY (1Password: "Hermai.ai — API Key", Klaravex vault).
Docs: https://docs.hermai.ai
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

BASE = os.getenv("HERMAI_BASE_URL", "https://api.hermai.ai")


class HermaiError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def _key() -> str:
    key = os.getenv("HERMAI_API_KEY", "")
    if not key:
        raise HermaiError("NO_KEY", "HERMAI_API_KEY not set")
    return key


def _request(method: str, path: str, payload: dict | None = None) -> dict[str, Any]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode()).get("error", {})
            raise HermaiError(err.get("code", f"HTTP_{e.code}"), err.get("message", "")) from e
        except json.JSONDecodeError:
            raise HermaiError(f"HTTP_{e.code}", e.reason) from e


def catalog(domain: str, intent: str) -> dict[str, Any]:
    """Look up known endpoints for a domain. Intent is required by the API."""
    qs = urllib.parse.urlencode({"intent": intent})
    return _request("GET", f"/v1/catalog/{domain}?{qs}")


def fetch(site: str, endpoint: str, params: dict | None = None) -> dict[str, Any]:
    """Run a registered endpoint through hermai's hosted fetch."""
    return _request(
        "POST", "/v1/fetch",
        {"site": site, "endpoint": endpoint, "params": params or {}},
    )


def probe() -> dict[str, Any]:
    """Connections-board style health check: key valid + quota reachable."""
    try:
        out = catalog("freelancermap.com", "list message conversations for inbox sync")
        return {"status": "connected", "detail": "API key valid", "sample": bool(out)}
    except HermaiError as exc:
        return {"status": "error", "error_class": exc.code, "detail": str(exc)}
