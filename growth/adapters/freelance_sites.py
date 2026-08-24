"""Growth adapters: Upwork / Guru / PeoplePerHour session probes.

List probes stay vault-only (cheap). Pass a payload (adapter invoke) to run
the live HTTP session check.
"""

from growth.adapters import poc_sandbox
from growth.poc import is_poc_mode
from growth.sessions.probe import probe
from growth.sessions.vault import PLATFORMS, cookie_present, metadata

__all__ = ["upwork", "guru", "peopleperhour"]


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
