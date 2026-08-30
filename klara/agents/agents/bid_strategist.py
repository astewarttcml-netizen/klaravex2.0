"""
app/agents/bid_strategist.py
──────────────────────────────
BidStrategyAgent (P2) — scores FreelanceProject records against Anthony's
skill profile and generates a personalised Claude-written cover letter + bid
amount for each qualifying project.

Flow:
  1. Fetch all FreelanceProject records with status=new (limit 20 per run).
  2. For each project, call Claude to:
       a) Score fit 0–100 against Anthony's core skills.
       b) Generate a cover letter (≤200 words, direct, not salesy).
       c) Recommend a bid amount based on project budget + platform norms.
  3. If score >= FREELANCE_MIN_FIT_SCORE (default 55):
       - Write fit_score, fit_rationale to FreelanceProject.
       - Create a PlatformBid record (status=queued).
       - Set FreelanceProject.status = bid_queued.
  4. If score < threshold:
       - Set FreelanceProject.status = ignored.
  5. Return summary dict.

The agent never submits bids — that is PlatformBidSubmitterAgent's job.
P2: no approval gate required for internal writes.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.freelance_project import FreelanceProject, FreelanceProjectStatus
from klara.rarv.platform_bid import PlatformBid, PlatformBidStatus

logger = structlog.get_logger(__name__)

# ── Default thresholds (overridden by env vars on Settings) ───────────────────
DEFAULT_MIN_FIT_SCORE = 55       # 0–100 — projects below this are ignored
BATCH_SIZE = 15                  # projects to process per agent run

# ── Skill profile prompt ──────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are an expert IT consultant and strategic bid advisor working with Anthony
Stewart, a senior freelance IT consultant based in Berlin with 15+ years of
enterprise experience.

Anthony's core skills and service areas (he is genuinely excellent at these):
  - Microsoft Azure (architecture, migration, cost optimisation, security)
  - Microsoft 365 / Office 365 (tenant setup, migration, governance, Teams)
  - Microsoft Entra ID (formerly Azure AD) — SSO, Conditional Access, MFA, SCIM
  - Microsoft Intune / Endpoint Manager (MDM, MAM, policy)
  - Windows Server (AD DS, DNS, DHCP, GPO, DFS)
  - VMware vSphere / ESXi (virtualisation, migration)
  - Cisco Meraki (networking, SD-WAN, security)
  - Citrix ADC / NetScaler
  - PowerShell scripting / automation
  - PKI / certificate management
  - Network security / Zero Trust / segmentation
  - IT project management / migrations / rollouts
  - English (native) + German (professional working)

Target clients:
  - English-speaking expats and international businesses in Berlin
  - European SMBs and mid-market companies
  - Companies migrating to cloud or modernising IT infrastructure

Anthony does NOT do:
  - General web development (React, Node, PHP, etc.)
  - Mobile app development
  - Data science / ML / AI model training
  - Graphic design
  - Non-IT consulting

When generating cover letters, follow these enhanced guidelines:
  - Start with a strong value proposition that directly addresses client needs
  - Reference specific project requirements by name (2-3 key items)
  - Highlight relevant experience or credentials that match the project scope
  - End with direct, non-pushy CTA that encourages a quick chat
  - Keep the tone direct and peer-to-peer, not salesy
  - Use the exact language of the project posting (English/german/etc.)
"""

_ANALYSIS_PROMPT = """\
Analyse this freelance project for fit with Anthony's skill profile.

PROJECT DATA:
{project_json}

Return ONLY valid JSON with exactly these fields:
{{
  "fit_score": <integer 0-100>,
  "fit_rationale": "<1-2 sentences explaining the score>",
  "key_matching_skills": ["<skill1>", "<skill2>"],
  "recommended_bid_amount": <number — in the project's currency, null if unclear>,
  "recommended_delivery_days": <integer — realistic delivery estimate, null if N/A>,
  "cover_letter": "<cover letter body — 150-200 words, direct, peer-to-peer, NOT salesy. Opens with project reference. Body only — NO signature, NO email address, NO URLs, NO contact details of any kind (platform rules prohibit them pre-award).>",
  "should_bid": <true|false — true if fit_score >= 40 AND project is not web dev / mobile / ML / design>
}}

Scoring rubric:
  90-100: Perfect match — core Azure/M365/Entra/Intune/network skills, right budget, verified client
  70-89:  Strong match — most required skills present, reasonable budget
  55-69:  Decent match — partial skill overlap, worth a bid
  40-54:  Borderline match — adjacent skill overlap, worth a low-effort bid
  20-39:  Weak match — limited overlap, do not bid
  0-19:   No match — web dev, mobile, ML, design, wrong domain — never bid

Cover letter rules:
  - Open with: "I came across your project [title] and I'm confident I can deliver."
  - Reference 2-3 specific project requirements by name.
  - Mention 1-2 concrete Anthony credentials relevant to the project.
  - Close with a single soft CTA inviting a quick chat — DO NOT include any URLs, links, or contact details.
  - STRICTLY FORBIDDEN in the cover letter: email addresses, URLs, phone numbers, website names,
    social media handles, Calendly links, or any other contact information. Platform ToS prohibit
    contact details pre-award and the API will reject the bid if any are present.
  - No pricing in the cover letter.
  - Language: detect the language of the project posting from its title and description, then
    write the cover letter in THAT language. German posting → German cover letter. English
    posting → English cover letter. Do NOT default to English for German postings.
  - End after the closing sentence — no signature block, no "Best,", no name, no company name.

Enhanced cover letter structure (following best practices from template improvements):
  - Start with a strong value proposition that directly addresses client needs
  - Reference specific project requirements by name (2-3 key items)
  - Highlight relevant experience or credentials that match the project scope
  - End with direct, non-pushy CTA that encourages a quick chat
"""


class BidStrategyAgent(BaseAgent):
    name = "bid_strategist"
    description = (
        "Scores new FreelanceProject records for fit, generates Claude-written cover letters "
        "and bid amounts, creates PlatformBid drafts for qualifying projects. P2 — no approval "
        "gate. Projects below fit threshold are marked ignored."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        input_data:
          project_id: str  — analyse a single project (optional)
          batch_size: int  — override default batch size

        Returns AgentResult.ok({
            "scored": int,
            "bids_queued": int,
            "ignored": int,
            "errors": int
        })
        """
        min_fit = float(
            input_data.get(
                "min_fit_score",
                getattr(context.settings, "freelance_min_fit_score", DEFAULT_MIN_FIT_SCORE),
            )
        )
        batch_size = int(input_data.get("batch_size", BATCH_SIZE))
        single_project_id = input_data.get("project_id")

        # ── Fetch projects to analyse ─────────────────────────────────────────
        if single_project_id:
            q = await context.db.execute(
                select(FreelanceProject).where(
                    FreelanceProject.id == single_project_id
                )
            )
            projects = [r for r in q.scalars().all()]
        else:
            q = await context.db.execute(
                select(FreelanceProject)
                .where(FreelanceProject.status == FreelanceProjectStatus.new)
                .order_by(FreelanceProject.posted_at.desc().nullslast())
                .limit(batch_size)
            )
            projects = list(q.scalars().all())

        if not projects:
            return AgentResult.ok(output={"scored": 0, "bids_queued": 0, "ignored": 0, "errors": 0})

        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        scored = bids_queued = ignored = errors = 0

        for project in projects:
            try:
                result = await _analyse_project(client, project, context.settings)
                if result is None:
                    errors += 1
                    continue

                # Update project with score
                project.fit_score = result.get("fit_score", 0)
                project.fit_rationale = result.get("fit_rationale", "")
                project.updated_at = datetime.now(tz=timezone.utc)
                scored += 1

                should_bid = result.get("should_bid", False) and (
                    (result.get("fit_score") or 0) >= min_fit
                )

                if should_bid:
                    # Create bid record
                    bid = PlatformBid(
                        project_id=project.id,
                        platform=project.platform,
                        cover_letter=result.get("cover_letter", ""),
                        bid_amount=result.get("recommended_bid_amount"),
                        bid_currency=project.budget_currency or "EUR",
                        delivery_days=result.get("recommended_delivery_days"),
                        status=PlatformBidStatus.queued,
                    )
                    context.db.add(bid)

                    project.status = FreelanceProjectStatus.bid_queued
                    project.bid_queued_at = datetime.now(tz=timezone.utc)
                    bids_queued += 1

                    logger.info(
                        "bid_strategist.bid_queued",
                        project_id=project.id,
                        platform=project.platform,
                        title=project.title[:60],
                        score=project.fit_score,
                        amount=result.get("recommended_bid_amount"),
                    )
                else:
                    project.status = FreelanceProjectStatus.ignored
                    ignored += 1
                    logger.info(
                        "bid_strategist.project_ignored",
                        project_id=project.id,
                        platform=project.platform,
                        title=project.title[:60],
                        score=project.fit_score,
                        reason="below_threshold_or_wrong_domain",
                    )

            except Exception as exc:
                logger.error(
                    "bid_strategist.project_error",
                    project_id=project.id,
                    error=str(exc),
                )
                errors += 1
                continue

        await context.db.commit()

        logger.info(
            "bid_strategist.run_complete",
            scored=scored,
            bids_queued=bids_queued,
            ignored=ignored,
            errors=errors,
        )

        return AgentResult.ok(
            output={
                "scored": scored,
                "bids_queued": bids_queued,
                "ignored": ignored,
                "errors": errors,
            }
        )


# ── Claude analysis helper ────────────────────────────────────────────────────

async def _analyse_project(
    client: AsyncAnthropic,
    project: FreelanceProject,
    settings,
) -> Optional[dict]:
    """Call Claude to score and generate a bid for one project. Returns parsed dict or None."""
    project_data = {
        "title": project.title,
        "description": (project.description or "")[:2000],  # truncate for token budget
        "skills_required": _parse_skills(project.skills_required),
        "category": project.category,
        "budget_min": float(project.budget_min or 0),
        "budget_max": float(project.budget_max or 0),
        "budget_type": project.budget_type,
        "budget_currency": project.budget_currency,
        "platform": project.platform,
        "client_location": project.client_location,
        "is_verified_client": project.is_verified_client,
        "proposals_count": project.proposals_count,
    }

    try:
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1500,
            system=_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": _ANALYSIS_PROMPT.format(
                    project_json=json.dumps(project_data, ensure_ascii=False, indent=2)
                ),
            }],
        )
        try:
            from klara.rarv.runtime.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=settings.anthropic_model,
                response=response, lead_id=getattr(context, 'lead_id', None),
            )
        except Exception:
            pass
        raw = response.content[0].text.strip()
        return _parse_json(raw)
    except Exception as exc:
        logger.error(
            "bid_strategist.claude_error",
            project_id=project.id,
            error=str(exc),
        )
        return None


def _parse_skills(skills_json: Optional[str]) -> list[str]:
    if not skills_json:
        return []
    try:
        return json.loads(skills_json)
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_json(text: str) -> Optional[dict]:
    """Extract first JSON object from Claude response."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None
