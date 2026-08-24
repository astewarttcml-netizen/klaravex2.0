"""
Hunter.io email verification client.

Verifies prospect email addresses before outreach to prevent bounces
and protect the domain sender reputation.

API docs: https://hunter.io/api-documentation/v2
"""
import httpx
import structlog

log = structlog.get_logger(__name__)
HUNTER_BASE = "https://api.hunter.io/v2"


async def verify_email(email: str, api_key: str) -> dict:
    """
    Verify an email address via Hunter.io.

    Returns a dict with keys:
      result:     "deliverable" | "risky" | "undeliverable" | "unknown"
      score:      0–100 deliverability score
      regexp:     bool — passes syntax/regex check
      gibberish:  bool — looks like a spam address
      disposable: bool — temporary/burner address

    Returns {"result": "unknown", "score": 0} on any API error so the
    pipeline degrades gracefully rather than crashing.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get(
                f"{HUNTER_BASE}/email-verifier",
                params={"email": email, "api_key": api_key},
            )
            r.raise_for_status()
            return r.json().get("data", {})
        except Exception as exc:
            log.warning("hunter_verify_failed", email=email, error=str(exc))
            return {"result": "unknown", "score": 0}


def should_skip_lead(verification: dict) -> bool:
    """
    Return True if outreach should be skipped based on verification result.

    Skips:
      - result == "undeliverable" (hard bounce guaranteed)
      - score < 50 (high bounce risk)
      - disposable == True (throwaway addresses)
    """
    if not verification:
        return False
    result = verification.get("result", "unknown")
    score = verification.get("score", 100)
    disposable = verification.get("disposable", False)

    if result == "undeliverable":
        return True
    if disposable:
        return True
    if score < 50:
        return True
    return False
