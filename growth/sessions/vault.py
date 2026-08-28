"""Session-cookie vault for freelance platforms that have no bid API.

Cookies live in ``growth/data/sessions/<platform>.cookie`` (mode 0600), with a
JSON sidecar of metadata that never includes the secret. Lookup order:

1. Vault file
2. ``UPWORK_SESSION_COOKIE`` / ``GURU_SESSION_COOKIE`` / ``PPH_SESSION_COOKIE`` / ``FREELANCERMAP_SESSION_COOKIE``
3. Worker ``.env`` (canonical Klaravex worker file)

Values containing ``[REDACTED`` are treated as absent (sanitized dumps).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PLATFORMS: dict[str, dict[str, str]] = {
    "upwork": {
        "label": "Upwork",
        "env": "UPWORK_SESSION_COOKIE",
        "login_url": "https://www.upwork.com/ab/account-security/login",
        "home_url": "https://www.upwork.com/nx/find-work/best-matches",
        "cookie_domain": ".upwork.com",
    },
    "guru": {
        "label": "Guru",
        "env": "GURU_SESSION_COOKIE",
        "login_url": "https://www.guru.com/login.aspx",
        "home_url": "https://www.guru.com/pro/",
        "cookie_domain": ".guru.com",
    },
    "peopleperhour": {
        "label": "PeoplePerHour",
        "env": "PPH_SESSION_COOKIE",
        "login_url": "https://www.peopleperhour.com/site/login",
        "home_url": "https://www.peopleperhour.com/freelance/dashboard",
        "cookie_domain": ".peopleperhour.com",
    },
    "freelancer": {
        "label": "Freelancer.com",
        "env": "FREELANCER_ACCESS_TOKEN",
        "login_url": "https://www.freelancer.com/developers",
        "home_url": "https://www.freelancer.com/dashboard",
        "cookie_domain": ".freelancer.com",
    },
    "freelancermap": {
        "label": "FreelancerMap",
        "env": "FREELANCERMAP_SESSION_COOKIE",
        "login_url": "https://www.freelancermap.de/login",
        "home_url": "https://www.freelancermap.de/mein_account.html",
        "cookie_domain": ".freelancermap.de",
    },
}

_REDACTED = re.compile(r"\[REDACTED", re.I)


def _growth_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sessions_dir() -> Path:
    explicit = os.getenv("GROWTH_SESSIONS_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return _growth_root() / "data" / "sessions"


def worker_env_path() -> Path:
    explicit = os.getenv("GROWTH_ADAPTER_ENV_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    root = os.getenv("GROWTH_KLARAVEX_ROOT", "/home/anthony/klaravex").strip()
    return Path(root) / "infra" / "docker-services" / "worker" / ".env"


def _cookie_path(platform: str) -> Path:
    return sessions_dir() / f"{platform}.cookie"


def _meta_path(platform: str) -> Path:
    return sessions_dir() / f"{platform}.meta.json"


def is_usable_cookie(value: str | None) -> bool:
    if not value:
        return False
    raw = value.strip()
    if len(raw) < 20:
        return False
    if _REDACTED.search(raw):
        return False
    if "\n" in raw or "\r" in raw:
        return False
    try:
        raw.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return "=" in raw


def _read_env_file_key(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        if k.strip() == key:
            val = v.strip().strip('"').strip("'")
            return val or None
    return None


def get_cookie(platform: str) -> str | None:
    if platform not in PLATFORMS:
        raise KeyError(platform)
    env_key = PLATFORMS[platform]["env"]

    path = _cookie_path(platform)
    if path.is_file():
        raw = path.read_text(encoding="utf-8", errors="replace").strip()
        if is_usable_cookie(raw):
            return raw

    env_val = os.getenv(env_key, "").strip()
    if is_usable_cookie(env_val):
        return env_val

    file_val = _read_env_file_key(worker_env_path(), env_key)
    if is_usable_cookie(file_val):
        return file_val
    return None


def cookie_present(platform: str) -> bool:
    try:
        return get_cookie(platform) is not None
    except KeyError:
        return False


def save_cookie(platform: str, cookie: str, *, source: str = "manual") -> dict[str, Any]:
    if platform not in PLATFORMS:
        raise KeyError(platform)
    if not is_usable_cookie(cookie):
        raise ValueError(
            "cookie unusable — needs a real Cookie header (not a [REDACTED] placeholder, "
            "latin-1 only, name=value pairs)"
        )
    raw = cookie.strip()
    d = sessions_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    cookie_file = _cookie_path(platform)
    cookie_file.write_text(raw + "\n", encoding="utf-8")
    os.chmod(cookie_file, 0o600)
    meta = {
        "platform": platform,
        "source": source,
        "stored_at": datetime.now(timezone.utc).isoformat(),
        "cookie_pairs": raw.count(";") + 1,
        "cookie_len": len(raw),
    }
    _meta_path(platform).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    os.chmod(_meta_path(platform), 0o600)
    _upsert_worker_env(PLATFORMS[platform]["env"], raw)
    return meta


def delete_cookie(platform: str) -> None:
    if platform not in PLATFORMS:
        raise KeyError(platform)
    for p in (_cookie_path(platform), _meta_path(platform)):
        if p.is_file():
            p.unlink()
    _upsert_worker_env(PLATFORMS[platform]["env"], "")


def metadata(platform: str) -> dict[str, Any] | None:
    path = _meta_path(platform)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        data.pop("cookie", None)
        data.pop("value", None)
        return data
    return None


def _upsert_worker_env(key: str, value: str) -> None:
    """Best-effort mirror into the worker .env so Docker picks it up on restart."""
    path = worker_env_path()
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines(True)
    except OSError:
        return
    prefix = f"{key}="
    replaced = False
    out: list[str] = []
    for line in lines:
        if line.startswith(prefix) or line.startswith(f"export {prefix}"):
            if value:
                out.append(f"{key}={value}\n")
            replaced = True
            continue
        out.append(line)
    if value and not replaced:
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        out.append(f"{key}={value}\n")
    path.write_text("".join(out), encoding="utf-8")
