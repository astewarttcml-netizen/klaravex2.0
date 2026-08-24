"""
app/api/public_pricing.py
──────────────────────────
phase18-001 + 002 — public marketing pages.

  GET /pricing        HTML — three retainer tiers, transparent
  GET /case-studies   HTML — won-deal stories with case_study: marker
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


_PRICING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="description" content="Transparent pricing for Klaravex — Microsoft 365, Azure, Intune, and security retainer tiers for SME and mid-market clients." />
  <meta name="robots" content="index, follow" />
  <title>Pricing — Klaravex</title>
  <style>
    body { font-family: -apple-system, system-ui, sans-serif; max-width: 1100px; margin: 0 auto; padding: 32px 24px; color: #1f2937; background: #fff; line-height: 1.5; }
    h1 { font-size: 32px; margin: 0 0 8px; }
    .subtitle { color: #6b7280; margin-bottom: 32px; font-size: 17px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; }
    .tier { padding: 24px; background: #f9fafb; border-radius: 8px; border: 1px solid #e5e7eb; }
    .tier.featured { border: 2px solid #2563eb; }
    .tier-name { font-size: 18px; font-weight: 600; margin-bottom: 4px; }
    .tier-tag { color: #6b7280; font-size: 13px; margin-bottom: 16px; }
    .tier-price { font-size: 28px; font-weight: 700; margin-bottom: 4px; color: #1f2937; }
    .tier-suffix { color: #6b7280; font-size: 14px; margin-bottom: 16px; }
    .tier ul { padding-left: 18px; margin: 0 0 20px; }
    .tier li { margin: 8px 0; }
    .cta { display: block; text-align: center; padding: 12px 20px; background: #1f2937; color: white; text-decoration: none; border-radius: 6px; font-weight: 600; }
    .cta:hover { background: #111827; }
    .footer { margin-top: 48px; padding-top: 16px; border-top: 1px solid #e5e7eb; color: #6b7280; font-size: 13px; }
    .footer a { color: #2563eb; text-decoration: none; }
  </style>
</head>
<body>
  <h1>Pricing</h1>
  <p class="subtitle">Transparent monthly retainers — no setup fees, cancel anytime with 30 days notice.</p>
  <div class="grid">
    <div class="tier">
      <div class="tier-name">Starter</div>
      <div class="tier-tag">For teams of 5-20</div>
      <div class="tier-price">€675</div>
      <div class="tier-suffix">/month</div>
      <ul>
        <li>Microsoft 365 administration</li>
        <li>Email + endpoint security</li>
        <li>Monthly check-in call</li>
        <li>Business-hours email support</li>
      </ul>
      <a class="cta" href="https://klaravex.de/contact">Get started &rarr;</a>
    </div>
    <div class="tier featured">
      <div class="tier-name">Growth</div>
      <div class="tier-tag">For teams of 20-100</div>
      <div class="tier-price">€1,575</div>
      <div class="tier-suffix">/month</div>
      <ul>
        <li>Everything in Starter</li>
        <li>Intune device management</li>
        <li>Azure infrastructure oversight</li>
        <li>Quarterly strategy review</li>
        <li>Priority response (1 business day)</li>
      </ul>
      <a class="cta" href="https://klaravex.de/contact">Talk to Anthony &rarr;</a>
    </div>
    <div class="tier">
      <div class="tier-name">Scale</div>
      <div class="tier-tag">For teams of 100-500</div>
      <div class="tier-price">€3,375+</div>
      <div class="tier-suffix">/month, customised</div>
      <ul>
        <li>Everything in Growth</li>
        <li>Dedicated security review</li>
        <li>Compliance reporting (ISO/SOC)</li>
        <li>Monthly executive briefings</li>
        <li>Same-day priority response</li>
      </ul>
      <a class="cta" href="https://klaravex.de/contact">Request quote &rarr;</a>
    </div>
  </div>
  <p class="footer">
    Need something different? <a href="https://klaravex.de/contact">Get in touch</a> for a custom quote.
  </p>
</body>
</html>
"""


@router.get("/pricing", response_class=HTMLResponse, include_in_schema=False)
async def pricing_landing() -> HTMLResponse:
    return HTMLResponse(content=_PRICING_HTML)


class CaseStudyEntry(BaseModel):
    company: Optional[str]
    name: Optional[str]
    summary: Optional[str]


@router.get("/api/v1/case-studies-public", response_model=List[CaseStudyEntry])
async def case_studies_json(
    db: AsyncSession = Depends(get_db),
) -> List[CaseStudyEntry]:
    q = await db.execute(
        select(Lead).where(
            Lead.status == LeadStatus.won.value,
            Lead.notes.is_not(None),
        ).limit(20)
    )
    out: List[CaseStudyEntry] = []
    for lead in q.scalars():
        notes = (lead.notes or "").strip()
        if "case_study:" not in notes.lower():
            continue
        idx = notes.lower().find("case_study:")
        summary = notes[idx + len("case_study:"):].strip().split("\n")[0]
        if summary:
            out.append(CaseStudyEntry(
                company=lead.company,
                name=lead.name,
                summary=summary[:600],
            ))
    return out


_CASE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="description" content="Real client case studies from Klaravex. Microsoft 365, Azure, security and infrastructure transformations." />
  <meta name="robots" content="index, follow" />
  <title>Case studies — Klaravex</title>
  <style>
    body { font-family: -apple-system, system-ui, sans-serif; max-width: 820px; margin: 0 auto; padding: 32px 24px; color: #1f2937; line-height: 1.5; }
    h1 { font-size: 28px; margin: 0 0 8px; }
    .subtitle { color: #6b7280; margin-bottom: 28px; }
    .case { padding: 20px; background: #f9fafb; border-radius: 6px; margin: 16px 0; border-left: 4px solid #16a34a; }
    .case h3 { margin: 0 0 6px; font-size: 17px; }
    .case .meta { color: #6b7280; font-size: 13px; margin-bottom: 8px; }
    .empty { color: #9ca3af; font-style: italic; padding: 16px 0; }
    .footer { margin-top: 48px; padding-top: 16px; border-top: 1px solid #e5e7eb; color: #6b7280; font-size: 13px; }
    .footer a { color: #2563eb; text-decoration: none; }
  </style>
</head>
<body>
  <h1>Case studies</h1>
  <p class="subtitle">Real outcomes from real clients.</p>
  <div id="cases"><p class="empty">Loading&hellip;</p></div>
  <p class="footer">
    Could your team be next? <a href="/pricing">See pricing</a> or
    <a href="https://klaravex.de/contact">get in touch</a>.
  </p>
<script>
fetch('/api/v1/case-studies-public')
  .then(r => r.ok ? r.json() : [])
  .then(rows => {
    const root = document.getElementById('cases');
    if (!rows.length) {
      root.innerHTML = '<p class="empty">Case studies coming soon.</p>';
      return;
    }
    root.innerHTML = rows.map(c => `
      <div class="case">
        <h3>${escapeHtml(c.company || 'Client')}</h3>
        <div class="meta">${escapeHtml(c.name || '')}</div>
        <p>${escapeHtml(c.summary || '')}</p>
      </div>`).join('');
  });
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
</script>
</body>
</html>
"""


@router.get("/case-studies", response_class=HTMLResponse, include_in_schema=False)
async def case_studies_landing() -> HTMLResponse:
    return HTMLResponse(content=_CASE_HTML)
