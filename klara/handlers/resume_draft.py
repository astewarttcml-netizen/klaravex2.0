"""
Resume draft generator — T6.3.3.

FastAPI router at /api/v1/resume/draft.
Accepts an analysis dict (from resume_analyzer) + target_role + sku.
Calls Anthropic API (claude-haiku-4-5-20251001) to generate an improved
resume in Markdown format.

Returns:
    {
        "draft_markdown": str,
        "word_count": int
    }

Mount with:
    from infra.klara.handlers.resume_draft import router as resume_draft_router
    app.include_router(resume_draft_router, prefix="/api/v1/resume")
"""

import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("klaravex.resume_draft")
router = APIRouter()

LITELLM_URL = os.environ.get("LITELLM_URL", "")
LITELLM_KEY = os.environ.get("LITELLM_MASTER_KEY", "")
MODEL = "deepseek"


# SKU-based guidance for tone/depth
_SKU_GUIDANCE: dict[str, str] = {
    "resume-basic": (
        "Create a clean, concise, ATS-optimised resume. "
        "Target 1 page. Use standard sections: Summary, Skills, Experience, Education."
    ),
    "resume-premium": (
        "Create a polished, comprehensive resume with strong action verbs and quantified achievements. "
        "Target 1–2 pages. Include Summary, Core Competencies, Experience (with metrics), Education, Certifications."
    ),
    "resume-executive": (
        "Create an executive-level resume emphasising leadership impact, P&L ownership, and strategic initiatives. "
        "Target 2 pages. Include Executive Summary, Areas of Expertise, Career Timeline (detailed), Board/Advisory roles if any, Education."
    ),
}
_DEFAULT_GUIDANCE = _SKU_GUIDANCE["resume-premium"]


_DRAFT_PROMPT = """\
You are a professional resume writer with 15 years of experience placing candidates at top companies.

Your task: write an improved, professional resume in Markdown format for the candidate described below.

Target role: {target_role}
Tier guidance: {sku_guidance}

Candidate analysis:
- Name: {name}
- Current role: {current_role}
- Total experience: approximately {experience_years} years
- Key skills: {skills}
- Identified gaps to address (incorporate improvements subtly): {gaps}

Instructions:
1. Write the full resume in well-formatted Markdown (use ## for sections, - for bullets).
2. Address the identified gaps where possible (add metrics, action verbs, modern skill framing).
3. Do NOT invent employment dates, companies, or educational credentials — use placeholders like [Company Name], [Dates], [Degree] if unknown.
4. Keep the tone professional and achievement-focused.
5. Output ONLY the Markdown resume — no preamble, no explanation, no commentary.
"""


class ResumeDraftRequest(BaseModel):
    analysis: dict[str, Any] = Field(description="Output dict from /analyze endpoint")
    target_role: str = Field(min_length=2, max_length=200)
    sku: str = Field(default="resume-premium", description="resume-basic | resume-premium | resume-executive")


@router.post("/draft")
async def draft_resume(payload: ResumeDraftRequest) -> dict[str, Any]:
    """Generate an improved resume in Markdown from an analysis result."""
    if not (LITELLM_URL and LITELLM_KEY):
        raise HTTPException(status_code=503, detail="LiteLLM not configured")

    analysis = payload.analysis
    contact = analysis.get("contact") or {}
    sku_guidance = _SKU_GUIDANCE.get(payload.sku, _DEFAULT_GUIDANCE)

    prompt = _DRAFT_PROMPT.format(
        target_role=payload.target_role,
        sku_guidance=sku_guidance,
        name=contact.get("name") or "Candidate",
        current_role=analysis.get("current_role") or "Not specified",
        experience_years=analysis.get("experience_years") or 0,
        skills=", ".join(analysis.get("skills") or []) or "Not specified",
        gaps="; ".join(analysis.get("gaps") or []) or "None identified",
    )

    async with httpx.AsyncClient(timeout=90) as client:
        try:
            r = await client.post(
                f"{LITELLM_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {LITELLM_KEY}"},
                json={"model": MODEL, "max_tokens": 4096, "messages": [{"role": "user", "content": prompt}]},
            )
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"LLM error: {r.status_code}")
            message = r.json()
        except httpx.HTTPError as e:
            log.exception("LLM API error: %s", e)
            raise HTTPException(status_code=502, detail=f"LLM API error: {e}")

    draft_markdown = message["choices"][0]["message"]["content"].strip()
    word_count = len(draft_markdown.split())

    return {
        "draft_markdown": draft_markdown,
        "word_count": word_count,
    }
