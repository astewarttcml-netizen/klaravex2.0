"""
Resume analyzer — T6.3.2.

FastAPI router at /api/v1/resume/analyze.
Accepts either a multipart file upload (PDF or DOCX) or a raw text body.
Calls Anthropic API (claude-haiku-4-5-20251001 — cheapest appropriate model)
to extract structured fields from the resume text.

Returns:
    {
        "contact": {name, email, phone, location},
        "skills": [...],
        "experience_years": int,
        "current_role": str,
        "target_role": str,
        "gaps": [...],
        "raw_char_count": int
    }

Mount with:
    from infra.klara.handlers.resume_analyzer import router as resume_analyzer_router
    app.include_router(resume_analyzer_router, prefix="/api/v1/resume")
"""

import io
import json
import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .lib.rate_limit import limiter

log = logging.getLogger("klaravex.resume_analyzer")
router = APIRouter()

LITELLM_URL = os.environ.get("LITELLM_URL", "")
LITELLM_KEY = os.environ.get("LITELLM_MASTER_KEY", "")
MODEL = "deepseek"
MAX_TEXT_CHARS = 30_000  # ~7500 tokens — enough for any resume


def _extract_text_from_bytes(content: bytes, filename: str) -> str:
    """Best-effort text extraction for PDF/DOCX. Falls back to UTF-8 decode."""
    fname = (filename or "").lower()

    if fname.endswith(".pdf"):
        try:
            import pypdf  # optional dep

            reader = pypdf.PdfReader(io.BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages).strip()
        except Exception as e:
            log.warning("pypdf extraction failed (%s), falling back to raw decode: %s", fname, e)

    if fname.endswith(".docx"):
        try:
            import docx  # python-docx optional dep

            doc = docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs).strip()
        except Exception as e:
            log.warning("python-docx extraction failed (%s), falling back to raw decode: %s", fname, e)

    # Fallback: try UTF-8, then latin-1
    try:
        return content.decode("utf-8").strip()
    except UnicodeDecodeError:
        return content.decode("latin-1", errors="replace").strip()


_EXTRACTION_PROMPT = """\
You are a professional resume parser. Extract structured information from the resume text below.

Return ONLY a JSON object with these exact keys (no markdown, no explanation):
{
  "contact": {
    "name": "<full name or null>",
    "email": "<email or null>",
    "phone": "<phone or null>",
    "location": "<city/state/country or null>"
  },
  "skills": ["<skill1>", "<skill2>", ...],
  "experience_years": <integer, estimate total years of professional experience, 0 if unclear>,
  "current_role": "<most recent job title or null>",
  "target_role": "<inferred target role based on trajectory, or null>",
  "gaps": ["<gap1>", "<gap2>", ...]
}

The "gaps" field should list observable gaps relative to a strong professional profile
(e.g. missing metrics, no certifications, employment gaps, missing LinkedIn/portfolio, etc.).
Keep each gap to one concise sentence.

Resume text:
---
{resume_text}
---"""


async def _call_llm(resume_text: str) -> dict[str, Any]:
    if not (LITELLM_URL and LITELLM_KEY):
        raise HTTPException(status_code=503, detail="LiteLLM not configured")

    truncated = resume_text[:MAX_TEXT_CHARS]
    prompt = _EXTRACTION_PROMPT.format(resume_text=truncated)

    async with httpx.AsyncClient(timeout=90) as client:
        try:
            r = await client.post(
                f"{LITELLM_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {LITELLM_KEY}"},
                json={"model": MODEL, "max_tokens": 1024, "messages": [{"role": "user", "content": prompt}]},
            )
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"LLM error: {r.status_code}")
        except httpx.HTTPError as e:
            log.exception("LLM API error: %s", e)
            raise HTTPException(status_code=502, detail=f"LLM API error: {e}")

    raw = r.json()["choices"][0]["message"]["content"].strip()

    # Strip possible markdown code fence
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        parsed: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error("JSON parse failed on LLM response: %s\nRaw: %s", e, raw[:500])
        raise HTTPException(status_code=502, detail="Resume parser returned malformed JSON")

    parsed["raw_char_count"] = len(resume_text)
    return parsed


class TextResumeBody(BaseModel):
    text: str


@router.post("/analyze")
@limiter.limit("20/minute")
async def analyze_resume(
    request: Request,
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
) -> JSONResponse:
    """
    Analyze a resume. Supply either:
    - multipart `file` (PDF or DOCX), or
    - form field `text` with raw resume text.
    """
    resume_text: str = ""

    if file is not None:
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(status_code=422, detail="Uploaded file is empty")
        resume_text = _extract_text_from_bytes(content, file.filename or "")
    elif text:
        resume_text = text.strip()
    else:
        raise HTTPException(status_code=422, detail="Supply either 'file' (PDF/DOCX) or 'text' field")

    if not resume_text:
        raise HTTPException(status_code=422, detail="Could not extract text from the supplied input")

    result = await _call_llm(resume_text)
    return JSONResponse(content=result)
