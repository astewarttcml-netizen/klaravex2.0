"""Read-only health probes for freelance session cookies. Never log cookie values."""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from typing import Any

from growth.sessions.vault import PLATFORMS, cookie_present, get_cookie, metadata

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_CTX = ssl.create_default_context()

_LOGIN_HINTS = ("login", "sign-in", "signin", "account-security/login", "log in")


def _fetch(url: str, cookie: str, timeout: float = 8) -> tuple[int | None, str, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml",
            "Cookie": cookie,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
            body = resp.read(4000).decode("utf-8", errors="replace")
            return resp.status, resp.geturl(), body
    except urllib.error.HTTPError as exc:
        body = exc.read(1500).decode("utf-8", errors="replace")
        return exc.code, getattr(exc, "url", url) or url, body
    except Exception as exc:
        return None, url, f"{type(exc).__name__}: {exc}"[:180]


def _looks_logged_out(url: str, body: str) -> bool:
    blob = f"{url} {body[:800]}".lower()
    return any(h in blob for h in _LOGIN_HINTS)


def probe(platform: str) -> dict[str, Any]:
    if platform not in PLATFORMS:
        raise KeyError(platform)
    spec = PLATFORMS[platform]
    label = spec["label"]
    cookie = get_cookie(platform)
    meta = metadata(platform) or {}
    base = {
        "adapter": platform,
        "action": "probe",
        "creds_configured": cookie_present(platform),
        "sample": {"source": meta.get("source"), "stored_at": meta.get("stored_at")},
    }
    if not cookie:
        return {
            **base,
            "status": "stub",
            "detail": (
                f"{label}: no session. Google SSO: python -m growth.sessions.login --all"
            ),
        }

    status, final_url, body = _fetch(spec["home_url"], cookie)
    if status is None:
        return {
            **base,
            "status": "error",
            "detail": f"{label}: session saved but probe failed ({body})",
        }
    if status in {401, 403} or _looks_logged_out(final_url, body):
        return {
            **base,
            "status": "error",
            "detail": (
                f"{label}: cookie present but session is dead (HTTP {status}). "
                f"Log in again (python -m growth.sessions.login {platform})."
            ),
        }
    if status >= 400:
        return {
            **base,
            "status": "error",
            "detail": f"{label}: probe HTTP {status}",
        }
    return {
        **base,
        "status": "connected",
        "detail": f"{label} session live (HTTP {status})",
        "sample": {**base["sample"], "http": status},
    }


def probe_upwork(*_a, **_k) -> dict[str, Any]:
    return probe("upwork")


def probe_guru(*_a, **_k) -> dict[str, Any]:
    return probe("guru")


def probe_peopleperhour(*_a, **_k) -> dict[str, Any]:
    return probe("peopleperhour")
