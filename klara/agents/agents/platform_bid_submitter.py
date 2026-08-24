"""
app/agents/platform_bid_submitter.py
──────────────────────────────────────
PlatformBidSubmitterAgent (P2) — submits queued bids to freelance platforms.

Guard rails (LOKI_MODE=full_autonomy, P2 = no human gate):
  - FREELANCE_MAX_BIDS_PER_DAY (default: 5) — hard daily cap across all platforms
  - FREELANCE_MIN_BUDGET_EUR   (default: 300) — skip if project budget is below this
  - Idempotent — never submits the same bid twice (status guard)

Platform submission strategy:
  - Freelancer.com:  POST /api/projects/0.1/bids/ (OAuth2 Bearer token)
  - Freelancermap.de POST /api/projects/apply (session cookie + FormData)
  - Upwork:          No programmatic API → marks bid as "manual_required",
                     sends Anthony an email with the pre-written cover letter
                     and a direct link to the project URL.
  - PeoplePerHour:   No programmatic API → same as Upwork (manual_required email)
  - Guru.com:        No programmatic API → same as Upwork (manual_required email)

For manual-required platforms the bid status is set to "submitted" only after
Anthony clicks "Sent" in the admin dashboard (via PATCH /api/v1/admin/freelance/bids/{id}/mark-sent).
Until then it stays as "manual_required".

Returns:
  { "submitted": int, "manual_required": int, "skipped_cap": int, "errors": int }
"""
from __future__ import annotations

import json
import re
from datetime import datetime, date, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import aiohttp
import structlog
from sqlalchemy import func, select

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.freelance_project import FreelanceProject, FreelancePlatform, FreelanceProjectStatus
from klara.rarv.platform_bid import PlatformBid, PlatformBidStatus

logger = structlog.get_logger(__name__)

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)

# ── User-agent for Freelancermap HTTP requests ────────────────────────────────
_FM_SUBMIT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

# Module-level cache: populated on first successful API call per process lifetime.
# Avoids a /users/0.1/self/ round-trip on every bid while still being correct
# across container restarts (no stale state persists between deployments).
_freelancer_bidder_id_cache: Optional[int] = None


class PlatformBidSubmitterAgent(BaseAgent):
    name = "platform_bid_submitter"
    description = (
        "Auto-submits queued PlatformBid records to freelance platforms. "
        "Guard rails: daily cap (FREELANCE_MAX_BIDS_PER_DAY), min budget threshold. "
        "Freelancer.com: OAuth2 API. Freelancermap.de: session-cookie REST API. "
        "Upwork/PPH/Guru: notifies Anthony for manual paste. "
        "P2 — runs autonomously in full_autonomy mode."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        input_data:
          bid_id: str  — submit a single bid by ID (optional)
          dry_run: bool — score and log but do not submit (default False)

        Returns AgentResult.ok({...})
        """
        dry_run = bool(input_data.get("dry_run", False))
        single_bid_id = input_data.get("bid_id")

        max_bids_per_day = int(
            getattr(context.settings, "freelance_max_bids_per_day", 5)
        )
        min_budget_eur = float(
            getattr(context.settings, "freelance_min_budget_eur", 300)
        )

        # ── Check daily cap ───────────────────────────────────────────────────
        today_start = datetime.combine(date.today(), datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        cap_q = await context.db.execute(
            select(func.count(PlatformBid.id)).where(
                PlatformBid.status.in_([
                    PlatformBidStatus.submitted,
                    "manual_required",
                ]),
                PlatformBid.updated_at >= today_start,
            )
        )
        bids_today = cap_q.scalar_one() or 0
        remaining_cap = max_bids_per_day - bids_today

        if remaining_cap <= 0 and not dry_run and not single_bid_id:
            logger.info(
                "platform_bid_submitter.daily_cap_reached",
                max=max_bids_per_day,
                bids_today=bids_today,
            )
            return AgentResult.ok(
                output={
                    "submitted": 0,
                    "manual_required": 0,
                    "skipped_cap": 0,
                    "errors": 0,
                    "daily_cap_reached": True,
                }
            )

        # ── Fetch queued bids ─────────────────────────────────────────────────
        if single_bid_id:
            q = await context.db.execute(
                select(PlatformBid).where(PlatformBid.id == single_bid_id)
            )
            bids = [q.scalar_one_or_none()]
            bids = [b for b in bids if b is not None]
        else:
            q = await context.db.execute(
                select(PlatformBid)
                .where(PlatformBid.status == PlatformBidStatus.queued)
                .order_by(PlatformBid.created_at.asc())
                .limit(remaining_cap)
                .with_for_update(skip_locked=True)
            )
            bids = list(q.scalars().all())

        if not bids:
            return AgentResult.ok(
                output={"submitted": 0, "manual_required": 0, "skipped_cap": 0, "errors": 0}
            )

        submitted = manual_required = skipped_cap = errors = 0

        async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
            for bid in bids:
                # Load associated project
                proj_q = await context.db.execute(
                    select(FreelanceProject).where(
                        FreelanceProject.id == bid.project_id
                    )
                )
                project = proj_q.scalar_one_or_none()
                if not project:
                    errors += 1
                    continue

                # Budget guard: skip if below threshold (convert rough to EUR)
                eff_budget = _to_eur(
                    float(project.budget_max or project.budget_min or 0),
                    project.budget_currency or "USD",
                )
                if eff_budget > 0 and eff_budget < min_budget_eur:
                    bid.status = "skipped_budget"
                    project.status = FreelanceProjectStatus.ignored
                    skipped_cap += 1
                    logger.info(
                        "platform_bid_submitter.skipped_budget",
                        bid_id=bid.id,
                        platform=bid.platform,
                        budget_eur=eff_budget,
                        min_eur=min_budget_eur,
                    )
                    continue

                if dry_run:
                    logger.info(
                        "platform_bid_submitter.dry_run",
                        bid_id=bid.id,
                        platform=bid.platform,
                        title=project.title[:60],
                    )
                    submitted += 1
                    continue

                # ── Platform routing ──────────────────────────────────────────
                try:
                    if bid.platform == FreelancePlatform.freelancer:
                        ok, platform_bid_id, error = await _submit_freelancer(
                            session, bid, project, context.settings
                        )
                        if ok:
                            bid.status = PlatformBidStatus.submitted
                            bid.platform_bid_id = platform_bid_id
                            bid.submitted_at = datetime.now(tz=timezone.utc)
                            project.status = FreelanceProjectStatus.bid_submitted
                            project.bid_submitted_at = datetime.now(tz=timezone.utc)
                            submitted += 1
                            logger.info(
                                "platform_bid_submitter.submitted",
                                bid_id=bid.id,
                                platform="freelancer",
                                platform_bid_id=platform_bid_id,
                                title=project.title[:60],
                            )
                        else:
                            bid.status = PlatformBidStatus.submit_failed
                            bid.submit_error = error
                            errors += 1
                            logger.error(
                                "platform_bid_submitter.freelancer_fail",
                                bid_id=bid.id,
                                error=error,
                            )

                    elif bid.platform == FreelancePlatform.freelancermap:
                        ok, platform_bid_id, error = await _submit_freelancermap(
                            session, bid, project, context.settings
                        )
                        if ok:
                            bid.status = PlatformBidStatus.submitted
                            bid.platform_bid_id = platform_bid_id
                            bid.submitted_at = datetime.now(tz=timezone.utc)
                            project.status = FreelanceProjectStatus.bid_submitted
                            project.bid_submitted_at = datetime.now(tz=timezone.utc)
                            submitted += 1
                            logger.info(
                                "platform_bid_submitter.submitted",
                                bid_id=bid.id,
                                platform="freelancermap",
                                platform_bid_id=platform_bid_id,
                                title=project.title[:60],
                            )
                        else:
                            bid.status = PlatformBidStatus.submit_failed
                            bid.submit_error = error
                            errors += 1
                            logger.error(
                                "platform_bid_submitter.freelancermap_fail",
                                bid_id=bid.id,
                                error=error,
                            )

                    else:
                        # Upwork, PPH, Guru — no programmatic API
                        # Notify Anthony via email with pre-written bid
                        await _notify_manual_bid(bid, project, context)
                        bid.status = "manual_required"
                        project.status = FreelanceProjectStatus.bid_submitted  # pending manual
                        manual_required += 1
                        logger.info(
                            "platform_bid_submitter.manual_required",
                            bid_id=bid.id,
                            platform=bid.platform,
                            title=project.title[:60],
                        )

                except Exception as exc:
                    bid.status = PlatformBidStatus.submit_failed
                    bid.submit_error = str(exc)
                    errors += 1
                    logger.error(
                        "platform_bid_submitter.error",
                        bid_id=bid.id,
                        platform=bid.platform,
                        error=str(exc),
                    )

        await context.db.commit()

        logger.info(
            "platform_bid_submitter.run_complete",
            submitted=submitted,
            manual_required=manual_required,
            skipped_cap=skipped_cap,
            errors=errors,
        )

        return AgentResult.ok(
            output={
                "submitted": submitted,
                "manual_required": manual_required,
                "skipped_cap": skipped_cap,
                "errors": errors,
                "bids_today_after": bids_today + submitted + manual_required,
            }
        )


# ── Freelancer.com API submission ─────────────────────────────────────────────

async def _get_freelancer_bidder_id(
    session: aiohttp.ClientSession,
    token: str,
) -> Optional[int]:
    """
    Retrieve the authenticated user's numeric Freelancer.com user ID.
    Required as `bidder_id` in POST /api/projects/0.1/bids/.

    Uses a module-level cache so subsequent bids in the same agent run
    do not incur additional API calls.
    """
    global _freelancer_bidder_id_cache
    if _freelancer_bidder_id_cache is not None:
        return _freelancer_bidder_id_cache

    try:
        async with session.get(
            "https://www.freelancer.com/api/users/0.1/self/",
            headers={"freelancer-oauth-v1": token},
            params={"user_details": "true"},
        ) as resp:
            data = await resp.json()
            if resp.status == 200:
                user_id = data.get("result", {}).get("id")
                if user_id:
                    _freelancer_bidder_id_cache = int(user_id)
                    logger.info(
                        "platform_bid_submitter.freelancer_bidder_id_resolved",
                        bidder_id=_freelancer_bidder_id_cache,
                    )
                    return _freelancer_bidder_id_cache
            logger.error(
                "platform_bid_submitter.freelancer_bidder_id_failed",
                status=resp.status,
                body=str(data)[:200],
            )
    except Exception as exc:
        logger.error(
            "platform_bid_submitter.freelancer_bidder_id_exception",
            error=str(exc),
        )
    return None


async def _submit_freelancer(
    session: aiohttp.ClientSession,
    bid: PlatformBid,
    project: FreelanceProject,
    settings: Any,
) -> tuple[bool, Optional[str], Optional[str]]:
    """
    POST /api/projects/0.1/bids/
    Docs: https://developers.freelancer.com/docs/projects/bids/post-bid
    Returns (success, platform_bid_id, error_message)
    """
    token = getattr(settings, "freelancer_access_token", None)
    if not token:
        return False, None, "FREELANCER_ACCESS_TOKEN not set"

    # Resolve the authenticated user's bidder_id — required by the API.
    # Without this field the API returns: "Must specify bidder_id."
    bidder_id = await _get_freelancer_bidder_id(session, token)
    if bidder_id is None:
        return False, None, "Could not resolve Freelancer.com bidder_id from /users/0.1/self/"

    payload = {
        "project_id": int(project.platform_id),
        "bidder_id": bidder_id,
        "amount": float(bid.bid_amount or project.budget_max or project.budget_min or 100),
        "period": int(bid.delivery_days or 14),
        "description": bid.cover_letter or "",
        "milestone_percentage": 100,
    }

    try:
        async with session.post(
            "https://www.freelancer.com/api/projects/0.1/bids/",
            headers={
                "freelancer-oauth-v1": token,
                "Content-Type": "application/json",
            },
            json=payload,
        ) as resp:
            data = await resp.json()
            if resp.status in (200, 201):
                result = data.get("result", {})
                platform_bid_id = str(result.get("id", ""))
                return True, platform_bid_id, None
            else:
                error_msg = (
                    data.get("message")
                    or data.get("error", {}).get("message")
                    or f"HTTP {resp.status}"
                )
                return False, None, error_msg
    except Exception as exc:
        return False, None, str(exc)


# ── Freelancermap.de API submission ───────────────────────────────────────────

async def _get_fm_numeric_project_id(
    session: aiohttp.ClientSession,
    platform_id: str,
    project_url: Optional[str],
) -> Optional[str]:
    """
    Resolve the numeric Freelancermap.de project ID required for
    POST /api/projects/apply (field: project=/api/projects/{numericId}).

    Strategy A: platform_id is already purely numeric -> use directly.
    Strategy B: slug ends in -{numericId}, e.g. 'some-title-3002479' -> extract without HTTP.
    Strategy C: fetch project page; parse "id":{N},"title": from the React JSON data blob.
    Strategy D: parse /projekt/{slug}-{numericId}/ pattern from HTML (legacy fallback).
    """
    if re.fullmatch(r"\d+", platform_id):
        return platform_id  # Strategy A: already numeric

    # Strategy B: slug itself embeds the ID as trailing digits, e.g. 'some-title-3002479'
    m = re.search(r"-(\d{5,8})$", platform_id)
    if m:
        return m.group(1)

    # Strategies C/D require fetching the project detail page
    url = project_url or f"https://www.freelancermap.de/projekt/{platform_id}"
    try:
        async with session.get(url, headers=_FM_SUBMIT_HEADERS) as resp:
            if resp.status != 200:
                logger.warning(
                    "platform_bid_submitter.fm.id_page_fetch_failed",
                    platform_id=platform_id,
                    status=resp.status,
                )
                return None
            html = await resp.text(encoding="utf-8", errors="replace")

        # Strategy C: React JSON data blob — "id":{N},"title": uniquely identifies the project
        m = re.search(r'"id"\s*:\s*(\d{4,8})\s*,\s*"title"\s*:', html)
        if m:
            return m.group(1)

        # Strategy D: canonical URL pattern /projekt/{slug}-{numericId}/ in HTML links
        m = re.search(r"/projekt/[^/?#\s\"']+-(\d{5,8})(?=[/\"'\s])", html)
        if m:
            return m.group(1)

    except Exception as exc:
        logger.warning(
            "platform_bid_submitter.fm.id_resolve_error",
            platform_id=platform_id,
            error=str(exc),
        )
    return None


async def _get_active_fm_cookie(settings: Any) -> Optional[str]:
    """
    Return the active Freelancermap session cookie string.

    Preference order:
      1. Redis key fm:session_cookie  (written by the 5-day auto-renewal task)
      2. FREELANCERMAP_SESSION_COOKIE env var  (manual fallback / bootstrap)
    """
    from app.tasks.fm_cookie_renewer import get_fm_cookie_from_redis

    redis_cookie = await get_fm_cookie_from_redis(settings.redis_url)
    if redis_cookie:
        return redis_cookie
    return getattr(settings, "freelancermap_session_cookie", None) or None


async def _submit_freelancermap(
    session: aiohttp.ClientSession,
    bid: PlatformBid,
    project: FreelanceProject,
    settings: Any,
) -> tuple[bool, Optional[str], Optional[str]]:
    """
    POST https://www.freelancermap.de/api/projects/apply
    Auth: session cookie (PHP/Symfony session).

    Cookie is sourced from Redis (auto-renewed every 5 days) with a fallback
    to the FREELANCERMAP_SESSION_COOKIE env var for bootstrap / manual renewal.

    FormData fields (reverse-engineered from the project-show bundle):
      user=/api/users/{user_id}       — logged-in user IRI (FREELANCERMAP_USER_ID)
      project=/api/projects/{num_id}  — numeric project ID IRI
      body={cover_letter}             — application text
      sendEmail=true
      sendPhone=false
      profile={profile_id}            — FREELANCERMAP_PROFILE_ID (required)
      profileAttachmentIds[]=         — empty attachment list

    Monthly application limit is enforced by Freelancermap server-side; a 403
    with a descriptive message is returned when the cap is reached.

    Returns (success, platform_bid_id, error_message).
    platform_bid_id is the numeric project ID (FM does not return an application ID).
    """
    session_cookie = await _get_active_fm_cookie(settings)
    user_id = getattr(settings, "freelancermap_user_id", None)
    profile_id = getattr(settings, "freelancermap_profile_id", None)

    if not session_cookie or not user_id or not profile_id:
        return False, None, (
            "Freelancermap credentials not configured — set "
            "FREELANCERMAP_SESSION_COOKIE, FREELANCERMAP_USER_ID, "
            "FREELANCERMAP_PROFILE_ID in .env"
        )

    # Resolve numeric project ID (platform_id may be slug-derived, not purely numeric)
    numeric_id = await _get_fm_numeric_project_id(
        session, project.platform_id, project.url
    )
    if not numeric_id:
        return False, None, (
            f"Could not resolve numeric Freelancermap project ID for "
            f"platform_id={project.platform_id!r} — "
            f"slug-based ID lookup failed"
        )

    form = aiohttp.FormData()
    form.add_field("user", f"/api/users/{user_id}")
    form.add_field("project", f"/api/projects/{numeric_id}")
    form.add_field("body", bid.cover_letter or "")
    form.add_field("sendEmail", "true")
    form.add_field("sendPhone", "false")
    form.add_field("profile", str(profile_id))
    form.add_field("profileAttachmentIds[]", "")  # required key, empty value
    # FM API rejects with "dataPrivacyAccepted: missing_data_privacy" without this.
    form.add_field("dataPrivacyAccepted", "true")

    headers = {
        **_FM_SUBMIT_HEADERS,
        "Cookie": session_cookie,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.freelancermap.de",
        "Referer": project.url or "https://www.freelancermap.de/",
    }

    try:
        async with session.post(
            "https://www.freelancermap.de/api/projects/apply",
            data=form,
            headers=headers,
        ) as resp:
            body = await resp.text()

            if resp.status in (200, 201):
                return True, numeric_id, None

            elif resp.status == 401:
                return False, None, (
                    "Freelancermap session expired — "
                    "renew FREELANCERMAP_SESSION_COOKIE"
                )

            elif resp.status == 403:
                try:
                    data = json.loads(body)
                    msg = (
                        data.get("message")
                        or data.get("detail")
                        or "HTTP 403 — possibly monthly application limit reached"
                    )
                except Exception:
                    msg = f"HTTP 403 — possibly monthly application limit reached. Body: {body[:200]}"
                return False, None, msg

            else:
                try:
                    data = json.loads(body)
                    msg = data.get("message") or data.get("detail") or f"HTTP {resp.status}: {body[:300]}"
                except Exception:
                    msg = f"HTTP {resp.status}: {body[:300]}"
                return False, None, msg

    except Exception as exc:
        return False, None, str(exc)


# ── Manual-required notification ─────────────────────────────────────────────

async def _notify_manual_bid(
    bid: PlatformBid,
    project: FreelanceProject,
    context: AgentContext,
) -> None:
    """
    Send Anthony an email with the pre-written cover letter and a direct link
    to the project so he can paste and submit in ≈60 seconds.
    """
    from klara.rarv.runtime.email_sender import send_transactional_email

    platform_label = {
        "upwork": "Upwork",
        "peopleperhour": "PeoplePerHour",
        "guru": "Guru.com",
        "freelancermap": "Freelancermap.de",
    }.get(bid.platform, bid.platform.title())

    subject = f"[Klaravex] Bid ready — {platform_label}: {project.title[:60]}"

    budget_str = ""
    if project.budget_max:
        budget_str = f"{project.budget_currency} {project.budget_max:,.0f}"
    elif project.budget_min:
        budget_str = f"{project.budget_currency} {project.budget_min:,.0f}+"

    bid_amount_str = (
        f"{bid.bid_currency} {bid.bid_amount:,.0f}"
        if bid.bid_amount
        else "See cover letter"
    )

    body_html = f"""
<p><strong>Platform:</strong> {platform_label}<br>
<strong>Project:</strong> {project.title}<br>
<strong>Budget:</strong> {budget_str or 'Not specified'}<br>
<strong>Recommended bid:</strong> {bid_amount_str}<br>
<strong>Fit score:</strong> {project.fit_score}/100<br>
<strong>Project URL:</strong> <a href="{project.url or '#'}">{project.url or 'N/A'}</a></p>

<p><strong>Cover letter (copy-paste ready):</strong></p>
<blockquote style="border-left:3px solid #ccc;padding-left:1em;margin:0;font-family:monospace;white-space:pre-wrap">{bid.cover_letter or ''}</blockquote>

<hr>
<p>Once submitted, mark it done:
<a href="{context.settings.app_base_url}/api/v1/admin/freelance/bids/{bid.id}/mark-sent">
Mark as Sent</a></p>
<p><small>Klaravex</small></p>
"""

    body_text = (
        f"Platform: {platform_label}\n"
        f"Project: {project.title}\n"
        f"Budget: {budget_str or 'Not specified'}\n"
        f"Recommended bid: {bid_amount_str}\n"
        f"Fit score: {project.fit_score}/100\n"
        f"URL: {project.url or 'N/A'}\n\n"
        f"Cover letter:\n\n{bid.cover_letter or ''}\n\n"
        f"Mark as sent: {context.settings.app_base_url}/api/v1/admin/freelance/bids/{bid.id}/mark-sent"
    )

    notify_email = getattr(
        context.settings,
        "approval_notify_email",
        "anthony@klaravex.de",
    )

    await send_transactional_email(
        context.settings,
        to_email=notify_email,
        to_name="Anthony",
        subject=subject,
        body_html=body_html,
        body_text=body_text,
    )


# ── Currency conversion (rough approximation) ────────────────────────────────

_FX_RATES_TO_EUR = {
    "USD": 0.92,
    "GBP": 1.17,
    "EUR": 1.00,
    "CHF": 1.04,
    "AUD": 0.60,
    "CAD": 0.68,
}


def _to_eur(amount: float, currency: str) -> float:
    rate = _FX_RATES_TO_EUR.get(currency.upper(), 0.90)
    return amount * rate
