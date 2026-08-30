"""Ads adapter — Google Ads + Meta Ads + LinkedIn Ads (read/report; no spend).

Probes credentialed platforms and pulls campaign performance for the ads
stream. Mutations (create/enable campaigns) stay human-gated; this module is
report-first for Nadia's weekly ads charter.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from growth.adapters import poc_sandbox
from growth.adapters.credentials import _merged_env
from growth.poc import is_poc_mode

GRAPH = "https://graph.facebook.com/v21.0"


def _env(key: str, default: str = "") -> str:
    return (_merged_env().get(key) or os.getenv(key) or default).strip()


def _readonly() -> bool:
    return os.getenv("ADS_READONLY", "true").lower() in {"1", "true", "yes", "on"}


# ── Google Ads ───────────────────────────────────────────────────────────────


def _google_client():
    from google.ads.googleads.client import GoogleAdsClient

    refresh = _env("GOOGLE_ADS_REFRESH_TOKEN")
    client_id = _env("GOOGLE_ADS_CLIENT_ID")
    client_secret = _env("GOOGLE_ADS_CLIENT_SECRET")
    developer = _env("GOOGLE_ADS_DEVELOPER_TOKEN")
    if not all([refresh, client_id, client_secret, developer]):
        raise RuntimeError("Google Ads OAuth/developer token incomplete")

    cfg: dict[str, Any] = {
        "developer_token": developer,
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh,
        "use_proto_plus": True,
    }
    login = _env("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    if login:
        cfg["login_customer_id"] = login
    return GoogleAdsClient.load_from_dict(cfg, version="v25")


def google_configured() -> bool:
    return bool(
        _env("GOOGLE_ADS_DEVELOPER_TOKEN")
        and _env("GOOGLE_ADS_CUSTOMER_ID")
        and _env("GOOGLE_ADS_REFRESH_TOKEN")
        and _env("GOOGLE_ADS_CLIENT_ID")
        and _env("GOOGLE_ADS_CLIENT_SECRET")
    )


def google_probe() -> dict[str, Any]:
    if not google_configured():
        return {"platform": "google", "ok": False, "detail": "missing Google Ads creds"}
    customer = _env("GOOGLE_ADS_CUSTOMER_ID")
    client = _google_client()
    ga = client.get_service("GoogleAdsService")
    q = (
        "SELECT customer.id, customer.descriptive_name, customer.currency_code, "
        "customer.time_zone FROM customer LIMIT 1"
    )
    for row in ga.search(customer_id=customer, query=q):
        c = row.customer
        return {
            "platform": "google",
            "ok": True,
            "customer_id": str(c.id),
            "name": c.descriptive_name,
            "currency": c.currency_code,
            "timezone": c.time_zone,
        }
    return {"platform": "google", "ok": False, "detail": "no customer row"}


def google_report(*, days: int = 7) -> dict[str, Any]:
    customer = _env("GOOGLE_ADS_CUSTOMER_ID")
    client = _google_client()
    ga = client.get_service("GoogleAdsService")
    end = date.today()
    start = end - timedelta(days=max(1, days))
    q = f"""
      SELECT
        campaign.id,
        campaign.name,
        campaign.status,
        metrics.impressions,
        metrics.clicks,
        metrics.cost_micros,
        metrics.conversions
      FROM campaign
      WHERE segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'
      ORDER BY metrics.cost_micros DESC
    """
    rows: list[dict[str, Any]] = []
    for row in ga.search(customer_id=customer, query=q):
        rows.append(
            {
                "id": str(row.campaign.id),
                "name": row.campaign.name,
                "status": row.campaign.status.name,
                "impressions": int(row.metrics.impressions),
                "clicks": int(row.metrics.clicks),
                "cost": round(row.metrics.cost_micros / 1_000_000, 2),
                "conversions": float(row.metrics.conversions),
            }
        )
    # Aggregate duplicate campaign rows across days
    by_id: dict[str, dict[str, Any]] = {}
    for r in rows:
        cur = by_id.get(r["id"])
        if not cur:
            by_id[r["id"]] = dict(r)
            continue
        cur["impressions"] += r["impressions"]
        cur["clicks"] += r["clicks"]
        cur["cost"] = round(cur["cost"] + r["cost"], 2)
        cur["conversions"] += r["conversions"]
    campaigns = sorted(by_id.values(), key=lambda x: x["cost"], reverse=True)
    return {
        "platform": "google",
        "customer_id": customer,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "campaigns": campaigns,
        "totals": {
            "impressions": sum(c["impressions"] for c in campaigns),
            "clicks": sum(c["clicks"] for c in campaigns),
            "cost": round(sum(c["cost"] for c in campaigns), 2),
            "conversions": round(sum(c["conversions"] for c in campaigns), 2),
        },
    }


# ── Meta Ads ─────────────────────────────────────────────────────────────────


def meta_configured() -> bool:
    return bool(_env("META_ADS_ACCESS_TOKEN") and _env("META_AD_ACCOUNT_ID"))


def _meta_get(path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    token = _env("META_ADS_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("META_ADS_ACCESS_TOKEN missing")
    q = dict(params or {})
    q["access_token"] = token
    url = f"{GRAPH}/{path.lstrip('/')}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Meta HTTP {exc.code}: {body}") from exc


META_REQUIRED_SCOPES = ("ads_management", "ads_read", "business_management")


def meta_scope_check() -> dict[str, Any]:
    """Read granted scopes via /me/permissions (works with user tokens; no
    app credential needed, unlike debug_token). Surfaces missing Marketing
    API scopes on the Connections board instead of mid-run 400s."""
    try:
        data = _meta_get("me/permissions", {"limit": "100"})
    except RuntimeError as exc:
        return {"scopes_ok": None, "detail": f"permissions read failed: {exc}"}
    granted = {
        row.get("permission")
        for row in data.get("data") or []
        if row.get("status") == "granted"
    }
    missing = [s for s in META_REQUIRED_SCOPES if s not in granted]
    return {
        "scopes_ok": not missing,
        "missing_scopes": missing,
        "granted_count": len(granted),
    }


def meta_probe() -> dict[str, Any]:
    if not meta_configured():
        return {"platform": "meta", "ok": False, "detail": "missing Meta Ads creds"}
    acct = _env("META_AD_ACCOUNT_ID")
    data = _meta_get(
        acct,
        {
            "fields": "name,account_id,account_status,currency,timezone_name",
        },
    )
    scopes = meta_scope_check()
    return {
        "platform": "meta",
        "ok": True,
        "account_id": data.get("id") or acct,
        "name": data.get("name"),
        "status": data.get("account_status"),
        "currency": data.get("currency"),
        "timezone": data.get("timezone_name"),
        **scopes,
    }


def meta_report(*, days: int = 7) -> dict[str, Any]:
    acct = _env("META_AD_ACCOUNT_ID")
    since = (date.today() - timedelta(days=max(1, days))).isoformat()
    until = date.today().isoformat()
    data = _meta_get(
        f"{acct}/insights",
        {
            "fields": "campaign_name,campaign_id,impressions,clicks,spend,actions",
            "time_range": json.dumps({"since": since, "until": until}),
            "level": "campaign",
            "limit": "50",
        },
    )
    campaigns: list[dict[str, Any]] = []
    for row in data.get("data") or []:
        conversions = 0.0
        for act in row.get("actions") or []:
            if act.get("action_type") in {
                "lead",
                "omni_complete_registration",
                "offsite_conversion.fb_pixel_lead",
                "complete_registration",
            }:
                conversions += float(act.get("value") or 0)
        campaigns.append(
            {
                "id": str(row.get("campaign_id") or ""),
                "name": row.get("campaign_name") or "",
                "impressions": int(row.get("impressions") or 0),
                "clicks": int(row.get("clicks") or 0),
                "cost": round(float(row.get("spend") or 0), 2),
                "conversions": conversions,
            }
        )
    return {
        "platform": "meta",
        "account_id": acct,
        "window": {"start": since, "end": until},
        "campaigns": campaigns,
        "totals": {
            "impressions": sum(c["impressions"] for c in campaigns),
            "clicks": sum(c["clicks"] for c in campaigns),
            "cost": round(sum(c["cost"] for c in campaigns), 2),
            "conversions": round(sum(c["conversions"] for c in campaigns), 2),
        },
    }


# ── LinkedIn Ads ─────────────────────────────────────────────────────────────


def linkedin_configured() -> bool:
    return bool(
        (_env("LINKEDIN_ADS_ACCESS_TOKEN") or _env("LINKEDIN_ADS_TOKEN"))
        and (_env("LINKEDIN_AD_ACCOUNT_NUMERIC") or _env("LINKEDIN_AD_ACCOUNT_ID"))
    )


def _linkedin_account_numeric() -> str:
    raw = _env("LINKEDIN_AD_ACCOUNT_NUMERIC")
    if raw:
        return raw
    urn = _env("LINKEDIN_AD_ACCOUNT_ID")
    if ":" in urn:
        return urn.rsplit(":", 1)[-1]
    return urn


def _linkedin_get(path: str) -> dict[str, Any]:
    token = _env("LINKEDIN_ADS_ACCESS_TOKEN") or _env("LINKEDIN_ADS_TOKEN")
    if not token:
        raise RuntimeError("LINKEDIN_ADS_ACCESS_TOKEN missing")
    url = f"https://api.linkedin.com{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "LinkedIn-Version": "202402",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"LinkedIn HTTP {exc.code}: {body}") from exc


def linkedin_probe() -> dict[str, Any]:
    if not linkedin_configured():
        return {"platform": "linkedin", "ok": False, "detail": "missing LinkedIn Ads creds"}
    acct = _linkedin_account_numeric()
    data = _linkedin_get(f"/v2/adAccountsV2/{acct}")
    return {
        "platform": "linkedin",
        "ok": True,
        "account_id": str(data.get("id") or acct),
        "name": data.get("name"),
        "status": data.get("status"),
        "currency": data.get("currency"),
        "serving": data.get("servingStatuses"),
    }


def linkedin_report(*, days: int = 7) -> dict[str, Any]:
    """Campaign list + status (analytics analytics API varies by product access)."""
    acct = _linkedin_account_numeric()
    data = _linkedin_get(
        f"/v2/adCampaignsV2?q=search&search=(account:(values:List(urn%3Ali%3AsponsoredAccount%3A{acct})))&count=50"
    )
    campaigns: list[dict[str, Any]] = []
    for row in data.get("elements") or []:
        campaigns.append(
            {
                "id": str(row.get("id") or ""),
                "name": row.get("name") or "",
                "status": row.get("status") or "",
                "type": row.get("type") or "",
                "daily_budget": (row.get("dailyBudget") or {}).get("amount"),
                "currency": (row.get("dailyBudget") or {}).get("currencyCode"),
            }
        )
    return {
        "platform": "linkedin",
        "account_id": acct,
        "window": {"days": days, "note": "campaign inventory (analytics gated by product)"},
        "campaigns": campaigns,
        "totals": {"campaign_count": len(campaigns)},
    }


# ── Unified entrypoints ──────────────────────────────────────────────────────


def probe_platforms() -> dict[str, Any]:
    platforms: list[dict[str, Any]] = []
    for fn in (google_probe, meta_probe, linkedin_probe):
        try:
            platforms.append(fn())
        except Exception as exc:  # noqa: BLE001
            platforms.append(
                {
                    "platform": fn.__name__.split("_")[0],
                    "ok": False,
                    "detail": str(exc)[:300],
                }
            )
    ok = sum(1 for p in platforms if p.get("ok"))
    return {
        "platforms": platforms,
        "ok_count": ok,
        "configured_count": sum(
            1
            for c in (google_configured(), meta_configured(), linkedin_configured())
            if c
        ),
    }


def pull_reports(*, days: int = 7) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    errors: dict[str, str] = {}
    if google_configured():
        try:
            reports["google"] = google_report(days=days)
        except Exception as exc:  # noqa: BLE001
            errors["google"] = str(exc)[:300]
    if meta_configured():
        try:
            reports["meta"] = meta_report(days=days)
        except Exception as exc:  # noqa: BLE001
            errors["meta"] = str(exc)[:300]
    if linkedin_configured():
        try:
            reports["linkedin"] = linkedin_report(days=days)
        except Exception as exc:  # noqa: BLE001
            errors["linkedin"] = str(exc)[:300]
    return {
        "pulled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "days": days,
        "reports": reports,
        "errors": errors,
    }


def render_inputs_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Ads performance pull — {payload.get('pulled_at', '')}",
        "",
        f"- **Window:** last {payload.get('days', 7)} days",
        f"- **Readonly:** {_readonly()}",
        "- **Source:** Growth ads adapter (Google / Meta / LinkedIn)",
        "",
    ]
    reports = payload.get("reports") or {}
    for key in ("google", "meta", "linkedin"):
        rep = reports.get(key)
        if not rep:
            continue
        lines += [f"## {key.title()}", ""]
        totals = rep.get("totals") or {}
        if "cost" in totals:
            lines.append(
                f"- Totals: impressions={totals.get('impressions')} · "
                f"clicks={totals.get('clicks')} · cost={totals.get('cost')} · "
                f"conversions={totals.get('conversions')}"
            )
        elif "campaign_count" in totals:
            lines.append(f"- Campaigns listed: {totals.get('campaign_count')}")
        lines += ["", "| Campaign | Status | Impr | Clicks | Cost | Conv |", "|---|---|---:|---:|---:|---:|"]
        for c in rep.get("campaigns") or []:
            lines.append(
                f"| {c.get('name', '')[:60]} | {c.get('status', '')} | "
                f"{c.get('impressions', '')} | {c.get('clicks', '')} | "
                f"{c.get('cost', c.get('daily_budget', ''))} | {c.get('conversions', '')} |"
            )
        lines.append("")
    errors = payload.get("errors") or {}
    if errors:
        lines += ["## Errors", ""]
        for k, v in errors.items():
            lines.append(f"- **{k}:** {v}")
        lines.append("")
    return "\n".join(lines)


def write_inputs(
    *,
    days: int = 7,
    revenue_agents_root: Path | None = None,
) -> dict[str, Any]:
    root = Path(
        revenue_agents_root
        or Path(__file__).resolve().parents[2] / "revenue-agents"
    )
    out_dir = root / "outbox" / "ads" / "inputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = pull_reports(days=days)
    day = date.today().isoformat()
    md_path = out_dir / f"{day}-performance.md"
    json_path = out_dir / f"{day}-performance.json"
    md_path.write_text(render_inputs_markdown(payload), encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["paths"] = {"markdown": str(md_path), "json": str(json_path)}
    return payload


def draft(payload: dict[str, Any] | None = None, **_kwargs) -> dict[str, Any]:
    """Registry probe / invoke entry — empty payload = probe; action=pull = report."""
    if is_poc_mode():
        return poc_sandbox(
            "ads",
            "probe",
            {"platforms": ["google", "meta", "linkedin"]},
        )

    data = dict(payload or {})
    data.update({k: v for k, v in _kwargs.items() if v is not None})
    action = str(data.get("action") or "probe").strip().lower()

    if action in {"pull", "report", "inputs"}:
        days = int(data.get("days") or 7)
        if data.get("write", True):
            result = write_inputs(days=days)
        else:
            result = pull_reports(days=days)
        return {
            "adapter": "ads",
            "status": "connected",
            "action": "pull",
            "detail": (
                f"pulled {len(result.get('reports') or {})} platform report(s); "
                f"errors={list((result.get('errors') or {}).keys())}"
            ),
            "sample": {
                "platforms": list((result.get("reports") or {}).keys()),
                "paths": result.get("paths"),
                "errors": result.get("errors"),
            },
            "creds_configured": True,
            "result": result,
        }

    probe = probe_platforms()
    ok = probe["ok_count"]
    return {
        "adapter": "ads",
        "status": "connected" if ok else "error",
        "action": "probe",
        "detail": f"{ok}/{probe['configured_count']} platforms OK",
        "sample": probe,
        "creds_configured": probe["configured_count"] > 0,
    }
