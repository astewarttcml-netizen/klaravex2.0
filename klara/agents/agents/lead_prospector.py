"""
app/agents/lead_prospector.py
──────────────────────────────
Lead Prospector Agent (PROSP).

Three-phase enrichment pipeline:

Phase 1 — Apollo people search (any tier)
  Queries /v1/mixed_people/api_search for ICP-matched contacts in DACH.
  Free tier returns first-name + title + company-name stubs (no email/domain).
  Paid tier returns full contact data; the pipeline degrades gracefully either way.

Phase 2 — Domain resolution (when Apollo returns no domain)
  2a. Hunter.io /name-to-domain  — works well for larger/international companies
  2b. Heuristic domain guesser   — strips GmbH/AG/etc., lowercases, tries .de/.com
      Each candidate is verified with HTTP HEAD before being accepted.

Phase 3 — Hunter.io domain-search (when domain found in Phase 2)
  Finds email contacts at the resolved domain; picks best IT-title match.

Deduplication: ProspectedLead.domain + inbound Lead.email-domain.
Daily limit: PROSPECTING_DAILY_LIMIT.

Env vars:
  APOLLO_API_KEY      — any Apollo key; paid tier skips phases 2-3
  HUNTER_API_KEY      — free tier: 75 credits; paid: $34+/month for 500+
  APOLLO_LOCATIONS    — comma-separated DACH locations
  APOLLO_TITLES       — ICP titles
  APOLLO_MIN/MAX_EMPLOYEES — org size filter
  PROSPECTING_DAILY_LIMIT  — hard cap per UTC calendar day
"""
from __future__ import annotations

import asyncio
import re
import secrets
from datetime import date
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import httpx
import structlog
from sqlalchemy import func, select

from app.agents.base import AgentContext
from app.models.lead import Lead
from app.models.prospected_lead import ProspectedLead, ProspectedLeadStatus

logger = structlog.get_logger(__name__)

APOLLO_SEARCH_URL       = "https://api.apollo.io/v1/mixed_people/api_search"
APOLLO_PEOPLE_MATCH_URL = "https://api.apollo.io/v1/people/match"
HUNTER_NAME_TO_DOMAIN   = "https://api.hunter.io/v2/name-to-domain"
HUNTER_EMAIL_FINDER     = "https://api.hunter.io/v2/email-finder"

# German/Austrian/Swiss legal-entity suffixes to strip before domain guessing
_LEGAL_SUFFIXES = re.compile(
    r"\b("
    r"gmbh\s*&\s*co\.?\s*kg|gmbh\s*&\s*co|gmbh\s*co\s*kg|"
    r"ag\s*&\s*co\.?\s*kg|"
    r"gmbh|ag|kg|ohg|gbr|ug|ev|se|ek|mbh|"
    r"healthcare|group|holding|digital|solutions|technologies|"
    r"services|consulting|systems|software|management|international|"
    r"das science center|das|science center"
    r")\b",
    re.IGNORECASE,
)

# German umlaut → ASCII mapping for domain guessing
_UMLAUT_MAP = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "ae", "Ö": "oe", "Ü": "ue",
    "ß": "ss", "–": "-", "—": "-",
})

class LeadProspectorAgent:
    name = "lead_prospector"

    async def run(self, context: AgentContext) -> List[ProspectedLead]:
        settings = context.settings

        if not settings.apollo_configured:
            logger.warning("lead_prospector.no_apollo_key")
            return []

        hunter_key: str = getattr(settings, "hunter_api_key", "") or ""
        hunter_enabled = bool(hunter_key and not _is_placeholder(hunter_key))
        if not hunter_enabled:
            logger.info("lead_prospector.hunter_disabled",
                        detail="HUNTER_API_KEY not set; domain-less stubs will be skipped")

        # ── Daily limit ───────────────────────────────────────────────────────
        today_count = await self._count_today(context)
        remaining   = settings.prospecting_daily_limit - today_count
        if remaining <= 0:
            logger.info("lead_prospector.daily_limit_reached",
                        limit=settings.prospecting_daily_limit, today=today_count)
            return []

        logger.info("lead_prospector.starting", remaining=remaining,
                    hunter=hunter_enabled, locations=settings.apollo_locations_list)

        # ── Phase 1: Apollo ───────────────────────────────────────────────────
        people = await self._query_apollo(context, settings,
                                          per_page=min(remaining * 4, 50))
        if people is None:
            return []
        if not people:
            logger.info("lead_prospector.apollo_empty")
            return []

        stubs = sum(1 for p in people if not _extract_domain(p))
        logger.info("lead_prospector.apollo_stubs", total=len(people),
                    stubs=stubs, hunter_will_enrich=hunter_enabled and stubs > 0)

        # ── Phase 2+3: enrich + persist ───────────────────────────────────────
        new_prospects: List[ProspectedLead] = []
        async with httpx.AsyncClient(timeout=15.0) as http:
            for person in people:
                if len(new_prospects) >= remaining:
                    break

                domain = _extract_domain(person)
                email: Optional[str] = (person.get("email") or "").strip() or None

                if not domain and hunter_enabled:
                    company = ((person.get("organization") or {}).get("name") or "").strip()
                    if company:
                        domain, email = await self._enrich(
                            http, company,
                            person.get("first_name") or "",
                            person.get("last_name") or "",
                            person.get("title") or "",
                            hunter_key,
                        )

                # ── Apollo people-match unlock ────────────────────────────────
                # mixed_people/api_search returns truncated records on lower
                # tiers: first_name only, no email. Apollo provides the rest
                # via /people/match — it accepts the search-result id plus
                # name + domain hints and returns the enriched person with
                # email + last_name (if Apollo has them). Costs 1 Apollo
                # credit per call. We only call when:
                #   1. Apollo gave us a person but no email, AND
                #   2. we have a domain (so the unlock has something to anchor on)
                # If unlock fails we fall through to Hunter and ultimately
                # may drop the prospect — same behaviour as before.
                if domain and not email:
                    unlocked = await self._apollo_people_match(
                        http, person, domain, settings.apollo_api_key
                    )
                    if unlocked:
                        # Merge unlocked fields back into `person` so
                        # _build_record can use the richer data.
                        for k in ("email", "first_name", "last_name",
                                  "title", "linkedin_url", "city", "country"):
                            v = unlocked.get(k)
                            if v and not person.get(k):
                                person[k] = v
                        email = (person.get("email") or "").strip() or None

                # ── Hunter email-finder fallback ──────────────────────────────
                # If Apollo still didn't give us an email but we have both
                # first + last name + domain, ask Hunter for the specific
                # person's email. Skip when we can't anchor on a full name.
                if domain and not email and hunter_enabled:
                    first = (person.get("first_name") or "").strip()
                    last  = (person.get("last_name")  or "").strip()
                    if first and last:
                        email = await self._hunter_email_finder(
                            http, domain, first, last, hunter_key
                        )

                if not domain:
                    logger.debug("lead_prospector.no_domain",
                                 name=f"{person.get('first_name')} "
                                      f"{person.get('last_name')}",
                                 company=(person.get("organization") or {}).get("name"))
                    continue

                if await self._domain_exists(context, domain):
                    logger.debug("lead_prospector.duplicate", domain=domain)
                    continue

                prospect = _build_record(person, domain, email)
                context.db.add(prospect)
                await context.db.flush()
                new_prospects.append(prospect)
                logger.info("lead_prospector.created", domain=domain,
                            company=prospect.company_name,
                            contact=f"{prospect.contact_first_name} "
                                    f"{prospect.contact_last_name}".strip(),
                            email_found=bool(email))

        logger.info("lead_prospector.done", new_prospects=len(new_prospects),
                    today_total=today_count + len(new_prospects))
        return new_prospects

    # ── Enrichment orchestrator ───────────────────────────────────────────────

    async def _enrich(
        self,
        http: httpx.AsyncClient,
        company: str,
        first_name: str,
        last_name: str,
        title: str,
        hunter_key: str,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Try paths to get (domain, email) for THE SPECIFIC PERSON Apollo named.

        Prior implementation used Hunter `domain-search` as the email fallback,
        which returns the best IT-titled person at the company — not necessarily
        the same person Apollo identified. That caused 14/74 audit-confirmed
        wrong-name outreach drafts on 2026-05-29: Apollo person name was stitched
        onto a different employee's email at the same domain.

        Current strategy:
          1. Hunter name-to-domain  → works for larger/international companies
          2. Heuristic domain guess → derives candidates from company name, verifies via HEAD
          3. Hunter email-finder    → finds the SAME PERSON's email at the resolved domain.
                                      Returns None if Hunter can't confirm the specific
                                      first/last → email mapping. We DROP the prospect
                                      rather than fall back to a different-person email.
        """
        # Path 1: Hunter name-to-domain
        domain = await self._hunter_name_to_domain(http, company, hunter_key)

        # Path 2: heuristic guess + HTTP verification
        if not domain:
            domain = await self._guess_domain(http, company)

        if not domain:
            return None, None

        # Path 3: Hunter email-finder — strictly per-person, never domain-fallback
        email: Optional[str] = None
        if first_name and last_name:
            email = await self._hunter_email_finder(
                http, domain, first_name, last_name, hunter_key
            )
        else:
            logger.debug(
                "lead_prospector.email_finder_skipped_no_name",
                domain=domain, has_first=bool(first_name), has_last=bool(last_name),
            )

        return domain, email

    # ── Hunter helpers ────────────────────────────────────────────────────────

    async def _hunter_name_to_domain(
        self, http: httpx.AsyncClient, company: str, hunter_key: str
    ) -> Optional[str]:
        try:
            r = await http.get(
                HUNTER_NAME_TO_DOMAIN,
                params={"company": company},
                headers={"Authorization": f"Bearer {hunter_key}"},
            )
            if r.status_code == 200:
                domain = (r.json().get("data", {}).get("domain") or "").strip().lower()
                if domain:
                    logger.debug("lead_prospector.hunter_n2d", company=company, domain=domain)
                    return domain
            elif r.status_code == 429:
                logger.warning("lead_prospector.hunter_rate_limit")
        except Exception as exc:
            logger.warning("lead_prospector.hunter_n2d_exc", error=str(exc))
        return None

    async def _apollo_people_match(
        self,
        http: httpx.AsyncClient,
        person: dict,
        domain: str,
        apollo_key: str,
    ) -> Optional[dict]:
        """Unlock a truncated Apollo person via `/v1/people/match`.

        Apollo's `mixed_people/api_search` returns truncated records for
        unpaid people (first_name only, no email). `/people/match` is the
        documented way to spend a credit and retrieve the full record
        including email + last_name + verified title.

        We pass first_name + domain (and last_name when present) as match
        keys. Apollo also accepts the search-result id but the public
        endpoint prefers name+org matching.

        Returns the unlocked `person` dict on success, or None on:
          - HTTP error (logged)
          - Apollo returns no match
          - Credit exhausted
        """
        if not apollo_key or _is_placeholder(apollo_key):
            return None

        first_name = (person.get("first_name") or "").strip()
        last_name  = (person.get("last_name")  or "").strip()
        if not first_name:
            return None

        payload = {
            "first_name": first_name,
            "domain": domain,
            "reveal_personal_emails": True,
        }
        if last_name:
            payload["last_name"] = last_name
        # The Apollo search result id is the strongest disambiguation signal —
        # without it, /people/match returns a generic "Felix at zwei.de" record
        # with no last_name or email. With it, Apollo unlocks the verified
        # record (verified email + full name) in one call. Confirmed live
        # 2026-05-29 against three production prospect ids.
        apollo_id = (person.get("id") or "").strip()
        if apollo_id:
            payload["id"] = apollo_id

        try:
            r = await http.post(
                APOLLO_PEOPLE_MATCH_URL,
                headers={
                    "Cache-Control": "no-cache",
                    "Content-Type":  "application/json",
                    "X-Api-Key":     apollo_key,
                },
                json=payload,
            )
            if r.status_code == 422:
                logger.debug(
                    "lead_prospector.apollo_match_no_match",
                    domain=domain, first_name=first_name,
                )
                return None
            if r.status_code != 200:
                logger.warning(
                    "lead_prospector.apollo_match_http_error",
                    status=r.status_code, domain=domain,
                    body=r.text[:200],
                )
                return None
            body = r.json()
            matched = body.get("person") or body.get("matched_person") or None
            if not matched:
                logger.debug(
                    "lead_prospector.apollo_match_empty",
                    domain=domain, first_name=first_name,
                )
                return None
            logger.info(
                "lead_prospector.apollo_match_unlocked",
                domain=domain, first_name=first_name,
                got_email=bool(matched.get("email")),
                got_last=bool(matched.get("last_name")),
            )
            return matched
        except Exception as exc:
            logger.warning(
                "lead_prospector.apollo_match_exc",
                domain=domain, first_name=first_name, error=str(exc),
            )
            return None

    async def _hunter_email_finder(
        self,
        http: httpx.AsyncClient,
        domain: str,
        first_name: str,
        last_name: str,
        hunter_key: str,
    ) -> Optional[str]:
        """
        Look up the email address of a SPECIFIC person at a given domain via
        Hunter's email-finder endpoint. Unlike `_hunter_domain_search`, this
        does not fall back to "the best person at the domain" — it returns
        only the email Hunter has indexed for (first_name + last_name @ domain),
        or None.

        Endpoint: GET /v2/email-finder?domain=...&first_name=...&last_name=...
        Docs:     https://hunter.io/api-documentation/v2#email-finder
        """
        try:
            r = await http.get(
                HUNTER_EMAIL_FINDER,
                params={
                    "domain": domain,
                    "first_name": first_name,
                    "last_name": last_name,
                },
                headers={"Authorization": f"Bearer {hunter_key}"},
            )
            if r.status_code == 429:
                logger.warning("lead_prospector.hunter_rate_limit",
                               endpoint="email-finder", domain=domain)
                return None
            if r.status_code != 200:
                logger.debug(
                    "lead_prospector.hunter_email_finder_no_match",
                    domain=domain, first=first_name, last=last_name,
                    status=r.status_code,
                )
                return None
            data = r.json().get("data") or {}
            email = (data.get("email") or "").strip() or None
            if not email:
                return None
            # Sanity: confirm the local-part isn't obviously someone else's.
            # Hunter returns score + verification — accept only if score >= 50.
            score = data.get("score") or 0
            if score < 50:
                logger.debug(
                    "lead_prospector.hunter_email_finder_low_score",
                    domain=domain, email=email, score=score,
                )
                return None
            logger.debug(
                "lead_prospector.hunter_email_finder_hit",
                domain=domain, email=email, score=score,
            )
            return email
        except Exception as exc:
            logger.warning(
                "lead_prospector.hunter_email_finder_exc",
                domain=domain, first=first_name, last=last_name, error=str(exc),
            )
            return None

    # ── Heuristic domain guesser ──────────────────────────────────────────────

    @staticmethod
    async def _guess_domain(
        http: httpx.AsyncClient, company: str
    ) -> Optional[str]:
        """
        Derives domain candidates from the company name, verifies via HTTP HEAD.

        Strategy:
          1. Normalize German umlauts (ö→oe, ü→ue, ä→ae, ß→ss)
          2. Strip legal suffixes (GmbH, AG, GmbH & Co. KG, …)
          3. Build slug variants: full, no-hyphens, first-2-words, first-word
          4. Try each with .de / .com — accept first with HTTP 2xx/3xx
        """
        # Umlaut normalization + legal-suffix stripping
        s = company.translate(_UMLAUT_MAP)
        s = _LEGAL_SUFFIXES.sub("", s)
        s = re.sub(r"[^\w\s-]", "", s)
        s = re.sub(r"\s+", "-", s.strip())
        s = re.sub(r"-+", "-", s).strip("-").lower()

        if not s or len(s) < 3:
            return None

        parts       = s.split("-")
        slug_full   = s
        slug_plain  = s.replace("-", "")
        slug_two    = "-".join(parts[:2]) if len(parts) > 1 else None
        slug_one    = parts[0]

        candidates: list[str] = []
        for v in dict.fromkeys(filter(None, [slug_full, slug_plain, slug_two, slug_one])):
            if len(v) >= 3:
                candidates += [f"{v}.de", f"{v}.com"]

        for candidate in candidates:
            try:
                r = await http.head(
                    f"https://{candidate}",
                    timeout=5.0,
                    follow_redirects=True,
                )
                if r.status_code < 400:
                    logger.debug("lead_prospector.domain_guess_hit",
                                 company=company, domain=candidate,
                                 status=r.status_code)
                    return candidate
            except Exception:
                pass

        logger.debug("lead_prospector.domain_guess_miss", company=company)
        return None

    # ── DB helpers ────────────────────────────────────────────────────────────

    async def _count_today(self, context: AgentContext) -> int:
        result = await context.db.execute(
            select(func.count()).where(
                func.date(ProspectedLead.created_at) == date.today()
            )
        )
        return result.scalar() or 0

    async def _domain_exists(self, context: AgentContext, domain: str) -> bool:
        if (await context.db.execute(
            select(ProspectedLead.id).where(
                ProspectedLead.domain == domain).limit(1)
        )).scalar_one_or_none():
            return True
        return bool((await context.db.execute(
            select(Lead.id).where(
                Lead.email.like(f"%@{domain}")).limit(1)
        )).scalar_one_or_none())

    async def _next_page(self, context: AgentContext, per_page: int) -> int:
        total = (await context.db.execute(
            select(func.count()).select_from(ProspectedLead)
        )).scalar() or 0
        page = 1 if total == 0 else max(2, (total // per_page) + 1)
        logger.info("lead_prospector.page", page=page,
                    stored=total, per_page=per_page)
        return page

    async def _query_apollo(
        self, context: AgentContext, settings, per_page: int = 10
    ) -> Optional[list]:
        page = await self._next_page(context, per_page)
        payload = {
            "page": page,
            "per_page": per_page,
            "person_locations": settings.apollo_locations_list,
            "person_titles": settings.apollo_titles_list,
            "organization_num_employees_ranges": [
                f"{settings.apollo_min_employees},{settings.apollo_max_employees}"
            ],
        }
        if settings.apollo_org_ids_list:
            payload["organization_ids"] = settings.apollo_org_ids_list
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.post(
                    APOLLO_SEARCH_URL,
                    json=payload,
                    headers={"Content-Type": "application/json",
                             "Cache-Control": "no-cache",
                             "X-Api-Key": settings.apollo_api_key},
                )
            if r.status_code == 200:
                people = r.json().get("people", [])
                logger.info("lead_prospector.apollo_ok",
                            returned=len(people), page=page)
                return people
            logger.error("lead_prospector.apollo_err",
                         status=r.status_code, body=r.text[:300])
            return None
        except httpx.TimeoutException:
            logger.error("lead_prospector.apollo_timeout")
            return None
        except Exception as exc:
            logger.error("lead_prospector.apollo_exc", error=str(exc))
            return None


# ── Module helpers ────────────────────────────────────────────────────────────

def _extract_domain(person: dict) -> Optional[str]:
    org = person.get("organization") or {}
    d = (org.get("primary_domain") or "").strip().lower()
    if d:
        return d.lstrip("www.") or None
    w = (org.get("website_url") or "").strip()
    if not w:
        return None
    try:
        if not w.startswith(("http://", "https://")):
            w = f"https://{w}"
        netloc = urlparse(w).netloc.lower().lstrip("www.")
        return netloc or None
    except Exception:
        return None


def _is_placeholder(val: str) -> bool:
    return val.lower() in {"your_key_here", "placeholder", "changeme", "xxx"}


def _build_record(
    person: dict, domain: str, enriched_email: Optional[str] = None
) -> ProspectedLead:
    org          = person.get("organization") or {}
    emp          = org.get("num_employees") or org.get("estimated_num_employees")
    title        = (person.get("title") or "").strip()
    company      = (org.get("name") or "").strip()
    industry     = (org.get("industry") or "").strip()
    city         = (person.get("city") or "").strip()
    country      = (person.get("country") or "").strip()
    location     = (f"{city}, {country}" if city and country
                    else country or "DACH")
    emp_str      = f"{emp} employees" if emp else "unknown size"
    signal       = " ".join(filter(None, [
        title,
        f"at {company}" if company else None,
        f"({industry})" if industry else None,
        f"— {location}, {emp_str}",
    ]))
    contact_email = (person.get("email") or "").strip() or enriched_email or None

    return ProspectedLead(
        domain=domain,
        company_name=company or None,
        industry=industry or None,
        employee_count=int(emp) if emp else None,
        location=location,
        contact_first_name=person.get("first_name") or None,
        contact_last_name=person.get("last_name") or None,
        contact_email=contact_email,
        contact_title=title or None,
        contact_linkedin=person.get("linkedin_url") or None,
        signal=signal,
        apollo_person_id=person.get("id") or None,
        apollo_organization_id=org.get("id") or None,
        tracking_token=secrets.token_urlsafe(48),
        status=ProspectedLeadStatus.new,
    )
