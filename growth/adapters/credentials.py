"""Adapter credential probes — read-only; never return secret values."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

# Required env keys per adapter (all must be non-empty).
ADAPTER_CRED_KEYS: dict[str, tuple[str, ...]] = {
    "clay": ("CLAY_API_KEY",),
    "hunter": ("HUNTER_API_KEY",),
    "taplio": ("TAPLIO_API_KEY",),  # Bearer auth → https://api.taplio.com/v1/
    "smartlead": ("SMARTLEAD_API_KEY",),
    "wordpress": ("WP_SITE_URL", "WP_APP_PASSWORD"),
    # Zernio also reads ~/.config/social/.env — see zernio._api_key()
    "zernio": ("ZERNIO_API_KEY",),
    "upwork": ("UPWORK_CLIENT_ID", "UPWORK_CLIENT_SECRET"),
    "guru": ("GURU_SESSION_COOKIE",),
    "peopleperhour": ("PPH_SESSION_COOKIE",),
    # Ads: at least one platform fully configured counts as "configured"
    "ads": (
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CUSTOMER_ID",
        "GOOGLE_ADS_REFRESH_TOKEN",
    ),
}


def _adapter_env_path() -> Path:
    explicit = os.getenv("GROWTH_ADAPTER_ENV_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    root = os.getenv("GROWTH_KLARAVEX_ROOT", "/home/anthony/klaravex").strip()
    return Path(root) / "infra" / "docker-services" / "worker" / ".env"


def _growth_env_path() -> Path:
    """Klaravex2.0 growth/.env (Google/Meta/LinkedIn ads tokens live here)."""
    explicit = os.getenv("GROWTH_ENV_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return Path(__file__).resolve().parents[1] / ".env"


@lru_cache(maxsize=1)
def _merged_env() -> dict[str, str]:
    """Process env + worker .env + growth/.env (os.environ wins)."""
    out: dict[str, str] = {}

    def _ingest(path: Path) -> None:
        if not path.is_file():
            return
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key) and val:
                out.setdefault(key, val)

    _ingest(_adapter_env_path())
    _ingest(_growth_env_path())
    for key, val in os.environ.items():
        if val:
            out[key] = val
    return out


def creds_configured(name: str) -> bool:
    keys = ADAPTER_CRED_KEYS.get(name)
    if not keys:
        return False
    if name == "upwork":
        from growth.upwork.oauth import client_configured, token_present
        from growth.sessions.vault import cookie_present

        return token_present() or client_configured() or cookie_present("upwork")
    if name in {"guru", "peopleperhour"}:
        from growth.sessions.vault import cookie_present

        return cookie_present(name)
    if name == "zernio":
        # Prefer social config file; also accept LATE_/POSTLY_ aliases.
        from growth.adapters import zernio as zernio_adapter

        return bool(zernio_adapter._api_key())
    if name == "ads":
        from growth.adapters import ads as ads_adapter

        return (
            ads_adapter.google_configured()
            or ads_adapter.meta_configured()
            or ads_adapter.linkedin_configured()
        )
    env = _merged_env()
    return all(bool(env.get(k, "").strip()) for k in keys)


def creds_detail(name: str) -> str:
    if name == "ads":
        from growth.adapters import ads as ads_adapter

        parts = []
        parts.append("google=" + ("ok" if ads_adapter.google_configured() else "missing"))
        parts.append("meta=" + ("ok" if ads_adapter.meta_configured() else "missing"))
        parts.append("linkedin=" + ("ok" if ads_adapter.linkedin_configured() else "missing"))
        return "platforms: " + ", ".join(parts)
    keys = ADAPTER_CRED_KEYS.get(name, ())
    env = _merged_env()
    if name == "upwork":
        from growth.upwork.oauth import client_configured, token_present
        from growth.sessions.vault import cookie_present

        if token_present():
            return "Upwork OAuth token saved"
        if client_configured():
            return "Upwork app keys saved — authorize to search jobs"
        if cookie_present("upwork"):
            return "session cookie saved (GraphQL OAuth preferred)"
        return "missing: UPWORK_CLIENT_ID / UPWORK_CLIENT_SECRET"
    if name in {"guru", "peopleperhour"}:
        from growth.sessions.vault import cookie_present

        return "session cookie saved" if cookie_present(name) else f"missing: {keys[0]}"
    missing = [k for k in keys if not env.get(k, "").strip()]
    if not missing:
        return f"credentials configured ({', '.join(keys)})"
    if len(missing) == len(keys):
        return f"missing: {', '.join(missing)}"
    return f"partial — missing: {', '.join(missing)}"
