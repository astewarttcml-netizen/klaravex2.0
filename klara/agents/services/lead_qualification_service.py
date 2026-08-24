"""
app/services/lead_qualification_service.py
───────────────────────────────────────────
Task 5.2 — Lead qualification workflow.

Steps:
  1. Classify the lead with Claude (company_size, pain_point, urgency, likely_service)
  2. Generate a 3-5 sentence structured summary
  3. Push to Notion leads database (if NOTION_API_KEY + NOTION_LEADS_DB_ID configured)
  4. Create an ApprovalRequest with action_type="send_proposal"
  5. Set Approval.priority="high" for urgent leads

All network calls are wrapped in try/except — a Notion failure does NOT
block the approval gate from being created.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from uuid import uuid4

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalRequest, ApprovalStatus, RiskLevel
from app.models.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Classification prompt
# ---------------------------------------------------------------------------

CLASSIFICATION_PROMPT = """\
You are a lead qualification specialist for Klaravex, an IT consultancy \
serving SMEs in Berlin and the DACH region.

Analyse the lead data below and return a JSON object with EXACTLY these fields:

  company_size: "solo" | "small" | "medium" | "large"
    solo   = 1 person / freelancer
    small  = 2-10 employees
    medium = 11-50 employees
    large  = 50+ employees

  pain_point: "website" | "it-support" | "cloud" | "security" | "other"

  urgency: "urgent" | "soon" | "planning"
    urgent   = broken NOW, ASAP, emergency
    soon     = within weeks / next 1-2 months
    planning = exploratory, 3+ months out

  likely_service: "web-design" | "it-maintenance" | "cloud-setup" | "security-audit" | "consulting"

  confidence: 0.0-1.0   (how confident you are in these classifications)

  summary: string  (3-5 sentences in English: who they are, what they need, why now, \
suggested service, confidence note)

Respond ONLY with valid JSON. No markdown fences, no extra keys.

Lead data:
{lead_data}
"""

# ---------------------------------------------------------------------------
# Notion helpers
# ---------------------------------------------------------------------------

async def _push_to_notion(
    settings,
    lead: Lead,
    classification: dict,
    summary: str,
) -> str | None:
    """
    Create a page in the Notion leads database.
    Returns the Notion page ID on success, None on failure.
    """
    import asyncio

    if not settings.notion_api_key or not settings.notion_leads_db_id:
        logger.warning(
            "lead_qualification.notion_not_configured",
            detail="NOTION_API_KEY or NOTION_LEADS_DB_ID not set — skipping Notion push",
        )
        return None

    def _sync_push() -> str | None:
        try:
            import httpx

            headers = {
                "Authorization": f"Bearer {settings.notion_api_key}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            }

            now_iso = datetime.now(timezone.utc).isoformat()

            payload = {
                "parent": {"database_id": settings.notion_leads_db_id},
                "properties": {
                    "Name": {
                        "title": [{"text": {"content": lead.name or "Unknown"}}]
                    },
                    "Email": {
                        "email": lead.email or ""
                    },
                    "Company": {
                        "rich_text": [{"text": {"content": lead.company or ""}}]
                    },
                    "Service": {
                        "select": {"name": classification.get("likely_service", "consulting")}
                    },
                    "Urgency": {
                        "select": {"name": classification.get("urgency", "planning")}
                    },
                    "Source": {
                        "select": {"name": lead.source or "contact_form"}
                    },
                    "Summary": {
                        "rich_text": [{"text": {"content": summary[:2000]}}]
                    },
                    "Created": {
                        "date": {"start": now_iso}
                    },
                    "LeadID": {
                        "rich_text": [{"text": {"content": lead.id}}]
                    },
                },
            }

            resp = httpx.post(
                "https://api.notion.com/v1/pages",
                headers=headers,
                json=payload,
                timeout=10.0,
            )
            resp.raise_for_status()
            page_id = resp.json().get("id")
            logger.info(
                "lead_qualification.notion_pushed",
                lead_id=lead.id,
                notion_page_id=page_id,
            )
            return page_id
        except Exception as exc:
            logger.error(
                "lead_qualification.notion_push_failed",
                lead_id=lead.id,
                error=str(exc),
            )
            return None

    return await asyncio.to_thread(_sync_push)


# ---------------------------------------------------------------------------
# Main qualification function
# ---------------------------------------------------------------------------

async def qualify_lead(
    *,
    db: AsyncSession,
    lead_id: str,
    settings,
) -> dict:
    """
    Run the full qualification workflow for a lead.

    Returns a dict with:
      classification, summary, approval_id, notion_page_id (may be None)
    """
    # ── Load lead ────────────────────────────────────────────────────────────
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise ValueError(f"Lead {lead_id} not found")

    lead_data = {
        "name": lead.name,
        "company": lead.company,
        "message": lead.message,
        "services_interest": lead.services_interest,
        "budget_range": lead.budget_range,
        "timeline": lead.timeline,
        "source": lead.source,
    }

    # ── Claude classification ─────────────────────────────────────────────────
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=800,
            messages=[{
                "role": "user",
                "content": CLASSIFICATION_PROMPT.format(
                    lead_data=json.dumps(lead_data, indent=2)
                ),
            }],
        )
        raw = response.content[0].text.strip()
        # Strip accidental markdown fences
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
        classification = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("lead_qualification_service.json_parse_error", lead_id=lead_id, error=str(exc))
        classification = {
            "company_size": "unknown",
            "pain_point": "other",
            "urgency": "planning",
            "likely_service": "consulting",
            "confidence": 0.0,
            "summary": "Classification failed — manual review required.",
        }
    except Exception as exc:
        logger.error("lead_qualification_service.claude_error", lead_id=lead_id, error=str(exc))
        classification = {
            "company_size": "unknown",
            "pain_point": "other",
            "urgency": "planning",
            "likely_service": "consulting",
            "confidence": 0.0,
            "summary": f"Claude error: {exc}",
        }

    summary = classification.pop("summary", "No summary generated.")

    logger.info(
        "lead_qualification_service.classified",
        lead_id=lead_id,
        company_size=classification.get("company_size"),
        urgency=classification.get("urgency"),
        likely_service=classification.get("likely_service"),
        confidence=classification.get("confidence"),
    )

    # ── Update lead status ───────────────────────────────────────────────────
    lead.status = LeadStatus.qualified
    await db.flush()

    # ── Push to Notion ───────────────────────────────────────────────────────
    notion_page_id = await _push_to_notion(settings, lead, classification, summary)

    # ── Create Approval record ───────────────────────────────────────────────
    urgency = classification.get("urgency", "planning")
    # priority field stored inside payload JSON (ApprovalRequest.payload is a text blob)
    approval_payload = {
        "lead_id": lead_id,
        "summary": summary,
        "suggested_service": classification.get("likely_service"),
        "urgency": urgency,
        "company_size": classification.get("company_size"),
        "pain_point": classification.get("pain_point"),
        "confidence": classification.get("confidence"),
        "notion_page_id": notion_page_id,
        "priority": "high" if urgency == "urgent" else "normal",
    }

    approval = ApprovalRequest(
        id=str(uuid4()),
        action_name="send_proposal",
        risk_level=RiskLevel.p3,
        payload=json.dumps(approval_payload),
        justification=summary,
        requested_by_agent="lead_qualification_service",
        lead_id=lead_id,
        status=ApprovalStatus.pending,
    )
    db.add(approval)
    await db.flush()

    logger.info(
        "lead_qualification_service.approval_created",
        lead_id=lead_id,
        approval_id=approval.id,
        urgency=urgency,
        priority=approval_payload["priority"],
    )

    return {
        "classification": classification,
        "summary": summary,
        "approval_id": approval.id,
        "notion_page_id": notion_page_id,
    }
