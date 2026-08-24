"""
Klaravex outbound prospecting pipeline — FastAPI router.

Routes:
  POST /internal/prospects/run        trigger a prospecting run (called by cron/scheduler)
  GET  /internal/prospects/list       list pending approvals
  POST /internal/prospects/approve/{approval_id}  approve and send an outreach email
  GET  /internal/prospects/approve/{approval_id}  one-click approve via email link (token in query)

Flow:
  1. /run → call Apollo People Search with US ICP filters
  2. Deduplicate against klaravex_prospected_leads by domain
  3. For each new prospect, draft a cold email via Claude (Anthropic)
  4. Store draft in klaravex_outreach_approvals with a one-time token
  5. Email Anthony the draft + approve link
  6. Operator clicks the link → email sent via M365 Graph (lib.email.send_email)

Required env vars:
  APOLLO_API_KEY          Apollo.io API key
  ANTHROPIC_API_KEY       Anthropic API key
  MS_GRAPH_*              tenant/client/secret/sender for Graph sendMail
  LOKI_INTERNAL_SECRET    shared secret to protect /run and /list
  APPROVAL_NOTIFY_EMAIL   where to send approval alerts (default: astewart@klaravex.com)
  OUTREACH_FROM_EMAIL     Display sender (default: hello@outreach.klaravex.com)
  OUTREACH_FROM_NAME      Sender display name (default: Klaravex)
  APP_BASE_URL            base URL for approve links (default: https://api.klaravex.com)
"""

import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

import anthropic
import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .lib.db import get_pool
from .lib.email import send_email

log = logging.getLogger("klaravex.prospecting")
router = APIRouter()

APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY", "")
HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
APPROVAL_EMAIL = os.environ.get("APPROVAL_NOTIFY_EMAIL", "astewart@klaravex.com")
OUTREACH_FROM = os.environ.get("OUTREACH_FROM_EMAIL", "hello@outreach.klaravex.com")
OUTREACH_NAME = os.environ.get("OUTREACH_FROM_NAME", "Anthony from Klaravex")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://api.klaravex.com")
PROSPECTING_DAILY_LIMIT = int(os.environ.get("PROSPECTING_DAILY_LIMIT", "75"))
HUNTER_EMAILS_PER_DOMAIN = int(os.environ.get("HUNTER_EMAILS_PER_DOMAIN", "3"))
INTERNAL_SECRET = os.environ.get("LOKI_INTERNAL_SECRET", "")

APOLLO_SEARCH_URL = "https://api.apollo.io/v1/mixed_people/api_search"
APOLLO_COMPANY_SEARCH_URL = "https://api.apollo.io/v1/organizations/search"
HUNTER_API = "https://api.hunter.io/v2"

# ── ICP definition (US market) ────────────────────────────────────────────────

ICP_TITLES = [
    "CEO", "CTO", "CIO", "COO", "IT Director", "IT Manager",
    "VP of IT", "Head of IT", "VP Engineering", "Managing Director",
    "Director of Operations", "VP Operations",
]

ICP_INDUSTRIES = [
    "Hospital & Health Care", "Medical Practice", "Medical Devices",
    "Law Practice", "Legal Services",
    "Accounting", "Financial Services", "Investment Management",
    "Information Technology and Services", "Computer Software",
    "Managed Security Services", "Computer & Network Security",
    "Real Estate", "Insurance",
]

# ── Internal auth helper ──────────────────────────────────────────────────────

def _check_internal(request: Request) -> None:
    if not INTERNAL_SECRET:
        return
    presented = request.headers.get("x-loki-internal-secret", "")
    if not secrets.compare_digest(INTERNAL_SECRET, presented):
        raise HTTPException(status_code=403, detail="forbidden")


# ── Apollo helpers ────────────────────────────────────────────────────────────

async def _query_apollo(page: int = 1, per_page: int = 10) -> list[dict[str, Any]]:
    """Query Apollo People Search for US ICP prospects. Returns raw people records."""
    if not APOLLO_API_KEY:
        log.warning("APOLLO_API_KEY not set — prospecting skipped")
        return []
    payload = {
        "page": page,
        "per_page": per_page,
        "person_titles": ICP_TITLES,
        "organization_num_employees_ranges": ["10,500"],
        "person_locations": ["United States"],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            APOLLO_SEARCH_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "X-Api-Key": APOLLO_API_KEY,
            },
        )
        r.raise_for_status()
    data = r.json()
    return data.get("people", data.get("contacts", []))


async def _query_apollo_companies(page: int = 1, per_page: int = 50) -> list[dict[str, Any]]:
    """Apollo Company Search — get ICP-matching ORGS (not people).

    Apollo's free/starter tier returns names + companies but withholds emails
    AND withholds full names on people-search. Company-search returns the org
    metadata reliably. Combined with Hunter Domain Search per org for email
    discovery, this is the working architecture for the prospect pipeline.
    """
    if not APOLLO_API_KEY:
        log.warning("APOLLO_API_KEY not set — company search skipped")
        return []
    # Rotate through ICP verticals — use random selection to avoid
    # returning the same companies on consecutive runs
    import random
    _VERTICAL_KEYWORDS = [
        "medical practice",
        "law firm",
        "accounting firm",
        "dental practice",
        "financial advisor",
        "insurance agency",
        "veterinary clinic",
        "physical therapy",
        "optometry practice",
        "chiropractic clinic",
        "CPA firm",
        "legal services",
        "healthcare clinic",
        "dermatology practice",
        "orthopedic practice",
    ]
    keyword = random.choice(_VERTICAL_KEYWORDS)
    payload = {
        "page": page,
        "per_page": per_page,
        "organization_num_employees_ranges": ["10,200"],
        "organization_locations": ["United States"],
        "q_organization_keyword_tags": [keyword],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            APOLLO_COMPANY_SEARCH_URL,
            json=payload,
            headers={"Content-Type": "application/json", "Cache-Control": "no-cache", "X-Api-Key": APOLLO_API_KEY},
        )
        r.raise_for_status()
    data = r.json()
    return data.get("organizations") or data.get("accounts") or []


def _extract_company_domain(company: dict[str, Any]) -> Optional[str]:
    """Pull a clean domain off an Apollo organization record."""
    raw = company.get("primary_domain") or company.get("website_url") or ""
    if not raw:
        return None
    raw = re.sub(r"^https?://", "", raw).rstrip("/").lower()
    raw = re.sub(r"^www\.", "", raw)
    # Trim any trailing path
    raw = raw.split("/")[0]
    return raw or None


def _build_company_signal(company: dict[str, Any]) -> str:
    """One-line signal/context string for the cold-email drafter."""
    parts: list[str] = []
    industry = company.get("industry") or ""
    if industry:
        parts.append(f"{industry} company")
    count = company.get("estimated_num_employees") or company.get("employee_count") or 0
    if count:
        parts.append(f"~{count} employees")
    city = (company.get("city") or "").strip()
    state = (company.get("state") or "").strip()
    if city and state:
        parts.append(f"based in {city}, {state}")
    elif state:
        parts.append(f"based in {state}")
    tech = company.get("technology_names") or []
    if tech:
        parts.append(f"uses: {', '.join(tech[:3])}")
    return "; ".join(parts) if parts else "US SMB ICP match"


_ICP_POSITION_KEYWORDS = [
    "ceo","cto","cio","coo","cfo","vp","vice president","president","founder","owner",
    "director","head","principal","partner","manager","administrator","operations","it","information technology",
    "security","compliance","practice manager","office manager","medical director","managing","engineering",
]


def _email_matches_icp(hunter_person: dict[str, Any]) -> bool:
    """Keep emails whose position/department aligns with our ICP titles.
    Hunter returns emails with `position` strings; we filter so we're not
    drafting cold pitches to receptionists.
    """
    pos = (hunter_person.get("position") or "").lower()
    dept = (hunter_person.get("department") or "").lower()
    if not pos and not dept:
        return True  # Hunter often has no position metadata; let the verifier + insert pipeline gate downstream
    blob = pos + " " + dept
    return any(kw in blob for kw in _ICP_POSITION_KEYWORDS)


def _format_company_location(company: dict[str, Any]) -> Optional[str]:
    city = (company.get("city") or "").strip()
    state = (company.get("state") or "").strip()
    if city and state:
        return f"{city}, {state}"
    return state or city or None


def _extract_domain(person: dict[str, Any]) -> Optional[str]:
    org = person.get("organization") or {}
    website = org.get("website_url") or org.get("primary_domain") or ""
    if not website:
        email = person.get("email") or ""
        if "@" in email:
            website = email.split("@")[-1]
    if not website:
        return None
    website = re.sub(r"^https?://", "", website).rstrip("/").lower()
    website = re.sub(r"^www\.", "", website)
    return website or None


# ── Hunter.io helpers ─────────────────────────────────────────────────────────
#
# Apollo finds people by ICP filters but frequently returns prospects without an
# email visible to us. Hunter.io fills that gap two ways:
#
#   1. Email Finder: given (domain, first_name, last_name), Hunter returns the
#      most likely email + confidence score. Used when Apollo gave us a person
#      but no email — without this, prospecting.py drops ~100% of Apollo's output.
#
#   2. Domain Search: given a domain, Hunter returns all emails it knows at that
#      org. Used as a SECOND source — we target specific company domains (e.g.,
#      from a target-account list) and walk every contact at that domain.
#
#   3. Email Verifier: validates deliverability before we add to the queue.
#      Anything not 'deliverable' or 'risky' is dropped so Smartlead reputation
#      is preserved.
#
# Hunter docs: https://hunter.io/api-documentation/v2


async def _hunter_find_email(
    domain: str, first_name: str, last_name: str
) -> tuple[Optional[str], Optional[int]]:
    """Email Finder: returns (email, confidence) or (None, None) on miss."""
    if not (HUNTER_API_KEY and domain and first_name and last_name):
        return None, None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{HUNTER_API}/email-finder",
                params={
                    "domain": domain,
                    "first_name": first_name,
                    "last_name": last_name,
                    "api_key": HUNTER_API_KEY,
                },
            )
        if r.status_code != 200:
            log.info("hunter email-finder %s: HTTP %s", domain, r.status_code)
            return None, None
        data = (r.json() or {}).get("data") or {}
        email = data.get("email")
        score = data.get("score")
        return email, (int(score) if isinstance(score, int) else None)
    except Exception as exc:
        log.warning("hunter email-finder exception for %s: %s", domain, exc)
        return None, None


async def _hunter_domain_search(domain: str, limit: int = 5) -> list[dict[str, Any]]:
    """Domain Search: returns people Hunter knows at this domain.

    Returns a list of {first_name, last_name, email, position, linkedin, confidence}.
    Used as a SECOND prospect source alongside Apollo's people search.
    """
    if not (HUNTER_API_KEY and domain):
        return []
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"{HUNTER_API}/domain-search",
                params={"domain": domain, "limit": limit, "api_key": HUNTER_API_KEY},
            )
        if r.status_code != 200:
            log.info("hunter domain-search %s: HTTP %s", domain, r.status_code)
            return []
        data = (r.json() or {}).get("data") or {}
        people = []
        for e in (data.get("emails") or [])[:limit]:
            if not e.get("value"):
                continue
            people.append({
                "first_name": e.get("first_name") or "",
                "last_name": e.get("last_name") or "",
                "email": e.get("value"),
                "position": e.get("position") or "",
                "linkedin": e.get("linkedin") or "",
                "confidence": e.get("confidence"),
                "department": e.get("department") or "",
            })
        return people
    except Exception as exc:
        log.warning("hunter domain-search exception for %s: %s", domain, exc)
        return []


async def _hunter_verify(email: str) -> str:
    """Email Verifier: returns deliverability verdict.

    Verdicts: deliverable | risky | undeliverable | unknown | accept_all
    We accept 'deliverable' + 'risky' + 'accept_all'; everything else is dropped
    so Smartlead/Klaravex sending reputation stays clean.

    Returns 'skip' shortcut when Hunter unavailable (don't gate on infra outage).
    """
    if not HUNTER_API_KEY or not email or "@" not in email:
        return "skip"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{HUNTER_API}/email-verifier",
                params={"email": email, "api_key": HUNTER_API_KEY},
            )
        if r.status_code != 200:
            return "skip"
        data = (r.json() or {}).get("data") or {}
        return (data.get("result") or "unknown").lower()
    except Exception as exc:
        log.warning("hunter verify exception for %s: %s", email, exc)
        return "skip"


def _build_prospect_signal(person: dict[str, Any]) -> str:
    org = person.get("organization") or {}
    parts = []
    industry = org.get("industry") or ""
    if industry:
        parts.append(f"{industry} company")
    count = org.get("employee_count") or org.get("num_employees") or 0
    if count:
        parts.append(f"~{count} employees")
    city = (person.get("city") or org.get("city") or "").strip()
    state = (person.get("state") or org.get("state") or "").strip()
    if city and state:
        parts.append(f"based in {city}, {state}")
    elif state:
        parts.append(f"based in {state}")
    tech = org.get("technology_names") or []
    if tech:
        parts.append(f"uses: {', '.join(tech[:3])}")
    return "; ".join(parts) if parts else "US SMB ICP match"


# ── Claude email draft ────────────────────────────────────────────────────────

DRAFT_PROMPT = """\
You are writing a cold outreach email for Klaravex — a US managed security and IT
advisory firm serving SMBs. The email is sent on behalf of the Klaravex team and
speaks as the corporation, never as an individual.

Voice policy (binding — non-negotiable):
- Speaker is "Klaravex" / "we" / "our team" — NEVER a person.
- No personal names anywhere. No "Anthony", no "our founder", no signed names.
- No first-person singular ("I", "me", "my"). Use "we" / "our" / "Klaravex".
- No founder narrative ("as the founder of…", "I built…", etc.).
- No personal email addresses in the signature; use "support@klaravex.com".

Write a cold outreach email in American English to a potential client.

Content rules:
- Tone: senior, calm, specific. Curious about their setup — not pitching.
- Body length: strictly 120 words or fewer.
- Open with the prospect's first name if known, otherwise "Hi there,".
- Mention their company name naturally in the first sentence.
- Weave in the prospecting signal (why we're reaching out) in one sentence.
- One clear CTA: a 30-minute discovery call.
- Signature (verbatim):
  "Best,\\nThe Klaravex team\\nhttps://klaravex.com | support@klaravex.com"
- Do NOT include: pricing, guarantees, excessive superlatives, competitor names.
- Do NOT make compliance claims or call Klaravex a compliance provider; use
  "readiness" / "preparation" / "advisory" instead.

Return ONLY a valid JSON object with exactly these fields (no markdown, no preamble):
{{
  "subject": "<concise subject, max 10 words; no personal names>",
  "body_text": "<plain-text body, newlines as \\n>",
  "body_html": "<HTML body, simple tags only, no html/head/body tags>"
}}

Prospect:
{prospect_context}
"""


LITELLM_URL = os.environ.get("LITELLM_URL", "")
LITELLM_KEY = os.environ.get("LITELLM_MASTER_KEY", "")
LITELLM_DRAFT_MODEL = os.environ.get("LITELLM_DRAFT_MODEL", "qwen-coder")

async def _draft_email(prospect: dict[str, Any]) -> Optional[dict[str, str]]:
    """Draft a cold-outreach email via the local LiteLLM proxy (private, fast,
    no per-token cost). No OpenRouter fallback (Anthony canceled OpenRouter,
    2026-08-16)."""
    context_parts = [
        f"Company: {prospect.get('company_name', 'Unknown')}",
        f"Contact: {prospect.get('contact_first_name', '')} {prospect.get('contact_last_name', '')}".strip() or "Unknown",
        f"Title: {prospect.get('contact_title', 'Unknown')}",
        f"Industry: {prospect.get('industry', 'Unknown')}",
        f"Employees: {prospect.get('employee_count', 'Unknown')}",
        f"Location: {prospect.get('location', 'US')}",
        f"Signal: {prospect.get('signal', '')}",
    ]
    prompt = DRAFT_PROMPT.format(prospect_context="\n".join(context_parts))

    raw: str | None = None
    provider_used = "none"

    # Try local LiteLLM first (private, fast, no per-token cost)
    if LITELLM_URL and LITELLM_KEY:
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                r = await client.post(
                    f"{LITELLM_URL}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {LITELLM_KEY}"},
                    json={
                        "model": LITELLM_DRAFT_MODEL,
                        "max_tokens": 1024,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
            if r.status_code == 200:
                data = r.json()
                choices = data.get("choices") or []
                if choices:
                    raw = (choices[0].get("message") or {}).get("content", "").strip()
                    provider_used = "litellm"
                    log.info("draft via litellm model=%s len=%d", LITELLM_DRAFT_MODEL, len(raw))
        except Exception as exc:
            log.warning("litellm draft failed, will try fallback: %s", exc)

    # 2026-08-16: OpenRouter fallback removed (Anthony canceled OpenRouter).
    if raw is None:
        log.warning("draft: no LLM provider available")
        return None

    log.info("DRAFT_DEBUG provider=%s first 400 chars: %r", provider_used, raw[:400])

    # Strip markdown code fences if present (single-line OR multi-line forms)
    raw = re.sub(r"^\s*```(?:json)?\s*\n?", "", raw)
    raw = re.sub(r"\n?\s*```\s*$", "", raw)
    raw = raw.strip()

    # Find the first valid JSON object in the response — Claude sometimes
    # prefixes "Here is the draft:" or wraps in commentary.
    parsed = None
    for candidate in [raw, _extract_json_object(raw)]:
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            parsed = obj
            break
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            parsed = obj[0]
            break

    if parsed is None:
        log.warning("draft: could not parse JSON — first 300 chars: %r", raw[:300])
        return None

    # Validate required keys exist. If the LLM returned them under a wrapper
    # ("draft", "result", etc.), unwrap one level.
    if "subject" not in parsed and "body_text" not in parsed:
        for key in ("draft", "result", "email", "output"):
            if isinstance(parsed.get(key), dict):
                parsed = parsed[key]
                break

    if not all(k in parsed for k in ("subject", "body_text", "body_html")):
        log.warning("draft: missing required keys. got keys: %s — first 300 chars: %r",
                    list(parsed.keys())[:10], raw[:300])
        return None

    # Voice-policy guard: reject any draft that contains banned personal-name
    # or first-person-founder language. Anything in this list would broadcast
    # a CLAUDE.md voice-policy violation to a real prospect.
    blob = " ".join(str(parsed.get(k, "")) for k in ("subject", "body_text", "body_html")).lower()
    banned = (
        "anthony",                       # founder name
        "anthony@klaravex.com",          # personal mailbox
        "our founder", "the founder",    # personified founder
        "as the founder", "i'm the founder", "i am the founder",
        "loki",                          # internal AI brand name
    )
    hits = [tok for tok in banned if tok in blob]
    if hits:
        log.warning("draft voice-policy reject: hits=%s — first 200 chars: %r", hits, blob[:200])
        return None

    return parsed


def _extract_json_object(text: str) -> Optional[str]:
    """Return the first balanced { ... } substring in `text`, or None."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i+1]
    return None


# ── Outreach send ─────────────────────────────────────────────────────────────
# 2026-06-25: migrated from Resend (deleted account) to M365 Graph via lib.email.
# NOTE on policy: Anthony's prospect-vs-client rule says prospects → Smartlead.
# This approval-link flow is the human-in-the-loop "first-touch" send for an
# already-drafted, already-approved cold email; routing through Smartlead would
# require a per-prospect single-step campaign or transactional send. Until that
# wiring lands, the approval click sends via Graph. Bulk multi-touch outreach
# still routes through Smartlead via lib/marketing_tools.smartlead_add_to_campaign.

SMARTLEAD_API_KEY = os.environ.get("SMARTLEAD_API_KEY", "")
SMARTLEAD_MASTER_CAMPAIGN_ID = int(os.environ.get("SMARTLEAD_MASTER_CAMPAIGN_ID", "0") or 0)
SMARTLEAD_BASE = "https://server.smartlead.ai/api/v1"


def _h_escape(s: str) -> str:
    """Minimal HTML escaper — avoids importing the stdlib `html` module just
    to render error/detail strings in approval response pages."""
    if not s: return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


async def _send_via_smartlead(
    *,
    contact_email: str,
    first_name: str,
    last_name: str,
    company_name: str,
    contact_title: str,
    subject: str,
    body_text: str,
    body_html: str,
) -> tuple[bool, str]:
    """Add an approved prospect to the Smartlead master campaign.

    Smartlead handles when to actually send (per-recipient timezone, warmup
    schedule, day-of-week optimization, inbox rotation, bounce/reply detection).
    Anthony's policy: cold outreach NEVER touches M365 / direct SMTP — only
    Smartlead, because it has the per-prospect timing intelligence we don't.

    Returns (success, message-or-error).
    """
    if not SMARTLEAD_API_KEY:
        return False, "SMARTLEAD_API_KEY not set"
    if not SMARTLEAD_MASTER_CAMPAIGN_ID:
        return False, "SMARTLEAD_MASTER_CAMPAIGN_ID not set"
    if not contact_email or "@" not in contact_email:
        return False, "invalid contact_email"

    # Pre-flight: the campaign's step-1 template references
    # {{custom_fields.subject}} and {{custom_fields.body_html}}. If either is
    # empty, Smartlead would send a blank email — or worse, leak the literal
    # placeholder text. Refuse the handoff instead.
    if not (subject or "").strip():
        return False, "pre-flight: empty subject"
    if not (body_html or "").strip():
        return False, "pre-flight: empty body_html"
    # Reject any residual template syntax in the drafted content — if the
    # draft contains {{ or }}, Smartlead's template engine would either
    # recurse into garbage or send the literal braces to the recipient.
    for fld_name, fld_val in (("subject", subject), ("body_text", body_text), ("body_html", body_html)):
        if "{{" in (fld_val or "") or "}}" in (fld_val or ""):
            return False, f"pre-flight: {fld_name} contains template syntax"
    # Voice-policy backstop (same banned tokens as the draft guard). If a
    # draft slipped through (e.g. manual edit), refuse the send.
    blob = f"{subject} {body_text} {body_html}".lower()
    voice_hits = [t for t in ("anthony", "anthony@klaravex.com", "our founder", "as the founder", "loki") if t in blob]
    if voice_hits:
        return False, f"pre-flight: voice-policy hits {voice_hits}"

    lead = {
        "email": contact_email.strip().lower(),
        "first_name": (first_name or "")[:80],
        "last_name": (last_name or "")[:80],
        "company_name": (company_name or "")[:120],
        "custom_fields": {
            "subject": (subject or "")[:200],
            "body_text": (body_text or "")[:8000],
            "body_html": (body_html or "")[:16000],
            "personalized_body": (body_html or "")[:16000],
            "contact_title": (contact_title or "")[:120],
        },
    }
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(
                f"{SMARTLEAD_BASE}/campaigns/{SMARTLEAD_MASTER_CAMPAIGN_ID}/leads",
                params={"api_key": SMARTLEAD_API_KEY},
                json={"lead_list": [lead]},
            )
    except Exception as exc:
        log.exception("smartlead add-to-campaign exception: %s", exc)
        return False, f"smartlead exception: {exc}"

    if r.status_code not in (200, 201):
        log.warning("smartlead add-to-campaign HTTP %s: %s", r.status_code, r.text[:300])
        return False, f"smartlead HTTP {r.status_code}: {r.text[:200]}"

    body = r.json() if r.text else {}
    upload_count = body.get("upload_count") or body.get("inserted") or 0
    duplicate_count = body.get("already_added_to_campaign") or body.get("duplicate") or 0
    if upload_count == 0 and duplicate_count > 0:
        return True, f"already in campaign (Smartlead dedupe — id existed)"
    if upload_count == 0:
        return False, f"smartlead accepted but did not insert: {str(body)[:200]}"
    return True, f"added to Smartlead campaign {SMARTLEAD_MASTER_CAMPAIGN_ID}"


async def _send_via_resend(to: str, subject: str, body_text: str, body_html: str) -> bool:
    """DEPRECATED — kept only as a soft-fail no-op for any stale callers.

    Cold outreach MUST go through Smartlead via _send_via_smartlead(). Direct
    M365 / SMTP / Resend to prospects is banned per Anthony's policy
    (sending-reputation, timing optimization, warmup all handled by Smartlead).
    """
    log.warning(
        "_send_via_resend called for to=%s — this path is deprecated. "
        "Cold outreach should call _send_via_smartlead() instead.",
        to,
    )
    return False


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _count_today() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM klaravex_prospected_leads WHERE created_at >= current_date"
        ) or 0


async def _domain_exists(domain: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return bool(await conn.fetchval(
            "SELECT 1 FROM klaravex_prospected_leads WHERE domain = $1", domain
        ))


async def _insert_prospect(p: dict[str, Any]) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO klaravex_prospected_leads
                (domain, company_name, industry, employee_count, location,
                 contact_first_name, contact_last_name, contact_email, contact_title,
                 contact_linkedin, signal, apollo_person_id, apollo_organization_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            ON CONFLICT (domain) DO NOTHING
            RETURNING id::text
            """,
            p["domain"], p.get("company_name"), p.get("industry"), p.get("employee_count"),
            p.get("location"), p.get("contact_first_name"), p.get("contact_last_name"),
            p.get("contact_email"), p.get("contact_title"), p.get("contact_linkedin"),
            p.get("signal"), p.get("apollo_person_id"), p.get("apollo_organization_id"),
        )


async def _insert_approval(prospect_id: str, subject: str, body_text: str, body_html: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    pool = await get_pool()
    async with pool.acquire() as conn:
        approval_id = await conn.fetchval(
            """
            INSERT INTO klaravex_outreach_approvals
                (prospect_id, subject, body_text, body_html, approval_token)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id::text
            """,
            prospect_id, subject, body_text, body_html, token,
        )
    return approval_id, token


# ── Approval notification email to Anthony ────────────────────────────────────

async def _notify_approval(approval_id: str, token: str, prospect: dict[str, Any], draft: dict[str, str]) -> None:
    approve_url = f"{APP_BASE_URL}/api/v1/internal/prospects/approve/{approval_id}?token={token}"
    body = (
        f"New outreach draft ready for approval.\n\n"
        f"Prospect: {prospect.get('contact_first_name', '')} {prospect.get('contact_last_name', '')} "
        f"@ {prospect.get('company_name', prospect.get('domain', ''))}\n"
        f"Email: {prospect.get('contact_email', '—')}\n"
        f"Title: {prospect.get('contact_title', '—')}\n\n"
        f"---DRAFT---\n"
        f"Subject: {draft['subject']}\n\n"
        f"{draft['body_text']}\n"
        f"---END DRAFT---\n\n"
        f"Click to approve and send:\n{approve_url}\n\n"
        f"To reject, simply ignore this email. The draft will expire after 7 days."
    )
    await send_email(
        to=APPROVAL_EMAIL,
        subject=f"[Klaravex Outreach] Approve: {draft['subject']}",
        body=body,
    )


# ── AI Gating Agent ──────────────────────────────────────────────────────────
# Replaces Anthony's manual approval. Checks every outreach email against
# voice policy, quality standards, and spam indicators before auto-sending.

_GATE_PROMPT = """You are a cold-email quality gate for Klaravex, a managed IT and security company.

Review this outbound email draft and decide: PASS or FAIL.

FAIL if ANY of these are true:
- Uses first-person singular ("I", "me", "my") — must use "we" or "Klaravex"
- Mentions personal names (Anthony, any founder name)
- Uses the word "Klara AI" (internal codename)
- Uses "compliance" instead of "readiness"
- Contains fake urgency ("act now", "limited time", "don't miss out")
- Contains unsubstantiated claims ("guaranteed", "100%", "#1")
- Is generic/template-feeling (no personalization to the recipient's company/industry)
- Has spam trigger words ("free money", "act fast", "click here now")
- Mentions competitors by name negatively
- Is longer than 150 words (cold emails must be concise)
- Missing a clear CTA (should have one specific ask — usually a call booking)

PASS if the email:
- Is personalized to the recipient's company/industry
- Uses corporate voice ("we" / "Klaravex")
- Has a clear, single CTA
- Is concise (<150 words)
- Sounds like a real person wrote it, not a template

Respond with EXACTLY one line: PASS or FAIL: <reason>
"""

async def _ai_gate_check(draft: dict, prospect: dict) -> tuple[bool, str]:
    """AI quality gate — checks outreach email before auto-sending.
    Returns (passed, reason).

    Tries local LiteLLM first (rig), falls back to OpenRouter (Azure).
    """
    import httpx

    text = f"TO: {prospect.get('contact_first_name','')} {prospect.get('contact_last_name','')} at {prospect.get('company_name','')}\nSUBJECT: {draft['subject']}\nBODY:\n{draft['body_text']}"

    messages = [
        {"role": "system", "content": _GATE_PROMPT},
        {"role": "user", "content": text},
    ]

    # Try local LiteLLM first (fast, free, private — works on rig)
    litellm_url = os.environ.get("LITELLM_URL", "")
    litellm_key = os.environ.get("LITELLM_MASTER_KEY", "")

    reply_text: str | None = None
    provider_used = "none"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if litellm_url and litellm_key:
                # Try local LiteLLM
                try:
                    r = await client.post(
                        f"{litellm_url}/v1/chat/completions",
                        headers={"Authorization": f"Bearer {litellm_key}"},
                        json={"model": "deepseek", "messages": messages, "max_tokens": 50, "temperature": 0.0},
                    )
                    if r.status_code == 200:
                        reply_text = r.json()["choices"][0]["message"]["content"].strip()
                        provider_used = "litellm"
                except Exception:
                    pass  # local LLM failed — no fallback (OpenRouter removed 2026-08-16)

        if reply_text is None:
            log.warning("AI gate: no LLM provider available — defaulting to PASS")
            return True, "no_provider_default_pass"

        if reply_text.upper().startswith("PASS"):
            return True, f"{reply_text} [{provider_used}]"
        elif reply_text.upper().startswith("FAIL"):
            return False, f"{reply_text} [{provider_used}]"
        else:
            log.warning("AI gate unclear response: %r — defaulting to PASS", reply_text)
            return True, f"unclear_response: {reply_text}"

    except Exception as exc:
        log.warning("AI gate exception: %s — defaulting to PASS", exc)
        return True, f"exception_default_pass: {exc}"


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/run", include_in_schema=False)
async def run_prospecting(request: Request) -> JSONResponse:
    """Trigger a prospecting run.

    Architecture (refactored 2026-06-26):
      1. Apollo company-search returns US SMB ICP companies (org metadata).
      2. For each new company, Hunter domain-search returns email contacts
         (filtered by ICP position/department).
      3. Hunter verifier drops undeliverable/disposable.
      4. Insert each (domain, email) pair as a prospect row + queue an
         approval-link email to Anthony.

    Target: PROSPECTING_DAILY_LIMIT (default 75) prospects per day.
    Apollo's free/starter tier withholds emails AND last_names on people-
    search; the company-search + Hunter-emails pattern is the working flow.
    """
    _check_internal(request)

    today_count = await _count_today()
    remaining = PROSPECTING_DAILY_LIMIT - today_count
    if remaining <= 0:
        return JSONResponse({"status": "daily_limit_reached", "today": today_count, "limit": PROSPECTING_DAILY_LIMIT})

    if not APOLLO_API_KEY:
        return JSONResponse({"status": "no_apollo_key"}, status_code=503)
    if not HUNTER_API_KEY:
        return JSONResponse({"status": "no_hunter_key"}, status_code=503)

    # Over-fetch companies so dedupe + no-email filtering doesn't starve the run.
    target_companies = max(remaining // max(HUNTER_EMAILS_PER_DOMAIN, 1), 25)
    per_page = min(target_companies * 2, 100)

    # Paginate through Apollo results — skip pages we've already exhausted.
    # Use a random page offset to avoid always hitting the same results.
    import random
    start_page = random.randint(2, 10)  # skip page 1 (already prospected)

    companies = []
    for page in range(start_page, start_page + 3):  # try up to 3 pages
        try:
            page_results = await _query_apollo_companies(page=page, per_page=per_page)
            companies.extend(page_results)
            if len(companies) >= target_companies * 2:
                break
        except Exception as exc:
            log.exception("Apollo company-search page %d failed: %s", page, exc)
            if not companies:
                return JSONResponse({"status": "apollo_error", "error": str(exc)}, status_code=502)
            break  # use what we got

    queued = 0
    skipped_no_domain = 0
    skipped_dup_domain = 0
    skipped_no_emails = 0
    skipped_undeliverable = 0
    failed = 0
    hunter_emails_found = 0
    hunter_emails_verified = 0
    companies_processed = 0

    for company in companies:
        if queued >= remaining:
            break

        domain = _extract_company_domain(company)
        if not domain:
            skipped_no_domain += 1
            continue

        if await _domain_exists(domain):
            skipped_dup_domain += 1
            continue

        # Phase 2: Hunter domain-search — get up to N emails per company.
        emails = await _hunter_domain_search(domain, limit=HUNTER_EMAILS_PER_DOMAIN)
        emails = [e for e in emails if _email_matches_icp(e)]
        if not emails:
            skipped_no_emails += 1
            continue

        hunter_emails_found += len(emails)
        companies_processed += 1
        company_signal = _build_company_signal(company)
        company_location = _format_company_location(company)
        company_name = company.get("name") or domain
        org_id = company.get("id")

        # Phase 3: for each Hunter email, verify + insert + queue approval.
        for hunter_person in emails:
            if queued >= remaining:
                break

            email = hunter_person.get("email") or ""
            if not email or "@" not in email:
                continue

            verdict = await _hunter_verify(email)
            if verdict in ("undeliverable", "disposable"):
                skipped_undeliverable += 1
                continue
            if verdict in ("deliverable", "risky", "accept_all"):
                hunter_emails_verified += 1

            prospect = {
                "domain": domain,
                "company_name": company_name,
                "industry": company.get("industry"),
                "employee_count": company.get("estimated_num_employees") or company.get("employee_count"),
                "location": company_location,
                "contact_first_name": hunter_person.get("first_name") or "",
                "contact_last_name": hunter_person.get("last_name") or "",
                "contact_email": email,
                "contact_title": hunter_person.get("position") or "",
                "contact_linkedin": hunter_person.get("linkedin") or "",
                "signal": company_signal,
                "apollo_person_id": None,
                "apollo_organization_id": org_id,
            }

            prospect_id = await _insert_prospect(prospect)
            if not prospect_id:
                continue  # dedupe conflict on (domain, email) — silent skip

            try:
                draft = await _draft_email(prospect)
                if not draft:
                    failed += 1
                    continue

                # AI gating agent — checks quality before auto-sending
                gate_pass, gate_reason = await _ai_gate_check(draft, prospect)
                if not gate_pass:
                    log.warning(
                        "AI gate REJECTED domain=%s email=%s reason=%s",
                        domain, email, gate_reason,
                    )
                    failed += 1
                    continue

                # Gate passed — send directly to Smartlead (no Anthony approval needed)
                ok, detail = await _send_via_smartlead(
                    contact_email=email,
                    first_name=prospect.get("contact_first_name", ""),
                    last_name=prospect.get("contact_last_name", ""),
                    company_name=company_name,
                    contact_title=prospect.get("contact_title", ""),
                    subject=draft["subject"],
                    body_text=draft["body_text"],
                    body_html=draft["body_html"],
                )
                if ok:
                    # Mark as queued in DB
                    pool = await get_pool()
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE klaravex_prospected_leads SET status='queued_smartlead', updated_at=now() WHERE id=$1",
                            prospect_id,
                        )
                    queued += 1
                    log.info("prospect AUTO-SENT domain=%s email=%s detail=%s", domain, email, detail)
                else:
                    log.warning("smartlead send failed domain=%s email=%s: %s", domain, email, detail)
                    failed += 1
            except Exception as exc:
                log.exception("draft/send failed for %s/%s: %s", domain, email, exc)
                failed += 1

    return JSONResponse({
        "status": "ok",
        "new_prospects": queued,
        "skipped_no_domain": skipped_no_domain,
        "skipped_dup_domain": skipped_dup_domain,
        "skipped_no_emails": skipped_no_emails,
        "skipped_undeliverable": skipped_undeliverable,
        "failed": failed,
        "companies_processed": companies_processed,
        "hunter_emails_found": hunter_emails_found,
        "hunter_emails_verified": hunter_emails_verified,
        "today_total": today_count + queued,
        "daily_limit": PROSPECTING_DAILY_LIMIT,
    })


# ── One-shot drain: process orphan prospects (insert succeeded, no draft) ────


@router.post("/draft-orphans", include_in_schema=False)
async def draft_orphan_prospects(request: Request) -> JSONResponse:
    """Walk every klaravex_prospected_leads row that has NO matching
    klaravex_outreach_approvals row, generate the cold-email draft via
    OpenRouter, insert the approval row, send Anthony the approval-link email.

    Use to drain prospects that landed without drafts (e.g. when the drafter
    was broken at insert time).
    """
    _check_internal(request)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.id, p.domain, p.company_name, p.contact_first_name,
                   p.contact_last_name, p.contact_title, p.contact_email,
                   p.industry, p.location, p.signal
            FROM klaravex_prospected_leads p
            WHERE NOT EXISTS (
                SELECT 1 FROM klaravex_outreach_approvals a WHERE a.prospect_id = p.id
            )
            ORDER BY p.created_at DESC
            LIMIT 100
        """)

    drafted = 0
    no_draft = 0
    approval_failed = 0
    notify_failed = 0
    samples: list[str] = []

    for r in rows:
        prospect = {
            "id": r["id"],
            "domain": r["domain"],
            "company_name": r["company_name"],
            "contact_first_name": r["contact_first_name"] or "",
            "contact_last_name": r["contact_last_name"] or "",
            "contact_title": r["contact_title"] or "",
            "contact_email": r["contact_email"],
            "industry": r["industry"] or "",
            "location": r["location"] or "US",
            "signal": r["signal"] or "US SMB ICP match",
        }
        try:
            draft = await _draft_email(prospect)
        except Exception as exc:
            log.warning("draft-orphans: draft failed for %s: %s", prospect["domain"], exc)
            no_draft += 1
            continue
        if not draft:
            no_draft += 1
            continue
        try:
            approval_id, token = await _insert_approval(
                str(r["id"]), draft["subject"], draft["body_text"], draft["body_html"],
            )
        except Exception as exc:
            log.warning("draft-orphans: approval insert failed for %s: %s", prospect["domain"], exc)
            approval_failed += 1
            continue
        try:
            await _notify_approval(approval_id, token, prospect, draft)
        except Exception as exc:
            log.warning("draft-orphans: notify failed for %s: %s", prospect["domain"], exc)
            notify_failed += 1
        drafted += 1
        if len(samples) < 3:
            samples.append(f"{prospect['domain']} → {draft['subject'][:60]}")

    return JSONResponse({
        "status": "ok",
        "found": len(rows),
        "drafted": drafted,
        "no_draft": no_draft,
        "approval_failed": approval_failed,
        "notify_failed": notify_failed,
        "samples": samples,
    })


# ── Hunter Domain Search — second prospect source ────────────────────────────


@router.post("/run-domains", include_in_schema=False)
async def run_domain_prospecting(request: Request) -> JSONResponse:
    """Hunter-only path: walk a list of target-account domains and queue every
    person Hunter knows at each. Use when you have a curated target-account list
    (industry research, customer-of-customer leads, conference attendee lists).

    Body: {"domains": ["acme.com", "globex.com", ...], "per_domain_limit": 3}
    """
    _check_internal(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    domains = body.get("domains") or []
    per_domain = int(body.get("per_domain_limit", 3))

    if not HUNTER_API_KEY:
        return JSONResponse({"status": "no_hunter_key"}, status_code=503)
    if not domains:
        return JSONResponse({"status": "no_domains"}, status_code=400)

    today_count = await _count_today()
    remaining = PROSPECTING_DAILY_LIMIT - today_count
    if remaining <= 0:
        return JSONResponse({"status": "daily_limit_reached", "today": today_count})

    queued = 0
    skipped = 0
    failed = 0

    for domain in domains:
        if queued >= remaining:
            break
        if await _domain_exists(domain):
            skipped += 1
            continue

        people = await _hunter_domain_search(domain, limit=per_domain)
        if not people:
            skipped += 1
            continue

        # Pick the person with the highest confidence + a senior position
        people.sort(key=lambda p: (p.get("confidence") or 0), reverse=True)
        person = people[0]

        verdict = await _hunter_verify(person["email"])
        if verdict in ("undeliverable", "disposable"):
            skipped += 1
            continue

        prospect = {
            "domain": domain,
            "company_name": domain,
            "industry": None,
            "employee_count": None,
            "location": None,
            "contact_first_name": person.get("first_name"),
            "contact_last_name": person.get("last_name"),
            "contact_email": person["email"],
            "contact_title": person.get("position"),
            "contact_linkedin": person.get("linkedin"),
            "signal": f"Hunter domain-search match (confidence {person.get('confidence', '?')})",
            "apollo_person_id": None,
            "apollo_organization_id": None,
        }

        prospect_id = await _insert_prospect(prospect)
        if not prospect_id:
            skipped += 1
            continue

        try:
            draft = await _draft_email(prospect)
            if not draft:
                failed += 1
                continue
            approval_id, token = await _insert_approval(
                prospect_id, draft["subject"], draft["body_text"], draft["body_html"]
            )
            await _notify_approval(approval_id, token, prospect, draft)
            queued += 1
        except Exception as exc:
            log.exception("draft/notify failed for %s: %s", domain, exc)
            failed += 1

    return JSONResponse({
        "status": "ok",
        "source": "hunter_domain_search",
        "new_prospects": queued,
        "skipped": skipped,
        "failed": failed,
        "today_total": today_count + queued,
    })


@router.get("/list", include_in_schema=False)
async def list_approvals(request: Request) -> JSONResponse:
    """List pending outreach approvals."""
    _check_internal(request)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT a.id, a.subject, a.status, a.created_at,
                   p.company_name, p.contact_first_name, p.contact_last_name,
                   p.contact_email, p.contact_title, p.domain
              FROM klaravex_outreach_approvals a
              JOIN klaravex_prospected_leads p ON p.id = a.prospect_id
             WHERE a.status = 'pending'
             ORDER BY a.created_at DESC
             LIMIT 50
            """
        )
    return JSONResponse({"pending": [dict(r) for r in rows]})


@router.get("/approve/{approval_id}", response_class=HTMLResponse, include_in_schema=False)
async def approve_get(approval_id: str, token: str = Query(...)) -> HTMLResponse:
    """One-click approve link from Anthony's email."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT a.id, a.subject, a.body_text, a.body_html, a.status,
                   a.approval_token, p.contact_email, p.company_name,
                   p.contact_first_name, p.contact_last_name
              FROM klaravex_outreach_approvals a
              JOIN klaravex_prospected_leads p ON p.id = a.prospect_id
             WHERE a.id = $1
            """,
            approval_id,
        )
    if not row:
        return HTMLResponse("<h1>Not found</h1>", status_code=404)
    if not secrets.compare_digest(row["approval_token"], token):
        return HTMLResponse("<h1>Invalid token</h1>", status_code=403)
    if row["status"] != "pending":
        return HTMLResponse(
            f"<h1>Already {row['status']}</h1><p>This email was already {row['status']}.</p>"
        )

    # Hand the prospect off to Smartlead — Smartlead decides WHEN to actually
    # send based on its per-recipient timing model + warmup schedule. We never
    # send cold outreach directly (no M365 / SMTP / Resend).
    ok, detail = await _send_via_smartlead(
        contact_email=row["contact_email"],
        first_name=row["contact_first_name"] or "",
        last_name=row["contact_last_name"] or "",
        company_name=row["company_name"] or "",
        contact_title=row["contact_title"] or "" if "contact_title" in row.keys() else "",
        subject=row["subject"],
        body_text=row["body_text"],
        body_html=row["body_html"],
    )

    if ok:
        pool2 = await get_pool()
        async with pool2.acquire() as conn:
            # status='approved' + sent_at=now() captures: Anthony approved + handed
            # off to Smartlead. The actual prospect-side send happens later on
            # Smartlead's schedule; we don't mirror that timestamp here.
            await conn.execute(
                "UPDATE klaravex_outreach_approvals SET status='approved', approved_at=now(), sent_at=now() WHERE id=$1",
                approval_id,
            )
            await conn.execute(
                "UPDATE klaravex_prospected_leads SET status='queued_smartlead', updated_at=now() "
                "WHERE id=(SELECT prospect_id FROM klaravex_outreach_approvals WHERE id=$1)",
                approval_id,
            )
        name = f"{row['contact_first_name'] or ''} {row['contact_last_name'] or ''}".strip() or row["contact_email"]
        return HTMLResponse(
            f"<h1>Queued in Smartlead</h1>"
            f"<p><strong>{name}</strong> at {row['company_name']} has been added to your Smartlead campaign.</p>"
            f"<p>Smartlead will send the email at the optimal time for this recipient — typically within the next business day at their local timezone. "
            f"Bounce / reply / unsubscribe handling is automatic.</p>"
            f"<p style='color:#6b7280;font-size:12px'>Detail: {_h_escape(detail)}</p>"
        )
    else:
        return HTMLResponse(
            f"<h1>Smartlead handoff failed</h1>"
            f"<p>Could not add the prospect to your Smartlead campaign.</p>"
            f"<pre>{_h_escape(detail)}</pre>"
            f"<p>The approval is still pending — fix the cause + try again.</p>",
            status_code=502,
        )
