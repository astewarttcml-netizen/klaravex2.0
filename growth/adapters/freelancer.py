"""Growth adapters: Freelancer.com bid submission.

This module provides functionality to submit bids to Freelancer.com platform,
integrating with the existing freelance bid pipeline.
"""

import os
import json
import requests
from typing import Dict, Any, Optional
from urllib.parse import urljoin

from growth.sessions.vault import PLATFORMS
from growth.poc import is_poc_mode
from growth.adapters.clay import enrich

# Constants for Freelancer.com API
FREELANCER_API_BASE = "https://www.freelancer.com/api/"
BID_SUBMISSION_ENDPOINT = "bids/0.1/bids/"

class FreelancerAdapterError(Exception):
    """Custom exception for Freelancer adapter errors."""
    pass

def _get_api_token() -> str:
    """Get the Freelancer API token from environment variables."""
    return (
        os.environ.get("FREELANCER_ACCESS_TOKEN") or
        os.environ.get("FREELANCER_OAUTH_TOKEN", "")
    )

def _is_configured() -> bool:
    """Check if Freelancer adapter is properly configured."""
    return bool(_get_api_token())

def _make_api_request(
    method: str,
    endpoint: str,
    data: Optional[Dict] = None,
    headers: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Make a request to the Freelancer.com API.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE)
        endpoint: API endpoint path
        data: Request payload data
        headers: Additional headers

    Returns:
        JSON response from the API

    Raises:
        FreelancerAdapterError: If the request fails
    """
    token = _get_api_token()
    if not token:
        raise FreelancerAdapterError("Freelancer API token not configured")

    url = urljoin(FREELANCER_API_BASE, endpoint)

    default_headers = {
        "Freelancer-OAuth-V1": token,
        "Content-Type": "application/json",
    }

    if headers:
        default_headers.update(headers)

    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=default_headers, timeout=30)
        elif method.upper() == "POST":
            response = requests.post(url, headers=default_headers, json=data, timeout=30)
        elif method.upper() == "PUT":
            response = requests.put(url, headers=default_headers, json=data, timeout=30)
        elif method.upper() == "DELETE":
            response = requests.delete(url, headers=default_headers, timeout=30)
        else:
            raise FreelancerAdapterError(f"Unsupported HTTP method: {method}")

        if response.status_code in [401, 403]:
            raise FreelancerAdapterError("Freelancer API authentication failed - check your token")
        elif response.status_code >= 400:
            try:
                error_data = response.json()
                error_msg = error_data.get('error', 'Unknown API error')
            except:
                error_msg = response.text
            raise FreelancerAdapterError(f"Freelancer API error ({response.status_code}): {error_msg}")

        return response.json()

    except requests.RequestException as exc:
        raise FreelancerAdapterError(f"Network request failed: {exc}")

def _get_project_details(project_id: str) -> Dict[str, Any]:
    """
    Get project details from Freelancer.com.

    Args:
        project_id: The ID of the project

    Returns:
        Project details dictionary
    """
    if is_poc_mode():
        return {
            "id": project_id,
            "title": "Sample Project for Testing",
            "description": "This is a sample project description for testing purposes.",
            "budget": {"min": 100, "max": 500},
            "skills": ["Python", "Django"],
        }

    try:
        response = _make_api_request("GET", f"projects/0.1/projects/{project_id}")
        return response.get('result', {})
    except Exception as exc:
        raise FreelancerAdapterError(f"Failed to fetch project details: {exc}")

def submit_bid(
    project_id: str,
    cover_letter: str,
    bid_amount: float,
    delivery_days: int = 7,
    currency_code: str = "EUR"
) -> Dict[str, Any]:
    """
    Submit a bid to a Freelancer.com project.

    Args:
        project_id: The ID of the project to bid on
        cover_letter: The cover letter for the bid
        bid_amount: The bid amount
        delivery_days: Number of days to complete the project
        currency_code: Currency code (default: EUR)

    Returns:
        Dictionary with submission result

    Raises:
        FreelancerAdapterError: If bid submission fails
    """
    if is_poc_mode():
        # Simulate successful submission in POC mode
        return {
            "status": "success",
            "bid_id": "test_bid_12345",
            "project_id": project_id,
            "message": "Bid submitted successfully (POC mode)"
        }

    if not _is_configured():
        raise FreelancerAdapterError("Freelancer adapter not configured - missing API token")

    # Prepare bid data
    bid_data = {
        "project_id": project_id,
        "bid_amount": bid_amount,
        "delivery_days": delivery_days,
        "currency_code": currency_code,
        "cover_letter": cover_letter,
        "is_private": True  # Make the bid private to avoid exposing contact info
    }

    try:
        response = _make_api_request("POST", BID_SUBMISSION_ENDPOINT, data=bid_data)

        if response.get('status') == 'success':
            return {
                "status": "success",
                "bid_id": response.get('result', {}).get('id'),
                "project_id": project_id,
                "message": "Bid submitted successfully to Freelancer.com"
            }
        else:
            error_msg = response.get('error', 'Unknown error')
            raise FreelancerAdapterError(f"Bid submission failed: {error_msg}")

    except Exception as exc:
        raise FreelancerAdapterError(f"Failed to submit bid to Freelancer.com: {exc}")

def get_user_profile() -> Dict[str, Any]:
    """
    Get the current user's profile information.

    Returns:
        User profile data
    """
    if is_poc_mode():
        return {
            "username": "test_user",
            "id": "test_user_12345",
            "display_name": "Test User",
            "reputation": 95,
            "country": "Germany"
        }

    try:
        response = _make_api_request("GET", "users/0.1/self/")
        return response.get('result', {})
    except Exception as exc:
        raise FreelancerAdapterError(f"Failed to fetch user profile: {exc}")

def probe_status() -> Dict[str, Any]:
    """
    Probe the Freelancer.com adapter status.

    Returns:
        Status information
    """
    if is_poc_mode():
        return {
            "adapter": "freelancer",
            "action": "probe",
            "status": "ready",
            "creds_configured": True,
            "detail": "Freelancer.com adapter in POC mode",
            "sample": {"mode": "poc"}
        }

    if not _is_configured():
        return {
            "adapter": "freelancer",
            "action": "probe",
            "status": "stub",
            "creds_configured": False,
            "detail": "Freelancer.com: no API token. Set FREELANCER_ACCESS_TOKEN from developers.freelancer.com",
            "sample": {},
        }

    try:
        profile = get_user_profile()
        return {
            "adapter": "freelancer",
            "action": "probe",
            "status": "connected",
            "creds_configured": True,
            "detail": f"Freelancer.com API connected (user {profile.get('username', 'unknown')})",
            "sample": {
                "username": profile.get("username"),
                "display_name": profile.get("display_name"),
                "reputation": profile.get("reputation")
            },
        }
    except Exception as exc:
        return {
            "adapter": "freelancer",
            "action": "probe",
            "status": "error",
            "creds_configured": True,
            "detail": f"Freelancer.com: probe failed ({exc})",
            "sample": {},
        }

def submit_bid_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Submit a bid using the payload from the freelance pipeline.

    Args:
        payload: The bid submission payload

    Returns:
        Submission result
    """
    try:
        # Extract required fields from payload
        project_id = payload.get('project_id')
        cover_letter = payload.get('cover_letter', '')
        bid_amount = payload.get('bid_amount')
        delivery_days = payload.get('delivery_days', 7)
        currency_code = payload.get('bid_currency', 'EUR')

        if not project_id:
            raise FreelancerAdapterError("Missing project_id in payload")

        if bid_amount is None:
            raise FreelancerAdapterError("Missing bid_amount in payload")

        # Submit the bid
        result = submit_bid(
            project_id=project_id,
            cover_letter=cover_letter,
            bid_amount=bid_amount,
            delivery_days=delivery_days,
            currency_code=currency_code
        )

        return {
            "success": True,
            "message": "Bid submitted successfully to Freelancer.com",
            **result
        }

    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "message": f"Failed to submit bid to Freelancer.com: {exc}"
        }

# Register the adapter
if __name__ == "__main__":
    # This is for testing purposes
    print("Freelancer.com adapter module loaded")