"""Tests for GA4 conversion intake handler (readiness_review_intake)."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request

from infra.klara.handlers.readiness_review_intake import (
    ReadinessReviewSubmit,
    submit,
)
from services.ga4_measurement_protocol import (
    _hashed_user_data,
    send_event,
)


def _fake_request() -> Request:
    """Minimal real starlette Request so @limiter.limit's isinstance(request,
    Request) check and client_key()'s header/client access both work when
    tests call `submit()` directly instead of going through the ASGI app."""
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
    monkeypatch.setenv("CALENDLY_READINESS_REVIEW_URL", "https://calendly.test/rr")


@pytest.mark.asyncio
async def test_readiness_review_submit_fires_ga4_event():
    mock_send_event = AsyncMock(return_value={"ok": True, "status": 200})
    mock_hashed_user_data = patch(
        "infra.klara.handlers.readiness_review_intake._hashed_user_data",
        return_value={"sha256_email_address": "hashed_email"},
    ).start()
    with patch(
        "infra.klara.handlers.readiness_review_intake.send_event", mock_send_event
    ):
        request_data = ReadinessReviewSubmit(
            email="test_rr@example.com",
            first_name="RR",
            last_name="User",
            phone_e164="+15559876543",
            company="RR_Corp",
            vertical="healthcare",
            firm_size=25,
            regulator="HIPAA",
            utm_source="linkedin",
            utm_medium="social",
            ga_client_id="GA1.1.rr_client_id",
        )
        response = await submit(request_data, _fake_request())

        assert response["ok"] is True
        assert "booking_id" in response
        assert response["calendly_url"] == "https://calendly.test/rr"
        mock_send_event.assert_called_once_with(
            client_id="GA1.1.rr_client_id",
            event_name="readiness_review_booked",
            params={
                "value": 250,
                "currency": "USD",
                "vertical": "healthcare",
                "channel": "linkedin",
                "firm_size": 25,
                "regulator": "HIPAA",
                "booking_id": response["booking_id"],
            },
            user_id="test_rr@example.com", # Corrected to "test_rr@example.com"
            user_data={"sha256_email_address": "hashed_email"},
        )
        mock_hashed_user_data.assert_called_once_with(
            email="test_rr@example.com",
            phone_e164="+15559876543",
            first_name="RR",
            last_name="User",
            country="US",
            postal_code=None,
        )

@pytest.mark.asyncio
async def test_ga4_event_sending_graceful_failure_rr(monkeypatch):
    monkeypatch.delenv("GA4_MEASUREMENT_ID", raising=False)
    monkeypatch.delenv("GA4_API_SECRET", raising=False)

    mock_send_event = AsyncMock(return_value={"ok": False, "status": 0, "reason": "missing_env"})
    with patch(
        "infra.klara.handlers.readiness_review_intake.send_event", mock_send_event
    ):
        request_data = ReadinessReviewSubmit(
            email="fail_rr@example.com",
            vertical="general",
            firm_size=10,
            regulator="None",
        )
        response = await submit(request_data, _fake_request())

        assert response["ok"] is True  # still ok from user perspective
        mock_send_event.assert_called_once()  # called, but returned not ok


@pytest.mark.asyncio
async def test_utm_source_channel_mapping_rr():
    mock_send_event = AsyncMock(return_value={"ok": True, "status": 200})
    with patch(
        "infra.klara.handlers.readiness_review_intake.send_event", mock_send_event
    ):
        req_gads = ReadinessReviewSubmit(email="gads_rr@example.com", vertical="general")
        req_gads.utm_source = "google_ads"
        req_gads.utm_medium = "cpc"
        await submit(req_gads, _fake_request())

        req_linkedin = ReadinessReviewSubmit(email="linkedin_rr@example.com", vertical="general")
        req_linkedin.utm_source = "linkedin"
        req_linkedin.utm_medium = "social"
        await submit(req_linkedin, _fake_request())

        req_direct = ReadinessReviewSubmit(email="direct_rr@example.com", vertical="general")
        await submit(req_direct, _fake_request())

        assert mock_send_event.call_count == 3
        call_gads = mock_send_event.call_args_list[0]
        assert call_gads[1]["params"]["channel"] == "google_ads"

        call_linkedin = mock_send_event.call_args_list[1]
        assert call_linkedin[1]["params"]["channel"] == "linkedin"

        call_direct = mock_send_event.call_args_list[2]
        assert call_direct[1]["params"]["channel"] == "direct"
