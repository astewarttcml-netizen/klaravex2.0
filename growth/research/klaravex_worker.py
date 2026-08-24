#!/usr/bin/env python3
"""
Run Apollo shortlist + 11-scraper gather_research using the legacy klaravex stack.

Invoked as a subprocess from Growth OS (klaravex .venv python required).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import httpx

# growth/research lives under Klaravex2.0; serialize helpers are imported after path fixup.
_GROWTH_RESEARCH_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _GROWTH_RESEARCH_DIR.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from growth.research.serialize import bundle_to_artifact, render_bundle_summary, slugify  # noqa: E402

APOLLO_SEARCH_URL = "https://api.apollo.io/v1/mixed_people/api_search"
APOLLO_PEOPLE_MATCH_URL = "https://api.apollo.io/v1/people/match"


def _extract_domain(person: dict) -> str | None:
    from urllib.parse import urlparse

    org = person.get("organization") or {}
    domain = (org.get("primary_domain") or "").strip().lower()
    if domain:
        return domain.lstrip("www.")
    website = (org.get("website_url") or "").strip()
    if not website:
        return None
    if not website.startswith(("http://", "https://")):
        website = f"https://{website}"
    try:
        netloc = urlparse(website).netloc.lower().lstrip("www.")
        return netloc or None
    except Exception:
        return None


def _is_us_plausible_domain(domain: str | None) -> bool:
    blocked_tlds = {"de", "at", "ch"}
    stopwords = {"the", "a", "an", "and", "of", "for", "to", "in", "on", "we", "my", "our", "your"}
    d = (domain or "").strip().lower()
    if not d or "." not in d:
        return False
    if d.rsplit(".", 1)[-1] in blocked_tlds:
        return False
    sld = d.split(".")[-2]
    if len(sld) < 2 or sld in stopwords:
        return False
    return True


def _person_to_prospect(person: dict, domain: str) -> dict[str, Any]:
    org = person.get("organization") or {}
    email = (person.get("email") or "").strip() or None
    return {
        "company_name": (org.get("name") or "").strip() or domain,
        "domain": domain,
        "apollo_org_id": (org.get("id") or "").strip(),
        "apollo_person_id": (person.get("id") or "").strip(),
        "linkedin_url": (person.get("linkedin_url") or "").strip(),
        "twitter_url": (person.get("twitter_url") or "").strip(),
        "contact_first_name": (person.get("first_name") or "").strip(),
        "contact_last_name": (person.get("last_name") or "").strip(),
        "contact_email": email,
        "email_source": "apollo" if email else None,
        "contact_title": (person.get("title") or "").strip(),
        "industry": (org.get("industry") or "").strip(),
        "employee_count": org.get("num_employees") or org.get("estimated_num_employees"),
        "city": (person.get("city") or "").strip(),
        "state": (person.get("state") or "").strip(),
        "vertical": _infer_vertical(org),
    }


def _infer_vertical(org: dict) -> str:
    industry = (org.get("industry") or "").lower()
    if "law" in industry or "legal" in industry:
        return "law"
    if "account" in industry or "cpa" in industry:
        return "accounting"
    if "medical" in industry or "health" in industry or "dental" in industry:
        return "medical"
    return "professional_services"


async def _apollo_people_match(
    client: httpx.AsyncClient,
    person: dict,
    domain: str,
    api_key: str,
) -> dict | None:
    first_name = (person.get("first_name") or "").strip()
    if not first_name or not api_key:
        return None
    payload: dict[str, Any] = {
        "first_name": first_name,
        "domain": domain,
        "reveal_personal_emails": True,
    }
    last_name = (person.get("last_name") or "").strip()
    if last_name:
        payload["last_name"] = last_name
    apollo_id = (person.get("id") or "").strip()
    if apollo_id:
        payload["id"] = apollo_id
    try:
        resp = await client.post(
            APOLLO_PEOPLE_MATCH_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "X-Api-Key": api_key,
            },
        )
        if resp.status_code != 200:
            return None
        body = resp.json()
        return body.get("person") or body.get("matched_person")
    except Exception:
        return None


async def _apollo_search_page(
    client: httpx.AsyncClient,
    settings: Any,
    *,
    page: int,
    per_page: int,
) -> list[dict]:
    payload: dict[str, Any] = {
        "page": page,
        "per_page": per_page,
        "organization_locations": settings.apollo_locations_list,
        "person_titles": settings.apollo_titles_list,
        "organization_num_employees_ranges": [
            f"{settings.apollo_min_employees},{settings.apollo_max_employees}"
        ],
    }
    industries = getattr(settings, "apollo_industries_list", None)
    if industries:
        payload["q_organization_keyword_tags"] = industries
    if settings.apollo_org_ids_list:
        payload["organization_ids"] = settings.apollo_org_ids_list
    resp = await client.post(
        APOLLO_SEARCH_URL,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": settings.apollo_api_key,
        },
    )
    if resp.status_code != 200:
        print(f"apollo search failed page={page}: {resp.status_code} {resp.text[:200]}", file=sys.stderr)
        return []
    return resp.json().get("people") or []


async def _person_to_enriched_prospect(
    client: httpx.AsyncClient,
    settings: Any,
    person: dict,
    excluded: set[str],
) -> dict | None:
    domain = _extract_domain(person)
    if not domain and person.get("first_name"):
        org = person.get("organization") or {}
        guess_domain = (org.get("primary_domain") or "").strip().lower()
        unlocked = await _apollo_people_match(
            client, person, guess_domain or "example.com", settings.apollo_api_key
        )
        if unlocked:
            for key in ("email", "first_name", "last_name", "title", "linkedin_url", "city", "state"):
                val = unlocked.get(key)
                if val and not person.get(key):
                    person[key] = val
            org = unlocked.get("organization") or org
            person["organization"] = org
            domain = _extract_domain(unlocked) or _extract_domain(person)
            if not domain:
                email = (unlocked.get("email") or "").strip()
                if "@" in email:
                    domain = email.split("@", 1)[1].lower()

    if not domain or not _is_us_plausible_domain(domain):
        return None
    if domain in excluded:
        return None

    prospect = _person_to_prospect(person, domain)
    if not prospect.get("contact_email"):
        unlocked = await _apollo_people_match(
            client, person, domain, settings.apollo_api_key
        )
        if unlocked:
            email = (unlocked.get("email") or "").strip()
            if email:
                prospect["contact_email"] = email
                prospect["email_source"] = "apollo"
            for key in ("first_name", "last_name", "title", "linkedin_url"):
                val = unlocked.get(key)
                if val and not prospect.get(f"contact_{key}" if key != "title" else "contact_title"):
                    if key == "title":
                        prospect["contact_title"] = val
                    elif key == "first_name":
                        prospect["contact_first_name"] = val
                    elif key == "last_name":
                        prospect["contact_last_name"] = val
            org = unlocked.get("organization") or {}
            if org.get("id"):
                prospect["apollo_org_id"] = org["id"]
    return prospect


async def _apollo_shortlist(settings: Any, *, max_prospects: int, excluded: set[str]) -> list[dict]:
    if not settings.apollo_configured:
        return []

    per_page = min(max(max_prospects, 25), 100)
    start_page = 1 + (date.today().toordinal() % 500)
    prospects: list[dict] = []
    pages_tried = 0
    page = start_page
    wrapped = False

    async with httpx.AsyncClient(timeout=25.0) as client:
        while len(prospects) < max_prospects and pages_tried < 20:
            people = await _apollo_search_page(
                client, settings, page=page, per_page=per_page
            )
            pages_tried += 1
            if not people:
                if not wrapped:
                    wrapped = True
                    page = 1
                    continue
                break
            for person in people:
                if len(prospects) >= max_prospects:
                    break
                prospect = await _person_to_enriched_prospect(
                    client, settings, person, excluded
                )
                if not prospect:
                    continue
                domain = prospect.get("domain")
                if domain:
                    excluded.add(str(domain))
                prospects.append(prospect)
            page += 1

    print(
        f"apollo shortlist collected={len(prospects)} target={max_prospects} pages={pages_tried}",
        file=sys.stderr,
    )
    return prospects


async def _enrich_one(settings: Any, prospect: dict, sem: asyncio.Semaphore) -> dict[str, Any]:
    from app.services.research.orchestrator import gather_research

    async with sem:
        research_input = {
            "company_name": prospect.get("company_name"),
            "domain": prospect.get("domain"),
            "apollo_org_id": prospect.get("apollo_org_id"),
            "linkedin_url": prospect.get("linkedin_url"),
            "twitter_url": prospect.get("twitter_url"),
        }
        bundle = await gather_research(research_input, settings)
        artifact = bundle_to_artifact(bundle)
        return {
            "prospect": prospect,
            "bundle": artifact,
            "status": "enriched",
        }


async def _run(args: argparse.Namespace) -> int:
    klaravex_root = Path(args.klaravex_root).resolve()
    if str(klaravex_root) not in sys.path:
        sys.path.insert(0, str(klaravex_root))

    from growth.research.legacy_settings import load_legacy_settings

    settings = load_legacy_settings(klaravex_root)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    excluded = set(args.excluded_domains or [])
    excluded_path = output_dir / "_excluded_domains.json"
    excluded_path.write_text(json.dumps(sorted(excluded), indent=2), encoding="utf-8")

    prospects = await _apollo_shortlist(
        settings,
        max_prospects=args.max_prospects,
        excluded=excluded,
    )

    from growth.research.hunter_enrich import enrich_shortlist, hunter_enabled

    hunter_stats: dict[str, int] = {"enabled": 0, "filled": 0, "verified": 0, "dropped": 0}
    if hunter_enabled() and settings.hunter_configured:
        prospects, hunter_stats = await enrich_shortlist(prospects)

    shortlist_meta = {
        "run_id": args.run_id,
        "prospect_count": len(prospects),
        "apollo_configured": settings.apollo_configured,
        "hunter_configured": settings.hunter_configured,
        "hunter_enrich": hunter_stats,
        "min_confidence": args.min_confidence,
    }
    (output_dir / "shortlist.json").write_text(
        json.dumps({"meta": shortlist_meta, "prospects": prospects}, indent=2),
        encoding="utf-8",
    )

    if not prospects:
        (output_dir / "README.md").write_text(
            "# Research pre-enrichment\n\nNo prospects returned from Apollo shortlist.\n",
            encoding="utf-8",
        )
        return 0

    sem = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(
        *[_enrich_one(settings, p, sem) for p in prospects],
        return_exceptions=True,
    )

    enriched: list[dict] = []
    skipped: list[dict] = []
    for idx, result in enumerate(results):
        if isinstance(result, BaseException):
            prospect = prospects[idx]
            skipped.append(
                {
                    "prospect": prospect,
                    "reason": f"research_error: {result}",
                }
            )
            continue
        confidence = float(result["bundle"].get("research_confidence") or 0.0)
        prospect = result["prospect"]
        slug = slugify(f"{prospect.get('company_name')}-{prospect.get('domain')}")
        prospect_dir = output_dir / slug
        prospect_dir.mkdir(parents=True, exist_ok=True)
        (prospect_dir / "prospect.json").write_text(
            json.dumps(prospect, indent=2),
            encoding="utf-8",
        )
        (prospect_dir / "bundle.json").write_text(
            json.dumps(result["bundle"], indent=2),
            encoding="utf-8",
        )
        (prospect_dir / "bundle.summary.md").write_text(
            render_bundle_summary(prospect, result["bundle"]),
            encoding="utf-8",
        )
        row = {
            "slug": slug,
            "prospect": prospect,
            "research_confidence": confidence,
            "signal_count": len(result["bundle"].get("signals") or []),
        }
        if confidence >= args.min_confidence:
            enriched.append(row)
        else:
            skipped.append({"prospect": prospect, "reason": f"low_confidence:{confidence:.2f}"})

    summary = {
        "run_id": args.run_id,
        "enriched_count": len(enriched),
        "skipped_count": len(skipped),
        "min_confidence": args.min_confidence,
        "enriched": enriched,
        "skipped": skipped,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    readme_lines = [
        "# Research pre-enrichment",
        "",
        f"- Run ID: `{args.run_id}`",
        f"- Prospects from Apollo: {len(prospects)}",
        f"- Hunter enrich: {hunter_stats if hunter_stats.get('enabled') else 'disabled'}",
        f"- Enriched (confidence >= {args.min_confidence}): {len(enriched)}",
        f"- Skipped: {len(skipped)}",
        "",
        "Read each `*/bundle.summary.md` before drafting outreach.",
        "",
    ]
    (output_dir / "README.md").write_text("\n".join(readme_lines), encoding="utf-8")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Growth OS leads research pre-enrichment worker")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--klaravex-root", default="/home/anthony/klaravex")
    parser.add_argument("--max-prospects", type=int, default=100)
    parser.add_argument("--min-confidence", type=float, default=0.30)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--excluded-domains", nargs="*", default=[])
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
