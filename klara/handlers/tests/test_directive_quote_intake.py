"""Tests for GA4 conversion intake handler (directive_quote_intake)."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request

from infra.klara.handlers.directive_quote_intake import (
    DirectiveQuoteRequest,
    request_pricing,
)
from services.ga4_measurement_protocol import (
    _hashed_user_data,
    send_event,
)


def _fake_request() -> Request:
    """Minimal real starlette Request so @limiter.limit's isinstance(request,
    Request) check and client_key()'s header/client access both work when
    tests call `request_pricing()` directly instead of going through the ASGI app."""
    return Request({
        "type": "http",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "method": "POST",
        "path": "/",
    })


@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    monkeypatch.setenv("GA4_MEASUREMENT_ID", "G-TEST-ID")
    monkeypatch.setenv("GA4_API_SECRET", "test-secret")


@pytest.mark.asyncio
async def test_directive_quote_request_fires_ga4_event():
    mock_send_event = AsyncMock(return_value={"ok": True, "status": 200})
    mock_hashed_user_data = patch(
        "infra.klara.handlers.directive_quote_intake._hashed_user_data",
        return_value={"sha256_email_address": "hashed_email"},
    ).start()
    with patch(
        "infra.klara.handlers.directive_quote_intake.send_event", mock_send_event
    ):
        request_data = DirectiveQuoteRequest(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            phone_e164="+15551234567",
            company="TestCorp",
            vertical="general",
            firm_size=50,
            regulator="SOC2",
            utm_source="google_ads",
            utm_medium="cpc",
            ga_client_id="GA1.1.test_client_id",
        )
        response = await request_pricing(request_data, _fake_request())

        assert response["ok"] is True
        assert "quote_id" in response
        mock_send_event.assert_called_once_with(
            client_id="GA1.1.test_client_id",
            event_name="directive_quote_requested",
            params={
                "value": 500,
                "currency": "USD",
                "vertical": "general",
                "channel": "google_ads",
                "firm_size": 50,
                "regulator": "SOC2",
                "quote_id": response["quote_id"],
            },
            user_id="test@example.com",
            user_data={"sha256_email_address": "hashed_email"},
        )
        mock_hashed_user_data.assert_called_once_with(
            email="test@example.com",
            phone_e164="+15551234567",
            first_name="Test",
            last_name="User",
            country="US", # Corrected to "US"
            postal_code=None,
        )


@pytest.mark.asyncio
async def test_ga4_event_sending_graceful_failure(monkeypatch):
    monkeypatch.delenv("GA4_MEASUREMENT_ID", raising=False)
    monkeypatch.delenv("GA4_API_SECRET", raising=False)

    mock_send_event = AsyncMock(return_value={"ok": False, "status": 0, "reason": "missing_env"})
    with patch(
        "infra.klara.handlers.directive_quote_intake.send_event", mock_send_event
    ):
        request_data = DirectiveQuoteRequest(
            email="fail@example.com",
            company="FailCorp",
            vertical="general",
            firm_size=10,
            regulator="None",
        )
        response = await request_pricing(request_data, _fake_request())

        assert response["ok"] is True  # still ok from user perspective
        mock_send_event.assert_called_once()  # called, but returned not ok


@pytest.mark.asyncio
async def test_utm_source_channel_mapping():
    # Mock send_event to prevent actual GA4 calls and capture parameters
    mock_send_event = AsyncMock(return_value={"ok": True, "status": 200})
    with patch(
        "infra.klara.handlers.directive_quote_intake.send_event", mock_send_event
    ):
        # Test with Google Ads UT
        req_gads = DirectiveQuoteRequest(email="gads@example.com", firm_size=1, regulator="X")
        req_gads.utm_source = "google_ads"
        req_gads.utm_medium = "cpc"
        await request_pricing(req_gads, _fake_request())

        # Test with LinkedIn UT
        req_linkedin = DirectiveQuoteRequest(email="linkedin@example.com", firm_size=1, regulator="X")
        req_linkedin.utm_source = "linkedin"
        req_linkedin.utm_medium = "social"
        await request_pricing(req_linkedin, _fake_request())

        # Test with direct traffic (no UTMs)
        req_direct = DirectiveQuoteRequest(email="direct@example.com", firm_size=1, regulator="X")
        await request_pricing(req_direct, _fake_request())

        # Assertions
        assert mock_send_event.call_count == 3
        call_gads = mock_send_event.call_args_list[0]
        assert call_gads[1]["params"]["channel"] == "google_ads"

        call_linkedin = mock_send_event.call_args_list[1]
        assert call_linkedin[1]["params"]["channel"] == "linkedin"

        call_direct = mock_send_event.call_args_list[2]
        assert call_direct[1]["params"]["channel"] == "direct"
