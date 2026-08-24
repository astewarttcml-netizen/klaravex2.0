"""Upwork GraphQL job search. Never logs tokens or job cookies."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from growth.upwork.oauth import get_access_token, public_status, token_present

GRAPHQL_URL = "https://api.upwork.com/graphql"

PROBE_QUERY = """
query SearchJobs($filter: MarketplaceJobPostingsSearchFilter) {
  marketplaceJobPostingsSearch(
    marketPlaceJobFilter: $filter
    searchType: USER_JOBS_SEARCH
    sortAttributes: [{ field: RECENCY }]
  ) {
    totalCount
  }
}
"""

SEARCH_QUERY = """
query SearchJobs($filter: MarketplaceJobPostingsSearchFilter) {
  marketplaceJobPostingsSearch(
    marketPlaceJobFilter: $filter
    searchType: USER_JOBS_SEARCH
    sortAttributes: [{ field: RECENCY }]
  ) {
    totalCount
    edges {
      node {
        id
        title
        description
        ciphertext
        createdDateTime
        publishedDateTime
        totalApplicants
        category
        subcategory
        amount { rawValue displayValue currency }
        hourlyBudgetMin { rawValue }
        hourlyBudgetMax { rawValue }
        skills { name }
        client { totalHires totalFeedback verificationStatus location { country } }
      }
    }
  }
}
"""


def _graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    token = get_access_token()
    if not token:
        raise RuntimeError("no Upwork access token — authorize via Connections")
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = Request(
        GRAPHQL_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except HTTPError as exc:
        raise RuntimeError(f"Upwork GraphQL HTTP {exc.code}") from None
    except Exception as exc:
        raise RuntimeError(f"Upwork GraphQL failed ({type(exc).__name__})") from None
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        raise RuntimeError("Upwork GraphQL response was not JSON") from None
    if status >= 400:
        raise RuntimeError(f"Upwork GraphQL HTTP {status}")
    errors = body.get("errors") if isinstance(body, dict) else None
    if errors:
        msg = errors[0].get("message") if isinstance(errors[0], dict) else "GraphQL error"
        raise RuntimeError(f"Upwork GraphQL: {msg}"[:220])
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError("Upwork GraphQL returned no data")
    return data


def probe_status() -> dict[str, Any]:
    base = public_status()
    if not token_present():
        if base["client_configured"]:
            return {
                **base,
                "status": "ready",
                "detail": (
                    "Upwork app keys saved — click Authorize on Connections "
                    f"(callback {base['redirect_uri']}). Enable “Read marketplace Job Postings”."
                ),
            }
        return {
            **base,
            "status": "stub",
            "detail": (
                "Upwork GraphQL: create an OAuth 2.0 app at "
                f"{base['apply_url']}, paste Client ID + Secret on Connections, then Authorize."
            ),
        }
    try:
        data = _graphql(
            PROBE_QUERY,
            {"filter": {"searchExpression_eq": "IT", "pagination_eq": {"after": "0", "first": 1}}},
        )
        total = (data.get("marketplaceJobPostingsSearch") or {}).get("totalCount")
        return {
            **base,
            "status": "connected",
            "detail": f"Upwork GraphQL live (marketplace search, totalCount={total})",
            "sample": {**base.get("sample", {}), "totalCount": total},
        }
    except Exception as exc:
        return {
            **base,
            "status": "error",
            "detail": f"Upwork OAuth token present but GraphQL failed ({exc})",
        }


def _money(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, dict):
        return None
    raw = value.get("rawValue")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    display = str(value.get("displayValue") or "")
    digits = "".join(ch for ch in display if ch.isdigit() or ch in ".-")
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def node_to_project(node: dict[str, Any], min_budget: float) -> dict[str, Any] | None:
    title = (node.get("title") or "").strip()
    if not title:
        return None
    ciphertext = (node.get("ciphertext") or "").strip()
    pid = ciphertext or str(node.get("id") or "")
    if not pid:
        return None
    hourly_max = _money(node.get("hourlyBudgetMax"))
    fixed = _money(node.get("amount"))
    budget_max = None
    budget_type = "fixed"
    if hourly_max:
        budget_max = hourly_max * 8.0
        budget_type = "hourly"
    elif fixed:
        budget_max = fixed
    if budget_max is not None and budget_max < min_budget:
        return None
    skills = node.get("skills") or []
    skill_names = [s.get("name") for s in skills if isinstance(s, dict) and s.get("name")]
    client = node.get("client") if isinstance(node.get("client"), dict) else {}
    loc = client.get("location") if isinstance(client.get("location"), dict) else {}
    url = f"https://www.upwork.com/jobs/~{ciphertext}" if ciphertext else f"https://www.upwork.com/jobs/{pid}"
    return {
        "platform_id": pid,
        "title": title[:200],
        "description": (node.get("description") or None),
        "skills_required": ", ".join(skill_names) if skill_names else None,
        "category": node.get("category") or node.get("subcategory"),
        "budget_min": _money(node.get("hourlyBudgetMin")),
        "budget_max": budget_max,
        "budget_type": budget_type,
        "budget_currency": "USD",
        "client_name": None,
        "client_location": loc.get("country"),
        "url": url,
        "posted_at": node.get("publishedDateTime") or node.get("createdDateTime"),
        "proposals_count": node.get("totalApplicants"),
        "is_verified_client": str(client.get("verificationStatus") or "").upper() == "VERIFIED",
    }


def search_jobs(keywords: list[str], min_budget_usd: float = 0, per_keyword: int = 10) -> list[dict[str, Any]]:
    if not token_present() and not get_access_token():
        return []
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for keyword in keywords[:8]:
        data = _graphql(
            SEARCH_QUERY,
            {
                "filter": {
                    "searchExpression_eq": keyword,
                    "pagination_eq": {"after": "0", "first": max(1, min(per_keyword, 20))},
                }
            },
        )
        edges = (data.get("marketplaceJobPostingsSearch") or {}).get("edges") or []
        for edge in edges:
            node = edge.get("node") if isinstance(edge, dict) else None
            if not isinstance(node, dict):
                continue
            project = node_to_project(node, min_budget_usd)
            if not project or project["platform_id"] in seen:
                continue
            seen.add(project["platform_id"])
            out.append(project)
    return out
