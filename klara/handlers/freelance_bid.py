"""
Klaravex freelance bid pipeline — FastAPI router.

Three-stage pipeline:
  1. Scout  — discover new projects from Freelancer.com (API) + Upwork (manual queue)
  2. Score  — Claude scores each project 0–100 + writes cover letter
  3. Submit — submit qualifying bids (Freelancer.com via API; Upwork via manual email)

Routes:
  POST /internal/freelance/scout       run a scout pass
  GET  /internal/freelance/projects    list discovered projects (pending score)
  POST /internal/freelance/score       run scoring on all 'new' projects
  GET  /internal/freelance/bids        list queued bids
  POST /internal/freelance/submit      submit all queued bids (daily cap enforced)
  POST /internal/freelance/run         convenience: scout + score + submit in one call
  POST /internal/freelance/bids/{id}/mark-sent  mark a manual bid as sent
  GET  /internal/freelance/report      daily summary

Required env vars:
  FREELANCER_ACCESS_TOKEN     Freelancer.com OAuth V1 token (FREELANCER_OAUTH_TOKEN also accepted)
  ANTHROPIC_API_KEY           Anthropic API key (already set)
  LOKI_INTERNAL_SECRET        shared secret to protect endpoints
  APPROVAL_NOTIFY_EMAIL       where to send bid alerts (default: astewart@klaravex.com)
  APP_BASE_URL                base URL (default: https://api.klaravex.com)
  FREELANCE_MIN_BUDGET_USD    min project budget to consider (default: 500)
  FREELANCE_MIN_FIT_SCORE     min fit score to bid (default: 55)
  FREELANCE_MAX_BIDS_PER_DAY  max bids per day (default: 5)
  FREELANCE_BIDS_ENABLED      kill-switch; set to "false" to pause the whole
                              pipeline without redeploy (default: enabled)
"""

import json
import logging
import os
import re
import secrets
from datetime import date, datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import uuid
from decimal import Decimal

import anthropic
import httpx
from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import JSONResponse

from .lib.db import get_pool
from .lib.email import send_email
from .lib.freelance.scout_multi import scout_all_platforms
from .lib.freelance.submit_fm import submit_freelancermap_bid
from .lib.freelance.fm_cookie import renew_fm_cookie
from .lib.freelance.converter import convert_won_bid


def _jsonable(obj: Any) -> Any:
    """Recursively convert asyncpg Record / UUID / datetime / Decimal to JSON-safe types."""
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return obj

log = logging.getLogger("klaravex.freelance_bid")
router = APIRouter()

# ── Config ────────────────────────────────────────────────────────────────────

FREELANCER_TOKEN = os.environ.get("FREELANCER_ACCESS_TOKEN") or os.environ.get("FREELANCER_OAUTH_TOKEN", "")
FREELANCER_USER_ID = int(os.environ.get("FREELANCER_USER_ID", "75913883"))  # account: Antkeith1
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
APPROVAL_EMAIL = os.environ.get("APPROVAL_NOTIFY_EMAIL", "astewart@klaravex.com")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://api.klaravex.com")
INTERNAL_SECRET = os.environ.get("LOKI_INTERNAL_SECRET", "")
MIN_BUDGET_USD = float(os.environ.get("FREELANCE_MIN_BUDGET_USD", "500"))
MIN_FIT_SCORE = int(os.environ.get("FREELANCE_MIN_FIT_SCORE", "55"))
MAX_BIDS_PER_DAY = int(os.environ.get("FREELANCE_MAX_BIDS_PER_DAY", "5"))

# Kill-switch for the autonomous freelance bid pipeline (manual + API platforms).
# Defaults to ENABLED (the pipeline is intentionally always-on); only pauses when
# FREELANCE_BIDS_ENABLED is explicitly "false". Mirrors the env var read by
# PlatformBidSubmitterAgent so a single flag gates both dispatch surfaces.
BIDS_ENABLED = os.environ.get("FREELANCE_BIDS_ENABLED", "").strip().lower() != "false"

FREELANCER_API = "https://www.freelancer.com/api"

# ── US MSP / Security keywords ────────────────────────────────────────────────
US_KEYWORDS = [
    "Microsoft 365", "M365", "Azure", "Intune", "Entra ID",
    "Office 365", "SharePoint", "Teams", "Active Directory",
    "cybersecurity", "HIPAA", "SOC 2", "ISO 27001",
    "IT consulting", "managed IT", "cloud migration",
    "zero trust", "endpoint security", "AWS", "IT support",
]

# ── Anthony's profile for bid scoring ────────────────────────────────────────
ANTHONY_PROFILE = """\
Anthony Stewart — Founder, Klaravex LLC (Wyoming, US)

Skills: Microsoft 365 administration, Azure AD / Entra ID, Intune MDM, SharePoint,
Teams, Exchange Online, Windows Server, Active Directory, PowerShell scripting,
network security (Ubiquiti UniFi), HIPAA compliance readiness, SOC 2 advisory,
ISO 27001 gap analysis, cloud migration, endpoint management, IT support for SMBs.

Background: 10+ years in IT infrastructure and security. Based in Germany, serving
US SMB clients (healthcare, legal, financial, professional services) via Klaravex LLC.
Primary language: English. Can work across US time zones remotely.

Hourly rate range: $85–$150/hr USD. Fixed projects: scope-dependent.
No defense / ITAR / government work.
"""


# ── Auth helper ───────────────────────────────────────────────────────────────

def _check_internal(request: Request) -> None:
    if not INTERNAL_SECRET:
        return
    if not secrets.compare_digest(INTERNAL_SECRET, request.headers.get("x-loki-internal-secret", "")):
        raise HTTPException(status_code=403, detail="forbidden")


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _platform_project_exists(platform: str, platform_id: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return bool(await conn.fetchval(
            "SELECT 1 FROM klaravex_freelance_projects WHERE platform=$1 AND platform_id=$2",
            platform, platform_id,
        ))


async def _insert_project(p: dict[str, Any]) -> Optional[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO klaravex_freelance_projects
                (platform, platform_id, title, description, skills_required,
                 budget_min, budget_max, budget_type, budget_currency,
                 client_location, url, posted_at, proposals_count, is_verified_client)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            ON CONFLICT (platform, platform_id) DO NOTHING
            RETURNING id::text
            """,
            p.get("platform"), p.get("platform_id"), p.get("title"), p.get("description"),
            json.dumps(p.get("skills", [])),
            p.get("budget_min"), p.get("budget_max"), p.get("budget_type", "fixed"),
            p.get("budget_currency", "USD"),
            p.get("client_location"), p.get("url"), p.get("posted_at"),
            p.get("proposals_count"), p.get("is_verified_client", False),
        )


async def _count_bids_today() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM klaravex_platform_bids WHERE submitted_at::date = current_date"
        ) or 0


# ── Freelancer.com scouting ───────────────────────────────────────────────────

async def _scout_freelancer(keyword: str) -> list[dict[str, Any]]:
    if not FREELANCER_TOKEN:
        return []
    params = {
        "query": keyword,
        "limit": 10,
        "min_budget": int(MIN_BUDGET_USD),
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"{FREELANCER_API}/projects/0.1/projects/active/",
                params=params,
                headers={"Freelancer-OAuth-V1": FREELANCER_TOKEN},
            )
        if r.status_code != 200:
            log.warning("Freelancer scout %s returned %s", keyword, r.status_code)
            return []
        data = r.json()
        return data.get("result", {}).get("projects", [])
    except Exception as exc:
        log.warning("Freelancer scout failed for %s: %s", keyword, exc)
        return []


def _parse_freelancer_project(p: dict[str, Any]) -> dict[str, Any]:
    budget = p.get("budget") or {}
    jobs = p.get("jobs") or []
    # Currency lives at the project root on Freelancer's API, NOT inside budget.
    currency_obj = p.get("currency") or {}
    curr_code = currency_obj.get("code", "USD") if isinstance(currency_obj, dict) else "USD"
    exchange_rate = float(currency_obj.get("exchange_rate", 1.0) or 1.0) if isinstance(currency_obj, dict) else 1.0
    # Store skills as list of {id, name} so we can validate against bidder's profile.
    skill_objs = [{"id": j.get("id"), "name": j.get("name", "")} for j in jobs if j.get("id")]
    # Normalize budget to USD for consistent thresholds + ranking.
    raw_min = float(budget.get("minimum", 0) or 0)
    raw_max = float(budget.get("maximum", 0) or 0)
    budget_min_usd = raw_min * exchange_rate
    budget_max_usd = raw_max * exchange_rate
    return {
        "platform": "freelancer",
        "platform_id": str(p.get("id", "")),
        "title": (p.get("title") or "")[:500],
        "description": (p.get("description") or "")[:5000],
        "skills": skill_objs,
        "budget_min": budget_min_usd,
        "budget_max": budget_max_usd,
        "budget_type": "fixed" if not p.get("hourly_project_info") else "hourly",
        "budget_currency": "USD",  # always normalized
        "native_currency": curr_code,
        "native_budget_min": raw_min,
        "native_budget_max": raw_max,
        "client_location": p.get("frontend_client", {}).get("location", {}).get("country", {}).get("name"),
        "url": f"https://www.freelancer.com/projects/{p.get('seo_url', str(p.get('id', '')))}",
        "posted_at": datetime.fromtimestamp(p.get("time_submitted", 0), tz=timezone.utc) if p.get("time_submitted") else None,
        "proposals_count": p.get("bid_stats", {}).get("bid_count"),
        "is_verified_client": bool(p.get("client_has_deposit_made")),
    }


# ── Bid strategy (Claude scoring + cover letter) ──────────────────────────────

SCORE_PROMPT = """\
You are evaluating a freelance project opportunity for Anthony Stewart at Klaravex.

Anthony's profile:
{profile}

Project listing:
Title: {title}
Description: {description}
Skills required: {skills}
Budget: {budget_min}–{budget_max} {currency} ({budget_type})
Client location: {client_location}
Platform: {platform}

Evaluate this project and return ONLY a valid JSON object (no preamble, no markdown):
{{
  "fit_score": <integer 0-100>,
  "fit_rationale": "<1-2 sentences explaining the score>",
  "cover_letter": "<cover letter ≤180 words, direct, not salesy, mentions their specific need>",
  "recommended_bid_usd": <number — hourly rate if hourly project, fixed total if fixed>,
  "pass": <true if fit_score >= {min_score} else false>
}}

Scoring guidance:
- 80-100: Strong keyword match (M365, Azure, HIPAA, SOC 2) + good budget + clear scope
- 60-79: Partial match (general IT, cloud) + reasonable budget
- 40-59: Weak match but some relevant skills
- <40: Poor fit, skip
- Immediately fail (<30): offshore-only, sub-$300 fixed scope for multi-week work, hardware/on-site required
"""


# 2026-08-21: default repointed from fcc-server (:8090) to the LiteLLM proxy
# (:8000, also Anthropic /v1/messages). Auth = LiteLLM master key.
FCC_URL = os.environ.get("FCC_SERVER_URL", "http://host.docker.internal:8000/v1/messages")
FREELANCE_MODEL = os.environ.get("KLARAVEX_WRITER_MODEL", "smart")
_LLM_PROXY_KEY = os.environ.get("LITELLM_MASTER_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")


def _extract_json_object_fl(text: str) -> Optional[str]:
    start = text.find("{")
    if start < 0: return None
    depth = 0; in_str = False; escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape: escape = False; continue
        if ch == "\\": escape = True; continue
        if ch == '"': in_str = not in_str; continue
        if in_str: continue
        if ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0: return text[start:i+1]
    return None


async def _score_project(project: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Score a freelance project via the local fcc-server gateway (DeepSeek)."""
    prompt = SCORE_PROMPT.format(
        profile=ANTHONY_PROFILE,
        title=project.get("title", ""),
        description=(project.get("description") or "")[:2000],
        skills=", ".join(json.loads(project.get("skills_required") or "[]")) if isinstance(project.get("skills_required"), str) else ", ".join(project.get("skills_required") or []),
        budget_min=project.get("budget_min") or 0,
        budget_max=project.get("budget_max") or 0,
        currency=project.get("budget_currency", "USD"),
        budget_type=project.get("budget_type", "fixed"),
        client_location=project.get("client_location") or "Unknown",
        platform=project.get("platform", ""),
        min_score=MIN_FIT_SCORE,
    )
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(
                FCC_URL,
                headers={"Content-Type": "application/json", "x-api-key": _LLM_PROXY_KEY},
                json={
                    "model": FREELANCE_MODEL,
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        if r.status_code != 200:
            log.warning("freelance score: fcc HTTP %s: %s", r.status_code, r.text[:200])
            return None
        data = r.json()
        raw = "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        ).strip()
    except Exception as exc:
        log.warning("freelance score: fcc exception: %s", exc)
        return None

    raw = re.sub(r"^\s*```(?:json)?\s*\n?", "", raw)
    raw = re.sub(r"\n?\s*```\s*$", "", raw)
    raw = raw.strip()

    parsed = None
    for candidate in [raw, _extract_json_object_fl(raw)]:
        if not candidate: continue
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            parsed = obj; break

    if parsed is None:
        log.warning("freelance score: JSON parse failed — first 300 chars: %r", raw[:300])
        return None
    return parsed


_SCORE_QUEUED = "queued"
_SCORE_IGNORED = "ignored"
_SCORE_ERROR = "error"


async def _score_and_queue(project_id: str, project: dict[str, Any]) -> str:
    """Score a project and create a platform bid if it passes.

    Returns one of _SCORE_QUEUED / _SCORE_IGNORED / _SCORE_ERROR.
    """
    try:
        result = await _score_project(project)
        if not result:
            return _SCORE_ERROR
        fit_score = int(result.get("fit_score", 0))
        # Trust the threshold, not the LLM's self-reported pass field. Claude
        # sometimes returns fit_score=88 with pass=false (incoherent) which is
        # why 246 high-fit rows ended up status='ignored' before 2026-06-26.
        passes = fit_score >= MIN_FIT_SCORE

        pool = await get_pool()
        async with pool.acquire() as conn:
            if passes:
                await conn.execute(
                    "UPDATE klaravex_freelance_projects SET fit_score=$1, fit_rationale=$2, status='bid_queued', bid_queued_at=now(), updated_at=now() WHERE id=$3",
                    fit_score, result.get("fit_rationale"), project_id,
                )
                await conn.fetchval(
                    """
                    INSERT INTO klaravex_platform_bids
                        (project_id, platform, cover_letter, bid_amount, bid_currency)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id::text
                    """,
                    project_id, project.get("platform"),
                    result.get("cover_letter"), result.get("recommended_bid_usd"),
                    "USD",
                )
                return _SCORE_QUEUED
            else:
                await conn.execute(
                    "UPDATE klaravex_freelance_projects SET fit_score=$1, fit_rationale=$2, status='ignored', updated_at=now() WHERE id=$3",
                    fit_score, result.get("fit_rationale"), project_id,
                )
                return _SCORE_IGNORED
    except Exception as exc:
        log.exception("scoring failed for project %s: %s", project_id, exc)
        return _SCORE_ERROR


# ── Skill verification ────────────────────────────────────────────────────────

_BIDDER_SKILL_CACHE: dict[str, set[int]] = {}


async def _fetch_bidder_skill_ids() -> set[int]:
    """Fetch the current Freelancer.com user's skill (job) IDs. Cached per process."""
    cached = _BIDDER_SKILL_CACHE.get("ids")
    if cached is not None:
        return cached
    if not FREELANCER_TOKEN:
        return set()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{FREELANCER_API}/users/0.1/self/?jobs=true&compact=false",
                headers={"Freelancer-OAuth-V1": FREELANCER_TOKEN},
            )
        if r.status_code != 200:
            log.warning("self lookup returned %s", r.status_code)
            return set()
        jobs = (r.json().get("result") or {}).get("jobs") or []
        ids = {j.get("id") for j in jobs if j.get("id")}
        _BIDDER_SKILL_CACHE["ids"] = ids
        return ids
    except Exception as exc:
        log.warning("self skill lookup failed: %s", exc)
        return set()


def _project_required_skill_ids(project: dict[str, Any]) -> list[dict[str, Any]]:
    """Return [{id, name}] for skills required by a project."""
    raw = project.get("skills")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    return [s for s in (raw or []) if isinstance(s, dict) and s.get("id")]


async def _check_bidder_has_required_skills(project: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return (has_all_skills, missing_skill_names)."""
    required = _project_required_skill_ids(project)
    if not required:
        return True, []
    bidder_ids = await _fetch_bidder_skill_ids()
    missing = [s.get("name", str(s.get("id"))) for s in required if s.get("id") not in bidder_ids]
    return (len(missing) == 0), missing


# ── Bid submission ────────────────────────────────────────────────────────────

async def _submit_freelancer_bid(project: dict[str, Any], bid: dict[str, Any]) -> tuple[bool, str]:
    """Submit a bid. Returns (success, error_detail). Pre-checks skill match first."""
    if not FREELANCER_TOKEN:
        return False, "FREELANCER_ACCESS_TOKEN not set"
    # Pre-flight skill check — refuse 403s before they happen.
    has_skills, missing = await _check_bidder_has_required_skills(project)
    if not has_skills:
        msg = f"skill_check_failed: bidder profile missing required skills: {', '.join(missing)}"
        log.info("skipping bid on %s — %s", project.get("platform_id"), msg)
        return False, msg
    payload = {
        "project_id": int(project["platform_id"]),
        "bidder_id": FREELANCER_USER_ID,
        "amount": float(bid.get("bid_amount") or 100),
        "period": 7,
        "milestone_percentage": 100,
        "description": bid.get("cover_letter", ""),
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{FREELANCER_API}/projects/0.1/bids/",
                json=payload,
                headers={
                    "Freelancer-OAuth-V1": FREELANCER_TOKEN,
                    "Content-Type": "application/json",
                },
            )
        if r.status_code in (200, 201):
            result = r.json().get("result", {})
            return bool(result.get("id")), ""
        log.warning("Freelancer bid submit failed: %s %s", r.status_code, r.text[:200])
        return False, f"http_{r.status_code}: {r.text[:200]}"
    except Exception as exc:
        log.exception("Freelancer bid submission error: %s", exc)
        return False, f"exception: {exc}"


async def _send_manual_bid_email(project: dict[str, Any], bid: dict[str, Any]) -> None:
    """Email Anthony for manual platforms (Upwork, Guru, PPH)."""
    title = project.get("title", "Unknown Project")
    url = project.get("url", "—")
    amount = bid.get("bid_amount") or "—"
    cover = bid.get("cover_letter") or "—"
    body = (
        f"Manual bid required on {project.get('platform', 'platform')}.\n\n"
        f"Project: {title}\nURL: {url}\n"
        f"Recommended bid: ${amount} USD\n\n"
        f"---COVER LETTER---\n{cover}\n---END---\n\n"
        f"After submitting, click to mark as sent:\n"
        f"{APP_BASE_URL}/api/v1/internal/freelance/bids/{bid['id']}/mark-sent"
    )
    await send_email(
        to=APPROVAL_EMAIL,
        subject=f"[Klaravex Bid] {title[:60]}",
        body=body,
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/scout", include_in_schema=False)
async def scout_projects(request: Request) -> JSONResponse:
    """Scan Freelancer.com for new US IT projects."""
    _check_internal(request)
    discovered = 0
    skipped = 0
    errors = 0

    seen_ids: set[str] = set()
    for keyword in US_KEYWORDS[:8]:  # limit API calls per run
        projects = await _scout_freelancer(keyword)
        for raw in projects:
            pid = str(raw.get("id", ""))
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            parsed = _parse_freelancer_project(raw)
            if parsed["budget_max"] and parsed["budget_max"] < MIN_BUDGET_USD:
                skipped += 1
                continue
            try:
                row_id = await _insert_project(parsed)
                if row_id:
                    discovered += 1
                else:
                    skipped += 1
            except Exception as exc:
                log.warning("insert project failed %s: %s", pid, exc)
                errors += 1

    return JSONResponse({"status": "ok", "discovered": discovered, "skipped": skipped, "errors": errors})


@router.post("/score", include_in_schema=False)
async def score_projects(request: Request) -> JSONResponse:
    """Score all 'new' projects and queue passing ones for bid submission."""
    _check_internal(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    limit = int(body.get("limit", 20))
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM klaravex_freelance_projects WHERE status='new' ORDER BY created_at DESC LIMIT $1",
            limit,
        )

    queued = 0
    ignored = 0
    errors = 0
    for row in rows:
        project = dict(row)
        outcome = await _score_and_queue(str(project["id"]), project)
        if outcome == _SCORE_QUEUED:
            queued += 1
        elif outcome == _SCORE_IGNORED:
            ignored += 1
        else:
            errors += 1

    return JSONResponse({"status": "ok", "processed": len(rows), "bid_queued": queued, "ignored": ignored, "errors": errors})


@router.post("/rescore", include_in_schema=False)
async def rescore_projects(request: Request) -> JSONResponse:
    """Re-score projects whose previous scoring incorrectly routed them to
    'ignored' (the Anthropic 401 + LLM-pass-field bug pre-2026-06-26). Defaults
    to processing the 'ignored' bucket. Pass `status` in body to override.

    Body: {"status": "ignored" | "new", "limit": 50}
    """
    _check_internal(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    target_status = body.get("status") or "ignored"
    limit = int(body.get("limit", 50))

    pool = await get_pool()
    async with pool.acquire() as conn:
        # NULLS FIRST then ASC so rows that have NEVER been rescored come first;
        # rows we just rescored go to the back of the queue. Prevents the loop
        # from hammering the same top-N rows repeatedly.
        rows = await conn.fetch(
            "SELECT * FROM klaravex_freelance_projects WHERE status=$1 "
            "ORDER BY updated_at ASC NULLS FIRST, created_at DESC LIMIT $2",
            target_status, limit,
        )

    queued = 0
    still_ignored = 0
    errors = 0
    for row in rows:
        project = dict(row)
        outcome = await _score_and_queue(str(project["id"]), project)
        if outcome == _SCORE_QUEUED:
            queued += 1
        elif outcome == _SCORE_IGNORED:
            still_ignored += 1
        else:
            errors += 1

    return JSONResponse({
        "status": "ok",
        "processed": len(rows),
        "from_status": target_status,
        "bid_queued": queued,
        "still_ignored": still_ignored,
        "errors": errors,
    })


@router.post("/submit", include_in_schema=False)
async def submit_bids(request: Request) -> JSONResponse:
    """Submit queued bids up to the daily cap."""
    _check_internal(request)
    if not BIDS_ENABLED:
        return JSONResponse({"status": "disabled", "reason": "freelance_bids_enabled=false"})
    today_count = await _count_bids_today()
    remaining = MAX_BIDS_PER_DAY - today_count
    if remaining <= 0:
        return JSONResponse({"status": "daily_cap_reached", "today": today_count})

    pool = await get_pool()
    async with pool.acquire() as conn:
        bids = await conn.fetch(
            """
            SELECT b.*, p.platform_id, p.title, p.description, p.url, p.budget_type,
                   p.budget_min, p.budget_max, p.budget_currency, p.client_location,
                   p.skills_required
              FROM klaravex_platform_bids b
              JOIN klaravex_freelance_projects p ON p.id = b.project_id
             WHERE b.status = 'queued'
             ORDER BY b.created_at ASC
             LIMIT $1
            """,
            remaining,
        )

    submitted = 0
    manual = 0
    errors = 0
    skipped_skills = 0

    for row in bids:
        bid = dict(row)
        # Build a project-shaped dict with the skills field expected by the skill checker.
        project_for_check = {
            "platform_id": bid.get("platform_id"),
            "skills": bid.get("skills_required"),
        }
        platform = bid.get("platform", "")
        try:
            if platform == "freelancer":
                ok, err = await _submit_freelancer_bid(project_for_check, bid)
                if not ok and err.startswith("skill_check_failed"):
                    # Mark as 'skipped_no_skills' so Anthony can review what to add.
                    pool2 = await get_pool()
                    async with pool2.acquire() as conn:
                        await conn.execute(
                            "UPDATE klaravex_platform_bids SET status='skipped_no_skills', error_detail=$1 WHERE id=$2",
                            err, bid["id"],
                        )
                    skipped_skills += 1
                    continue
                if ok:
                    pool2 = await get_pool()
                    async with pool2.acquire() as conn:
                        await conn.execute(
                            "UPDATE klaravex_platform_bids SET status='submitted', submitted_at=now() WHERE id=$1",
                            bid["id"],
                        )
                        await conn.execute(
                            "UPDATE klaravex_freelance_projects SET status='bid_submitted', bid_submitted_at=now(), updated_at=now() WHERE id=$1",
                            bid["project_id"],
                        )
                    submitted += 1
                else:
                    pool2 = await get_pool()
                    async with pool2.acquire() as conn:
                        await conn.execute(
                            "UPDATE klaravex_platform_bids SET status='submit_failed', error_detail=$1 WHERE id=$2",
                            err, bid["id"],
                        )
                    errors += 1
            elif platform == "freelancermap":
                # Freelancermap.de — POST /api/projects/apply with session cookie.
                # Cookie comes from klaravex_runtime_secrets (auto-renewed every
                # 5 days) with FREELANCERMAP_SESSION_COOKIE env as fallback.
                ok, fm_numeric_id, fm_err = await submit_freelancermap_bid(
                    platform_id=str(bid.get("platform_id") or ""),
                    project_url=bid.get("url"),
                    cover_letter=bid.get("cover_letter") or "",
                )
                pool2 = await get_pool()
                if ok:
                    async with pool2.acquire() as conn:
                        await conn.execute(
                            "UPDATE klaravex_platform_bids SET status='submitted', "
                            "platform_bid_id=$1, submitted_at=now(), updated_at=now() "
                            "WHERE id=$2",
                            fm_numeric_id, bid["id"],
                        )
                        await conn.execute(
                            "UPDATE klaravex_freelance_projects SET status='bid_submitted', "
                            "bid_submitted_at=now(), updated_at=now() WHERE id=$1",
                            bid["project_id"],
                        )
                    submitted += 1
                else:
                    async with pool2.acquire() as conn:
                        await conn.execute(
                            "UPDATE klaravex_platform_bids SET status='submit_failed', "
                            "error_detail=$1, updated_at=now() WHERE id=$2",
                            fm_err, bid["id"],
                        )
                    errors += 1
            else:
                # Manual platforms (Upwork, Guru, PPH) — email Anthony
                await _send_manual_bid_email(bid, bid)
                pool2 = await get_pool()
                async with pool2.acquire() as conn:
                    await conn.execute(
                        "UPDATE klaravex_platform_bids SET status='manual_required' WHERE id=$1",
                        bid["id"],
                    )
                manual += 1
        except Exception as exc:
            log.exception("bid submit error %s: %s", bid["id"], exc)
            errors += 1

    return JSONResponse({
        "status": "ok",
        "submitted": submitted,
        "manual_required": manual,
        "skipped_no_skills": skipped_skills,
        "errors": errors,
    })


@router.post("/run", include_in_schema=False)
async def run_pipeline(request: Request) -> JSONResponse:
    """Convenience: run scout → score → submit in sequence."""
    _check_internal(request)
    scout_result = await scout_projects(request)
    score_result = await score_projects(request)
    submit_result = await submit_bids(request)
    return JSONResponse({
        "scout": json.loads(scout_result.body),
        "score": json.loads(score_result.body),
        "submit": json.loads(submit_result.body),
    })


@router.get("/projects", include_in_schema=False)
async def list_projects(request: Request) -> JSONResponse:
    _check_internal(request)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, platform, title, status, fit_score, budget_min, budget_max, budget_currency, created_at "
            "FROM klaravex_freelance_projects ORDER BY created_at DESC LIMIT 50"
        )
    return JSONResponse({"projects": [_jsonable(dict(r)) for r in rows]})


@router.get("/bids", include_in_schema=False)
async def list_bids(request: Request) -> JSONResponse:
    _check_internal(request)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT b.id, b.platform, b.status, b.bid_amount, b.bid_currency,
                   b.created_at, b.submitted_at, p.title, p.url
              FROM klaravex_platform_bids b
              JOIN klaravex_freelance_projects p ON p.id = b.project_id
             ORDER BY b.created_at DESC LIMIT 50
            """
        )
    return JSONResponse({"bids": [_jsonable(dict(r)) for r in rows]})


@router.post("/bids/{bid_id}/mark-sent", include_in_schema=False)
async def mark_bid_sent(bid_id: str = Path(...)) -> JSONResponse:
    """Anthony clicks this after manually submitting a bid on Upwork/PPH/Guru."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, project_id FROM klaravex_platform_bids WHERE id=$1", bid_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="bid not found")
        await conn.execute(
            "UPDATE klaravex_platform_bids SET status='submitted', submitted_at=now() WHERE id=$1",
            bid_id,
        )
        await conn.execute(
            "UPDATE klaravex_freelance_projects SET status='bid_submitted', bid_submitted_at=now(), updated_at=now() WHERE id=$1",
            row["project_id"],
        )
    return JSONResponse({"status": "marked_sent", "bid_id": bid_id})


@router.post("/scout-multi", include_in_schema=False)
async def scout_multi_platform(request: Request) -> JSONResponse:
    """Scan Freelancermap.de / PeoplePerHour / Guru / Upwork for new projects.

    Body (all optional):
      {
        "platforms": ["freelancermap","peopleperhour","guru","upwork"],
        "keywords": [...],
        "min_budget_usd": 300
      }

    Freelancer.com is intentionally NOT here — that lives in /scout (it uses
    the official OAuth API path, no scraping). Run both endpoints back-to-back
    for full coverage.
    """
    _check_internal(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    result = await scout_all_platforms(
        platforms=body.get("platforms"),
        keywords=body.get("keywords"),
        min_budget_usd=body.get("min_budget_usd"),
    )
    return JSONResponse({"status": "ok", **result})


@router.post("/fm-cookie-renew", include_in_schema=False)
async def fm_cookie_renew(request: Request) -> JSONResponse:
    """Renew the Freelancermap.de session cookie (5-day cron).

    Runs the email/password login flow and stores the resulting cookie in
    klaravex_runtime_secrets with a 6-day expiry. Submit path reads from
    there with FREELANCERMAP_SESSION_COOKIE env as fallback.
    """
    _check_internal(request)
    result = await renew_fm_cookie()
    if not result.get("ok"):
        # Email Anthony so he can renew manually if the auto-login broke.
        try:
            await send_email(
                to=APPROVAL_EMAIL,
                subject="[Klaravex] Freelancermap cookie auto-renewal failed",
                body=(
                    f"Auto-renew failed: {result.get('error')}\n\n"
                    f"Action: log into freelancermap.de in a browser, extract "
                    f"the Cookie header, set FREELANCERMAP_SESSION_COOKIE on "
                    f"the Azure container app, and redeploy.\n"
                ),
            )
        except Exception as exc:
            log.warning("fm_cookie_renew alert email failed: %s", exc)
    return JSONResponse(result)


@router.post("/bids/{bid_id}/mark-won", include_in_schema=False)
async def mark_bid_won(request: Request, bid_id: str = Path(...)) -> JSONResponse:
    """Mark a bid as won → create klaravex_clients lead → fire onboarding.

    Optional body fields: client_name, client_email, client_phone (override
    whatever the project record has).
    """
    _check_internal(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    result = await convert_won_bid(
        bid_id=bid_id,
        client_name=body.get("client_name"),
        client_email=body.get("client_email"),
        client_phone=body.get("client_phone"),
    )
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status_code)


@router.post("/requeue-manual", include_in_schema=False)
async def requeue_manual_bids(request: Request) -> JSONResponse:
    """One-shot: re-queue bids stuck in 'manual_required' status.

    Body (optional): {"platform": "freelancermap"} — restrict to one platform.
    Use after porting (Freelancermap bids previously went to manual_required
    because there was no auto-submit path). After this endpoint runs, the
    next /submit pass will pick them up and try the new FM auto-submit.
    """
    _check_internal(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    platform_filter = body.get("platform")
    pool = await get_pool()
    async with pool.acquire() as conn:
        if platform_filter:
            res = await conn.execute(
                "UPDATE klaravex_platform_bids "
                "   SET status='queued', updated_at=now(), error_detail=NULL "
                " WHERE status='manual_required' AND platform=$1",
                platform_filter,
            )
        else:
            res = await conn.execute(
                "UPDATE klaravex_platform_bids "
                "   SET status='queued', updated_at=now(), error_detail=NULL "
                " WHERE status='manual_required'"
            )
    # asyncpg returns "UPDATE <n>" on execute
    requeued = 0
    try:
        requeued = int((res or "UPDATE 0").split()[-1])
    except Exception:
        pass
    return JSONResponse({
        "status": "ok",
        "platform": platform_filter or "all",
        "requeued": requeued,
    })


@router.post("/check-outcomes", include_in_schema=False)
async def check_outcomes(request: Request) -> JSONResponse:
    """Placeholder for future bid-outcome polling. Currently summarizes age
    distribution of submitted bids that haven't been marked won/lost.
    """
    _check_internal(request)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT platform,
                   COUNT(*)                             AS total,
                   COUNT(*) FILTER (WHERE submitted_at < now() - interval '7 days')  AS over_7d,
                   COUNT(*) FILTER (WHERE submitted_at < now() - interval '30 days') AS over_30d
              FROM klaravex_platform_bids
             WHERE status = 'submitted'
             GROUP BY platform
            """
        )
    return JSONResponse({
        "status": "ok",
        "outstanding": [_jsonable(dict(r)) for r in rows],
    })


@router.get("/report", include_in_schema=False)
async def daily_report(request: Request) -> JSONResponse:
    _check_internal(request)
    pool = await get_pool()
    async with pool.acquire() as conn:
        total_projects = await conn.fetchval("SELECT COUNT(*) FROM klaravex_freelance_projects")
        bids_today = await conn.fetchval(
            "SELECT COUNT(*) FROM klaravex_platform_bids WHERE submitted_at::date = current_date"
        )
        pending_score = await conn.fetchval(
            "SELECT COUNT(*) FROM klaravex_freelance_projects WHERE status='new'"
        )
        queued_bids = await conn.fetchval(
            "SELECT COUNT(*) FROM klaravex_platform_bids WHERE status='queued'"
        )
        manual_required = await conn.fetchval(
            "SELECT COUNT(*) FROM klaravex_platform_bids WHERE status='manual_required'"
        )
    return JSONResponse({
        "total_projects_discovered": total_projects,
        "pending_scoring": pending_score,
        "bids_submitted_today": bids_today,
        "bids_queued": queued_bids,
        "manual_bid_emails_sent": manual_required,
        "daily_cap": MAX_BIDS_PER_DAY,
    })
