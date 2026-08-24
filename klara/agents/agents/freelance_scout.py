"""
app/agents/freelance_scout.py
──────────────────────────────
FreelanceScoutAgent (P1) — discovers new projects on freelance platforms
and writes FreelanceProject records to the DB.

Platforms (active):
  - Freelancer.com   → Official REST API (OAuth2 access token)
  - Freelancermap.de → HTML scrape of DACH project listings (server-side rendered)
  - PeoplePerHour    → Playwright/Chromium (AWS WAF JS challenge — needs real browser)
  - Guru.com         → Playwright/Chromium + stealth (Cloudflare + React CSR)
  - Upwork           → Playwright/Chromium + stealth (session cookie required)

Platforms (disabled):
  - (none — all five platforms active)

Deduplication: platform + platform_id unique index — ON CONFLICT DO NOTHING.

Search criteria (configurable via input_data):
  Keywords: Azure, M365, Microsoft 365, Intune, Entra ID, Office 365,
            PowerShell, VMware, IT Support, IT Consulting, Network Security,
            Windows Server, Active Directory, Entra, Meraki, IT consultant
  Min budget: FREELANCE_MIN_BUDGET_EUR (default 300 EUR)
  Geography: DACH (Freelancermap country=1 = Germany)

The agent does NOT score projects — that is BidStrategyAgent's job.
It only fetches, deduplicates, and stores raw project data.

Returns:
  { "discovered": int, "skipped_duplicate": int, "platforms": {...} }
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode, quote_plus

import aiohttp
import structlog
import uuid as _uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel
from app.models.freelance_project import (
    FreelanceProject,
    FreelancePlatform,
    FreelanceProjectStatus,
)

logger = structlog.get_logger(__name__)

# ── Search keywords (Anthony's core DACH IT skill set) ───────────────────────
SEARCH_KEYWORDS = [
    "Azure", "Microsoft 365", "M365", "Intune", "Entra ID",
    "Office 365", "PowerShell", "Entra", "Active Directory",
    "IT Support", "IT Consulting", "Windows Server", "VMware", "Meraki",
    "network security", "IT consultant",
]

# ── Timeout for all HTTP requests ─────────────────────────────────────────────
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)

# ── Playwright browser timeout (ms) ───────────────────────────────────────────
_PW_NAVIGATION_TIMEOUT = 30_000   # 30s page load
_PW_WAIT_TIMEOUT       = 15_000   # 15s for selector/network idle

# ── User-agent string for scraping requests ───────────────────────────────────
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ── Freelancermap-specific request headers ────────────────────────────────────
_FM_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── PeoplePerHour-specific request headers (aiohttp fallback, unused if PW works) ─
_PPH_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "en-GB,en;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Referer": "https://www.peopleperhour.com/",
    "Accept-Encoding": "gzip, deflate, br",
}


class FreelanceScoutAgent(BaseAgent):
    name = "freelance_scout"
    description = (
        "Scans Freelancer.com, Freelancermap.de, PeoplePerHour, Guru.com, and Upwork "
        "for DACH IT/Azure/M365 projects matching Anthony's skill set. "
        "Creates FreelanceProject records. Scout writes to freelance_projects table. P2."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        input_data:
          platforms:  list[str]  — subset of platform names; defaults to all active
          keywords:   list[str]  — override search keywords
          min_budget: float      — override minimum budget EUR (default from settings)

        Returns AgentResult.ok({
            "discovered": int,
            "skipped_duplicate": int,
            "platforms": { platform: { discovered, skipped } }
        })
        """
        platforms = input_data.get(
            "platforms",
            [
                FreelancePlatform.freelancer,
                FreelancePlatform.freelancermap,
                FreelancePlatform.peopleperhour,
                FreelancePlatform.guru,
                FreelancePlatform.upwork,
            ],
        )
        keywords = input_data.get("keywords", SEARCH_KEYWORDS)
        min_budget = float(
            input_data.get("min_budget", context.settings.freelance_min_budget_eur)
        )

        totals: dict[str, dict] = {}
        total_new = 0
        total_dupes = 0

        # ── aiohttp session (Freelancer + Freelancermap) ──────────────────────
        async with aiohttp.ClientSession(
            timeout=_HTTP_TIMEOUT, headers={"User-Agent": _UA}
        ) as session:
            for platform in platforms:
                try:
                    if platform == FreelancePlatform.freelancer:
                        projects = await _fetch_freelancer(
                            session, keywords, min_budget, context.settings
                        )
                    elif platform == FreelancePlatform.freelancermap:
                        projects = await _fetch_freelancermap(
                            session, keywords, min_budget
                        )
                    elif platform == FreelancePlatform.peopleperhour:
                        projects = await _fetch_pph_playwright(
                            keywords, min_budget
                        )
                    elif platform == FreelancePlatform.guru:
                        projects = await _fetch_guru_playwright(
                            keywords, min_budget
                        )
                    elif platform == FreelancePlatform.upwork:
                        projects = await _fetch_upwork_playwright(
                            keywords, min_budget, context.settings
                        )
                    else:
                        logger.warning(
                            "freelance_scout.unknown_platform", platform=platform
                        )
                        continue

                    new_count, dupe_count = await _upsert_projects(
                        context, platform, projects
                    )
                    totals[platform] = {
                        "discovered": new_count,
                        "skipped": dupe_count,
                    }
                    total_new += new_count
                    total_dupes += dupe_count

                    logger.info(
                        "freelance_scout.platform_done",
                        platform=platform,
                        new=new_count,
                        dupes=dupe_count,
                    )

                except Exception as exc:
                    logger.error(
                        "freelance_scout.platform_error",
                        platform=platform,
                        error=str(exc),
                    )
                    totals[platform] = {
                        "discovered": 0,
                        "skipped": 0,
                        "error": str(exc),
                    }

        logger.info(
            "freelance_scout.complete",
            total_new=total_new,
            total_dupes=total_dupes,
            platforms=list(totals.keys()),
        )

        # ── RARV submission (best-effort, never breaks scouting) ──────────────
        # Append a scout-run line to today's daily journal so the RARV pipeline
        # has a real producer feeding the vault. See loki-vault/knowledge/rarv-pipeline.md.
        await _submit_scout_observation(context, total_new, total_dupes, totals)

        return AgentResult.ok(
            output={
                "discovered": total_new,
                "skipped_duplicate": total_dupes,
                "platforms": totals,
            }
        )


async def _submit_scout_observation(
    context: AgentContext,
    total_new: int,
    total_dupes: int,
    totals: dict,
) -> None:
    """
    INSERT a daily-kind note_submission summarizing this scout run.

    The RARV journal team picks it up on the next heartbeat (every 30 min)
    and appends it to daily/<today-Berlin>.md in the vault.

    Best-effort: any failure here is logged but does NOT propagate. The scout
    must keep working even if the RARV pipeline is unreachable.
    """
    try:
        import hashlib
        import json
        import uuid
        from sqlalchemy import text as _sql

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"### {ts} -- freelance_scout run",
            "",
            f"- **Discovered:** {total_new} new project(s)",
            f"- **Skipped (dup):** {total_dupes}",
            "",
            "**Per platform:**",
        ]
        for platform, stats in sorted(totals.items()):
            err = stats.get("error")
            base = (
                f"- `{platform}`: "
                f"new={stats.get('discovered', 0)} "
                f"skipped={stats.get('skipped', 0)}"
            )
            if err:
                base += f" — ❌ error: {str(err)[:160]}"
            lines.append(base)
        content = "\n".join(lines) + "\n"
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()

        await context.db.execute(
            _sql(
                """
                INSERT INTO note_submissions
                (submission_uuid, agent_id, topic_slug, note_kind, title,
                 content, content_sha256, proposed_frontmatter,
                 priority, status, max_attempts, journal_team_attempts)
                VALUES
                (:u, :agent, :slug, 'daily', :title,
                 :content, :sha, CAST(:f AS jsonb),
                 5, 'pending', 3, 0)
                """
            ),
            {
                "u": str(uuid.uuid4()),
                "agent": "freelance_scout",
                "slug": "freelance-scout-runs",
                "title": f"Scout run {ts}",
                "content": content,
                "sha": sha,
                "f": json.dumps({
                    "source_agent": "freelance_scout",
                    "run_at": ts,
                    "total_new": total_new,
                    "total_dupes": total_dupes,
                    "platforms": list(totals.keys()),
                }),
            },
        )
        await context.db.commit()
        logger.info(
            "freelance_scout.rarv_submitted",
            total_new=total_new,
            platforms=list(totals.keys()),
        )
    except Exception as exc:
        # Never break the scout because RARV submission failed.
        logger.warning(
            "freelance_scout.rarv_submit_failed",
            error=str(exc),
        )


# ── Platform fetchers — HTTP ──────────────────────────────────────────────────

async def _fetch_freelancer(
    session: aiohttp.ClientSession,
    keywords: list[str],
    min_budget: float,
    settings: Any,
) -> list[dict]:
    """
    Freelancer.com REST API v1.
    Endpoint: GET /api/projects/0.1/projects/active
    Auth: OAuth2 Bearer token (FREELANCER_ACCESS_TOKEN env var)
    """
    token = getattr(settings, "freelancer_access_token", None)
    if not token:
        logger.warning("freelance_scout.freelancer.no_token")
        return []

    headers = {"freelancer-oauth-v1": token}
    projects: list[dict] = []

    for keyword in keywords[:5]:
        params = {
            "query": keyword,
            "project_types[]": ["fixed", "hourly"],
            "min_avg_price": int(min_budget),
            "limit": 20,
            "offset": 0,
            "full_description": True,
            "job_details": True,
        }
        url = (
            "https://www.freelancer.com/api/projects/0.1/projects/active?"
            + urlencode(params, doseq=True)
        )

        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 401:
                    logger.error("freelance_scout.freelancer.auth_failed")
                    return []
                if resp.status != 200:
                    logger.warning(
                        "freelance_scout.freelancer.http_error",
                        status=resp.status,
                        keyword=keyword,
                    )
                    continue
                data = await resp.json()
                raw_projects = data.get("result", {}).get("projects", [])
                for p in raw_projects:
                    projects.append(_normalise_freelancer(p))
        except Exception as exc:
            logger.warning(
                "freelance_scout.freelancer.fetch_error",
                keyword=keyword,
                error=str(exc),
            )

    seen: set[str] = set()
    unique = []
    for p in projects:
        if p["platform_id"] not in seen:
            seen.add(p["platform_id"])
            unique.append(p)
    return unique


def _normalise_freelancer(p: dict) -> dict:
    """Map Freelancer.com project object → internal dict."""
    budget = p.get("budget", {})
    return {
        "platform_id": str(p.get("id", "")),
        "title": p.get("title", "Untitled"),
        "description": p.get("description", ""),
        "skills_required": json.dumps(
            [j.get("name", "") for j in p.get("jobs", [])]
        ),
        "category": (
            p.get("type", {}).get("name")
            if isinstance(p.get("type"), dict)
            else None
        ),
        "budget_min": float(budget.get("minimum", 0) or 0),
        "budget_max": float(budget.get("maximum", 0) or 0),
        "budget_type": "hourly" if p.get("hourly_project_info") else "fixed",
        "budget_currency": (
            budget.get("currency", {}).get("code", "EUR")
            if isinstance(budget.get("currency"), dict)
            else "EUR"
        ),
        "client_name": None,
        "client_location": (
            p.get("location", {}).get("country", {}).get("name")
            if isinstance(p.get("location"), dict)
            else None
        ),
        "client_rating": None,
        "client_reviews_count": None,
        "client_spend_total": None,
        "url": f"https://www.freelancer.com/projects/{p.get('seo_url', p.get('id', ''))}",
        "posted_at": (
            datetime.fromtimestamp(p["time_submitted"], tz=timezone.utc)
            if p.get("time_submitted")
            else None
        ),
        "proposals_count": (
            p.get("bid_stats", {}).get("bid_count")
            if isinstance(p.get("bid_stats"), dict)
            else None
        ),
        "is_verified_client": bool(
            p.get("employer", {}).get("status", {}).get("payment_verified")
        ) if isinstance(p.get("employer"), dict) else False,
    }


async def _fetch_freelancermap(
    session: aiohttp.ClientSession,
    keywords: list[str],
    min_budget: float,
) -> list[dict]:
    """
    Freelancermap.de — DACH-native German freelance platform.
    Server-side rendered — no bot challenge from Hetzner IP.
    """
    projects: list[dict] = []
    seen_pids: set[str] = set()

    for keyword in keywords[:6]:
        url = (
            f"https://www.freelancermap.de/projekte"
            f"?query={quote_plus(keyword)}&country%5B%5D=1"
        )
        try:
            async with session.get(url, headers=_FM_HEADERS) as resp:
                if resp.status != 200:
                    logger.warning(
                        "freelance_scout.fm.http_error",
                        status=resp.status,
                        keyword=keyword,
                    )
                    continue
                html = await resp.text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.warning(
                "freelance_scout.fm.fetch_error",
                keyword=keyword,
                error=str(exc),
            )
            continue

        links = re.findall(
            r'href=["\'](?:https://www\.freelancermap\.de)?(/projekt/[^"\'?#]+)["\']',
            html,
        )
        new_this_kw = 0

        for slug in links:
            meta = _parse_fm_slug(slug)
            pid = meta["pid"]

            if pid in seen_pids:
                continue
            seen_pids.add(pid)

            budget_max = meta["budget_max_daily"]
            if budget_max is not None and budget_max < min_budget:
                continue

            projects.append({
                "platform_id": pid,
                "title": meta["title"],
                "description": None,
                "skills_required": None,
                "category": None,
                "budget_min": None,
                "budget_max": budget_max,
                "budget_type": "hourly" if meta["hourly_rate"] is not None else None,
                "budget_currency": "EUR",
                "client_name": None,
                "client_location": None if meta["is_remote"] else "Germany",
                "client_rating": None,
                "client_reviews_count": None,
                "client_spend_total": None,
                "url": "https://www.freelancermap.de" + slug,
                "posted_at": None,
                "proposals_count": None,
                "is_verified_client": False,
            })
            new_this_kw += 1

        logger.info(
            "freelance_scout.fm.keyword_done",
            keyword=keyword,
            links_found=len(links),
            new_added=new_this_kw,
        )

    return projects


# ── Platform fetchers — Playwright ────────────────────────────────────────────

def _make_pw_browser_args() -> list[str]:
    """Common Chromium launch args for all Playwright scrapers."""
    return [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--window-size=1920,1080",
    ]


async def _fetch_pph_playwright(
    keywords: list[str],
    min_budget: float,
) -> list[dict]:
    """
    PeoplePerHour — Playwright/Chromium scraper.

    PPH returns HTTP 202 (AWS WAF JavaScript proof-of-work challenge) for plain
    HTTP requests from datacenter IPs. Real Chromium solves the JS challenge
    automatically, sets the aws-waf-token cookie, and fetches the real content.

    PPH is a React SPA. Job data is embedded in the page HTML as a normalised
    Redux store object — no separate search AJAX fires from datacenter IPs.
    We load the general jobs feed (one page load) and filter by keyword locally
    against title + description in _parse_pph_listings.
    """
    from playwright.async_api import async_playwright

    projects: list[dict] = []
    seen_pids: set[str] = set()

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=_make_pw_browser_args(),
            )
            ctx = await browser.new_context(
                user_agent=_UA,
                locale="en-GB",
                viewport={"width": 1920, "height": 1080},
                extra_http_headers={"Accept-Language": "en-GB,en;q=0.9"},
            )
            page = await ctx.new_page()
            # Suppress images/fonts to speed up loads
            await page.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2}", lambda r: r.abort())

            # PPH embeds job data as a Redux store blob in the page HTML.
            # Keyword search AJAX is WAF-blocked from DC IPs, so we load
            # IT-relevant category pages directly and skip keyword filtering —
            # BidStrategyAgent handles relevance scoring downstream.
            category_urls = [
                "https://www.peopleperhour.com/freelance-jobs/technology-programming",
                "https://www.peopleperhour.com/freelance-jobs/technology-programming/it-support",
            ]
            for url in category_urls:
                try:
                    await page.goto(url, timeout=_PW_NAVIGATION_TIMEOUT, wait_until="load")
                    try:
                        await page.wait_for_load_state("networkidle", timeout=20_000)
                    except Exception:
                        pass  # networkidle can stall on dynamic SPAs; proceed anyway

                    html = await page.content()
                    # No keyword filter — category already scopes to IT jobs
                    new_count = _parse_pph_listings(html, seen_pids, projects, min_budget)
                    logger.info(
                        "freelance_scout.pph.category_done",
                        url=url,
                        new_added=new_count,
                    )

                except Exception as exc:
                    logger.warning(
                        "freelance_scout.pph.page_error",
                        url=url,
                        error=str(exc),
                    )

            await browser.close()

    except Exception as exc:
        logger.error("freelance_scout.pph.playwright_error", error=str(exc))

    return projects


async def _fetch_guru_playwright(
    keywords: list[str],
    min_budget: float,
) -> list[dict]:
    """
    Guru.com — Playwright/Chromium + stealth scraper.

    Guru uses Cloudflare JS challenge AND React client-side rendering.
    playwright-stealth patches navigator.webdriver and other automation
    fingerprints to pass Cloudflare's bot detection.

    Job listings: https://www.guru.com/d/jobs/q/{keyword}/
    Each job card contains a link: /d/jobs/id/{numeric-id}/{title-slug}/
    """
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async as _stealth
    except ImportError:
        _stealth = None
        logger.warning("freelance_scout.guru.stealth_unavailable")

    projects: list[dict] = []
    seen_pids: set[str] = set()

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=_make_pw_browser_args(),
            )
            ctx = await browser.new_context(
                user_agent=_UA,
                locale="en-US",
                viewport={"width": 1920, "height": 1080},
            )
            page = await ctx.new_page()
            if _stealth:
                await _stealth(page)
            await page.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2}", lambda r: r.abort())

            for keyword in keywords[:6]:
                # 2026-05-28: guru.com retired /d/jobs/q/{kw}/ — it 301s to
                # /errors/pagenotfound.aspx. The skill-slug URL still serves.
                slug = keyword.strip().lower().replace(" ", "-")
                url = f"https://www.guru.com/d/jobs/skill/{quote_plus(slug)}/"
                try:
                    await page.goto(url, timeout=_PW_NAVIGATION_TIMEOUT, wait_until="networkidle")
                    # React hydration complete when job cards appear
                    try:
                        await page.wait_for_selector(
                            "a[href*='/d/jobs/id/']",
                            timeout=_PW_WAIT_TIMEOUT,
                        )
                    except Exception:
                        logger.warning(
                            "freelance_scout.guru.no_listings",
                            keyword=keyword,
                            url=page.url,
                        )
                        continue

                    html = await page.content()
                    new_this_kw = _parse_guru_listings(html, seen_pids, projects, min_budget)
                    logger.info(
                        "freelance_scout.guru.keyword_done",
                        keyword=keyword,
                        new_added=new_this_kw,
                    )

                except Exception as exc:
                    logger.warning(
                        "freelance_scout.guru.page_error",
                        keyword=keyword,
                        error=str(exc),
                    )

            await browser.close()

    except Exception as exc:
        logger.error("freelance_scout.guru.playwright_error", error=str(exc))

    return projects


async def _fetch_upwork_playwright(
    keywords: list[str],
    min_budget: float,
    settings: Any,
) -> list[dict]:
    """
    Upwork — Playwright/Chromium + stealth scraper.

    Upwork's job search is React-rendered and Cloudflare-protected. Login is
    required to see full job details and avoid CAPTCHA loops. Provide a valid
    session cookie via UPWORK_SESSION_COOKIE in .env (copy the Cookie header
    from a logged-in browser session; refresh every ~30 days).

    Job search URL: https://www.upwork.com/nx/jobs/search/?q={keyword}&sort=recency
    Job links:      /jobs/~{base64-like-id} or /ab/jobs/search/job-detail/{id}
    """
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async as _stealth
    except ImportError:
        _stealth = None
        logger.warning("freelance_scout.upwork.stealth_unavailable")

    session_cookie = getattr(settings, "upwork_session_cookie", None)
    if not session_cookie:
        logger.warning(
            "freelance_scout.upwork.no_session_cookie",
            hint="Set UPWORK_SESSION_COOKIE in .env to enable Upwork scout",
        )
        return []

    projects: list[dict] = []
    seen_pids: set[str] = set()

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=_make_pw_browser_args(),
            )
            ctx = await browser.new_context(
                user_agent=_UA,
                locale="en-US",
                viewport={"width": 1920, "height": 1080},
            )

            # Inject session cookies before navigating
            await _inject_cookie_string(ctx, "https://www.upwork.com", session_cookie)

            page = await ctx.new_page()
            if _stealth:
                await _stealth(page)
            await page.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2}", lambda r: r.abort())

            for keyword in keywords[:5]:
                url = (
                    f"https://www.upwork.com/nx/jobs/search/"
                    f"?q={quote_plus(keyword)}&sort=recency"
                )
                try:
                    await page.goto(url, timeout=_PW_NAVIGATION_TIMEOUT, wait_until="networkidle")

                    # Detect login wall
                    if "login" in page.url or "signup" in page.url:
                        logger.warning(
                            "freelance_scout.upwork.session_expired",
                            hint="UPWORK_SESSION_COOKIE is expired — renew it",
                        )
                        break

                    # Wait for job tiles
                    try:
                        await page.wait_for_selector(
                            "[data-test='job-tile-list'] article, section[data-test='JobTile']",
                            timeout=_PW_WAIT_TIMEOUT,
                        )
                    except Exception:
                        # Try alternative selector
                        try:
                            await page.wait_for_selector(
                                "article.job-tile, div[data-test='UpCJobTile']",
                                timeout=5_000,
                            )
                        except Exception:
                            logger.warning(
                                "freelance_scout.upwork.no_listings",
                                keyword=keyword,
                                url=page.url,
                            )
                            continue

                    html = await page.content()
                    new_this_kw = _parse_upwork_listings(html, seen_pids, projects, min_budget)
                    logger.info(
                        "freelance_scout.upwork.keyword_done",
                        keyword=keyword,
                        new_added=new_this_kw,
                    )

                except Exception as exc:
                    logger.warning(
                        "freelance_scout.upwork.page_error",
                        keyword=keyword,
                        error=str(exc),
                    )

            await browser.close()

    except Exception as exc:
        logger.error("freelance_scout.upwork.playwright_error", error=str(exc))

    return projects


async def _inject_cookie_string(ctx: Any, domain: str, cookie_str: str) -> None:
    """
    Parse a raw Cookie header string (k=v; k2=v2; ...) and inject each cookie
    into the Playwright browser context for the given domain.
    """
    cookies = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        value = value.strip()
        if name:
            cookies.append({
                "name": name,
                "value": value,
                "domain": ".upwork.com",
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            })
    if cookies:
        await ctx.add_cookies(cookies)


# ── HTML parsers ──────────────────────────────────────────────────────────────

def _parse_pph_listings(
    html: str,
    seen_pids: set[str],
    projects: list[dict],
    min_budget: float,
    keywords: Optional[list[str]] = None,
) -> int:
    """
    Parse PeoplePerHour embedded Redux/normalised store JSON.

    PPH is a React SPA. All job data is serialised as a normalised object keyed
    by project ID inside the page HTML:
      "JOBID": {"id":"JOBID","type":"projects","attributes":{...}}

    Because PPH's keyword-search AJAX is WAF-blocked from datacenter IPs, we
    load the general jobs feed and filter locally using keywords.

    Mutates seen_pids and projects in-place. Returns count of newly added jobs.
    """
    import json as _json

    new_count = 0
    kw_lower = [k.lower() for k in (keywords or [])]
    attrs_pattern = re.compile(r'"type"\s*:\s*"projects"\s*,\s*"attributes"\s*:\s*(\{)')

    for m in attrs_pattern.finditer(html):
        start = m.start(1)
        # Walk forward counting braces to find end of the attributes object
        depth = 0
        i = start
        while i < len(html):
            c = html[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        try:
            a = _json.loads(html[start: i + 1])
        except Exception:
            continue

        pid = str(a.get("proj_id", ""))
        if not pid or pid in seen_pids:
            continue

        title: str = a.get("title") or ""
        description: str = a.get("proj_desc") or ""

        # Client-side keyword filter — search AJAX doesn't fire from DC IPs
        if kw_lower:
            text = (title + " " + description).lower()
            if not any(kw in text for kw in kw_lower):
                continue

        # Budget — budget_converted is normalised to GBP; budget is in job currency
        raw_budget = a.get("budget_converted") or a.get("budget")
        try:
            budget_val = float(raw_budget) if raw_budget is not None else 0.0
        except (TypeError, ValueError):
            budget_val = 0.0

        project_type = str(a.get("project_type", "")).lower()
        is_hourly = "hour" in project_type
        # For min_budget comparison treat hourly rate as an 8-hour day equivalent
        effective_budget = budget_val * 8.0 if is_hourly else budget_val
        if min_budget > 0 and effective_budget < min_budget:
            continue

        seen_pids.add(pid)

        # Decode unicode escapes in URL (/ → /)
        raw_url: str = a.get("url", "")
        try:
            url = raw_url.encode("utf-8").decode("unicode_escape") if "\\u" in raw_url else raw_url
        except Exception:
            url = raw_url

        # Client info
        client: dict = a.get("client") or {}
        client_name = (
            f"{client.get('firstname', '')} {client.get('lastname', '')}".strip()
            or client.get("username")
            or None
        )

        projects.append({
            "platform_id": pid,
            "title": title,
            "description": description[:500] if description else None,
            "skills_required": None,
            "category": (a.get("category") or {}).get("cate_name"),
            "budget_min": None,
            "budget_max": budget_val if budget_val > 0 else None,
            "budget_type": "hourly" if is_hourly else "fixed",
            "budget_currency": a.get("currency", "GBP"),
            "client_name": client_name,
            "client_location": None,
            "client_rating": None,
            "client_reviews_count": None,
            "client_spend_total": None,
            "url": url,
            "posted_at": _parse_pph_posted_dt(a.get("posted_dt")),
            "proposals_count": a.get("proposalCount"),
            "is_verified_client": False,
        })
        new_count += 1

    return new_count


def _parse_pph_posted_dt(value) -> Optional[datetime]:
    # PPH's Redux store serialises posted_dt as "YYYY-MM-DD HH:MM:SS" in UTC.
    # asyncpg's DateTime(timezone=True) column rejects strings — parse here.
    if value is None or isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace(" ", "T")).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _parse_guru_listings(
    html: str,
    seen_pids: set[str],
    projects: list[dict],
    min_budget: float,
) -> int:
    """
    Parse Guru.com search results HTML (post-React-hydration).

    Guru job links: /d/jobs/id/{numeric_id}/{title-slug}/
    Budget appears as "$X - $Y" or "$X/hr" in card text near the link.
    """
    new_count = 0

    # /d/jobs/id/NUMERICID/title-slug/
    link_pattern = re.compile(
        r'href=["\'](/d/jobs/id/(\d+)/([^"\'?#/]+)/?)["\']'
    )

    for m in link_pattern.finditer(html):
        full_path = m.group(1)
        pid = m.group(2)
        title_slug = m.group(3)

        if pid in seen_pids:
            continue
        seen_pids.add(pid)

        title = " ".join(w.capitalize() for w in title_slug.replace("-", " ").split()) or "Guru Project"

        # Budget context: ~500 chars around the link
        ctx = html[m.start(): m.start() + 500]
        budget_max = _parse_guru_budget(ctx)
        if budget_max is not None and budget_max < min_budget:
            continue

        hourly = bool(re.search(r"\$[\d,.]+\s*/\s*(?:hr|hour)\b", ctx, re.IGNORECASE))
        budget_type = "hourly" if hourly else ("fixed" if budget_max else None)

        projects.append({
            "platform_id": pid,
            "title": title,
            "description": None,
            "skills_required": None,
            "category": None,
            "budget_min": None,
            "budget_max": budget_max,
            "budget_type": budget_type,
            "budget_currency": "USD",
            "client_name": None,
            "client_location": None,
            "client_rating": None,
            "client_reviews_count": None,
            "client_spend_total": None,
            "url": "https://www.guru.com" + full_path,
            "posted_at": None,
            "proposals_count": None,
            "is_verified_client": False,
        })
        new_count += 1

    return new_count


def _parse_guru_budget(context: str) -> Optional[float]:
    """
    Extract budget from Guru listing context.
    Formats: "$500 - $1,000"  "$25/hr"  "$2,500"
    Uses the maximum of any range.
    """
    # Range: $500 - $1,000 → take the upper bound
    range_match = re.search(
        r"\$\s*([\d,]+(?:\.[\d]+)?)\s*[-–]\s*\$\s*([\d,]+(?:\.[\d]+)?)",
        context,
    )
    if range_match:
        return float(range_match.group(2).replace(",", ""))

    # Hourly: $25/hr
    hr_match = re.search(
        r"\$\s*([\d,]+(?:\.[\d]+)?)\s*/\s*(?:hr|hour)\b",
        context, re.IGNORECASE,
    )
    if hr_match:
        return float(hr_match.group(1).replace(",", "")) * 8.0

    # Fixed: $2,500
    fixed = re.search(r"\$\s*([\d,]+(?:\.[\d]+)?)", context)
    if fixed:
        return float(fixed.group(1).replace(",", ""))

    return None


def _parse_upwork_listings(
    html: str,
    seen_pids: set[str],
    projects: list[dict],
    min_budget: float,
) -> int:
    """
    Parse Upwork job search results HTML (post-React-hydration).

    Upwork job links:
      /jobs/~{alphanumeric-id}         (newer format)
      /ab/jobs/search/job-detail/{id}  (older format, still in use)

    Budget text near job tiles: "Fixed-Price - $500" or "Hourly - $25.00-$50.00/hr"
    """
    new_count = 0

    # Match both job URL formats; capture the unique ID
    link_pattern = re.compile(
        r'href=["\']((?:/jobs/~([A-Za-z0-9]+)|/ab/jobs/search/job-detail/([0-9]+))[^"\'?#]*)["\']'
    )

    for m in link_pattern.finditer(html):
        full_path = m.group(1).split("?")[0]  # strip query params
        pid = m.group(2) or m.group(3)
        if not pid:
            continue

        if pid in seen_pids:
            continue
        seen_pids.add(pid)

        # Title: look for nearby heading text (h2, h3, aria-label, data-test=job-title)
        ctx = html[max(0, m.start() - 200): m.start() + 600]
        title = _extract_upwork_title(ctx) or "Upwork Project"

        budget_max, budget_type, is_hourly = _parse_upwork_budget(ctx)
        if budget_max is not None and budget_max < min_budget:
            continue

        projects.append({
            "platform_id": pid,
            "title": title,
            "description": None,
            "skills_required": None,
            "category": None,
            "budget_min": None,
            "budget_max": budget_max,
            "budget_type": budget_type,
            "budget_currency": "USD",
            "client_name": None,
            "client_location": None,
            "client_rating": None,
            "client_reviews_count": None,
            "client_spend_total": None,
            "url": "https://www.upwork.com" + full_path,
            "posted_at": None,
            "proposals_count": None,
            "is_verified_client": False,
        })
        new_count += 1

    return new_count


def _extract_upwork_title(context: str) -> Optional[str]:
    """Extract job title from HTML context near a job link."""
    # data-test="job-tile-title" or aria-label or <h2>/<h3>
    for pattern in [
        r'data-test=["\']job-?tile-?title["\'][^>]*>([^<]{5,120})<',
        r'aria-label=["\']((?:(?!Apply|Save|Like)[^"\'<>]){5,120})["\']',
        r'<h[23][^>]*>\s*<a[^>]*>([^<]{5,120})</a>',
        r'<h[23][^>]*>([^<]{5,120})</h[23]>',
    ]:
        m = re.search(pattern, context, re.IGNORECASE | re.DOTALL)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()
            if len(title) >= 5:
                return title[:200]
    return None


def _parse_upwork_budget(context: str) -> tuple[Optional[float], Optional[str], bool]:
    """
    Parse Upwork budget from card context.
    Returns (budget_max, budget_type, is_hourly).

    Formats:
      "Fixed-Price - $500"        → (500, "fixed", False)
      "Hourly: $25.00-$50.00/hr"  → (50*8, "hourly", True)  ← take upper bound
      "Budget: $1,000"            → (1000, "fixed", False)
      "$5,000+" or "$10K+"        → approximated
    """
    is_hourly = bool(re.search(r"(?:Hourly|/hr|per hour)", context, re.IGNORECASE))
    budget_type = "hourly" if is_hourly else "fixed"

    # Hourly range: $25.00-$50.00/hr → upper bound × 8
    hr_range = re.search(
        r"\$\s*([\d,]+(?:\.[\d]+)?)\s*[-–]\s*\$\s*([\d,]+(?:\.[\d]+)?)\s*/\s*(?:hr|hour)\b",
        context, re.IGNORECASE,
    )
    if hr_range:
        return float(hr_range.group(2).replace(",", "")) * 8.0, "hourly", True

    # Single hourly rate: $35/hr
    hr_single = re.search(
        r"\$\s*([\d,]+(?:\.[\d]+)?)\s*/\s*(?:hr|hour)\b",
        context, re.IGNORECASE,
    )
    if hr_single:
        return float(hr_single.group(1).replace(",", "")) * 8.0, "hourly", True

    # K-suffix: $10K, $2.5K
    k_match = re.search(r"\$\s*([\d]+(?:\.[\d]+)?)[Kk]\b", context)
    if k_match:
        return float(k_match.group(1)) * 1000.0, budget_type, False

    # Fixed range: $500 - $1,000 → upper
    fixed_range = re.search(
        r"\$\s*([\d,]+(?:\.[\d]+)?)\s*[-–]\s*\$\s*([\d,]+(?:\.[\d]+)?)",
        context,
    )
    if fixed_range:
        return float(fixed_range.group(2).replace(",", "")), "fixed", False

    # Single fixed: $500
    fixed_single = re.search(r"\$\s*([\d,]+(?:\.[\d]+)?)", context)
    if fixed_single:
        return float(fixed_single.group(1).replace(",", "")), budget_type, False

    return None, budget_type, is_hourly


# ── Freelancermap slug parser ─────────────────────────────────────────────────

def _parse_fm_slug(slug: str) -> dict:
    """Parse a Freelancermap.de /projekt/{slug} path into structured metadata."""
    path = slug.lstrip("/")
    if path.startswith("projekt/"):
        path = path[len("projekt/"):]

    pid_match = re.search(r"-(\d{5,8})$", path)
    pid: Optional[str] = pid_match.group(1) if pid_match else None
    if pid_match:
        path = path[: pid_match.start()]

    is_remote = bool(re.search(r"\b(?:remote|homeoffice)\b", path, re.IGNORECASE))

    rate_match = re.search(
        r"(\d+)(?:-(\d{2}))?-euro-(?:h|std|stunde)(?:-|$)", path, re.IGNORECASE
    )
    hourly_rate: Optional[float] = None
    if rate_match:
        integer_part = rate_match.group(1)
        decimal_part = rate_match.group(2) or "00"
        hourly_rate = float(f"{integer_part}.{decimal_part}")
        path = path[: rate_match.start()] + path[rate_match.end():]

    _NOISE = [
        r"\b100-prozent-remote\b", r"\bremote\b", r"\bhomeoffice\b",
        r"\bhybrid\b", r"\bm-w-d\b", r"\bm-f-d\b",
        r"\bstart-\d{2}-\d{2}-\d{4}\b", r"\bid-\d+\b", r"\bst-\d{4}\b",
        r"\bnur-nearshore\b", r"\bonly-nearshore\b", r"-id$", r"\bund-\w+$",
    ]
    for pattern in _NOISE:
        path = re.sub(pattern, "", path, flags=re.IGNORECASE)

    path = re.sub(r"-{2,}", "-", path).strip("-")
    words = [w for w in path.split("-") if w]
    title = " ".join(w.capitalize() for w in words) if words else "Freelancermap Project"

    if not pid:
        pid = re.sub(r"[^a-z0-9]", "", path.lower())[:40] or slug.lstrip("/")[-40:]

    budget_max_daily = hourly_rate * 8 if hourly_rate is not None else None

    return {
        "pid": pid,
        "title": title,
        "hourly_rate": hourly_rate,
        "budget_max_daily": budget_max_daily,
        "is_remote": is_remote,
    }


# ── DB upsert ─────────────────────────────────────────────────────────────────

async def _upsert_projects(
    context: AgentContext,
    platform: str,
    raw_projects: list[dict],
) -> tuple[int, int]:
    """Insert new FreelanceProject records, skipping duplicates (ON CONFLICT DO NOTHING)."""
    if not raw_projects:
        return 0, 0

    new_count = 0
    dupe_count = 0

    for p in raw_projects:
        platform_id = p.get("platform_id", "")
        if not platform_id:
            continue

        stmt = (
            pg_insert(FreelanceProject)
            .values(
                id=str(_uuid.uuid4()),
                platform=platform,
                platform_id=platform_id,
                title=(p.get("title") or "Untitled")[:500],
                description=p.get("description") or None,
                skills_required=p.get("skills_required"),
                category=p.get("category"),
                budget_min=p.get("budget_min"),
                budget_max=p.get("budget_max"),
                budget_type=p.get("budget_type"),
                budget_currency=p.get("budget_currency", "EUR"),
                client_name=p.get("client_name"),
                client_location=p.get("client_location"),
                client_rating=p.get("client_rating"),
                client_reviews_count=p.get("client_reviews_count"),
                client_spend_total=p.get("client_spend_total"),
                url=p.get("url"),
                posted_at=p.get("posted_at"),
                proposals_count=p.get("proposals_count"),
                is_verified_client=bool(p.get("is_verified_client", False)),
                status=FreelanceProjectStatus.new,
            )
            .on_conflict_do_nothing(index_elements=["platform", "platform_id"])
        )
        result = await context.db.execute(stmt)
        if result.rowcount > 0:
            new_count += 1
        else:
            dupe_count += 1

    await context.db.commit()
    return new_count, dupe_count


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
