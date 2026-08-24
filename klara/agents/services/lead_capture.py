"""
app/services/lead_capture.py
─────────────────────────────
Task 5.1 — Lead capture ingestion.

Responsibilities:
  - Spam validation (marks as spam rather than hard-rejecting)
  - Source attribution (source field, referrer, UTM params)
  - Lead deduplication (same email → skip, return existing lead_id)
  - structlog events: lead.created, lead.duplicate_skipped, lead.spam_detected
  - PII-safe logging (no email address or full name in log events)

Called from app/api/leads.py before handing off to the agent pipeline.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

import structlog
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.lead import Lead, LeadSource, LeadStatus

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Spam detection
# ---------------------------------------------------------------------------

# Keyword patterns — case-insensitive, word-boundary anchored where possible
SPAM_KEYWORDS: list[str] = [
    r"\bviagra\b",
    r"\bcialis\b",
    r"\bcasino\b",
    r"\bpoker\b",
    r"\blottery\b",
    r"\blotto\b",
    r"\bcrypto\s+invest",
    r"\bbitcoin\s+profit",
    r"\bforex\s+trad",
    r"\bseo\s+servic",
    r"\bbacklink",
    r"\bguaranteed\s+ranking",
    r"\bpenis\b",
    r"\bporn\b",
    r"\bclick\s+here\s+to\s+win",
    r"\bfree\s+money\b",
    r"\bcheap\s+meds\b",
    r"\bweight\s+loss\s+pill",
]

_SPAM_PATTERNS = [re.compile(p, re.IGNORECASE) for p in SPAM_KEYWORDS]


def _spam_score(message: str, name: str, email: str) -> float:
    """
    Return a spam score 0.0–1.0.

    Scoring:
      - Each matching keyword: +0.3 (capped at 0.9 from keywords alone)
      - Fake-looking email (no dot in domain, single char local part): +0.4
      - Message too short (<10) or too long (>5000): contributes to hard-reject
        before this function is called, so not scored here.
    """
    score = 0.0

    for pattern in _SPAM_PATTERNS:
        if pattern.search(message):
            score += 0.3
        if score >= 0.9:
            break

    # Suspicious email heuristics
    try:
        local, domain = email.rsplit("@", 1)
        if len(local) <= 1:
            score += 0.4
        if "." not in domain:
            score += 0.4
    except ValueError:
        score += 0.5  # malformed email

    return min(score, 1.0)


def _is_valid_email_shape(email: str) -> bool:
    """Minimal structural check — pydantic EmailStr already validated; this
    catches edge cases like 'x@localhost' or 'a@b' that pass basic regex."""
    try:
        local, domain = email.rsplit("@", 1)
    except ValueError:
        return False
    if len(local) < 2:
        return False
    if "." not in domain:
        return False
    return True


# ---------------------------------------------------------------------------
# Public dataclass returned to callers
# ---------------------------------------------------------------------------

@dataclass
class CaptureResult:
    lead_id: str
    is_new: bool
    is_spam: bool
    is_duplicate: bool
    spam_score: float
    source: str
    utm: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def capture_lead(
    *,
    db: AsyncSession,
    name: str,
    email: str,
    message: str,
    phone: Optional[str] = None,
    company: Optional[str] = None,
    services_interest: Optional[list] = None,
    budget_range: Optional[str] = None,
    timeline: Optional[str] = None,
    gdpr_consent: bool = False,
    gdpr_consent_ip: Optional[str] = None,
    source: str = LeadSource.contact_form,
    request: Optional[Request] = None,
) -> CaptureResult:
    """
    Normalise a contact-form (or API/chat) submission into a Lead record.

    Returns a CaptureResult.  Does NOT raise on spam or duplicate — the caller
    decides how to respond to the user.
    """
    email = email.strip().lower()
    name = (name or "").strip()

    # ── UTM / referrer extraction ────────────────────────────────────────────
    utm: dict[str, str] = {}
    referrer_url: Optional[str] = None

    if request:
        referrer_url = request.headers.get("X-Referrer") or request.headers.get("Referer")
        params = dict(request.query_params)
        for utm_key in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"):
            if utm_key in params:
                utm[utm_key] = params[utm_key]

    # ── Hard-reject guards (return spam record) ──────────────────────────────
    spam_score = 0.0
    is_spam = False

    if not name or not email:
        is_spam = True
        spam_score = 1.0
    elif not _is_valid_email_shape(email):
        is_spam = True
        spam_score = 0.8
    elif len(message) < 10 or len(message) > 5000:
        is_spam = True
        spam_score = 0.7
    else:
        spam_score = _spam_score(message, name, email)
        if spam_score >= 0.6:
            is_spam = True

    email_domain = email.split("@")[-1] if "@" in email else "unknown"

    # ── Deduplication check ──────────────────────────────────────────────────
    result = await db.execute(
        select(Lead).where(Lead.email == email).limit(1)
    )
    existing_lead = result.scalar_one_or_none()

    if existing_lead:
        logger.info(
            "lead.duplicate_skipped",
            lead_id=existing_lead.id,
            email_domain=email_domain,
            source=source,
        )
        return CaptureResult(
            lead_id=existing_lead.id,
            is_new=False,
            is_spam=False,
            is_duplicate=True,
            spam_score=spam_score,
            source=source,
            utm=utm,
        )

    # ── Create lead ──────────────────────────────────────────────────────────
    from datetime import datetime, timezone

    services_json = json.dumps(services_interest or [])
    status = LeadStatus.new if not is_spam else "spam"

    lead = Lead(
        name=name,
        email=email,
        phone=phone,
        company=company,
        message=message,
        services_interest=services_json,
        budget_range=budget_range,
        timeline=timeline,
        source=source,
        status=status,
        score=None,
        gdpr_consent=gdpr_consent,
        gdpr_consent_timestamp=datetime.now(timezone.utc) if gdpr_consent else None,
        gdpr_consent_ip=gdpr_consent_ip,
        notes=json.dumps({
            "referrer_url": referrer_url,
            "utm": utm,
            "spam_score": spam_score,
        }) if (referrer_url or utm or is_spam) else None,
    )
    db.add(lead)
    await db.flush()  # populate lead.id without committing

    if is_spam:
        logger.warning(
            "lead.spam_detected",
            lead_id=lead.id,
            email_domain=email_domain,
            spam_score=spam_score,
            source=source,
        )
    else:
        logger.info(
            "lead.created",
            lead_id=lead.id,
            source=source,
            email_domain=email_domain,
            spam_score=spam_score,
        )

    return CaptureResult(
        lead_id=lead.id,
        is_new=True,
        is_spam=is_spam,
        is_duplicate=False,
        spam_score=spam_score,
        source=source,
        utm=utm,
    )
