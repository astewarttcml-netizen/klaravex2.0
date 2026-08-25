"""Growth adapters: Upwork / Guru / PeoplePerHour session probes + Freelancer.com API.

List probes stay vault-only (cheap). Pass a payload (adapter invoke) to run
the live HTTP session check. Freelancer.com uses its official OAuth V1 API
(header ``Freelancer-OAuth-V1``), not a session cookie.
"""

import os

import requests

from growth.adapters import poc_sandbox
from growth.poc import is_poc_mode
from growth.sessions.probe import probe
from growth.sessions.vault import PLATFORMS, cookie_present, metadata

__all__ = ["upwork", "guru", "peopleperhour", "freelancer"]


def _vault_status(platform: str) -> dict:
    spec = PLATFORMS[platform]
    label = spec["label"]
    meta = metadata(platform) or {}
    present = cookie_present(platform)
    if present:
        return {
            "adapter": platform,
            "action": "probe",
            "status": "ready",
            "creds_configured": True,
            "detail": f"{label} session cookie saved — live check via GET /v1/sessions/{platform}",
            "sample": {"source": meta.get("source"), "stored_at": meta.get("stored_at")},
        }
    return {
        "adapter": platform,
        "action": "probe",
        "status": "stub",
        "creds_configured": False,
        "detail": (
            f"{label}: no session. Google SSO: python -m growth.sessions.login --all"
        ),
        "sample": {},
    }


def _run(platform: str, payload=None):
    if is_poc_mode():
        return poc_sandbox(platform, "probe", {"mode": "session"})
    if payload is not None:
        return probe(platform)
    return _vault_status(platform)


def upwork(payload=None, *_a, **_k):
    if is_poc_mode():
        return poc_sandbox("upwork", "probe", {"mode": "graphql"})
    from growth.upwork.graphql import probe_status

    return probe_status()


def guru(payload=None, *_a, **_k):
    return _run("guru", payload)


def peopleperhour(payload=None, *_a, **_k):
    return _run("peopleperhour", payload)


def freelancer(payload=None, *_a, **_k):
    """Freelancer.com official API probe (OAuth V1, not session cookie)."""
    if is_poc_mode():
        return poc_sandbox("freelancer", "probe", {"mode": "api"})
    token = os.environ.get("FREELANCER_ACCESS_TOKEN") or os.environ.get("FREELANCER_OAUTH_TOKEN", "")
    if not token:
        return {
            "adapter": "freelancer",
            "action": "probe",
            "status": "stub",
            "creds_configured": False,
            "detail": "Freelancer.com: no API token. Set FREELANCER_ACCESS_TOKEN (OAuth V1) from developers.freelancer.com",
            "sample": {},
        }
    url = "https://www.freelancer.com/api/users/0.1/self/"
    try:
        resp = requests.get(
            url,
            headers={"Freelancer-OAuth-V1": token},
            timeout=8,
        )
    except requests.RequestException as exc:
        return {
            "adapter": "freelancer",
            "action": "probe",
            "status": "error",
            "creds_configured": bool(token),
            "detail": f"Freelancer.com: probe failed ({exc})",
            "sample": {},
        }
    code = resp.status_code
    if code == 200:
        username = ""
        try:
            body = resp.json()
            result = body.get("result") if isinstance(body, dict) else None
            if isinstance(result, dict):
                username = str(result.get("username") or result.get("display_name") or "")
        except ValueError:
            username = ""
        who = username or "self"
        return {
            "adapter": "freelancer",
            "action": "probe",
            "status": "connected",
            "creds_configured": True,
            "detail": f"Freelancer.com API live (user {who})",
            "sample": {"username": username} if username else {},
        }
    if code in (401, 403):
        return {
            "adapter": "freelancer",
            "action": "probe",
            "status": "error",
            "creds_configured": True,
            "detail": f"Freelancer.com: token rejected (HTTP {code}). Re-authorize at developers.freelancer.com",
            "sample": {},
        }
    return {
        "adapter": "freelancer",
        "action": "probe",
        "status": "error",
        "creds_configured": bool(token),
        "detail": f"Freelancer.com: unexpected HTTP {code}",
        "sample": {},
    }
