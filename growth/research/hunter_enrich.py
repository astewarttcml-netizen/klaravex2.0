"""Hunter.io email find + verify for Growth OS leads research (post-Apollo)."""

from __future__ import annotations

import os
from typing import Any

import httpx

HUNTER_API = "https://api.hunter.io/v2"
ACCEPT_VERDICTS = frozenset({"deliverable", "risky", "accept_all", "accept-all"})


def hunter_enabled() -> bool:
    if os.getenv("GROWTH_HUNTER_ENRICH_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
        return False
    return bool(os.getenv("HUNTER_API_KEY", "").strip())


def _api_key() -> str:
    return os.getenv("HUNTER_API_KEY", "").strip()


async def _email_finder(
    client: httpx.AsyncClient,
    *,
    domain: str,
    first_name: str,
    last_name: str,
    api_key: str,
) -> tuple[str | None, int | None]:
    if not (first_name and last_name):
        return None, None
    resp = await client.get(
        f"{HUNTER_API}/email-finder",
        params={
            "domain": domain,
            "first_name": first_name,
            "last_name": last_name,
            "api_key": api_key,
        },
    )
    if resp.status_code != 200:
        return None, None
    data = (resp.json() or {}).get("data") or {}
    email = (data.get("email") or "").strip() or None
    score = data.get("score")
    return email, int(score) if isinstance(score, int) else None


async def _domain_search(
    client: httpx.AsyncClient,
    *,
    domain: str,
    api_key: str,
    limit: int = 3,
) -> dict[str, Any] | None:
    resp = await client.get(
        f"{HUNTER_API}/domain-search",
        params={"domain": domain, "limit": limit, "api_key": api_key},
    )
    if resp.status_code != 200:
        return None
    emails = ((resp.json() or {}).get("data") or {}).get("emails") or []
    best: dict[str, Any] | None = None
    best_score = -1
    for row in emails:
        if not row.get("value"):
            continue
        conf = row.get("confidence") or 0
        try:
            conf = int(conf)
        except (TypeError, ValueError):
            conf = 0
        if conf > best_score:
            best_score = conf
            best = row
    return best


async def _verify_email(
    client: httpx.AsyncClient,
    *,
    email: str,
    api_key: str,
) -> dict[str, Any]:
    resp = await client.get(
        f"{HUNTER_API}/email-verifier",
        params={"email": email, "api_key": api_key},
    )
    if resp.status_code != 200:
        return {"result": "unknown", "score": 0}
    return (resp.json() or {}).get("data") or {"result": "unknown", "score": 0}


def _should_drop(verification: dict[str, Any]) -> bool:
    if os.getenv("GROWTH_HUNTER_DROP_INVALID", "true").lower() not in {"1", "true", "yes", "on"}:
        return False
    result = (verification.get("result") or "unknown").lower().replace("_", "-")
    if result in ACCEPT_VERDICTS:
        return False
    if result in {"undeliverable", "invalid"}:
        return True
    if verification.get("disposable"):
        return True
    score = verification.get("score")
    if isinstance(score, (int, float)) and score < 50:
        return True
    return result not in {"unknown", "skip"} and result not in ACCEPT_VERDICTS


async def enrich_prospect(prospect: dict[str, Any], *, api_key: str) -> dict[str, Any] | None:
    """
    Fill missing email via Hunter; verify deliverability.

    Returns updated prospect, or None if prospect should be dropped.
    """
    domain = (prospect.get("domain") or "").strip().lower()
    if not domain:
        return prospect

    email = (prospect.get("contact_email") or "").strip()
    hunter_source = prospect.get("email_source") or ("apollo" if email else None)
    hunter_confidence: int | None = None

    async with httpx.AsyncClient(
        timeout=20.0,
        headers={"User-Agent": os.getenv("HUNTER_USER_AGENT", "KlaravexGrowth/2.0 (+growth-research)")},
    ) as client:
        if not email:
            first = (prospect.get("contact_first_name") or "").strip()
            last = (prospect.get("contact_last_name") or "").strip()
            found, score = await _email_finder(
                client, domain=domain, first_name=first, last_name=last, api_key=api_key
            )
            if found:
                email = found
                hunter_source = "hunter_finder"
                hunter_confidence = score
            else:
                hit = await _domain_search(client, domain=domain, api_key=api_key)
                if hit:
                    email = (hit.get("value") or "").strip()
                    if email:
                        hunter_source = "hunter_domain_search"
                        try:
                            hunter_confidence = int(hit.get("confidence") or 0)
                        except (TypeError, ValueError):
                            hunter_confidence = None
                        if hit.get("first_name") and not prospect.get("contact_first_name"):
                            prospect["contact_first_name"] = hit["first_name"]
                        if hit.get("last_name") and not prospect.get("contact_last_name"):
                            prospect["contact_last_name"] = hit["last_name"]
                        if hit.get("position") and not prospect.get("contact_title"):
                            prospect["contact_title"] = hit["position"]

        if not email:
            prospect["email_source"] = hunter_source or "unenriched"
            return prospect

        prospect["contact_email"] = email
        prospect["email_source"] = hunter_source or "apollo"

        if hunter_confidence is not None:
            prospect["hunter_confidence"] = hunter_confidence

        if os.getenv("GROWTH_HUNTER_VERIFY", "true").lower() in {"1", "true", "yes", "on"}:
            verification = await _verify_email(client, email=email, api_key=api_key)
            prospect["hunter_verdict"] = verification.get("result")
            prospect["hunter_score"] = verification.get("score")
            if _should_drop(verification):
                return None

    return prospect


async def enrich_shortlist(prospects: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Run Hunter find/verify across Apollo shortlist."""
    api_key = _api_key()
    if not api_key or not hunter_enabled():
        return prospects, {"enabled": 0, "filled": 0, "verified": 0, "dropped": 0}

    out: list[dict[str, Any]] = []
    stats = {"enabled": 1, "filled": 0, "verified": 0, "dropped": 0}

    for prospect in prospects:
        had_email = bool((prospect.get("contact_email") or "").strip())
        enriched = await enrich_prospect(dict(prospect), api_key=api_key)
        if enriched is None:
            stats["dropped"] += 1
            continue
        if not had_email and enriched.get("contact_email"):
            stats["filled"] += 1
        if enriched.get("hunter_verdict"):
            stats["verified"] += 1
        out.append(enriched)

    return out, stats
