"""Upwork OAuth 2.0 (authorization code). Tokens never appear in logs or API bodies."""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from growth.sessions.vault import sessions_dir, worker_env_path

AUTHORIZE_URL = "https://www.upwork.com/ab/account-security/oauth2/authorize"
TOKEN_URL = "https://www.upwork.com/api/v3/oauth2/token"
DEFAULT_REDIRECT = "http://127.0.0.1:4100/api/oauth/upwork/callback"
APPLY_URL = "https://www.upwork.com/developer/keys/apply"

_STATE_TTL_S = 600


def redirect_uri() -> str:
    return os.getenv("UPWORK_REDIRECT_URI", DEFAULT_REDIRECT).strip() or DEFAULT_REDIRECT


def _token_path() -> Path:
    return sessions_dir() / "upwork.oauth.json"


def _state_path() -> Path:
    return sessions_dir() / "upwork.oauth-state.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_secret_json(path: Path, data: dict[str, Any]) -> None:
    d = path.parent
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _load() -> dict[str, Any]:
    stored = _read_json(_token_path())
    env_id = os.getenv("UPWORK_CLIENT_ID", "").strip()
    env_secret = os.getenv("UPWORK_CLIENT_SECRET", "").strip()
    env_access = os.getenv("UPWORK_ACCESS_TOKEN", "").strip()
    env_refresh = os.getenv("UPWORK_REFRESH_TOKEN", "").strip()
    if env_id and not stored.get("client_id"):
        stored["client_id"] = env_id
    if env_secret and not stored.get("client_secret"):
        stored["client_secret"] = env_secret
    if env_access and not stored.get("access_token"):
        stored["access_token"] = env_access
    if env_refresh and not stored.get("refresh_token"):
        stored["refresh_token"] = env_refresh
    if not stored.get("client_id") or not stored.get("client_secret"):
        stored.update(_read_worker_client())
    return stored


def _read_worker_client() -> dict[str, str]:
    path = worker_env_path()
    if not path.is_file():
        return {}
    wanted = {
        "UPWORK_CLIENT_ID": "client_id",
        "UPWORK_CLIENT_SECRET": "client_secret",
        "UPWORK_ACCESS_TOKEN": "access_token",
        "UPWORK_REFRESH_TOKEN": "refresh_token",
    }
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        key = k.strip()
        if key in wanted and v.strip() and not v.strip().startswith("[REDACTED"):
            out.setdefault(wanted[key], v.strip().strip('"').strip("'"))
    return out


def _persist(data: dict[str, Any]) -> None:
    blob = {
        "client_id": data.get("client_id") or "",
        "client_secret": data.get("client_secret") or "",
        "access_token": data.get("access_token") or "",
        "refresh_token": data.get("refresh_token") or "",
        "token_type": data.get("token_type") or "Bearer",
        "expires_at": data.get("expires_at") or "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_secret_json(_token_path(), blob)
    from growth.sessions.vault import _upsert_worker_env

    _upsert_worker_env("UPWORK_CLIENT_ID", blob["client_id"])
    _upsert_worker_env("UPWORK_CLIENT_SECRET", blob["client_secret"])
    _upsert_worker_env("UPWORK_ACCESS_TOKEN", blob["access_token"])
    _upsert_worker_env("UPWORK_REFRESH_TOKEN", blob["refresh_token"])


def save_client(client_id: str, client_secret: str) -> dict[str, Any]:
    cid = client_id.strip()
    secret = client_secret.strip()
    if len(cid) < 8 or len(secret) < 8:
        raise ValueError("Upwork client id and secret are required")
    data = _load()
    data["client_id"] = cid
    data["client_secret"] = secret
    _persist(data)
    return public_status()


def client_configured() -> bool:
    data = _load()
    return bool(data.get("client_id") and data.get("client_secret"))


def token_present() -> bool:
    data = _load()
    return bool(data.get("access_token"))


def public_status() -> dict[str, Any]:
    data = _load()
    return {
        "adapter": "upwork",
        "action": "oauth",
        "client_configured": client_configured(),
        "token_present": token_present(),
        "redirect_uri": redirect_uri(),
        "apply_url": APPLY_URL,
        "expires_at": data.get("expires_at") or None,
        "sample": {"has_refresh": bool(data.get("refresh_token"))},
    }


def authorize_url() -> dict[str, str]:
    data = _load()
    client_id = data.get("client_id") or ""
    if not client_id:
        raise ValueError(
            f"UPWORK_CLIENT_ID missing — create an app at {APPLY_URL} "
            "(OAuth 2.0, permission: Read marketplace Job Postings) and paste the keys on Connections"
        )
    state = secrets.token_urlsafe(32)
    _write_secret_json(
        _state_path(),
        {"state": state, "created_at": int(time.time())},
    )
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "state": state,
    }
    return {"authorize_url": f"{AUTHORIZE_URL}?{urlencode(params)}", "state": state}


def _valid_state(state: str) -> bool:
    rec = _read_json(_state_path())
    saved = rec.get("state") or ""
    created = int(rec.get("created_at") or 0)
    if not state or not saved or state != saved:
        return False
    if time.time() - created > _STATE_TTL_S:
        return False
    return True


def _token_request(form: dict[str, str]) -> dict[str, Any]:
    body = urlencode(form).encode("utf-8")
    req = Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except Exception as exc:
        from urllib.error import HTTPError

        if isinstance(exc, HTTPError):
            raw = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"Upwork token HTTP {exc.code}") from None
        raise RuntimeError(f"Upwork token request failed ({type(exc).__name__})") from None
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        raise RuntimeError("Upwork token response was not JSON") from None
    if status >= 400 or not isinstance(payload, dict) or not payload.get("access_token"):
        raise RuntimeError("Upwork token exchange failed")
    return payload


def exchange_code(code: str, state: str) -> dict[str, Any]:
    if not code.strip():
        raise ValueError("missing authorization code")
    if not _valid_state(state):
        raise ValueError("invalid or expired OAuth state")
    data = _load()
    payload = _token_request(
        {
            "grant_type": "authorization_code",
            "client_id": data["client_id"],
            "client_secret": data["client_secret"],
            "code": code.strip(),
            "redirect_uri": redirect_uri(),
        }
    )
    _apply_token_payload(data, payload)
    if _state_path().is_file():
        _state_path().unlink()
    return public_status()


def _apply_token_payload(data: dict[str, Any], payload: dict[str, Any]) -> None:
    expires_in = int(payload.get("expires_in") or 86400)
    data["access_token"] = payload["access_token"]
    if payload.get("refresh_token"):
        data["refresh_token"] = payload["refresh_token"]
    data["token_type"] = payload.get("token_type") or "Bearer"
    data["expires_at"] = datetime.fromtimestamp(time.time() + expires_in, tz=timezone.utc).isoformat()
    _persist(data)


def refresh_access_token() -> str:
    data = _load()
    refresh = data.get("refresh_token") or ""
    if not refresh:
        raise RuntimeError("no Upwork refresh token — authorize again")
    payload = _token_request(
        {
            "grant_type": "refresh_token",
            "client_id": data["client_id"],
            "client_secret": data["client_secret"],
            "refresh_token": refresh,
        }
    )
    _apply_token_payload(data, payload)
    return data["access_token"]


def get_access_token() -> str | None:
    data = _load()
    token = data.get("access_token") or ""
    if not token:
        return None
    expires_at = data.get("expires_at") or ""
    try:
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
    except ValueError:
        exp = 0
    if exp and time.time() > exp - 120:
        try:
            return refresh_access_token()
        except Exception:
            return token
    return token


def delete_tokens() -> None:
    data = _load()
    data["access_token"] = ""
    data["refresh_token"] = ""
    data["expires_at"] = ""
    _persist(data)
    if _state_path().is_file():
        _state_path().unlink()
