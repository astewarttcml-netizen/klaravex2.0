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
from growth.adapters.cover_letter_templates import CoverLetterTemplateManager

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
  - Use the improved template system for consistent structure and messaging
  - For healthcare projects, include references to compliance requirements (HIPAA, GDPR)
  - Ensure cover letters are between 150-200 words with clear structure:
    * Opening hook with value proposition
    * Project-specific reference
    * Relevant experience or credentials
    * Strong CTA that encourages a quick chat
"""

_ANALYSIS_PROMPT = """\
Analyse this freelance project for fit with Anthony's skill profile.

PROJECT DATA:
{project_json}

Return ONLY valid JSON with exactly these fields:
{
  "fit_score": <integer 0-100>,
  "fit_rationale": "<1-2 sentences explaining the score>",
  "key_matching_skills": ["<skill1>", "<skill2>"],
  "recommended_bid_amount": <number — in the project's currency, null if unclear>,
  "recommended_delivery_days": <integer — realistic delivery estimate, null if N/A>,
  "cover_letter": "<cover letter body — 150-200 words, direct, peer-to-peer, NOT salesy. Opens with project reference. Body only — NO signature, NO email address, NO URLs, NO contact details of any kind (platform rules prohibit them pre-award).>",
  "should_bid": <true|false — true if fit_score >= 40 AND project is not web dev / mobile / ML / design>
}

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
  - Structure should include:
    * Opening hook with value proposition (e.g., "Klaravex AI resolves most IT issues instantly...")
    * Project-specific reference
    * Relevant experience or credentials that match project scope
    * Strong CTA that encourages a quick chat

Enhanced cover letter structure (following best practices from template improvements):
  - Start with a strong value proposition that directly addresses client needs
  - Reference specific project requirements by name (2-3 key items)
  - Highlight relevant experience or credentials that match the project scope
  - End with direct, non-pushy CTA that encourages a quick chat
  - For healthcare projects, include compliance references (HIPAA, GDPR)
"""

# ── Agent implementation ──────────────────────────────────────────────────────


class BidStrategyAgent(BaseAgent):
    name = "bid_strategist"
    description = (
        "Scores new FreelanceProject records for fit, generates Claude-written cover letters "
        "and bid amounts, creates PlatformBid drafts for qualifying projects. P2 — no approval "
        "gate. Projects below fit threshold are marked ignored."
    )
    permission_level = PermissionLevel.P2

    async def run(self, ctx: AgentContext, input: dict) -> AgentResult:
        """
        Score projects and generate cover letters for qualifying ones.
        """
        # ── Fetch new projects ───────────────────────────────────────────────────
        projects = await ctx.db.execute(
            select(FreelanceProject)
            .where(FreelanceProject.status == FreelanceProjectStatus.new)
            .limit(BATCH_SIZE)
        )
        projects = projects.scalars().all()

        if not projects:
            logger.info("bid_strategy.no_new_projects")
            return AgentResult(success=True, output={"scored": 0, "bids_queued": 0, "ignored": 0})

        # ── Get settings ─────────────────────────────────────────────────────────
        min_fit_score = int(ctx.settings.FREELANCE_MIN_FIT_SCORE or DEFAULT_MIN_FIT_SCORE)

        # ── Process each project ─────────────────────────────────────────────────
        scored = 0
        bids_queued = 0
        ignored = 0
        errors = 0

        for project in projects:
            try:
                # ── Generate Claude response ───────────────────────────────────────
                client = AsyncAnthropic(api_key=ctx.settings.ANTHROPIC_API_KEY)
                response = await client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=1024,
                    temperature=0.5,
                    system=_SYSTEM_PROMPT,
                    messages=[
                        {
                            "role": "user",
                            "content": _ANALYSIS_PROMPT.format(project_json=json.dumps(project.to_dict(), default=str)),
                        }
                    ],
                )

                result = json.loads(response.content[0].text)
                logger.info("bid_strategy.claude_response", project_id=project.id, response=result)

                # ── Update project with score and rationale ───────────────────────
                project.fit_score = result["fit_score"]
                project.fit_rationale = result["fit_rationale"]
                project.key_matching_skills = result["key_matching_skills"]

                # ── Generate cover letter using improved templates ─────────────────
                cover_letter = ""
                if result["should_bid"] and result["fit_score"] >= min_fit_score:
                    # Initialize template manager
                    template_manager = CoverLetterTemplateManager()

                    # Prepare project data for template context
                    project_data = project.to_dict()

                    # Determine platform - default to generic if not specified
                    platform = "generic"
                    if hasattr(project, 'platform') and project.platform:
                        platform = project.platform.lower()

                        # Map common platform names to our templates
                        platform_mapping = {
                            "freelancer": "freelancer",
                            "upwork": "upwork",
                            "guru": "guru",
                            "peopleperhour": "peopleperhour",
                            "freelancermap_de": "freelancermap_de"
                        }

                        if platform in platform_mapping:
                            platform = platform_mapping[platform]

                    # Special handling for healthcare projects
                    healthcare_keywords = ['healthcare', 'medical', 'hospital', 'clinic', 'health', 'patient', 'clinical', 'pharmacy', 'healthcare compliance', 'HIPAA', 'GDPR', 'compliance', 'security', 'cybersecurity']
                    is_healthcare_project = False

                    # Check in title and description with case-insensitive search
                    project_text = (project_data.get('title', '') + ' ' + project_data.get('description', '')).lower()
                    found_keywords = []

                    # More comprehensive healthcare detection - look for combinations of keywords
                    for keyword in healthcare_keywords:
                        if keyword.lower() in project_text:
                            is_healthcare_project = True
                            found_keywords.append(keyword)

                    # Additional check for common healthcare-related phrases
                    healthcare_phrases = [
                        'health information system',
                        'patient data',
                        'medical records',
                        'clinical information',
                        'health data protection',
                        'healthcare network'
                    ]

                    for phrase in healthcare_phrases:
                        if phrase.lower() in project_text:
                            is_healthcare_project = True
                            found_keywords.append(phrase)

                    # Log healthcare detection result for debugging
                    logger.info("Healthcare project detection",
                               project_title=project_data.get('title', ''),
                               is_healthcare=is_healthcare_project,
                               keywords_found=found_keywords)

                    if is_healthcare_project:
                        # Use the most comprehensive healthcare template available
                        template_manager = CoverLetterTemplateManager()
                        available_platforms = template_manager.get_available_platforms()

                        # Try to use the most comprehensive healthcare template first
                        if "healthcare_security_enhanced_v5" in available_platforms:
                            platform = "healthcare_security_enhanced_v5"
                        elif "healthcare_security_enhanced_v4" in available_platforms:
                            platform = "healthcare_security_enhanced_v4"
                        elif "healthcare_security_comprehensive_v2" in available_platforms:
                            platform = "healthcare_security_comprehensive_v2"
                        elif "healthcare_security_enhanced_v3" in available_platforms:
                            platform = "healthcare_security_enhanced_v3"
                        elif "healthcare_security_comprehensive" in available_platforms:
                            platform = "healthcare_security_comprehensive"
                        elif "healthcare_security_enhanced_v2" in available_platforms:
                            platform = "healthcare_security_enhanced_v2"
                        elif "healthcare_security_enhanced" in available_platforms:
                            platform = "healthcare_security_enhanced"
                        elif "healthcare_security_directive" in available_platforms:
                            platform = "healthcare_security_directive"
                        else:
                            # Fallback to the most basic healthcare template
                            platform = "healthcare_security"

                    # Enhance project data with additional context for better template matching
                    enhanced_project_data = {
                        **project_data,
                        "specific_result": result.get("cover_letter", "")[:50] + "...",
                        "timeframe": "project timeline",
                        "industry_sector": "healthcare/IT",
                        "measurable_outcome": "significant improvements in security and compliance",
                        "desired_outcome": "secure, compliant healthcare IT infrastructure",
                        "client_reference": "leading healthcare organizations",
                        "quantifiable_result": "measurable security improvements and compliance achievements",
                        "specific_benefit": "secure, HIPAA-compliant IT solutions",
                        "client_type": "healthcare organizations",
                        "similar_client": "healthcare providers and medical institutions",
                        "project_budget": project_data.get("budget", 0),
                        "project_duration": project_data.get("duration", "")
                    }

                    # Generate cover letter using templates
                    try:
                        cover_letter = template_manager.generate_cover_letter(
                            project_data=enhanced_project_data,
                            platform=platform,
                            freelancer_name="Anthony Stewart"
                        )

                        # If the generated cover letter is too short or looks like a fallback,
                        # use the Claude-generated version instead
                        if len(cover_letter.strip()) < 100 or "Could not generate" in cover_letter:
                            logger.warning("Template-based cover letter was too short or invalid, falling back to Claude")
                            cover_letter = result.get("cover_letter", "")

                        # Log the generated cover letter length for debugging
                        logger.info("Cover letter generation complete",
                                   platform=platform,
                                   cover_letter_length=len(cover_letter.strip()),
                                   cover_letter_preview=cover_letter[:200] + "..." if len(cover_letter) > 200 else cover_letter)
                    except Exception as e:
                        logger.warning(f"Error generating cover letter with template: {e}")
                        # Fall back to Claude-generated version if template fails
                        cover_letter = result.get("cover_letter", "")
                else:
                    # If not bidding, still generate a fallback cover letter using Claude
                    cover_letter = result.get("cover_letter", "")

                # ── Handle bid creation or ignore ─────────────────────────────────
                if result["should_bid"] and result["fit_score"] >= min_fit_score:
                    # ── Create PlatformBid record ────────────────────────────────
                    bid = PlatformBid(
                        project_id=project.id,
                        amount=result["recommended_bid_amount"],
                        delivery_days=result["recommended_delivery_days"],
                        cover_letter=cover_letter,
                        status=PlatformBidStatus.queued,
                    )
                    await ctx.db.add(bid)
                    project.status = FreelanceProjectStatus.bid_queued
                    bids_queued += 1
                else:
                    project.status = FreelanceProjectStatus.ignored
                    ignored += 1

                scored += 1

            except Exception as e:
                logger.error("bid_strategy.processing_error", project_id=project.id, error=str(e))
                errors += 1
                continue

        # ── Commit changes ───────────────────────────────────────────────────────
        await ctx.db.commit()

        return AgentResult(
            success=True,
            output={
                "scored": scored,
                "bids_queued": bids_queued,
                "ignored": ignored,
                "errors": errors,
            },
        )