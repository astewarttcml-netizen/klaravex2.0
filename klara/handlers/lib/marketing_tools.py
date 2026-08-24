"""
Tool catalog for marketing AI agents.

Each tool is async, returns a JSON-serializable dict, and degrades gracefully
when credentials are missing (the agent sees a uniform schema either way).

Tools are categorized:
  - paid: meta_ads, google_ads, linkedin_ads
  - outbound: apollo_search, apollo_sequence_add
  - organic: linkedin_post, twitter_post, instagram_post
  - email: resend_send
  - content: claude_draft (already available via anthropic), image_generate (Higgsfield)
  - utility: log_action, request_human_approval

All side-effects route through klaravex_marketing_actions for audit.
"""

import json
import logging
import os
from typing import Any, Optional

import httpx

from .db import get_pool
from .email import send_email

log = logging.getLogger("klaravex.marketing_tools")

APPROVAL_EMAIL = os.environ.get("APPROVAL_NOTIFY_EMAIL", "astewart@klaravex.com")
PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _missing(env_required: list[str]) -> dict:
    missing = [e for e in env_required if not os.environ.get(e)]
    if missing:
        return {
            "ok": False,
            "reason": "credentials_needed",
            "env_required": missing,
            "human_action": (
                f"Anthony needs to set these env vars in Azure Container App: {', '.join(missing)}"
            ),
        }
    return {}


async def _log_action(
    team_id: str,
    action_type: str,
    payload: dict,
    result: dict,
    *,
    action_target: Optional[str] = None,
    status: str = "executed",
    approval_required: bool = False,
    run_id: Optional[str] = None,
) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO klaravex_marketing_actions
              (team_id, run_id, action_type, action_target, payload, result,
               status, approval_required, executed_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8, now())
            RETURNING id::text
            """,
            team_id, run_id, action_type, action_target,
            json.dumps(payload), json.dumps(result),
            status, approval_required,
        )


# ── Paid Ads ──────────────────────────────────────────────────────────────────

# Meta's Marketing API objective enum is case-sensitive and doesn't accept
# free-form strings — confirmed live 2026-07-16: "conversions" (lowercase, as
# an LLM-drafted proposal wrote it) is rejected outright with a 400. Normalize
# common lowercase/friendly names to the actual enum so a draft written in
# natural language doesn't silently fail at execution time.
_META_OBJECTIVE_MAP = {
    "conversions": "OUTCOME_LEADS",
    "leads": "OUTCOME_LEADS",
    "lead_generation": "OUTCOME_LEADS",
    "sales": "OUTCOME_SALES",
    "traffic": "OUTCOME_TRAFFIC",
    "engagement": "OUTCOME_ENGAGEMENT",
    "awareness": "OUTCOME_AWARENESS",
    "app_promotion": "OUTCOME_APP_PROMOTION",
}


def _normalize_meta_objective(objective: str) -> str:
    key = (objective or "").strip().lower()
    return _META_OBJECTIVE_MAP.get(key, objective.strip().upper())


async def meta_ads_create_campaign(
    team_id: str, *, name: str, daily_budget_usd: float,
    objective: str = "OUTCOME_LEADS", target_url: str,
    creative_text: str, creative_image_url: Optional[str] = None,
    audience: Optional[dict] = None, run_id: Optional[str] = None,
) -> dict:
    gate = _missing(["META_ADS_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"])
    objective = _normalize_meta_objective(objective)
    payload = {"name": name, "daily_budget_usd": daily_budget_usd, "objective": objective,
               "target_url": target_url, "creative_text": creative_text,
               "creative_image_url": creative_image_url, "audience": audience}
    if gate:
        await _log_action(team_id, "meta_ads.create_campaign", payload, gate,
                          status="blocked", run_id=run_id)
        return gate

    token = os.environ["META_ADS_ACCESS_TOKEN"]
    acct = os.environ["META_AD_ACCOUNT_ID"]
    base = f"https://graph.facebook.com/v19.0"
    auth = {"access_token": token}
    result: dict = {"ok": False, "campaign_id": None, "adset_id": None,
                    "creative_id": None, "ad_id": None, "steps": {}}

    async with httpx.AsyncClient(timeout=20) as client:

        # ── Step 1: Campaign ──────────────────────────────────────────────────
        try:
            r = await client.post(
                f"{base}/{acct}/campaigns",
                params=auth,
                json={
                    "name": name,
                    "objective": objective,
                    "status": "PAUSED",  # always start paused for human review
                    "daily_budget": int(daily_budget_usd * 100),
                    "special_ad_categories": [],
                },
            )
            campaign_body = r.json() if r.text else {}
            campaign_id = campaign_body.get("id")
            result["steps"]["campaign"] = {"http": r.status_code, "id": campaign_id}
            result["campaign_id"] = campaign_id
            log.info("meta_ads campaign created id=%s", campaign_id)
        except Exception as exc:
            result["steps"]["campaign"] = {"error": str(exc)}
            log.error("meta_ads campaign step failed: %s", exc)
            await _log_action(team_id, "meta_ads.create_campaign", payload, result,
                              status="failed", run_id=run_id)
            return result

        if not campaign_id:
            result["steps"]["campaign"]["error"] = "no id returned"
            await _log_action(team_id, "meta_ads.create_campaign", payload, result,
                              status="failed", run_id=run_id)
            return result

        # ── Step 2: Ad Set ────────────────────────────────────────────────────
        # Build targeting: caller-supplied audience dict overrides defaults.
        default_targeting = {
            "geo_locations": {"countries": ["US"]},
            "age_min": 25,
            "age_max": 65,
            "locales": [6],  # English
        }
        targeting = {**default_targeting, **(audience or {})}

        try:
            r = await client.post(
                f"{base}/{acct}/adsets",
                params=auth,
                json={
                    "name": f"{name} — Ad Set",
                    "campaign_id": campaign_id,
                    "daily_budget": int(daily_budget_usd * 100),
                    "billing_event": "IMPRESSIONS",
                    "optimization_goal": "LEAD_GENERATION",
                    "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                    "targeting": targeting,
                    "status": "PAUSED",
                },
            )
            adset_body = r.json() if r.text else {}
            adset_id = adset_body.get("id")
            result["steps"]["adset"] = {"http": r.status_code, "id": adset_id}
            result["adset_id"] = adset_id
            log.info("meta_ads adset created id=%s", adset_id)
        except Exception as exc:
            result["steps"]["adset"] = {"error": str(exc)}
            log.error("meta_ads adset step failed: %s", exc)
            await _log_action(team_id, "meta_ads.create_campaign", payload, result,
                              action_target=campaign_id, status="partial", run_id=run_id)
            return result

        if not adset_id:
            result["steps"]["adset"]["error"] = "no id returned"
            await _log_action(team_id, "meta_ads.create_campaign", payload, result,
                              action_target=campaign_id, status="partial", run_id=run_id)
            return result

        # ── Step 3: Ad Creative ───────────────────────────────────────────────
        object_story_spec: dict = {
            "page_id": os.environ.get("META_PAGE_ID", ""),
            "link_data": {
                "message": creative_text,
                "link": target_url,
            },
        }
        if creative_image_url:
            object_story_spec["link_data"]["picture"] = creative_image_url

        try:
            r = await client.post(
                f"{base}/{acct}/adcreatives",
                params=auth,
                json={
                    "name": f"{name} — Creative",
                    "object_story_spec": object_story_spec,
                },
            )
            creative_body = r.json() if r.text else {}
            creative_id = creative_body.get("id")
            result["steps"]["creative"] = {"http": r.status_code, "id": creative_id}
            result["creative_id"] = creative_id
            log.info("meta_ads creative created id=%s", creative_id)
        except Exception as exc:
            result["steps"]["creative"] = {"error": str(exc)}
            log.error("meta_ads creative step failed: %s", exc)
            await _log_action(team_id, "meta_ads.create_campaign", payload, result,
                              action_target=campaign_id, status="partial", run_id=run_id)
            return result

        if not creative_id:
            result["steps"]["creative"]["error"] = "no id returned"
            await _log_action(team_id, "meta_ads.create_campaign", payload, result,
                              action_target=campaign_id, status="partial", run_id=run_id)
            return result

        # ── Step 4: Ad ────────────────────────────────────────────────────────
        try:
            r = await client.post(
                f"{base}/{acct}/ads",
                params=auth,
                json={
                    "name": f"{name} — Ad",
                    "adset_id": adset_id,
                    "creative": {"creative_id": creative_id},
                    "status": "PAUSED",
                },
            )
            ad_body = r.json() if r.text else {}
            ad_id = ad_body.get("id")
            result["steps"]["ad"] = {"http": r.status_code, "id": ad_id}
            result["ad_id"] = ad_id
            log.info("meta_ads ad created id=%s", ad_id)
        except Exception as exc:
            result["steps"]["ad"] = {"error": str(exc)}
            log.error("meta_ads ad step failed: %s", exc)
            await _log_action(team_id, "meta_ads.create_campaign", payload, result,
                              action_target=campaign_id, status="partial", run_id=run_id)
            return result

    result["ok"] = bool(result["campaign_id"] and result["adset_id"]
                        and result["creative_id"] and result["ad_id"])
    await _log_action(
        team_id, "meta_ads.create_campaign", payload, result,
        action_target=campaign_id,
        status="executed" if result["ok"] else "partial",
        run_id=run_id,
    )
    return result


async def google_ads_create_campaign(
    team_id: str, *, name: str, daily_budget_usd: float,
    keywords: list[str], target_url: str, headlines: list[str], descriptions: list[str],
    run_id: Optional[str] = None,
    # Optional knobs with sane defaults — keep signature additive only.
    geo_target_country_code: str = "US",
    language_code: str = "en",
    default_cpc_bid_usd: float = 1.0,
) -> dict:
    gate = _missing([
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CUSTOMER_ID",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
        "GOOGLE_ADS_SERVICE_ACCOUNT_JSON",
    ])
    payload = {"name": name, "daily_budget_usd": daily_budget_usd, "keywords": keywords,
               "target_url": target_url, "headlines": headlines, "descriptions": descriptions,
               "geo_target_country_code": geo_target_country_code,
               "language_code": language_code,
               "default_cpc_bid_usd": default_cpc_bid_usd}
    if gate:
        await _log_action(team_id, "google_ads.create_campaign", payload, gate,
                          status="blocked", run_id=run_id)
        return gate

    # Lazy imports — google-ads SDK is heavy and not always installed in dev envs.
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from google.ads.googleads.errors import GoogleAdsException
        from google.oauth2.service_account import Credentials as SACredentials
    except ImportError as exc:
        result = {"ok": False, "error": f"google_ads_sdk_missing: {exc}"}
        await _log_action(team_id, "google_ads.create_campaign", payload, result,
                          status="failed", run_id=run_id)
        return result

    developer_token = os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"]
    customer_id = os.environ["GOOGLE_ADS_CUSTOMER_ID"].replace("-", "")
    login_customer_id = os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"].replace("-", "")
    sa_json_raw = os.environ["GOOGLE_ADS_SERVICE_ACCOUNT_JSON"]

    # Google Ads SDK is synchronous; run the entire build in a thread so the
    # event loop isn't blocked by gRPC calls.
    import asyncio

    def _do_create() -> dict:
        try:
            sa_info = json.loads(sa_json_raw)
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"service_account_json_invalid: {exc}"}

        # Required OAuth scope for Google Ads API.
        scopes = ["https://www.googleapis.com/auth/adwords"]
        try:
            credentials = SACredentials.from_service_account_info(sa_info, scopes=scopes)
        except Exception as exc:
            return {"ok": False, "error": f"service_account_credentials_invalid: {exc}"}

        try:
            client = GoogleAdsClient(
                credentials=credentials,
                developer_token=developer_token,
                login_customer_id=login_customer_id,
                version="v17",
            )
        except Exception as exc:
            return {"ok": False, "error": f"google_ads_client_init_failed: {exc}"}

        try:
            # 1. Campaign Budget (daily, STANDARD delivery, micros).
            budget_service = client.get_service("CampaignBudgetService")
            budget_op = client.get_type("CampaignBudgetOperation")
            budget = budget_op.create
            budget.name = f"{name} — budget"
            budget.amount_micros = int(daily_budget_usd * 1_000_000)
            budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
            budget_resp = budget_service.mutate_campaign_budgets(
                customer_id=customer_id, operations=[budget_op],
            )
            budget_resource_name = budget_resp.results[0].resource_name

            # 2. Search Campaign — PAUSED, ManualCpc, linked to budget.
            campaign_service = client.get_service("CampaignService")
            campaign_op = client.get_type("CampaignOperation")
            campaign = campaign_op.create
            campaign.name = name
            campaign.advertising_channel_type = (
                client.enums.AdvertisingChannelTypeEnum.SEARCH
            )
            campaign.status = client.enums.CampaignStatusEnum.PAUSED
            campaign.manual_cpc.enhanced_cpc_enabled = False
            campaign.campaign_budget = budget_resource_name
            # Search network only by default — Display partners off to keep
            # spend predictable while a human is reviewing.
            campaign.network_settings.target_google_search = True
            campaign.network_settings.target_search_network = True
            campaign.network_settings.target_content_network = False
            campaign.network_settings.target_partner_search_network = False
            campaign_resp = campaign_service.mutate_campaigns(
                customer_id=customer_id, operations=[campaign_op],
            )
            campaign_resource_name = campaign_resp.results[0].resource_name

            # 3. Ad Group — PAUSED, default CPC bid in micros.
            ad_group_service = client.get_service("AdGroupService")
            ad_group_op = client.get_type("AdGroupOperation")
            ad_group = ad_group_op.create
            ad_group.name = f"{name} — ad group"
            ad_group.campaign = campaign_resource_name
            ad_group.status = client.enums.AdGroupStatusEnum.PAUSED
            ad_group.type_ = client.enums.AdGroupTypeEnum.SEARCH_STANDARD
            ad_group.cpc_bid_micros = int(default_cpc_bid_usd * 1_000_000)
            ad_group_resp = ad_group_service.mutate_ad_groups(
                customer_id=customer_id, operations=[ad_group_op],
            )
            ad_group_resource_name = ad_group_resp.results[0].resource_name

            # 4. Keywords as AdGroupCriterion rows, PHRASE match.
            keyword_results: list[str] = []
            if keywords:
                criterion_service = client.get_service("AdGroupCriterionService")
                criterion_ops = []
                for kw_text in keywords:
                    if not kw_text or not kw_text.strip():
                        continue
                    crit_op = client.get_type("AdGroupCriterionOperation")
                    criterion = crit_op.create
                    criterion.ad_group = ad_group_resource_name
                    criterion.status = (
                        client.enums.AdGroupCriterionStatusEnum.PAUSED
                    )
                    criterion.keyword.text = kw_text.strip()
                    criterion.keyword.match_type = (
                        client.enums.KeywordMatchTypeEnum.PHRASE
                    )
                    criterion_ops.append(crit_op)
                if criterion_ops:
                    crit_resp = criterion_service.mutate_ad_group_criteria(
                        customer_id=customer_id, operations=criterion_ops,
                    )
                    keyword_results = [r.resource_name for r in crit_resp.results]

            # 5. Responsive Search Ad — PAUSED, Final URL = target_url.
            ad_group_ad_service = client.get_service("AdGroupAdService")
            ad_op = client.get_type("AdGroupAdOperation")
            ad_group_ad = ad_op.create
            ad_group_ad.ad_group = ad_group_resource_name
            ad_group_ad.status = client.enums.AdGroupAdStatusEnum.PAUSED

            ad = ad_group_ad.ad
            ad.final_urls.append(target_url)

            # Google requires 3–15 headlines, 30 char max each;
            # 2–4 descriptions, 90 char max each. Trim defensively.
            for h in headlines[:15]:
                asset = client.get_type("AdTextAsset")
                asset.text = (h or "")[:30]
                ad.responsive_search_ad.headlines.append(asset)
            for d in descriptions[:4]:
                asset = client.get_type("AdTextAsset")
                asset.text = (d or "")[:90]
                ad.responsive_search_ad.descriptions.append(asset)

            ad_resp = ad_group_ad_service.mutate_ad_group_ads(
                customer_id=customer_id, operations=[ad_op],
            )
            ad_resource_name = ad_resp.results[0].resource_name

            return {
                "ok": True,
                "budget_resource_name": budget_resource_name,
                "campaign_resource_name": campaign_resource_name,
                "ad_group_resource_name": ad_group_resource_name,
                "ad_resource_name": ad_resource_name,
                "keyword_resource_names": keyword_results,
                "status": "PAUSED",
            }
        except GoogleAdsException as exc:
            details: list[str] = []
            try:
                for err in exc.failure.errors:
                    details.append(getattr(err, "message", "") or str(err))
            except Exception:
                pass
            return {
                "ok": False,
                "error": str(exc),
                "request_id": getattr(exc, "request_id", None),
                "details": details,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    try:
        result = await asyncio.to_thread(_do_create)
    except Exception as exc:
        result = {"ok": False, "error": f"thread_dispatch_failed: {exc}"}

    await _log_action(
        team_id, "google_ads.create_campaign", payload, result,
        action_target=result.get("campaign_resource_name"),
        status="executed" if result.get("ok") else "failed",
        run_id=run_id,
    )
    return result


# LinkedIn industry label → URN map. Inline + intentionally small. Unknown
# labels are silently skipped (the agent's targeting widens, not errors). Keep
# keys lowercased for case-insensitive lookup.
_LINKEDIN_INDUSTRY_URNS = {
    "legal services":           "urn:li:industry:9",
    "law practice":             "urn:li:industry:10",
    "accounting":               "urn:li:industry:47",
    "hospital & health care":   "urn:li:industry:14",
    "hospital and health care": "urn:li:industry:14",
    "medical practice":         "urn:li:industry:13",
    "mental health care":       "urn:li:industry:139",
    "financial services":       "urn:li:industry:43",
    "banking":                  "urn:li:industry:41",
    "insurance":                "urn:li:industry:42",
    "professional services":    "urn:li:industry:1810",
    "management consulting":    "urn:li:industry:11",
    "information technology and services": "urn:li:industry:96",
    "it services":              "urn:li:industry:96",
    "computer & network security": "urn:li:industry:118",
    "computer and network security": "urn:li:industry:118",
    "computer software":        "urn:li:industry:4",
    "real estate":              "urn:li:industry:44",
    "construction":             "urn:li:industry:48",
    "manufacturing":            "urn:li:industry:55",
    "pharmaceuticals":          "urn:li:industry:15",
    "biotechnology":            "urn:li:industry:12",
}


def _normalize_linkedin_account_id(raw: str) -> tuple[str, str]:
    """Return (numeric_id, urn) regardless of which form was provided.

    Accepts either `urn:li:sponsoredAccount:123` or plain `123`."""
    if raw.startswith("urn:li:sponsoredAccount:"):
        numeric = raw.split(":")[-1]
    else:
        numeric = raw
    return numeric, f"urn:li:sponsoredAccount:{numeric}"


async def linkedin_ads_create_campaign(
    team_id: str, *, name: str, daily_budget_usd: float,
    target_url: str, ad_copy: str, audience_industries: list[str],
    run_id: Optional[str] = None,
) -> dict:
    """Create a paused LinkedIn Sponsored Content campaign end-to-end.

    Walks the four-object flow: campaign group → campaign → UGC post →
    creative. All objects are left in DRAFT/PAUSED state — an operator must
    manually activate inside LinkedIn Campaign Manager. Safety policy:
    we never auto-launch paid spend on LinkedIn.
    """
    gate = _missing(["LINKEDIN_ADS_ACCESS_TOKEN", "LINKEDIN_AD_ACCOUNT_ID"])
    payload = {"name": name, "daily_budget_usd": daily_budget_usd, "target_url": target_url,
               "ad_copy": ad_copy, "audience_industries": audience_industries}
    if gate:
        await _log_action(team_id, "linkedin_ads.create_campaign", payload, gate,
                          status="blocked", run_id=run_id)
        return gate

    token = os.environ["LINKEDIN_ADS_ACCESS_TOKEN"]
    account_raw = os.environ["LINKEDIN_AD_ACCOUNT_ID"]
    account_numeric, account_urn = _normalize_linkedin_account_id(account_raw)
    org_urn = os.environ.get("LINKEDIN_COMPANY_ORG_ID", "")

    # LinkedIn's REST surface requires a versioned header. Pin to a known
    # recent stable; bump in lockstep with their deprecation cadence.
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": "202405",
        "Content-Type": "application/json",
    }
    base = "https://api.linkedin.com/rest"

    # Resolve audience industry URNs from the inline map. Unknown labels are
    # dropped (warning surfaced in the result), not fatal.
    industry_urns: list[str] = []
    unknown_industries: list[str] = []
    for label in (audience_industries or []):
        urn = _LINKEDIN_INDUSTRY_URNS.get((label or "").strip().lower())
        if urn:
            industry_urns.append(urn)
        else:
            unknown_industries.append(label)

    # Start time: now, in milliseconds since epoch. LinkedIn requires this on
    # the runSchedule even for DRAFT objects.
    import time
    start_ms = int(time.time() * 1000)

    warnings: list[str] = []
    if unknown_industries:
        warnings.append(
            f"unknown_industries_skipped: {unknown_industries}"
        )
    if not org_urn:
        warnings.append(
            "LINKEDIN_COMPANY_ORG_ID not set — creative step will fail; "
            "set it to e.g. urn:li:organization:122373998"
        )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # ── 1. Campaign Group ────────────────────────────────────────
            group_body = {
                "name": f"{name} [group]",
                "status": "DRAFT",
                "totalBudget": None,
                "runSchedule": {"start": start_ms},
            }
            r_group = await client.post(
                f"{base}/adAccounts/{account_numeric}/adCampaignGroups",
                headers=headers, json=group_body,
            )
            if r_group.status_code not in (200, 201):
                result = {
                    "ok": False, "http": r_group.status_code,
                    "body": r_group.json() if r_group.text else {},
                    "error": "campaign_group_create_failed",
                    "stage": "campaign_group",
                }
                await _log_action(
                    team_id, "linkedin_ads.create_campaign", payload, result,
                    status="failed", run_id=run_id,
                )
                return result
            # LinkedIn returns the new entity id in `x-restli-id` header or
            # `id` in the body — prefer the header (consistent across endpoints).
            group_id = (
                r_group.headers.get("x-restli-id")
                or r_group.headers.get("X-RestLi-Id")
                or (r_group.json() if r_group.text else {}).get("id", "")
            )
            group_urn = f"urn:li:sponsoredCampaignGroup:{group_id}"

            # ── 2. Campaign ──────────────────────────────────────────────
            targeting_include_and: list[dict] = [
                {"or": {"urn:li:adTargetingFacet:locations": ["urn:li:geo:103644278"]}}
            ]
            if industry_urns:
                targeting_include_and.append(
                    {"or": {"urn:li:adTargetingFacet:industries": industry_urns}}
                )
            campaign_body = {
                "name": name,
                "campaignGroup": group_urn,
                "type": "SPONSORED_UPDATES",
                "format": "STANDARD_UPDATE",
                "status": "DRAFT",
                "dailyBudget": {
                    "currencyCode": "USD",
                    "amount": f"{daily_budget_usd:.2f}",
                },
                "objectiveType": "WEBSITE_VISIT",
                "costType": "CPC",
                "runSchedule": {"start": start_ms},
                "targetingCriteria": {
                    "include": {"and": targeting_include_and},
                },
            }
            r_camp = await client.post(
                f"{base}/adAccounts/{account_numeric}/adCampaigns",
                headers=headers, json=campaign_body,
            )
            if r_camp.status_code not in (200, 201):
                result = {
                    "ok": False, "http": r_camp.status_code,
                    "body": r_camp.json() if r_camp.text else {},
                    "error": "campaign_create_failed",
                    "stage": "campaign",
                    "campaign_group_id": group_id,
                }
                await _log_action(
                    team_id, "linkedin_ads.create_campaign", payload, result,
                    status="failed", run_id=run_id,
                )
                return result
            campaign_id = (
                r_camp.headers.get("x-restli-id")
                or r_camp.headers.get("X-RestLi-Id")
                or (r_camp.json() if r_camp.text else {}).get("id", "")
            )
            campaign_urn = f"urn:li:sponsoredCampaign:{campaign_id}"

            # ── 3. UGC Share / Post (must exist before a creative refs it) ─
            # `feedDistribution: NONE` keeps the post off the company's organic
            # feed — it exists only as the underlying content for the ad.
            if not org_urn:
                result = {
                    "ok": False,
                    "error": "LINKEDIN_COMPANY_ORG_ID_missing",
                    "stage": "ugc_post",
                    "campaign_group_id": group_id,
                    "campaign_id": campaign_id,
                    "warnings": warnings,
                }
                await _log_action(
                    team_id, "linkedin_ads.create_campaign", payload, result,
                    status="failed", run_id=run_id,
                )
                return result
            post_body = {
                "author": org_urn,
                "commentary": ad_copy,
                "visibility": "PUBLIC",
                "lifecycleState": "PUBLISHED",
                "distribution": {
                    "feedDistribution": "NONE",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                # NOTE: LinkedIn's Posts API does not accept arbitrary outbound
                # URLs at the post level — they get pulled from creative
                # `landingPage` if/when the surface area supports it. We embed
                # target_url in commentary so it is never lost.
                "isReshareDisabledByAuthor": False,
            }
            # Belt-and-suspenders: append target_url to commentary if not
            # already present, so the operator sees where clicks should go.
            if target_url and target_url not in ad_copy:
                post_body["commentary"] = f"{ad_copy}\n\n{target_url}"
            r_post = await client.post(
                f"{base}/posts",
                headers=headers, json=post_body,
            )
            if r_post.status_code not in (200, 201):
                result = {
                    "ok": False, "http": r_post.status_code,
                    "body": r_post.json() if r_post.text else {},
                    "error": "ugc_post_create_failed",
                    "stage": "ugc_post",
                    "campaign_group_id": group_id,
                    "campaign_id": campaign_id,
                    "warnings": warnings,
                }
                await _log_action(
                    team_id, "linkedin_ads.create_campaign", payload, result,
                    status="failed", run_id=run_id,
                )
                return result
            # /rest/posts returns the share URN in x-restli-id (already URN-shaped)
            share_urn = (
                r_post.headers.get("x-restli-id")
                or r_post.headers.get("X-RestLi-Id")
                or (r_post.json() if r_post.text else {}).get("id", "")
            )

            # ── 4. Creative — bind the share to the campaign ─────────────
            creative_body = {
                "campaign": campaign_urn,
                "intendedStatus": "DRAFT",
                "reference": share_urn,
            }
            r_creative = await client.post(
                f"{base}/adAccounts/{account_numeric}/creatives",
                headers=headers, json=creative_body,
            )
            if r_creative.status_code not in (200, 201):
                result = {
                    "ok": False, "http": r_creative.status_code,
                    "body": r_creative.json() if r_creative.text else {},
                    "error": "creative_create_failed",
                    "stage": "creative",
                    "campaign_group_id": group_id,
                    "campaign_id": campaign_id,
                    "share_urn": share_urn,
                    "warnings": warnings,
                }
                await _log_action(
                    team_id, "linkedin_ads.create_campaign", payload, result,
                    status="failed", run_id=run_id,
                )
                return result
            creative_id = (
                r_creative.headers.get("x-restli-id")
                or r_creative.headers.get("X-RestLi-Id")
                or (r_creative.json() if r_creative.text else {}).get("id", "")
            )

            result = {
                "ok": True,
                "campaign_group_id": str(group_id),
                "campaign_id": str(campaign_id),
                "creative_id": str(creative_id),
                "share_urn": share_urn,
                "account_urn": account_urn,
                "manual_activation_url": (
                    f"https://www.linkedin.com/campaignmanager/accounts/"
                    f"{account_numeric}/campaigns/{campaign_id}"
                ),
                "requires_manual_activation": True,
                "status": "DRAFT",
                "warnings": warnings,
            }
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}

    await _log_action(
        team_id, "linkedin_ads.create_campaign", payload, result,
        action_target=str(result.get("campaign_id", "")),
        status="executed" if result.get("ok") else "failed",
        run_id=run_id,
    )
    return result


# ── Outbound ──────────────────────────────────────────────────────────────────

async def apollo_search_contacts(
    team_id: str, *, titles: list[str], industries: Optional[list[str]] = None,
    employee_range: str = "10,200", country: str = "United States",
    limit: int = 25, run_id: Optional[str] = None,
) -> dict:
    gate = _missing(["APOLLO_API_KEY"])
    payload = {"titles": titles, "industries": industries, "employee_range": employee_range,
               "country": country, "limit": limit}
    if gate:
        await _log_action(team_id, "apollo.search", payload, gate, status="blocked", run_id=run_id)
        return gate
    api_key = os.environ["APOLLO_API_KEY"]
    body = {"page": 1, "per_page": min(limit, 25),
            "person_titles": titles,
            "organization_num_employees_ranges": [employee_range],
            "person_locations": [country]}
    if industries:
        body["q_organization_industry"] = industries
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(
                "https://api.apollo.io/v1/mixed_people/api_search",
                json=body,
                headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            )
        data = r.json() if r.text else {}
        contacts = [
            {"name": p.get("name"), "email": p.get("email"),
             "title": p.get("title"), "company": (p.get("organization") or {}).get("name"),
             "linkedin": p.get("linkedin_url")}
            for p in (data.get("people") or [])
        ]
        result = {"ok": r.status_code == 200, "count": len(contacts), "contacts": contacts[:limit]}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    await _log_action(team_id, "apollo.search", payload, result,
                      status="executed" if result.get("ok") else "failed", run_id=run_id)
    return result


async def smartlead_add_to_campaign(
    team_id: str, *,
    campaign_id: int,
    leads: list[dict],
    run_id: Optional[str] = None,
) -> dict:
    """Add Apollo-sourced leads into a Smartlead campaign for warmed, sequenced
    delivery. THIS is the correct cold-outreach path — NOT raw Resend.

    Smartlead handles: inbox rotation, domain warm-up, reply detection,
    bounce handling, unsubscribe. Raw cold email via Resend is forbidden
    for the marketing AI agents (would tank Klaravex domain reputation).

    leads: list of {email, first_name, last_name, company_name,
                    custom_fields: {title, linkedin, ...}}
    """
    gate = _missing(["SMARTLEAD_API_KEY"])
    payload = {"campaign_id": campaign_id, "lead_count": len(leads)}
    if gate:
        await _log_action(team_id, "smartlead.add_to_campaign", payload, gate,
                          status="blocked", run_id=run_id)
        return gate
    api_key = os.environ["SMARTLEAD_API_KEY"]
    # Smartlead's add-leads endpoint expects {"lead_list": [...]}
    cleaned = []
    for lead in leads[:50]:  # cap per call
        e = (lead.get("email") or "").strip().lower()
        if not e or "@" not in e:
            continue
        cleaned.append({
            "email": e,
            "first_name": (lead.get("first_name") or lead.get("name", "").split(" ")[0])[:80],
            "last_name":  (lead.get("last_name")  or " ".join(lead.get("name","").split(" ")[1:]))[:80],
            "company_name": (lead.get("company") or lead.get("company_name") or "")[:120],
            "custom_fields": lead.get("custom_fields") or {},
        })
    if not cleaned:
        result = {"ok": False, "reason": "no_valid_leads"}
        await _log_action(team_id, "smartlead.add_to_campaign", payload, result,
                          status="failed", run_id=run_id)
        return result
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(
                f"https://server.smartlead.ai/api/v1/campaigns/{campaign_id}/leads",
                params={"api_key": api_key},
                json={"lead_list": cleaned},
            )
        ok = r.status_code in (200, 201)
        body = r.json() if r.text else {}
        result = {
            "ok": ok,
            "http": r.status_code,
            "added": len(cleaned),
            "smartlead_response": body if ok else (body or r.text)[:500],
        }
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    await _log_action(team_id, "smartlead.add_to_campaign",
                      {**payload, "leads_attempted": len(cleaned)}, result,
                      action_target=str(campaign_id),
                      status="executed" if result.get("ok") else "failed",
                      run_id=run_id)
    return result


async def smartlead_list_campaigns(
    team_id: str, *, run_id: Optional[str] = None,
) -> dict:
    """Return the catalog of Smartlead campaigns the agent can add leads to.
    Agents should call this first to discover which campaign matches their ICP."""
    gate = _missing(["SMARTLEAD_API_KEY"])
    if gate:
        await _log_action(team_id, "smartlead.list_campaigns", {}, gate,
                          status="blocked", run_id=run_id)
        return gate
    api_key = os.environ["SMARTLEAD_API_KEY"]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://server.smartlead.ai/api/v1/campaigns",
                params={"api_key": api_key},
            )
        data = r.json() if r.text else []
        campaigns = [
            {"id": c.get("id"), "name": c.get("name"), "status": c.get("status")}
            for c in (data if isinstance(data, list) else [])
        ]
        result = {"ok": True, "count": len(campaigns), "campaigns": campaigns}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    await _log_action(team_id, "smartlead.list_campaigns", {}, result,
                      status="executed" if result.get("ok") else "failed",
                      run_id=run_id)
    return result


# ── Audience ownership (prevents team duplication) ────────────────────────────
# Alpha owns B2B marketing (klaravex.com targets). Beta owns consumer marketing
# (personal.klaravex.com targets). Both teams can use ANY channel — the split is
# by audience, not by platform. This prevents duplicate messaging while giving
# each team full creative freedom within their audience.
#
# Enforcement: the `target_url` or `topic` in the draft determines audience.
# If a draft targets klaravex.com → Alpha's lane. personal.klaravex.com → Beta's.
# Generic/unclear → allowed for either (race-promotion, brand awareness).

def _check_audience_ownership(team_code: str, target_url: str = "", topic: str = "") -> tuple[bool, str]:
    """Return (allowed, reason). Enforces audience-based lane separation."""
    target = (target_url + " " + topic).lower()

    is_b2b = any(s in target for s in [
        "klaravex.com/healthcare", "klaravex.com/legal", "klaravex.com/financial",
        "klaravex.com/vciso", "klaravex.com/business", "compliance", "hipaa",
        "soc 2", "iso 27001", "directive", "assurance", "foundation",
        "managed service", "b2b", "enterprise",
    ])
    is_consumer = any(s in target for s in [
        "personal.klaravex.com", "consumer", "family", "senior", "scam",
        "resume", "job-hunt", "ai coaching", "fresh start", "solo-business",
        "it help", "repair", "per-incident",
    ])

    if team_code == "alpha" and is_consumer and not is_b2b:
        return False, "audience_not_owned: Alpha owns B2B — this targets consumer (Beta's lane)"
    if team_code == "beta" and is_b2b and not is_consumer:
        return False, "audience_not_owned: Beta owns consumer — this targets B2B (Alpha's lane)"

    # Generic/unclear or dual-audience → allow for either team
    return True, "ok"


# ── Organic ────────────────────────────────────────────────────────────────────

# Anthony (2026-07-16): a 30-min tick cadence across two competing teams
# produced far more draft volume than one person can review in a day. Cap
# organic post drafting to 2 windows/day total (morning + evening), across
# BOTH teams combined — this is an approval-bandwidth limit, not a per-team
# quota, since the actual constraint is how many drafts Anthony can review.
_ORGANIC_DRAFT_WINDOWS_UTC = [(0, 12), (12, 24)]  # (start_hour, end_hour), UTC

# Weekly batching (2026-07-26): teams submit a week's content plan on Monday,
# Anthony reviews the batch, and approved posts are auto-published on schedule.
# MARKETING_CADENCE env var: "daily" (default, 2 posts/day) or "weekly" (batch Monday)
_MARKETING_CADENCE = os.environ.get("MARKETING_CADENCE", "daily")


async def _organic_draft_window_available(conn) -> tuple[bool, str]:
    """Return (allowed, reason). Checks how many drafts already exist for the
    CURRENT UTC window today, across all teams/platforms.

    In weekly mode: only allows drafts on Monday (ISO weekday 1). Teams submit
    their week's content plan in one batch. Anthony reviews the batch and
    approved posts are auto-published on their scheduled dates.
    """
    now = await conn.fetchval("SELECT now()")

    # Weekly batching: only allow drafts on Monday
    if _MARKETING_CADENCE == "weekly":
        weekday = now.isoweekday()  # 1=Monday
        if weekday != 1:
            return False, f"weekly_cadence: drafts only on Monday (today is day {weekday})"
        # On Monday: allow up to 14 drafts (2/day × 7 days worth of content)
        count = await conn.fetchval(
            "SELECT count(*) FROM klaravex_social_drafts WHERE created_at >= date_trunc('day', now())"
        )
        if count and count >= 14:
            return False, f"weekly_batch_full: {count} drafts already submitted this Monday"
        return True, "ok"

    # Daily mode (default)
    hour = now.hour
    window = next((w for w in _ORGANIC_DRAFT_WINDOWS_UTC if w[0] <= hour < w[1]), None)
    if window is None:
        return False, "no_window_configured"
    count = await conn.fetchval(
        """
        SELECT count(*) FROM klaravex_social_drafts
        WHERE created_at >= date_trunc('day', now()) + make_interval(hours => $1)
          AND created_at <  date_trunc('day', now()) + make_interval(hours => $2)
        """,
        window[0], window[1],
    )
    if count and count > 0:
        return False, f"window_quota_used ({window[0]}-{window[1]}h UTC already has {count} draft(s) today)"
    return True, "ok"


async def organic_post_draft(
    team_id: str, *, platform: str, content: str, topic: str = "",
    run_id: Optional[str] = None,
) -> dict:
    """Drafts a social post into klaravex_social_drafts (existing pipeline).
    Anthony approves; on approve, /publish ships it. This way agents can
    "post" without actually publishing without approval."""
    if platform not in ("linkedin_company", "linkedin_personal", "twitter", "facebook", "instagram", "reddit"):
        return {"ok": False, "error": f"unknown platform: {platform}"}

    # Channel ownership check — prevent teams from duplicating
    team_code = team_id[:5] if len(team_id) > 5 else team_id  # extract alpha/beta
    # Look up team_code from team_id (UUID) if needed
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT team_code FROM klaravex_marketing_teams WHERE id::text = $1",
            team_id,
        )
        if row:
            team_code = row["team_code"]
    ch_allowed, ch_reason = _check_audience_ownership(team_code, topic=topic)
    if not ch_allowed:
        result = {"ok": False, "error": f"audience_blocked: {ch_reason}"}
        await _log_action(team_id, "organic.post_draft", {"platform": platform, "topic": topic},
                          result, status="blocked", run_id=run_id)
        return result

    import uuid, secrets
    token = secrets.token_hex(16)
    async with pool.acquire() as conn:
        allowed, reason = await _organic_draft_window_available(conn)
        if not allowed:
            result = {"ok": False, "error": f"rate_limited: {reason}"}
            await _log_action(team_id, "organic.post_draft", {"platform": platform, "topic": topic},
                              result, status="blocked", run_id=run_id)
            return result
        draft_id = await conn.fetchval(
            """
            INSERT INTO klaravex_social_drafts (platform, content, approval_token, status)
            VALUES ($1, $2, $3, 'pending') RETURNING id::text
            """,
            platform, content, token,
        )
    approve_url = f"{PORTAL_BASE_URL}/api/v1/internal/social/approve/{draft_id}?token={token}"
    result = {"ok": True, "draft_id": draft_id, "approve_url": approve_url, "status": "pending_approval"}
    await _log_action(team_id, "organic.post_draft", {"platform": platform, "topic": topic, "content_chars": len(content)},
                      result, action_target=draft_id,
                      status="executed", approval_required=True, run_id=run_id)
    return result


# ── Utility ───────────────────────────────────────────────────────────────────

async def request_human_approval(
    team_id: str, *, action_summary: str, reason: str,
    proposed_payload: dict, run_id: Optional[str] = None,
) -> dict:
    """Agent escalates a decision to Anthony. Logged + emailed.

    Dedup gate: if an identical (same action_type + action_target) request is
    already in ``pending`` status, skip the email and return the existing row
    rather than flooding Anthony's inbox.

    Cooldown gate: if the same action_type + action_target was *rejected*
    (status='blocked') within the last 24 hours, refuse the re-request.
    """
    # Derive a stable key from the summary + proposed payload so slight
    # wording changes don't bypass dedup. We use action_type from the payload
    # if present, otherwise fall back to the summary text (max 120 chars).
    action_type_key = (
        proposed_payload.get("action_type")
        or proposed_payload.get("type")
        or action_summary[:120]
    )
    action_target_key = (
        proposed_payload.get("action_target")
        or proposed_payload.get("target")
        or proposed_payload.get("name")
        or ""
    )

    pool = await get_pool()
    async with pool.acquire() as conn:
        # 1. Cooldown check: was this same key rejected in the last 24 h?
        blocked_row = await conn.fetchrow(
            """
            SELECT id::text, approved_at
              FROM klaravex_marketing_actions
             WHERE team_id = $1
               AND action_type = 'human.approval_request'
               AND status = 'blocked'
               AND payload->>'summary' LIKE $2
               AND created_at >= now() - interval '24 hours'
             ORDER BY created_at DESC
             LIMIT 1
            """,
            team_id,
            f"%{action_type_key[:80]}%",
        )
        if blocked_row:
            result = {
                "ok": False,
                "skipped": True,
                "reason": "cooldown_active",
                "detail": (
                    "This action was rejected within the last 24 h. "
                    "Re-request after the cooldown expires."
                ),
                "existing_action_id": blocked_row["id"],
            }
            log.info(
                "approval_request cooldown skip team=%s key=%r target=%r",
                team_id[:8], action_type_key[:40], action_target_key[:40],
            )
            return result

        # 2. Dedup check: is there already a pending row for this same action?
        pending_row = await conn.fetchrow(
            """
            SELECT id::text
              FROM klaravex_marketing_actions
             WHERE team_id = $1
               AND action_type = 'human.approval_request'
               AND status = 'pending'
               AND approval_required
               AND payload->>'summary' LIKE $2
             ORDER BY created_at DESC
             LIMIT 1
            """,
            team_id,
            f"%{action_type_key[:80]}%",
        )
        if pending_row:
            result = {
                "ok": True,
                "skipped": True,
                "reason": "already_pending",
                "detail": "An identical approval request is already queued.",
                "existing_action_id": pending_row["id"],
                "status": "pending_anthony_review",
            }
            log.info(
                "approval_request dedup skip team=%s existing=%s",
                team_id[:8], pending_row["id"],
            )
            return result

    payload = {"summary": action_summary, "reason": reason, "proposed": proposed_payload}
    action_id = await _log_action(team_id, "human.approval_request", payload, {"queued": True},
                                  status="pending", approval_required=True, run_id=run_id)
    try:
        await send_email(
            to=APPROVAL_EMAIL,
            subject=f"[Marketing AI {team_id[:8]}] approval needed: {action_summary[:80]}",
            body=(
                f"Team requests approval.\n\n"
                f"Summary: {action_summary}\n"
                f"Reason: {reason}\n\n"
                f"Proposed payload:\n{json.dumps(proposed_payload, indent=2)}\n\n"
                f"Review in portal: {PORTAL_BASE_URL}/portal/admin/marketing-leaderboard\n"
            ),
        )
    except Exception as exc:
        log.warning("approval email failed: %s", exc)
    return {"ok": True, "action_id": action_id, "status": "pending_anthony_review"}


async def log_observation(team_id: str, *, summary: str, data: dict,
                          run_id: Optional[str] = None) -> dict:
    """Generic logging for analyst-agent observations."""
    action_id = await _log_action(team_id, "observation", {"summary": summary, "data": data}, {},
                                  status="executed", run_id=run_id)
    return {"ok": True, "action_id": action_id}


# ── Brand-voice guardrail ─────────────────────────────────────────────────────

async def brand_voice_classifier(text: str) -> dict:
    """Local LLM call that classifies copy against Klaravex brand voice.
    Returns {ok: bool, reason: str}. Used by organic_post_draft + ad copy paths
    before any external API call."""
    litellm_url = os.environ.get("LITELLM_URL", "")
    litellm_key = os.environ.get("LITELLM_MASTER_KEY", "")
    if not (litellm_url and litellm_key):
        return {"ok": True, "reason": "classifier_disabled"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{litellm_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {litellm_key}"},
                json={
                    "model": "deepseek",
                    "max_tokens": 80,
                    "temperature": 0.0,
                    "messages": [{
                        "role": "user",
                        "content": (
                            "You are the Klaravex brand voice gate. Klaravex is a corporation; "
                            "every surface must speak as the corporation, never as an individual. "
                            "FAIL immediately if the copy: uses first-person singular ('I', 'me', "
                            "'my', 'I built…', 'I was let go…'); tells a personal biography or "
                            "layoff story; names the founder/operator; says 'Klara AI' (internal name — "
                            "should be 'our AI' or 'Klaravex AI'); signs off as an individual person. "
                            "Also FAIL for: buzzwords, overclaiming, fake urgency, scarcity tricks, "
                            "excessive emojis. Brand voice is direct, confident, third-person, "
                            "speaks as 'we'/'Klaravex'. Reply with exactly one of:\n"
                            "PASS\n"
                            "FAIL: <one-sentence reason>\n\n"
                            f"Copy:\n---\n{text[:1500]}\n---"
                        ),
                    }],
                },
            )
            if r.status_code != 200:
                return {"ok": True, "reason": f"classifier_llm_error_{r.status_code}"}
            out = r.json()["choices"][0]["message"]["content"].strip()
        if out.startswith("PASS"):
            return {"ok": True, "reason": "pass"}
        return {"ok": False, "reason": out[:300]}
    except Exception as exc:
        return {"ok": True, "reason": f"classifier_error_open_fail: {exc}"}


# Exported tool catalog the agents see.
#
# Cold outreach MUST go through Smartlead (handles inbox rotation, warm-up,
# reply detection, unsubscribe). Raw Resend is NOT exposed to agents to
# protect Klaravex domain reputation.
TOOL_CATALOG = {
    "meta_ads.create_campaign":     meta_ads_create_campaign,
    "google_ads.create_campaign":   google_ads_create_campaign,
    "linkedin_ads.create_campaign": linkedin_ads_create_campaign,
    "apollo.search_contacts":       apollo_search_contacts,
    "smartlead.list_campaigns":     smartlead_list_campaigns,
    "smartlead.add_to_campaign":    smartlead_add_to_campaign,
    "organic.post_draft":           organic_post_draft,
    "human.request_approval":       request_human_approval,
    "log.observation":              log_observation,
}
