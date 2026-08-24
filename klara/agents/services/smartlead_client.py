"""
app/services/smartlead_client.py
──────────────────────────────────
Async HTTPX wrapper around the Smartlead REST API.

Smartlead is Klara AI's cold-outreach transport from 2026-05-29 onward — replacing
the direct Resend dispatch for prospecting_outreach.send. Resend remains in
place for transactional system mail (daily reports, etc.).

Architecture:
  - One master campaign (id pinned in settings.smartlead_master_campaign_id)
  - Sequence template uses Mustache-style `{{subject_line}}` / `{{personalized_body}}`
  - Each Klara AI prospect is added to the campaign with the Claude-drafted
    subject + body as custom_fields on the lead
  - Smartlead's scheduler dispatches via the OAuth-connected M365 mailbox
  - Reply / bounce / open / click / unsubscribe events come back via the
    /api/v1/webhooks/smartlead receiver in app/api/webhooks_smartlead.py

All methods are async and use httpx.AsyncClient with explicit timeouts. Errors
return the raw httpx.Response so callers can decide whether to retry, fall back
to Resend, or surface to the dashboard.

API reference: https://api.smartlead.ai/reference/
"""
from __future__ import annotations

from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)


class SmartleadError(Exception):
    """Raised when the Smartlead API returns a non-2xx response."""

    def __init__(self, status_code: int, body: str, path: str):
        super().__init__(f"Smartlead {status_code} on {path}: {body[:200]}")
        self.status_code = status_code
        self.body = body
        self.path = path


class SmartleadClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://server.smartlead.ai/api/v1",
        timeout: float = 30.0,
    ):
        if not api_key:
            raise ValueError("SmartleadClient requires a non-empty api_key")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout, connect=10.0)

    # ── Internal request helpers ──────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> Any:
        merged_params = {"api_key": self._api_key}
        if params:
            merged_params.update(params)
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.request(
                    method, url, params=merged_params, json=json_body
                )
            except httpx.TimeoutException as exc:
                logger.error("smartlead.timeout", path=path, method=method)
                raise SmartleadError(0, f"timeout: {exc}", path) from exc
            except httpx.HTTPError as exc:
                logger.error("smartlead.transport_error", path=path, error=str(exc))
                raise SmartleadError(0, f"transport: {exc}", path) from exc

        if resp.status_code >= 400:
            logger.error(
                "smartlead.error",
                path=path,
                method=method,
                status=resp.status_code,
                body=resp.text[:300],
            )
            raise SmartleadError(resp.status_code, resp.text, path)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # ── Campaign management ───────────────────────────────────────────────────

    async def list_campaigns(self) -> list[dict]:
        return await self._request("GET", "/campaigns/")

    async def get_campaign(self, campaign_id: int) -> dict:
        return await self._request("GET", f"/campaigns/{campaign_id}")

    async def create_campaign(
        self, name: str, client_id: Optional[int] = None
    ) -> dict:
        return await self._request(
            "POST",
            "/campaigns/create",
            json_body={"name": name, "client_id": client_id},
        )

    async def update_campaign_settings(
        self,
        campaign_id: int,
        *,
        max_leads_per_day: Optional[int] = None,
        min_time_btwn_emails: Optional[int] = None,
        stop_lead_settings: Optional[str] = None,
        unsubscribe_text: Optional[str] = None,
        track_settings: Optional[list[str]] = None,
        send_as_plain_text: Optional[bool] = None,
        follow_up_percentage: Optional[int] = None,
        enable_ai_esp_matching: Optional[bool] = None,
    ) -> dict:
        body: dict[str, Any] = {}
        if max_leads_per_day is not None:
            body["max_leads_per_day"] = max_leads_per_day
        if min_time_btwn_emails is not None:
            body["min_time_btwn_emails"] = min_time_btwn_emails
        if stop_lead_settings is not None:
            body["stop_lead_settings"] = stop_lead_settings
        if unsubscribe_text is not None:
            body["unsubscribe_text"] = unsubscribe_text
        if track_settings is not None:
            body["track_settings"] = track_settings
        if send_as_plain_text is not None:
            body["send_as_plain_text"] = send_as_plain_text
        if follow_up_percentage is not None:
            body["follow_up_percentage"] = follow_up_percentage
        if enable_ai_esp_matching is not None:
            body["enable_ai_esp_matching"] = enable_ai_esp_matching
        return await self._request(
            "POST", f"/campaigns/{campaign_id}/settings", json_body=body
        )

    async def set_campaign_schedule(
        self,
        campaign_id: int,
        *,
        timezone_str: str = "Europe/Berlin",
        days_of_the_week: Optional[list[int]] = None,
        start_hour: str = "09:00",
        end_hour: str = "18:00",
        min_time_btw_emails: int = 20,
        max_new_leads_per_day: int = 30,
        schedule_start_time: Optional[str] = None,
    ) -> dict:
        if days_of_the_week is None:
            days_of_the_week = [1, 2, 3, 4, 5]
        body = {
            "timezone": timezone_str,
            "days_of_the_week": days_of_the_week,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "min_time_btw_emails": min_time_btw_emails,
            "max_new_leads_per_day": max_new_leads_per_day,
        }
        if schedule_start_time:
            body["schedule_start_time"] = schedule_start_time
        return await self._request(
            "POST", f"/campaigns/{campaign_id}/schedule", json_body=body
        )

    async def add_email_accounts_to_campaign(
        self, campaign_id: int, email_account_ids: list[int]
    ) -> dict:
        return await self._request(
            "POST",
            f"/campaigns/{campaign_id}/email-accounts",
            json_body={"email_account_ids": email_account_ids},
        )

    async def list_campaign_email_accounts(self, campaign_id: int) -> list[dict]:
        return await self._request(
            "GET", f"/campaigns/{campaign_id}/email-accounts"
        )

    async def start_campaign(self, campaign_id: int) -> dict:
        return await self._request(
            "POST",
            f"/campaigns/{campaign_id}/status",
            json_body={"status": "START"},
        )

    async def pause_campaign(self, campaign_id: int) -> dict:
        return await self._request(
            "POST",
            f"/campaigns/{campaign_id}/status",
            json_body={"status": "PAUSED"},
        )

    # ── Sequence (email template) ─────────────────────────────────────────────

    async def get_sequences(self, campaign_id: int) -> list[dict]:
        return await self._request("GET", f"/campaigns/{campaign_id}/sequences")

    async def save_sequences(
        self, campaign_id: int, sequences: list[dict]
    ) -> dict:
        """
        sequences is a list of step dicts, each shaped like:
          {
            "seq_number": 1,
            "seq_delay_details": {"delay_in_days": 0},
            "variant_distribution_type": "MANUAL_EQUAL",
            "lead_distribution_percentage": 100,
            "winning_metric_property": "OPEN_RATE",
            "seq_variants": [
              {"subject": "{{subject_line}}",
               "email_body": "{{personalized_body}}",
               "variant_label": "A"},
            ]
          }
        """
        return await self._request(
            "POST",
            f"/campaigns/{campaign_id}/sequences",
            json_body={"sequences": sequences},
        )

    # ── Leads ─────────────────────────────────────────────────────────────────

    async def add_leads_to_campaign(
        self,
        campaign_id: int,
        leads: list[dict],
        *,
        ignore_global_block_list: bool = False,
        ignore_unsubscribe_list: bool = False,
        ignore_duplicate_leads_in_other_campaign: bool = False,
    ) -> dict:
        """
        Each lead is shaped like:
          {
            "first_name": "...",
            "last_name": "...",
            "email": "...",
            "company_name": "...",
            "custom_fields": {
              "subject_line": "...",
              "personalized_body": "...",
              ...
            }
          }
        """
        body = {
            "lead_list": leads,
            "settings": {
                "ignore_global_block_list": ignore_global_block_list,
                "ignore_unsubscribe_list": ignore_unsubscribe_list,
                "ignore_duplicate_leads_in_other_campaign":
                    ignore_duplicate_leads_in_other_campaign,
            },
        }
        return await self._request(
            "POST", f"/campaigns/{campaign_id}/leads", json_body=body
        )

    async def list_campaign_leads(
        self, campaign_id: int, *, limit: int = 100, offset: int = 0
    ) -> dict:
        return await self._request(
            "GET",
            f"/campaigns/{campaign_id}/leads",
            params={"limit": limit, "offset": offset},
        )

    async def get_lead_by_email(self, email: str) -> dict:
        return await self._request(
            "GET", "/leads/", params={"email": email}
        )

    # ── Email accounts ────────────────────────────────────────────────────────

    async def list_email_accounts(
        self, *, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        return await self._request(
            "GET",
            "/email-accounts/",
            params={"limit": limit, "offset": offset},
        )

    # ── Suppression (global block list) ───────────────────────────────────────

    async def add_to_block_list(
        self, *, domain_block_list: Optional[list[str]] = None
    ) -> dict:
        """
        Add domain(s) to the workspace-wide block list. Smartlead's suppression
        model is domain-scoped at the global level; individual email addresses
        are blocked by adding their domain (use this for bounced emails by
        passing the full address as a single-element list — the API accepts
        both domain and full-address forms).
        """
        body = {"domain_block_list": domain_block_list or []}
        return await self._request(
            "POST", "/leads/add-domain-block-list", json_body=body
        )

    # ── Webhooks ──────────────────────────────────────────────────────────────

    async def list_webhooks(self, campaign_id: int) -> list[dict]:
        return await self._request(
            "GET", f"/campaigns/{campaign_id}/webhooks"
        )

    async def register_webhook(
        self,
        campaign_id: int,
        *,
        name: str,
        webhook_url: str,
        event_types: list[str],
        categories: Optional[list[str]] = None,
        webhook_id: Optional[int] = None,
    ) -> dict:
        """
        event_types: any combination of
          "EMAIL_SENT", "EMAIL_OPEN", "EMAIL_LINK_CLICK", "EMAIL_REPLY",
          "EMAIL_BOUNCE", "LEAD_CATEGORY_UPDATED"
        """
        body: dict[str, Any] = {
            "name": name,
            "webhook_url": webhook_url,
            "event_types": event_types,
        }
        if categories is not None:
            body["categories"] = categories
        if webhook_id is not None:
            body["id"] = webhook_id
        return await self._request(
            "POST", f"/campaigns/{campaign_id}/webhooks", json_body=body
        )

    async def delete_webhook(self, campaign_id: int, webhook_id: int) -> dict:
        return await self._request(
            "DELETE",
            f"/campaigns/{campaign_id}/webhooks",
            params={"id": webhook_id},
        )


def get_client(settings) -> SmartleadClient:
    """Factory that reads credentials from Settings — raises if unconfigured."""
    if not settings.smartlead_api_key:
        raise RuntimeError(
            "SMARTLEAD_API_KEY not configured — set in .env to enable the "
            "Smartlead transport."
        )
    return SmartleadClient(
        api_key=settings.smartlead_api_key,
        base_url=settings.smartlead_api_base,
    )
