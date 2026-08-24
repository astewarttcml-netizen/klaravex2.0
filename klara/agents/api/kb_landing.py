"""
app/api/kb_landing.py
──────────────────────
phase13-004 — public /kb HTML landing.

Server-rendered search page that consumes /api/v1/kb-public/search. No auth.
SEO-friendly meta + lightweight responsive layout. Single endpoint:

  GET /kb           (HTML)
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="description" content="Knowledge base — common IT issues and fixes from Klaravex." />
  <meta name="robots" content="index, follow" />
  <title>Knowledge base — Klaravex</title>
  <style>
    body { font-family: -apple-system, system-ui, sans-serif; max-width: 820px; margin: 0 auto; padding: 32px 24px; color: #1f2937; background: #fff; line-height: 1.5; }
    h1 { font-size: 28px; margin: 0 0 8px; }
    .subtitle { color: #6b7280; margin-bottom: 28px; }
    .search { display: flex; gap: 8px; margin-bottom: 24px; }
    .search input { flex: 1; padding: 10px 14px; font-size: 16px; border: 1px solid #d1d5db; border-radius: 6px; }
    .search button { padding: 10px 20px; background: #1f2937; color: white; border: 0; border-radius: 6px; font-size: 15px; cursor: pointer; }
    .search button:hover { background: #111827; }
    .result { padding: 16px 0; border-bottom: 1px solid #e5e7eb; }
    .result h3 { margin: 0 0 4px; font-size: 17px; color: #1f2937; }
    .result .meta { color: #6b7280; font-size: 13px; margin-bottom: 6px; }
    .result .body { color: #374151; }
    .empty { color: #9ca3af; font-style: italic; padding: 16px 0; }
    .footer { margin-top: 48px; padding-top: 16px; border-top: 1px solid #e5e7eb; color: #6b7280; font-size: 13px; }
    .footer a { color: #2563eb; text-decoration: none; }
  </style>
</head>
<body>
  <h1>Knowledge base</h1>
  <p class="subtitle">Common IT issues and fixes. Search below or browse common entries.</p>

  <form class="search" onsubmit="event.preventDefault(); doSearch();">
    <input id="q" type="search" placeholder="Search e.g. azure, intune, m365…" autofocus />
    <button type="submit">Search</button>
  </form>

  <div id="results"></div>

  <p class="footer">
    Powered by Klaravex · <a href="https://klaravex.de">klaravex.de</a>
  </p>

<script>
async function doSearch() {
  const q = document.getElementById('q').value.trim();
  const results = document.getElementById('results');
  if (!q) { results.innerHTML = ''; return; }
  results.innerHTML = '<p class="empty">Searching…</p>';
  try {
    const resp = await fetch('/api/v1/kb-public/search?q=' + encodeURIComponent(q));
    if (!resp.ok) {
      results.innerHTML = '<p class="empty">Search unavailable.</p>';
      return;
    }
    const data = await resp.json();
    if (!data.items || data.items.length === 0) {
      results.innerHTML = '<p class="empty">No matches for "' + q + '".</p>';
      return;
    }
    results.innerHTML = data.items.map(it => `
      <div class="result">
        <h3>${escapeHtml(it.product || 'General')}: ${escapeHtml(it.symptom || '')}</h3>
        <div class="meta">${escapeHtml(it.diagnosis || '')}</div>
        <div class="body">${escapeHtml((it.fix_steps_markdown || '').slice(0, 240))}${it.fix_steps_markdown && it.fix_steps_markdown.length > 240 ? '…' : ''}</div>
      </div>`).join('');
  } catch (e) {
    results.innerHTML = '<p class="empty">Search error.</p>';
  }
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
// auto-search if ?q= present
const params = new URLSearchParams(window.location.search);
const initialQ = params.get('q');
if (initialQ) { document.getElementById('q').value = initialQ; doSearch(); }
</script>
</body>
</html>
"""


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def kb_landing() -> HTMLResponse:
    return HTMLResponse(content=_PAGE_HTML)
