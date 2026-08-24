"""Multi-platform freelance scout — port of FreelanceScoutAgent.

The existing Klaravex `freelance_bid.py` already handles Freelancer.com via
its REST API. This module covers the other 4 platforms the itexperts-berlin
agent supported:

  - Freelancermap.de   HTTP scrape of /projekte search results (no auth needed)
  - PeoplePerHour      Playwright/Chromium (AWS WAF JS challenge)
  - Guru.com           Playwright/Chromium + stealth (Cloudflare + React CSR)
  - Upwork             Playwright/Chromium + stealth (session cookie required)

Each fetcher returns list[dict] in the shape klaravex_freelance_projects
accepts. Caller is expected to upsert with ON CONFLICT DO NOTHING.

Public entry: `scout_all_platforms(keywords=None, min_budget_usd=None)` runs
the four platforms and returns a per-platform breakdown.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote_plus

import aiohttp

from pathlib import Path

from ..db import get_pool

log = logging.getLogger("klaravex.freelance.scout_multi")

_SESSION_ENV = {
    "upwork": "UPWORK_SESSION_COOKIE",
    "guru": "GURU_SESSION_COOKIE",
    "peopleperhour": "PPH_SESSION_COOKIE",
}


def _usable_session_cookie(value: str | None) -> str:
    raw = (value or "").strip()
    if len(raw) < 20 or "[REDACTED" in raw or "=" not in raw:
        return ""
    if "\n" in raw or "\r" in raw:
        return ""
    return raw


def _growth_vault_cookie(platform: str) -> str:
    """Env first, then Klaravex 2.0 session vault file (host-run scouts)."""
    key = _SESSION_ENV.get(platform)
    if not key:
        return ""
    from_env = _usable_session_cookie(os.environ.get(key, ""))
    if from_env:
        return from_env
    root = os.environ.get("GROWTH_SESSIONS_DIR", "").strip() or "/home/anthony/Klaravex2.0/growth/data/sessions"
    try:
        raw = Path(root).expanduser().joinpath(f"{platform}.cookie").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return ""
    return _usable_session_cookie(raw)


async def _fetch_upwork_graphql(keywords: list[str], min_budget_usd: float) -> list[dict] | None:
    """Official GraphQL search when UPWORK_ACCESS_TOKEN is set. None = not configured."""
    token = os.environ.get("UPWORK_ACCESS_TOKEN", "").strip()
    if not token or token.startswith("[REDACTED") or len(token) < 20:
        # Host-run: Growth oauth vault
        root = os.environ.get("GROWTH_SESSIONS_DIR", "").strip() or "/home/anthony/Klaravex2.0/growth/data/sessions"
        try:
            data = json.loads(Path(root).joinpath("upwork.oauth.json").read_text(encoding="utf-8"))
            token = str(data.get("access_token") or "").strip()
        except (OSError, json.JSONDecodeError, TypeError):
            token = ""
    if not token or token.startswith("[REDACTED"):
        return None
    query = """
    query SearchJobs($filter: MarketplaceJobPostingsSearchFilter) {
      marketplaceJobPostingsSearch(
        marketPlaceJobFilter: $filter
        searchType: USER_JOBS_SEARCH
        sortAttributes: [{ field: RECENCY }]
      ) {
        edges {
          node {
            id title description ciphertext createdDateTime
            totalApplicants category
            amount { rawValue }
            hourlyBudgetMax { rawValue }
            skills { name }
          }
        }
      }
    }
    """
    projects: list[dict] = []
    seen: set[str] = set()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
            for keyword in keywords[:5]:
                payload = {
                    "query": query,
                    "variables": {
                        "filter": {
                            "searchExpression_eq": keyword,
                            "pagination_eq": {"after": "0", "first": 10},
                        }
                    },
                }
                async with session.post("https://api.upwork.com/graphql", json=payload, headers=headers) as resp:
                    if resp.status in {401, 403}:
                        log.warning("upwork.graphql_unauthorized — re-authorize on Connections")
                        return []
                    body = await resp.json(content_type=None)
                if not isinstance(body, dict) or body.get("errors"):
                    log.warning("upwork.graphql_error kw=%r", keyword)
                    continue
                edges = ((body.get("data") or {}).get("marketplaceJobPostingsSearch") or {}).get("edges") or []
                for edge in edges:
                    node = (edge or {}).get("node") or {}
                    pid = (node.get("ciphertext") or node.get("id") or "").strip()
                    title = (node.get("title") or "").strip()
                    if not pid or not title or pid in seen:
                        continue
                    amount = node.get("amount") or {}
                    hourly = node.get("hourlyBudgetMax") or {}
                    try:
                        budget = float(hourly.get("rawValue") or 0) * 8.0 or float(amount.get("rawValue") or 0) or None
                    except (TypeError, ValueError):
                        budget = None
                    if budget is not None and budget < min_budget_usd:
                        continue
                    seen.add(pid)
                    cipher = (node.get("ciphertext") or "").strip()
                    skills = [s.get("name") for s in (node.get("skills") or []) if isinstance(s, dict) and s.get("name")]
                    projects.append({
                        "platform_id": pid, "title": title[:200],
                        "description": node.get("description"),
                        "skills_required": ", ".join(skills) if skills else None,
                        "category": node.get("category"),
                        "budget_min": None, "budget_max": budget,
                        "budget_type": "hourly" if hourly.get("rawValue") else "fixed",
                        "budget_currency": "USD",
                        "client_name": None, "client_location": None,
                        "url": f"https://www.upwork.com/jobs/~{cipher}" if cipher else f"https://www.upwork.com/jobs/{pid}",
                        "posted_at": node.get("createdDateTime"),
                        "proposals_count": node.get("totalApplicants"),
                        "is_verified_client": False,
                    })
    except Exception as exc:
        log.warning("upwork.graphql_failed err=%s", exc)
        return []
    log.info("upwork.graphql_ok discovered=%s", len(projects))
    return projects

# ── Default keyword set (Anthony's US MSP / Microsoft / cloud / security stack) ─
DEFAULT_KEYWORDS = [
    "Microsoft 365", "M365", "Azure", "Intune", "Entra ID",
    "Office 365", "SharePoint", "Teams", "Active Directory",
    "PowerShell", "Windows Server", "AWS", "IT support",
    "IT consulting", "cloud migration", "endpoint security",
    "HIPAA", "SOC 2", "managed IT",
]

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)
_PW_NAVIGATION_TIMEOUT = 30_000
_PW_WAIT_TIMEOUT = 15_000

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_FM_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ── DB upsert ────────────────────────────────────────────────────────────────

async def _upsert_projects(platform: str, projects: list[dict]) -> tuple[int, int]:
    """Insert new rows; skip rows that already exist on (platform, platform_id).

    Returns (inserted, skipped_duplicates).
    """
    if not projects:
        return 0, 0
    pool = await get_pool()
    inserted = 0
    skipped = 0
    async with pool.acquire() as conn:
        for p in projects:
            pid = p.get("platform_id") or ""
            if not pid:
                continue
            row_id = await conn.fetchval(
                """
                INSERT INTO klaravex_freelance_projects
                    (platform, platform_id, title, description, skills_required,
                     category, budget_min, budget_max, budget_type, budget_currency,
                     client_name, client_location, client_rating,
                     client_reviews_count, client_spend_total,
                     url, posted_at, proposals_count, is_verified_client)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
                ON CONFLICT (platform, platform_id) DO NOTHING
                RETURNING id::text
                """,
                platform, pid,
                (p.get("title") or "Untitled")[:500],
                p.get("description"),
                p.get("skills_required") if isinstance(p.get("skills_required"), str)
                    else json.dumps(p.get("skills_required") or []),
                p.get("category"),
                p.get("budget_min"), p.get("budget_max"),
                p.get("budget_type") or "fixed",
                p.get("budget_currency") or "USD",
                p.get("client_name"), p.get("client_location"),
                p.get("client_rating"), p.get("client_reviews_count"),
                p.get("client_spend_total"),
                p.get("url"), p.get("posted_at"),
                p.get("proposals_count"),
                bool(p.get("is_verified_client", False)),
            )
            if row_id:
                inserted += 1
            else:
                skipped += 1
    return inserted, skipped


# ── Freelancermap.de — server-side HTML scrape ────────────────────────────────

async def fetch_freelancermap(keywords: list[str], min_budget_usd: float) -> list[dict]:
    """Fetch DACH IT projects from freelancermap.de search results.

    Server-side rendered — no bot challenge from datacenter IPs. We extract
    project slugs from search-result HTML and decode title/budget/remote
    metadata from the slug itself.
    """
    projects: list[dict] = []
    seen_pids: set[str] = set()

    async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT, headers=_FM_HEADERS) as session:
        for keyword in keywords[:6]:
            url = (
                f"https://www.freelancermap.de/projekte"
                f"?query={quote_plus(keyword)}&country%5B%5D=1"
            )
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        log.warning("fm.scout http_error status=%d kw=%r", resp.status, keyword)
                        continue
                    html = await resp.text(encoding="utf-8", errors="replace")
            except Exception as exc:
                log.warning("fm.scout fetch_error kw=%r err=%s", keyword, exc)
                continue

            links = re.findall(
                r'href=["\'](?:https://www\.freelancermap\.de)?(/projekt/[^"\'?#]+)["\']',
                html,
            )
            for slug in links:
                meta = _parse_fm_slug(slug)
                pid = meta["pid"]
                if not pid or pid in seen_pids:
                    continue
                seen_pids.add(pid)

                budget_max = meta["budget_max_daily"]
                # min_budget_usd is approximate — FM is EUR. Treat as same number
                # (no FX) since both are signal not contract.
                if budget_max is not None and budget_max < min_budget_usd:
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
                    "url": "https://www.freelancermap.de" + slug,
                    "posted_at": None,
                    "proposals_count": None,
                    "is_verified_client": False,
                })
    return projects


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

    _noise = [
        r"\b100-prozent-remote\b", r"\bremote\b", r"\bhomeoffice\b",
        r"\bhybrid\b", r"\bm-w-d\b", r"\bm-f-d\b",
        r"\bstart-\d{2}-\d{2}-\d{4}\b", r"\bid-\d+\b", r"\bst-\d{4}\b",
        r"\bnur-nearshore\b", r"\bonly-nearshore\b", r"-id$", r"\bund-\w+$",
    ]
    for pat in _noise:
        path = re.sub(pat, "", path, flags=re.IGNORECASE)
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


# ── Playwright helpers ────────────────────────────────────────────────────────

def _make_pw_browser_args() -> list[str]:
    return [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--window-size=1920,1080",
    ]


async def _inject_cookie_string(ctx: Any, cookie_domain: str, cookie_str: str) -> None:
    """Parse `name=value; name=value` and inject into a Playwright context."""
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
                "name": name, "value": value, "domain": cookie_domain,
                "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax",
            })
    if cookies:
        await ctx.add_cookies(cookies)


# ── PeoplePerHour scout ───────────────────────────────────────────────────────

async def fetch_peopleperhour(keywords: list[str], min_budget_usd: float) -> list[dict]:
    """PeoplePerHour: AWS WAF JS challenge → needs real Chromium.

    PPH embeds job data as Redux store JSON in the page HTML. Search AJAX is
    WAF-blocked from datacenter IPs, so we load IT-relevant category pages
    and let downstream scoring handle relevance.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.warning("pph.playwright_unavailable — skipping")
        return []

    projects: list[dict] = []
    seen_pids: set[str] = set()

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=_make_pw_browser_args())
            ctx = await browser.new_context(
                user_agent=_UA, locale="en-GB",
                viewport={"width": 1920, "height": 1080},
                extra_http_headers={"Accept-Language": "en-GB,en;q=0.9"},
            )
            page = await ctx.new_page()
            await page.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2}",
                             lambda r: asyncio.create_task(r.abort()))

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
                        pass
                    html = await page.content()
                    _parse_pph_listings(html, seen_pids, projects, min_budget_usd)
                except Exception as exc:
                    log.warning("pph.page_error url=%s err=%s", url, exc)
            await browser.close()
    except Exception as exc:
        log.error("pph.playwright_error err=%s", exc)
    return projects


def _parse_pph_listings(html: str, seen_pids: set[str], projects: list[dict], min_budget: float) -> int:
    attrs_pattern = re.compile(r'"type"\s*:\s*"projects"\s*,\s*"attributes"\s*:\s*(\{)')
    new_count = 0
    for m in attrs_pattern.finditer(html):
        start = m.start(1)
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
            a = json.loads(html[start: i + 1])
        except Exception:
            continue
        pid = str(a.get("proj_id", ""))
        if not pid or pid in seen_pids:
            continue
        title = a.get("title") or ""
        description = a.get("proj_desc") or ""

        raw_budget = a.get("budget_converted") or a.get("budget")
        try:
            budget_val = float(raw_budget) if raw_budget is not None else 0.0
        except (TypeError, ValueError):
            budget_val = 0.0
        project_type = str(a.get("project_type", "")).lower()
        is_hourly = "hour" in project_type
        effective = budget_val * 8.0 if is_hourly else budget_val
        if min_budget > 0 and effective < min_budget:
            continue
        seen_pids.add(pid)

        raw_url = a.get("url", "")
        try:
            url = raw_url.encode("utf-8").decode("unicode_escape") if "\\u" in raw_url else raw_url
        except Exception:
            url = raw_url

        client = a.get("client") or {}
        client_name = (
            f"{client.get('firstname', '')} {client.get('lastname', '')}".strip()
            or client.get("username") or None
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
            "url": url,
            "posted_at": _parse_pph_posted_dt(a.get("posted_dt")),
            "proposals_count": a.get("proposalCount"),
            "is_verified_client": False,
        })
        new_count += 1
    return new_count


def _parse_pph_posted_dt(value) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace(" ", "T")).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


# ── Guru.com scout ────────────────────────────────────────────────────────────

async def fetch_guru(keywords: list[str], min_budget_usd: float) -> list[dict]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.warning("guru.playwright_unavailable — skipping")
        return []
    try:
        from playwright_stealth import stealth_async as _stealth
    except ImportError:
        _stealth = None

    projects: list[dict] = []
    seen_pids: set[str] = set()

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=_make_pw_browser_args())
            ctx = await browser.new_context(
                user_agent=_UA, locale="en-US",
                viewport={"width": 1920, "height": 1080},
            )
            page = await ctx.new_page()
            if _stealth:
                await _stealth(page)
            await page.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2}",
                             lambda r: asyncio.create_task(r.abort()))

            for keyword in keywords[:6]:
                slug = keyword.strip().lower().replace(" ", "-")
                url = f"https://www.guru.com/d/jobs/skill/{quote_plus(slug)}/"
                try:
                    await page.goto(url, timeout=_PW_NAVIGATION_TIMEOUT, wait_until="networkidle")
                    try:
                        await page.wait_for_selector("a[href*='/d/jobs/id/']", timeout=_PW_WAIT_TIMEOUT)
                    except Exception:
                        log.warning("guru.no_listings kw=%r url=%s", keyword, page.url)
                        continue
                    html = await page.content()
                    _parse_guru_listings(html, seen_pids, projects, min_budget_usd)
                except Exception as exc:
                    log.warning("guru.page_error kw=%r err=%s", keyword, exc)
            await browser.close()
    except Exception as exc:
        log.error("guru.playwright_error err=%s", exc)
    return projects


def _parse_guru_listings(html: str, seen_pids: set[str], projects: list[dict], min_budget: float) -> int:
    new_count = 0
    link_pattern = re.compile(r'href=["\'](/d/jobs/id/(\d+)/([^"\'?#/]+)/?)["\']')
    for m in link_pattern.finditer(html):
        full_path = m.group(1)
        pid = m.group(2)
        title_slug = m.group(3)
        if pid in seen_pids:
            continue
        seen_pids.add(pid)

        title = " ".join(w.capitalize() for w in title_slug.replace("-", " ").split()) or "Guru Project"
        ctx = html[m.start(): m.start() + 500]
        budget_max = _parse_guru_budget(ctx)
        if budget_max is not None and budget_max < min_budget:
            continue
        hourly = bool(re.search(r"\$[\d,.]+\s*/\s*(?:hr|hour)\b", ctx, re.IGNORECASE))
        budget_type = "hourly" if hourly else ("fixed" if budget_max else None)
        projects.append({
            "platform_id": pid, "title": title, "description": None,
            "skills_required": None, "category": None,
            "budget_min": None, "budget_max": budget_max,
            "budget_type": budget_type, "budget_currency": "USD",
            "client_name": None, "client_location": None,
            "url": "https://www.guru.com" + full_path,
            "posted_at": None, "proposals_count": None, "is_verified_client": False,
        })
        new_count += 1
    return new_count


def _parse_guru_budget(ctx: str) -> Optional[float]:
    range_match = re.search(
        r"\$\s*([\d,]+(?:\.[\d]+)?)\s*[-–]\s*\$\s*([\d,]+(?:\.[\d]+)?)", ctx,
    )
    if range_match:
        return float(range_match.group(2).replace(",", ""))
    hr_match = re.search(r"\$\s*([\d,]+(?:\.[\d]+)?)\s*/\s*(?:hr|hour)\b", ctx, re.IGNORECASE)
    if hr_match:
        return float(hr_match.group(1).replace(",", "")) * 8.0
    fixed = re.search(r"\$\s*([\d,]+(?:\.[\d]+)?)", ctx)
    if fixed:
        return float(fixed.group(1).replace(",", ""))
    return None


# ── Upwork scout ──────────────────────────────────────────────────────────────

async def fetch_upwork(keywords: list[str], min_budget_usd: float) -> list[dict]:
    """Upwork: official GraphQL when OAuth token is present; else session-cookie Playwright."""
    graphql = await _fetch_upwork_graphql(keywords, min_budget_usd)
    if graphql is not None:
        return graphql
    session_cookie = _growth_vault_cookie("upwork")
    if not session_cookie:
        log.warning("upwork.no_session_cookie — skipping. Set UPWORK_SESSION_COOKIE or save via Connections.")
        return []
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.warning("upwork.playwright_unavailable — skipping")
        return []
    try:
        from playwright_stealth import stealth_async as _stealth
    except ImportError:
        _stealth = None

    projects: list[dict] = []
    seen_pids: set[str] = set()

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=_make_pw_browser_args())
            ctx = await browser.new_context(
                user_agent=_UA, locale="en-US",
                viewport={"width": 1920, "height": 1080},
            )
            await _inject_cookie_string(ctx, ".upwork.com", session_cookie)
            page = await ctx.new_page()
            if _stealth:
                await _stealth(page)
            await page.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2}",
                             lambda r: asyncio.create_task(r.abort()))

            for keyword in keywords[:5]:
                url = (
                    f"https://www.upwork.com/nx/jobs/search/"
                    f"?q={quote_plus(keyword)}&sort=recency"
                )
                try:
                    await page.goto(url, timeout=_PW_NAVIGATION_TIMEOUT, wait_until="networkidle")
                    if "login" in page.url or "signup" in page.url:
                        log.warning("upwork.session_expired — UPWORK_SESSION_COOKIE needs refresh")
                        break
                    try:
                        await page.wait_for_selector(
                            "[data-test='job-tile-list'] article, section[data-test='JobTile']",
                            timeout=_PW_WAIT_TIMEOUT,
                        )
                    except Exception:
                        try:
                            await page.wait_for_selector(
                                "article.job-tile, div[data-test='UpCJobTile']", timeout=5_000,
                            )
                        except Exception:
                            log.warning("upwork.no_listings kw=%r url=%s", keyword, page.url)
                            continue
                    html = await page.content()
                    _parse_upwork_listings(html, seen_pids, projects, min_budget_usd)
                except Exception as exc:
                    log.warning("upwork.page_error kw=%r err=%s", keyword, exc)
            await browser.close()
    except Exception as exc:
        log.error("upwork.playwright_error err=%s", exc)
    return projects


def _parse_upwork_listings(html: str, seen_pids: set[str], projects: list[dict], min_budget: float) -> int:
    new_count = 0
    link_pattern = re.compile(
        r'href=["\']((?:/jobs/~([A-Za-z0-9]+)|/ab/jobs/search/job-detail/([0-9]+))[^"\'?#]*)["\']'
    )
    for m in link_pattern.finditer(html):
        full_path = m.group(1).split("?")[0]
        pid = m.group(2) or m.group(3)
        if not pid or pid in seen_pids:
            continue
        seen_pids.add(pid)
        ctx = html[max(0, m.start() - 200): m.start() + 600]
        title = _extract_upwork_title(ctx) or "Upwork Project"
        budget_max, budget_type, _is_hourly = _parse_upwork_budget(ctx)
        if budget_max is not None and budget_max < min_budget:
            continue
        projects.append({
            "platform_id": pid, "title": title, "description": None,
            "skills_required": None, "category": None,
            "budget_min": None, "budget_max": budget_max,
            "budget_type": budget_type, "budget_currency": "USD",
            "client_name": None, "client_location": None,
            "url": "https://www.upwork.com" + full_path,
            "posted_at": None, "proposals_count": None, "is_verified_client": False,
        })
        new_count += 1
    return new_count


def _extract_upwork_title(context: str) -> Optional[str]:
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


def _parse_upwork_budget(ctx: str) -> tuple[Optional[float], Optional[str], bool]:
    is_hourly = bool(re.search(r"(?:Hourly|/hr|per hour)", ctx, re.IGNORECASE))
    budget_type = "hourly" if is_hourly else "fixed"
    hr_range = re.search(
        r"\$\s*([\d,]+(?:\.[\d]+)?)\s*[-–]\s*\$\s*([\d,]+(?:\.[\d]+)?)\s*/\s*(?:hr|hour)\b",
        ctx, re.IGNORECASE,
    )
    if hr_range:
        return float(hr_range.group(2).replace(",", "")) * 8.0, "hourly", True
    hr_single = re.search(r"\$\s*([\d,]+(?:\.[\d]+)?)\s*/\s*(?:hr|hour)\b", ctx, re.IGNORECASE)
    if hr_single:
        return float(hr_single.group(1).replace(",", "")) * 8.0, "hourly", True
    k_match = re.search(r"\$\s*([\d]+(?:\.[\d]+)?)[Kk]\b", ctx)
    if k_match:
        return float(k_match.group(1)) * 1000.0, budget_type, False
    fixed_range = re.search(
        r"\$\s*([\d,]+(?:\.[\d]+)?)\s*[-–]\s*\$\s*([\d,]+(?:\.[\d]+)?)", ctx,
    )
    if fixed_range:
        return float(fixed_range.group(2).replace(",", "")), "fixed", False
    fixed_single = re.search(r"\$\s*([\d,]+(?:\.[\d]+)?)", ctx)
    if fixed_single:
        return float(fixed_single.group(1).replace(",", "")), budget_type, False
    return None, budget_type, is_hourly


# ── Driver ────────────────────────────────────────────────────────────────────

async def scout_all_platforms(
    keywords: Optional[list[str]] = None,
    min_budget_usd: Optional[float] = None,
    platforms: Optional[list[str]] = None,
) -> dict:
    """Run all enabled scrape platforms. Returns per-platform stats.

    platforms — optional subset of {freelancermap, peopleperhour, guru, upwork}.
    Default: run all four. Freelancer.com is intentionally NOT here; that one
    lives in the existing freelance_bid.py router.
    """
    kws = keywords or DEFAULT_KEYWORDS
    min_budget = float(min_budget_usd if min_budget_usd is not None
                       else os.environ.get("FREELANCE_MIN_BUDGET_USD", "300"))
    selected = set(platforms or ["freelancermap", "peopleperhour", "guru", "upwork"])

    totals: dict[str, dict] = {}

    if "freelancermap" in selected:
        try:
            projects = await fetch_freelancermap(kws, min_budget)
            ins, dup = await _upsert_projects("freelancermap", projects)
            totals["freelancermap"] = {"discovered": ins, "skipped": dup}
        except Exception as exc:
            log.error("scout.freelancermap_failed err=%s", exc)
            totals["freelancermap"] = {"discovered": 0, "skipped": 0, "error": str(exc)}

    if "peopleperhour" in selected:
        try:
            projects = await fetch_peopleperhour(kws, min_budget)
            ins, dup = await _upsert_projects("peopleperhour", projects)
            totals["peopleperhour"] = {"discovered": ins, "skipped": dup}
        except Exception as exc:
            log.error("scout.pph_failed err=%s", exc)
            totals["peopleperhour"] = {"discovered": 0, "skipped": 0, "error": str(exc)}

    if "guru" in selected:
        try:
            projects = await fetch_guru(kws, min_budget)
            ins, dup = await _upsert_projects("guru", projects)
            totals["guru"] = {"discovered": ins, "skipped": dup}
        except Exception as exc:
            log.error("scout.guru_failed err=%s", exc)
            totals["guru"] = {"discovered": 0, "skipped": 0, "error": str(exc)}

    if "upwork" in selected:
        try:
            projects = await fetch_upwork(kws, min_budget)
            ins, dup = await _upsert_projects("upwork", projects)
            totals["upwork"] = {"discovered": ins, "skipped": dup}
        except Exception as exc:
            log.error("scout.upwork_failed err=%s", exc)
            totals["upwork"] = {"discovered": 0, "skipped": 0, "error": str(exc)}

    total_new = sum(t.get("discovered", 0) for t in totals.values())
    total_dupes = sum(t.get("skipped", 0) for t in totals.values())
    return {
        "discovered": total_new,
        "skipped_duplicate": total_dupes,
        "platforms": totals,
    }
