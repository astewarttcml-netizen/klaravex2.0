"""
app/api/prospecting_admin.py
─────────────────────────────
Admin endpoints for the outbound prospecting pipeline.

Routes (all require X-API-Key admin auth):
  POST /api/v1/admin/prospecting/import-csv
      Upload an Apollo CSV export → parse → deduplicate → create
      ProspectedLead records → fire ProspectingOutreachAgent for each.

  POST /api/v1/admin/prospecting/trigger
      Manually trigger the Celery prospect_leads task (same as the
      scheduled 08:00 run).  Useful once Apollo Outbound API is active.

  GET  /api/v1/admin/prospecting/status
      Today's prospecting stats: created, queued, failed, sent.

  GET  /api/v1/admin/prospecting/leads
      Paginated list of ProspectedLead records with status filter.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.portal_auth import require_admin
from app.agents.base import AgentContext
from app.config import get_settings
from app.models.prospected_lead import ProspectedLead, ProspectedLeadStatus
from app.models.lead import Lead

logger = structlog.get_logger(__name__)
router = APIRouter()

# ── Apollo CSV column aliases ─────────────────────────────────────────────────
# Apollo changes column names between export versions — normalise all known variants.
_COL_MAP = {
    # Name
    "first_name":     ["first name", "firstname"],
    "last_name":      ["last name", "lastname", "surname"],
    "full_name":      ["name", "full name", "contact name"],
    # Title
    "title":          ["title", "job title", "position"],
    # Email
    "email":          ["email", "email address", "work email"],
    "email_status":   ["email status", "email_status", "verified"],
    # Company
    "company":        ["company", "company name", "organization", "organisation", "account name"],
    "website":        ["website", "company website", "website url", "company url", "domain"],
    # Location
    "city":           ["city", "company city", "hq city"],
    "state":          ["state", "company state", "hq state"],
    "country":        ["country", "company country", "hq country"],
    # Size / industry
    "employees":      ["employees", "# employees", "num employees", "employee count",
                       "company size", "number of employees"],
    "industry":       ["industry", "company industry"],
    # IDs
    "apollo_person_id": ["apollo id", "person id", "people id", "apollo person id"],
    "apollo_org_id":    ["account id", "company id", "apollo account id", "organization id"],
    # Phone (not used, but normalise to avoid confusion)
    "phone":          ["phone", "phone number", "mobile", "corporate phone"],
}


def _normalise_headers(raw_headers: list[str]) -> dict[str, str]:
    """
    Map raw CSV headers → canonical field names.
    Returns dict: canonical_name → original_header.
    """
    lower = {h.lower().strip(): h for h in raw_headers}
    result: dict[str, str] = {}
    for canonical, aliases in _COL_MAP.items():
        for alias in aliases:
            if alias in lower:
                result[canonical] = lower[alias]
                break
    return result


def _extract_domain(website: str, email: str) -> str | None:
    """Derive root domain from website URL or email address."""
    if website:
        try:
            url = website if "://" in website else f"https://{website}"
            parsed = urlparse(url)
            host = parsed.netloc or parsed.path
            host = re.sub(r"^www\.", "", host).split("/")[0].strip()
            if host and "." in host:
                return host.lower()
        except Exception:
            pass
    if email and "@" in email:
        domain = email.split("@")[-1].lower().strip()
        if domain and "." in domain:
            return domain
    return None


def _get(row: dict, header_map: dict[str, str], field: str, default: str = "") -> str:
    original = header_map.get(field)
    if not original:
        return default
    return (row.get(original) or "").strip()


async def _existing_domains(db: AsyncSession) -> set[str]:
    result = await db.execute(
        select(ProspectedLead.domain).where(ProspectedLead.domain.isnot(None))
    )
    return {r[0].lower() for r in result.fetchall()}


async def _existing_emails(db: AsyncSession) -> set[str]:
    result = await db.execute(
        select(ProspectedLead.contact_email).where(ProspectedLead.contact_email.isnot(None))
    )
    return {r[0].lower() for r in result.fetchall()}


async def _inbound_domains(db: AsyncSession) -> set[str]:
    result = await db.execute(
        select(Lead.email).where(Lead.email.isnot(None))
    )
    domains: set[str] = set()
    for (em,) in result.fetchall():
        if "@" in em:
            domains.add(em.split("@")[-1].lower().strip())
    return domains


# ── CSV Import ────────────────────────────────────────────────────────────────

@router.post("/import-csv", dependencies=[Depends(require_admin)])
async def import_apollo_csv(
    file: UploadFile = File(...),
    fire_outreach: bool = Query(True, description="Draft outreach emails for each new prospect"),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload an Apollo CSV export and load net-new contacts into the
    prospecting pipeline.  Deduplicates against existing prospected_leads
    and inbound leads.  Optionally fires ProspectingOutreachAgent for each
    new record (default: True).

    Accepts UTF-8 or latin-1 encoded CSV (Apollo exports either).
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")

    raw = await file.read()
    # Try UTF-8 first, fall back to latin-1
    try:
        content = raw.decode("utf-8-sig")  # utf-8-sig strips BOM if present
    except UnicodeDecodeError:
        content = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    header_map = _normalise_headers(list(reader.fieldnames))
    rows = list(reader)

    if not rows:
        return {"imported": 0, "skipped_duplicate": 0, "skipped_no_email": 0,
                "skipped_no_domain": 0, "rows_in_file": 0, "detail": "CSV is empty"}

    # Load dedup sets
    known_domains = await _existing_domains(db)
    known_emails  = await _existing_emails(db)
    inbound_domains = await _inbound_domains(db)
    blocked_domains = known_domains | inbound_domains

    settings = get_settings()
    context = AgentContext(
        db=db,
        settings=settings,
        conversation_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        lead_id=None,
    )

    from app.agents.registry import registry
    outreach_agent = registry.get("prospecting_outreach")

    imported = 0
    skipped_duplicate = 0
    skipped_no_email = 0
    skipped_no_domain = 0
    skipped_invalid_email = 0
    outreach_fired = 0
    outreach_failed = 0
    imported_companies: list[str] = []

    for row in rows:
        # Resolve full name
        full_name = _get(row, header_map, "full_name")
        if not full_name:
            first = _get(row, header_map, "first_name")
            last  = _get(row, header_map, "last_name")
            full_name = f"{first} {last}".strip() or None

        title    = _get(row, header_map, "title") or None
        email    = _get(row, header_map, "email") or None
        email_st = _get(row, header_map, "email_status").lower()
        company  = _get(row, header_map, "company") or None
        website  = _get(row, header_map, "website") or None
        city     = _get(row, header_map, "city") or None
        country  = _get(row, header_map, "country") or None
        industry = _get(row, header_map, "industry") or None
        emp_raw  = _get(row, header_map, "employees")
        apollo_pid = _get(row, header_map, "apollo_person_id") or None
        apollo_oid = _get(row, header_map, "apollo_org_id") or None

        # Skip invalid emails from Apollo
        if email_st == "invalid":
            skipped_invalid_email += 1
            continue

        if not email:
            skipped_no_email += 1
            continue

        domain = _extract_domain(website, email)
        if not domain:
            skipped_no_domain += 1
            continue

        # Deduplication
        if domain in blocked_domains or email.lower() in known_emails:
            skipped_duplicate += 1
            continue

        # Parse employee count
        employee_count: int | None = None
        if emp_raw:
            digits = re.sub(r"[^\d]", "", emp_raw.split("-")[0].split("+")[0])
            if digits:
                try:
                    employee_count = int(digits)
                except ValueError:
                    pass

        # Build prospecting signal
        signal_parts: list[str] = []
        if title:
            signal_parts.append(f"{title} at {company or domain}")
        if employee_count:
            signal_parts.append(f"{employee_count}-person company")
        if city:
            signal_parts.append(f"based in {city}")
        if industry:
            signal_parts.append(f"industry: {industry}")
        signal_parts.append("source: Apollo CSV export")
        prospecting_signal = ", ".join(signal_parts)

        # Split full_name into first/last (best-effort; Apollo CSV rarely gives
        # separate first/last columns so we work with the joined value)
        name_parts = (full_name or "").split(" ", 1)
        first_name = name_parts[0] or None
        last_name  = name_parts[1] if len(name_parts) > 1 else None

        prospect = ProspectedLead(
            company_name=company or domain,
            domain=domain,
            industry=industry,
            employee_count=employee_count,
            city=city or None,
            country=country or None,
            contact_first_name=first_name,
            contact_last_name=last_name,
            contact_email=email,
            contact_title=title,
            apollo_person_id=apollo_pid,
            apollo_organization_id=apollo_oid,
            signal=prospecting_signal,
            status=ProspectedLeadStatus.new,
        )
        db.add(prospect)
        await db.flush()

        blocked_domains.add(domain)
        known_emails.add(email.lower())
        imported += 1
        imported_companies.append(company or domain)

        logger.info(
            "prospecting_admin.csv_imported",
            prospect_id=prospect.id,
            company=company,
            domain=domain,
            contact=full_name,
        )

        if fire_outreach:
            try:
                result = await outreach_agent(context, {"prospect_id": prospect.id})
                if result.success and result.output.get("status") == "outreach_queued":
                    outreach_fired += 1
                else:
                    outreach_failed += 1
                    logger.warning(
                        "prospecting_admin.outreach_failed",
                        prospect_id=prospect.id,
                        error=result.error,
                    )
            except Exception as exc:
                outreach_failed += 1
                logger.error("prospecting_admin.outreach_error",
                             prospect_id=prospect.id, error=str(exc))

    await db.flush()

    return {
        "rows_in_file": len(rows),
        "imported": imported,
        "outreach_queued": outreach_fired,
        "outreach_failed": outreach_failed,
        "skipped_duplicate": skipped_duplicate,
        "skipped_no_email": skipped_no_email,
        "skipped_no_domain": skipped_no_domain,
        "skipped_invalid_email": skipped_invalid_email,
        "companies": imported_companies,
    }


# ── Manual trigger ────────────────────────────────────────────────────────────

@router.post("/trigger", dependencies=[Depends(require_admin)])
async def trigger_prospecting_run():
    """
    Manually fire the Celery prospect_leads task.
    Equivalent to the scheduled 08:00 weekday run.
    Use once Apollo Outbound API plan is active.
    """
    from app.tasks.prospect_leads import run_prospecting
    task = run_prospecting.delay(triggered_by="admin_api")
    return {
        "queued": True,
        "task_id": task.id,
        "note": "Task dispatched to Celery default queue. Check logs for results.",
    }


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status", dependencies=[Depends(require_admin)])
async def prospecting_status(db: AsyncSession = Depends(get_db)):
    """Today's prospecting pipeline summary."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    async def count(status: ProspectedLeadStatus | None = None,
                    since: datetime | None = None) -> int:
        q = select(func.count()).select_from(ProspectedLead)
        if status:
            q = q.where(ProspectedLead.status == status)
        if since:
            q = q.where(ProspectedLead.created_at >= since)
        return (await db.execute(q)).scalar_one() or 0

    total_all_time     = await count()
    created_today      = await count(since=today_start)
    queued             = await count(ProspectedLeadStatus.outreach_queued)
    sent               = await count(ProspectedLeadStatus.sent)
    draft_failed       = await count(ProspectedLeadStatus.draft_failed)
    disqualified       = await count(ProspectedLeadStatus.disqualified)

    settings = get_settings()
    return {
        "apollo_configured": settings.apollo_configured,
        "daily_limit": settings.prospecting_daily_limit,
        "created_today": created_today,
        "total_all_time": total_all_time,
        "outreach_queued": queued,
        "outreach_sent": sent,
        "draft_failed": draft_failed,
        "disqualified": disqualified,
    }


# ── Lead list ─────────────────────────────────────────────────────────────────

@router.get("/leads", dependencies=[Depends(require_admin)])
async def list_prospected_leads(
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Paginated list of ProspectedLead records."""
    _valid_statuses = {
        ProspectedLeadStatus.new, ProspectedLeadStatus.outreach_queued,
        ProspectedLeadStatus.draft_failed, ProspectedLeadStatus.approved,
        ProspectedLeadStatus.sent, ProspectedLeadStatus.bounced,
        ProspectedLeadStatus.replied, ProspectedLeadStatus.disqualified,
    }

    q = select(ProspectedLead).order_by(ProspectedLead.created_at.desc())
    if status:
        if status not in _valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
        q = q.where(ProspectedLead.status == status)

    offset = (page - 1) * per_page
    result = await db.execute(q.offset(offset).limit(per_page))
    leads = result.scalars().all()

    count_q = select(func.count()).select_from(ProspectedLead)
    if status:
        count_q = count_q.where(ProspectedLead.status == status)
    total = (await db.execute(count_q)).scalar_one() or 0

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "leads": [
            {
                "id": str(l.id),
                "company": l.company_name,
                "domain": l.domain,
                "contact_name": l.contact_name,
                "contact_title": l.contact_title,
                "contact_email": l.contact_email,
                "status": l.status,
                "prospecting_signal": l.signal,
                "outreach_subject": l.outreach_subject,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in leads
        ],
    }
