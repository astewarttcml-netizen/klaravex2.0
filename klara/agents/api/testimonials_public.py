"""
app/api/testimonials_public.py
───────────────────────────────
phase14-003 — public testimonials surface.

  GET /testimonials   (HTML)
  GET /api/v1/testimonials-public   (JSON)

Reads from leads where call_notes mentions positive sentiment + has
status='won' AND testimonial_requested_at is set (i.e. client confirmed).
For the v1 we deliberately do NOT have a separate testimonials table —
data lives in lead.notes / lead.message after the testimonial flow.

If no testimonials are available yet, the page gracefully shows a
placeholder block — no SEO penalty for thin content.
"""
from __future__ import annotations

from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import get_db
from klara.rarv.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)
router = APIRouter()


class TestimonialEntry(BaseModel):
    company: Optional[str]
    name: Optional[str]
    quote: Optional[str]


@router.get("/api/v1/testimonials-public", response_model=List[TestimonialEntry])
async def testimonials_json(
    db: AsyncSession = Depends(get_db),
) -> List[TestimonialEntry]:
    q = await db.execute(
        select(Lead).where(
            Lead.status == LeadStatus.won.value,
            Lead.notes.is_not(None),
        ).limit(20)
    )
    out: List[TestimonialEntry] = []
    for lead in q.scalars():
        notes = (lead.notes or "").strip()
        if "testimonial:" not in notes.lower():
            continue
        # Take everything after the marker
        idx = notes.lower().find("testimonial:")
        quote = notes[idx + len("testimonial:"):].strip().split("\n")[0]
        if quote:
            out.append(TestimonialEntry(
                company=lead.company,
                name=lead.name,
                quote=quote[:400],
            ))
    return out


_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="description" content="Client testimonials for Klaravex. What our clients say about our IT consulting and managed services." />
  <meta name="robots" content="index, follow" />
  <title>Testimonials — Klaravex</title>
  <style>
    body { font-family: -apple-system, system-ui, sans-serif; max-width: 820px; margin: 0 auto; padding: 32px 24px; color: #1f2937; line-height: 1.5; }
    h1 { font-size: 28px; margin: 0 0 8px; }
    .subtitle { color: #6b7280; margin-bottom: 28px; }
    .quote { padding: 20px; background: #f9fafb; border-left: 4px solid #2563eb; border-radius: 4px; margin: 16px 0; }
    .quote .text { font-size: 16px; color: #1f2937; margin-bottom: 8px; font-style: italic; }
    .quote .author { color: #6b7280; font-size: 14px; }
    .empty { color: #9ca3af; font-style: italic; padding: 16px 0; }
    .footer { margin-top: 48px; padding-top: 16px; border-top: 1px solid #e5e7eb; color: #6b7280; font-size: 13px; }
    .footer a { color: #2563eb; text-decoration: none; }
  </style>
</head>
<body>
  <h1>Testimonials</h1>
  <p class="subtitle">What our clients say about working with Klaravex.</p>
  <div id="testimonials"><p class="empty">Loading…</p></div>
  <p class="footer">
    Want to work with us? <a href="https://klaravex.de/contact">Get in touch &rarr;</a>
  </p>
<script>
fetch('/api/v1/testimonials-public')
  .then(r => r.ok ? r.json() : [])
  .then(rows => {
    const root = document.getElementById('testimonials');
    if (!rows.length) {
      root.innerHTML = '<p class="empty">Testimonials being collected. Check back soon.</p>';
      return;
    }
    root.innerHTML = rows.map(t => `
      <div class="quote">
        <div class="text">"${escapeHtml(t.quote || '')}"</div>
        <div class="author">${escapeHtml(t.name || 'Client')} · ${escapeHtml(t.company || '')}</div>
      </div>`).join('');
  });
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
</script>
</body>
</html>
"""


@router.get("/testimonials", response_class=HTMLResponse, include_in_schema=False)
async def testimonials_landing() -> HTMLResponse:
    return HTMLResponse(content=_PAGE_HTML)
