"""
app/api/admin_dashboard.py
───────────────────────────
Admin dashboard — serves the single-page approval queue UI and captures
NPS survey scores.

Routes:
  GET  /admin               — self-contained HTML dashboard
  GET  /api/v1/survey/nps   — NPS click capture (no auth; email link target)

The dashboard is a single HTML page with no external dependencies.
It authenticates to the existing /api/v1/approvals/ endpoints via a
user-supplied API key stored in sessionStorage.

NPS capture:
  client_satisfaction.py sends emails with links like:
    GET /api/v1/survey/nps?lead_id=<uuid>&score=<0-10>
  This endpoint writes lead.satisfaction_score and returns a thank-you page.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from klara.rarv.runtime import get_db

import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── NPS survey capture ────────────────────────────────────────────────────────

@router.get("/api/v1/survey/nps", response_class=HTMLResponse, include_in_schema=False)
async def capture_nps_score(
    lead_id: str = Query(..., description="Lead UUID"),
    score: int = Query(..., ge=0, le=10, description="NPS score 0–10"),
    db: AsyncSession = Depends(get_db),
):
    """
    Click-through endpoint from NPS survey email links.
    Writes the score to leads.satisfaction_score and returns a thank-you page.
    No auth required — link is only sent to known clients and is one-time use
    (subsequent clicks update the score, which is acceptable).
    """
    from klara.rarv.lead import Lead

    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()

    if not lead:
        return HTMLResponse(_nps_page("error"), status_code=404)

    # Always write the latest score (client may revisit link)
    lead.satisfaction_score = float(score)
    await db.commit()

    logger.info("nps.score_captured", lead_id=lead_id, score=score)

    return HTMLResponse(_nps_page("thank_you", score=score))


def _nps_page(state: str, score: int = 0) -> str:
    if state == "error":
        body = """
          <div class="card error">
            <h2>Link not found</h2>
            <p>This survey link is invalid or has expired. If you believe
            this is an error, please contact us at
            <a href="mailto:hello@klaravex.de">hello@klaravex.de</a>.</p>
          </div>"""
        title = "Survey — Klaravex"
    else:
        emoji = "🙂" if score >= 9 else ("😐" if score >= 7 else "😟")
        color = "#2e7d32" if score >= 9 else ("#e65100" if score >= 7 else "#c62828")
        body = f"""
          <div class="card">
            <div class="score" style="color:{color};">{emoji} {score} / 10</div>
            <h2>Thank you for your feedback!</h2>
            <p>Your response has been recorded. We truly value your input and
            will use it to improve our service.</p>
            <p>If you'd like to share more details or speak with us,
            please reply to the survey email or reach us at
            <a href="mailto:hello@klaravex.de">hello@klaravex.de</a>.</p>
          </div>"""
        title = "Thank you — Klaravex"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="robots" content="noindex,nofollow">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:Arial,sans-serif;background:#f5f5f5;display:flex;
         align-items:center;justify-content:center;min-height:100vh;padding:20px}}
    .card{{background:#fff;border-radius:8px;padding:40px;max-width:480px;
           width:100%;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,.1)}}
    .card.error{{border-top:4px solid #c62828}}
    .score{{font-size:56px;margin-bottom:16px}}
    h2{{font-size:22px;margin-bottom:12px;color:#333}}
    p{{color:#555;line-height:1.6;margin-bottom:10px}}
    a{{color:#1565c0}}
  </style>
</head>
<body>{body}</body>
</html>"""


# ── Admin dashboard HTML ──────────────────────────────────────────────────────

@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_dashboard(request: Request):
    """
    Serve the self-contained admin approval dashboard.
    The page authenticates to /api/v1/approvals/ using a user-entered API key
    stored in sessionStorage — no server-side session needed.
    """
    return HTMLResponse(_DASHBOARD_HTML)


_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="robots" content="noindex,nofollow">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Klara AI — Approval Dashboard</title>
  <style>
    :root {
      --bg: #0f1117;
      --surface: #1a1d27;
      --surface2: #252836;
      --border: #2e3247;
      --text: #e2e4ef;
      --muted: #7a7f9a;
      --accent: #5c6bc0;
      --p3: #ef6c00;
      --p4: #c62828;
      --p5: #6a1b9a;
      --green: #2e7d32;
      --red-btn: #c62828;
      --radius: 8px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', Arial, sans-serif; background: var(--bg);
           color: var(--text); min-height: 100vh; }

    /* ── Auth overlay ── */
    #auth-overlay {
      position: fixed; inset: 0; background: var(--bg);
      display: flex; align-items: center; justify-content: center; z-index: 100;
    }
    #auth-overlay.hidden { display: none; }
    .auth-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 40px; width: 360px;
    }
    .auth-card h1 { font-size: 20px; margin-bottom: 8px; }
    .auth-card p { color: var(--muted); font-size: 13px; margin-bottom: 20px; }
    .auth-card input {
      width: 100%; padding: 10px 12px; background: var(--surface2);
      border: 1px solid var(--border); border-radius: 6px; color: var(--text);
      font-size: 14px; font-family: monospace; margin-bottom: 12px;
    }
    .auth-card input:focus { outline: 2px solid var(--accent); }
    .btn { padding: 10px 20px; border-radius: 6px; border: none; cursor: pointer;
           font-size: 14px; font-weight: 600; transition: opacity .15s; }
    .btn:hover { opacity: .85; }
    .btn-primary { background: var(--accent); color: #fff; width: 100%; }
    .btn-approve { background: var(--green); color: #fff; }
    .btn-reject  { background: var(--red-btn); color: #fff; }
    .btn-sm { padding: 6px 14px; font-size: 13px; }

    /* ── Layout ── */
    header {
      background: var(--surface); border-bottom: 1px solid var(--border);
      padding: 14px 24px; display: flex; align-items: center; gap: 16px;
    }
    header h1 { font-size: 18px; }
    header .sub { color: var(--muted); font-size: 13px; margin-left: auto; }
    #refresh-btn { background: var(--surface2); border: 1px solid var(--border);
                   color: var(--text); padding: 6px 14px; border-radius: 6px;
                   cursor: pointer; font-size: 13px; }
    #logout-btn  { background: none; border: 1px solid var(--border);
                   color: var(--muted); padding: 6px 14px; border-radius: 6px;
                   cursor: pointer; font-size: 13px; }

    /* ── Tabs ── */
    .tabs { display: flex; gap: 4px; padding: 16px 24px 0; border-bottom: 1px solid var(--border); }
    .tab {
      padding: 8px 16px; border-radius: 6px 6px 0 0; cursor: pointer;
      font-size: 14px; color: var(--muted); border: 1px solid transparent;
      border-bottom: none; position: relative; top: 1px;
    }
    .tab.active { background: var(--surface); border-color: var(--border);
                  color: var(--text); }
    .badge {
      display: inline-block; background: var(--accent); color: #fff;
      border-radius: 10px; padding: 1px 7px; font-size: 11px;
      font-weight: 700; margin-left: 6px;
    }
    .badge.red { background: var(--red-btn); }

    /* ── Content ── */
    #content { padding: 24px; max-width: 960px; }

    /* ── Approval card ── */
    .approval-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); margin-bottom: 16px; overflow: hidden;
      transition: border-color .15s;
    }
    .approval-card:hover { border-color: var(--accent); }
    .card-header {
      padding: 14px 16px; display: flex; align-items: center; gap: 12px;
      cursor: pointer;
    }
    .risk-badge {
      font-size: 12px; font-weight: 700; padding: 3px 9px; border-radius: 4px;
      flex-shrink: 0;
    }
    .risk-P3 { background: #bf360c; color: #fff; }
    .risk-P4 { background: #b71c1c; color: #fff; }
    .risk-P5 { background: #4a148c; color: #fff; }
    .card-action { font-size: 15px; font-weight: 600; }
    .card-meta { font-size: 12px; color: var(--muted); margin-left: auto;
                 text-align: right; }
    .card-body { padding: 0 16px 16px; display: none; }
    .card-body.open { display: block; }
    .field { margin-bottom: 10px; }
    .field label { font-size: 11px; color: var(--muted); text-transform: uppercase;
                   letter-spacing: .05em; display: block; margin-bottom: 4px; }
    .field value { font-size: 13px; display: block; word-break: break-word; }
    pre.payload {
      background: var(--surface2); border: 1px solid var(--border);
      border-radius: 6px; padding: 12px; font-size: 12px;
      white-space: pre-wrap; word-break: break-all; max-height: 200px;
      overflow-y: auto; color: #b0bec5; margin-bottom: 12px;
    }
    .card-actions { display: flex; gap: 8px; margin-top: 12px; }
    .status-badge { font-size: 12px; font-weight: 600; padding: 3px 9px;
                    border-radius: 4px; }
    .status-approved { background: #1b5e20; color: #a5d6a7; }
    .status-rejected { background: #4a0000; color: #ef9a9a; }
    .status-pending  { background: #1a237e; color: #9fa8da; }
    .status-expired  { background: #212121; color: #9e9e9e; }

    /* ── Empty state ── */
    .empty { text-align: center; color: var(--muted); padding: 60px 20px;
             font-size: 15px; }
    .loading { color: var(--muted); padding: 40px 0; text-align: center; }

    /* ── Modal ── */
    #modal-overlay {
      position: fixed; inset: 0; background: rgba(0,0,0,.65);
      display: flex; align-items: center; justify-content: center; z-index: 200;
    }
    #modal-overlay.hidden { display: none; }
    .modal {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 28px; width: 440px;
    }
    .modal h2 { font-size: 17px; margin-bottom: 6px; }
    .modal p { color: var(--muted); font-size: 13px; margin-bottom: 16px; }
    .modal input, .modal textarea {
      width: 100%; background: var(--surface2); border: 1px solid var(--border);
      border-radius: 6px; color: var(--text); font-size: 13px;
      padding: 9px 12px; margin-bottom: 12px; font-family: inherit;
    }
    .modal input:focus, .modal textarea:focus { outline: 2px solid var(--accent); }
    .modal textarea { resize: vertical; min-height: 72px; }
    .modal-actions { display: flex; gap: 10px; justify-content: flex-end; }
    .btn-cancel { background: var(--surface2); border: 1px solid var(--border);
                  color: var(--text); }

    /* ── Toast ── */
    #toast {
      position: fixed; bottom: 24px; right: 24px; background: var(--surface);
      border: 1px solid var(--border); border-radius: 8px; padding: 12px 20px;
      font-size: 14px; transition: opacity .3s; opacity: 0; pointer-events: none;
      z-index: 300;
    }
    #toast.show { opacity: 1; }
    #toast.success { border-left: 4px solid var(--green); }
    #toast.error   { border-left: 4px solid var(--red-btn); }

    /* ── Auto-refresh indicator ── */
    #refresh-indicator { font-size: 12px; color: var(--muted); }

    /* ── Leads tab ── */
    .leads-toolbar {
      display: flex; gap: 10px; align-items: center; margin-bottom: 16px;
      flex-wrap: wrap;
    }
    .leads-toolbar select, .leads-toolbar input {
      background: var(--surface2); border: 1px solid var(--border);
      border-radius: 6px; color: var(--text); padding: 7px 10px; font-size: 13px;
    }
    .leads-toolbar select:focus, .leads-toolbar input:focus {
      outline: 2px solid var(--accent);
    }
    .leads-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .leads-table th {
      text-align: left; padding: 8px 10px; color: var(--muted);
      font-size: 11px; text-transform: uppercase; letter-spacing: .05em;
      border-bottom: 1px solid var(--border); white-space: nowrap;
    }
    .leads-table td {
      padding: 10px 10px; border-bottom: 1px solid var(--border);
      vertical-align: middle;
    }
    .leads-table tr:hover td { background: var(--surface2); }
    .lead-status {
      display: inline-block; font-size: 11px; font-weight: 700;
      padding: 2px 8px; border-radius: 4px; white-space: nowrap;
    }
    .ls-new        { background: #1a237e; color: #9fa8da; }
    .ls-qualified  { background: #1b5e20; color: #a5d6a7; }
    .ls-disqualified { background: #4a0000; color: #ef9a9a; }
    .ls-discovery_done { background: #e65100; color: #ffe0b2; }
    .ls-proposal_sent  { background: #4a148c; color: #e1bee7; }
    .ls-won        { background: #1b5e20; color: #69f0ae; }
    .ls-lost       { background: #212121; color: #9e9e9e; }
    .ls-anonymised { background: #212121; color: #616161; }
    .score-pill {
      display: inline-block; font-size: 11px; font-weight: 700;
      padding: 2px 8px; border-radius: 10px; min-width: 34px; text-align: center;
    }
    .score-hi  { background: #1b5e20; color: #a5d6a7; }
    .score-mid { background: #e65100; color: #ffe0b2; }
    .score-lo  { background: #4a0000; color: #ef9a9a; }
    .score-nil { background: var(--surface2); color: var(--muted); }
    .btn-won {
      background: #1b5e20; color: #fff; font-size: 12px;
      padding: 5px 12px; border-radius: 5px; border: none; cursor: pointer;
      font-weight: 600; white-space: nowrap;
    }
    .btn-won:hover { opacity: .85; }
    .btn-won:disabled { opacity: .4; cursor: default; }
    .lead-name { font-weight: 600; }
    .lead-company { color: var(--muted); font-size: 12px; }
  </style>
</head>
<body>

<!-- Auth overlay -->
<div id="auth-overlay">
  <div class="auth-card">
    <h1>🔐 Klara AI Admin</h1>
    <p>Enter your API key to access the approval dashboard.</p>
    <input type="password" id="api-key-input" placeholder="API key" autocomplete="off">
    <button class="btn btn-primary" onclick="authenticate()">Sign In</button>
    <p id="auth-error" style="color:#ef5350;font-size:12px;margin-top:8px;display:none;">
      Invalid API key. Check your management key.</p>
  </div>
</div>

<!-- Approve/Reject modal -->
<div id="modal-overlay" class="hidden">
  <div class="modal">
    <h2 id="modal-title">Approve action?</h2>
    <p id="modal-subtitle"></p>
    <label style="font-size:12px;color:var(--muted);">YOUR NAME</label>
    <input type="text" id="modal-reviewer" value="Anthony" placeholder="Reviewer name">
    <label style="font-size:12px;color:var(--muted);">NOTE (optional)</label>
    <textarea id="modal-note" placeholder="Optional review note..."></textarea>
    <div class="modal-actions">
      <button class="btn btn-cancel" onclick="closeModal()">Cancel</button>
      <button class="btn" id="modal-confirm-btn" onclick="confirmModal()">Confirm</button>
    </div>
  </div>
</div>

<!-- Toast -->
<div id="toast"></div>

<!-- Main layout (hidden until authenticated) -->
<div id="main-layout" style="display:none;">
  <header>
    <h1>⚡ Klara AI Approval Dashboard</h1>
    <span id="refresh-indicator"></span>
    <span class="sub" id="header-sub"></span>
    <button id="refresh-btn" onclick="loadTab(currentTab, true)">↻ Refresh</button>
    <button id="logout-btn" onclick="logout()">Sign Out</button>
  </header>

  <div class="tabs">
    <div class="tab active" id="tab-pending" onclick="loadTab('pending')">
      Pending <span class="badge red" id="badge-pending">0</span>
    </div>
    <div class="tab" id="tab-approved" onclick="loadTab('approved')">
      Approved <span class="badge" id="badge-approved"></span>
    </div>
    <div class="tab" id="tab-rejected" onclick="loadTab('rejected')">
      Rejected <span class="badge" id="badge-rejected"></span>
    </div>
    <div class="tab" id="tab-leads" onclick="loadTab('leads')">
      Leads <span class="badge" id="badge-leads"></span>
    </div>
    <div class="tab" id="tab-sequences" onclick="loadTab('sequences')">
      Sequences <span class="badge red" id="badge-sequences"></span>
    </div>
    <div class="tab" id="tab-funnel" onclick="loadTab('funnel')">
      Funnel <span class="badge" id="badge-funnel"></span>
    </div>
    <div class="tab" id="tab-intel" onclick="loadTab('intel')">
      Intelligence <span class="badge" id="badge-intel"></span>
    </div>
    <div class="tab" id="tab-content" onclick="loadTab('content')">
      Content <span class="badge" id="badge-content"></span>
    </div>
    <div class="tab" id="tab-audit" onclick="loadTab('audit')">
      Audit <span class="badge" id="badge-audit"></span>
    </div>
    <div class="tab" id="tab-ops" onclick="loadTab('ops')">
      Ops <span class="badge" id="badge-ops"></span>
    </div>
    <div class="tab" id="tab-cost" onclick="loadTab('cost')">
      Cost <span class="badge" id="badge-cost"></span>
    </div>
    <div class="tab" id="tab-quality" onclick="loadTab('quality')">
      Quality <span class="badge" id="badge-quality"></span>
    </div>
    <div class="tab" id="tab-experiments" onclick="loadTab('experiments')">
      Experiments <span class="badge" id="badge-experiments"></span>
    </div>
    <div class="tab" id="tab-contracts" onclick="loadTab('contracts')">
      Contracts <span class="badge" id="badge-contracts"></span>
    </div>
    <div class="tab" id="tab-inbox" onclick="loadTab('inbox')">
      Inbox <span class="badge" id="badge-inbox"></span>
    </div>
    <div class="tab" id="tab-linkedin" onclick="loadTab('linkedin')">
      LinkedIn <span class="badge" id="badge-linkedin"></span>
    </div>
  </div>

  <div id="content">
    <div class="loading" id="loading-msg">Loading…</div>
    <div id="approval-list"></div>
  </div>
</div>

<script>
  // ── State ──────────────────────────────────────────────────────────────────
  const API_KEY_KEY = 'loki_api_key';
  let currentTab = 'pending';
  let pendingModal = null;    // { approvalId, action }
  let refreshTimer = null;
  let refreshCountdown = 60;

  // ── Auth ───────────────────────────────────────────────────────────────────
  async function authenticate() {
    const key = document.getElementById('api-key-input').value.trim();
    if (!key) return;
    // Test the key against the approvals endpoint
    const resp = await fetch('/api/v1/approvals/?status_filter=pending&limit=1', {
      headers: { 'X-API-Key': key }
    });
    if (resp.ok) {
      sessionStorage.setItem(API_KEY_KEY, key);
      document.getElementById('auth-overlay').classList.add('hidden');
      document.getElementById('main-layout').style.display = 'block';
      loadTab('pending');
      startAutoRefresh();
    } else {
      document.getElementById('auth-error').style.display = 'block';
    }
  }

  function logout() {
    sessionStorage.removeItem(API_KEY_KEY);
    clearInterval(refreshTimer);
    document.getElementById('auth-overlay').classList.remove('hidden');
    document.getElementById('main-layout').style.display = 'none';
    document.getElementById('api-key-input').value = '';
  }

  function apiKey() { return sessionStorage.getItem(API_KEY_KEY) || ''; }

  // On page load — check if key already stored
  window.onload = () => {
    const key = sessionStorage.getItem(API_KEY_KEY);
    if (key) {
      document.getElementById('auth-overlay').classList.add('hidden');
      document.getElementById('main-layout').style.display = 'block';
      loadTab('pending');
      startAutoRefresh();
    }
    document.getElementById('api-key-input').addEventListener('keydown', e => {
      if (e.key === 'Enter') authenticate();
    });
  };

  // ── Auto-refresh ───────────────────────────────────────────────────────────
  function startAutoRefresh() {
    clearInterval(refreshTimer);
    refreshCountdown = 60;
    updateCountdown();
    refreshTimer = setInterval(() => {
      refreshCountdown--;
      updateCountdown();
      if (refreshCountdown <= 0) {
        if (currentTab === 'pending') loadTab('pending', false);
        refreshCountdown = 60;
      }
    }, 1000);
  }

  function updateCountdown() {
    document.getElementById('refresh-indicator').textContent =
      currentTab === 'pending' ? `Auto-refresh in ${refreshCountdown}s` : '';
  }

  // ── Tabs ───────────────────────────────────────────────────────────────────
  async function loadTab(tab, showLoading = true) {
    currentTab = tab;
    ['pending','approved','rejected','leads','sequences','funnel','intel','content','audit','ops','cost','quality','experiments','contracts','inbox','linkedin'].forEach(t => {
      document.getElementById(`tab-${t}`).classList.toggle('active', t === tab);
    });
    if (tab === 'pending') { refreshCountdown = 60; updateCountdown(); }
    else document.getElementById('refresh-indicator').textContent = '';

    if (tab === 'leads')     { await loadLeadsTab(showLoading);     return; }
    if (tab === 'sequences') { await loadSequencesTab(showLoading); return; }
    if (tab === 'funnel')    { await loadFunnelTab(showLoading);    return; }
    if (tab === 'intel')     { await loadIntelTab(showLoading);     return; }
    if (tab === 'content')   { await loadContentTab(showLoading);   return; }
    if (tab === 'audit')     { await loadAuditTab(showLoading);     return; }
    if (tab === 'ops')       { await loadOpsTab(showLoading);       return; }
    if (tab === 'cost')      { await loadCostTab(showLoading);      return; }
    if (tab === 'quality')   { await loadQualityTab(showLoading);   return; }
    if (tab === 'experiments') { await loadExperimentsTab(showLoading); return; }
    if (tab === 'contracts')   { await loadContractsTab(showLoading); return; }
    if (tab === 'inbox')       { await loadInboxTab(showLoading);     return; }
    if (tab === 'linkedin')    { await loadLinkedinTab(showLoading);  return; }

    if (showLoading) {
      document.getElementById('approval-list').innerHTML = '';
      document.getElementById('loading-msg').style.display = 'block';
    }

    const limit = tab === 'pending' ? 100 : 50;
    const resp = await fetch(
      `/api/v1/approvals/?status_filter=${tab}&limit=${limit}`,
      { headers: { 'X-API-Key': apiKey() } }
    );
    document.getElementById('loading-msg').style.display = 'none';

    if (!resp.ok) { showToast('Failed to load approvals.', 'error'); return; }
    const items = await resp.json();

    // Update badge
    const badge = document.getElementById(`badge-${tab}`);
    if (items.length > 0) { badge.textContent = items.length; badge.style.display = ''; }
    else { badge.textContent = ''; badge.style.display = 'none'; }

    // Update pending badge always
    if (tab === 'pending') {
      document.getElementById('header-sub').textContent =
        items.length > 0 ? `${items.length} action${items.length>1?'s':''} awaiting review` : '';
    }

    renderApprovals(items, tab);
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  function renderApprovals(items, tab) {
    const list = document.getElementById('approval-list');
    if (items.length === 0) {
      list.innerHTML = `<div class="empty">✅ No ${tab} approvals</div>`;
      return;
    }
    list.innerHTML = items.map(a => renderCard(a, tab)).join('');
  }

  function renderCard(a, tab) {
    const riskClass = `risk-${a.risk_level}`;
    const age = timeSince(a.created_at);
    const expires = a.expires_at ? `Expires ${timeSince(a.expires_at, true)}` : '';
    const statusHtml = tab !== 'pending'
      ? `<span class="status-badge status-${a.status}">${a.status}</span>` : '';
    const actionsHtml = tab === 'pending' ? `
      <div class="card-actions">
        <button class="btn btn-approve btn-sm" onclick="openModal('${a.id}','approve','${esc(a.action_name)}')">
          ✓ Approve
        </button>
        <button class="btn btn-reject btn-sm" onclick="openModal('${a.id}','reject','${esc(a.action_name)}')">
          ✗ Reject
        </button>
      </div>` : '';

    return `
    <div class="approval-card" id="card-${a.id}">
      <div class="card-header" onclick="toggleCard('${a.id}')">
        <span class="risk-badge ${riskClass}">${a.risk_level}</span>
        <span class="card-action">${esc(a.action_name)}</span>
        ${statusHtml}
        <span class="card-meta">
          ${esc(a.requested_by_agent)}<br>
          <span style="font-size:11px;">${age}${expires ? ' · '+expires : ''}</span>
        </span>
      </div>
      <div class="card-body" id="body-${a.id}">
        <div class="field">
          <label>Justification</label>
          <value>${esc(a.justification || '—')}</value>
        </div>
        ${a.lead_id ? `<div class="field"><label>Lead ID</label><value><code>${esc(a.lead_id)}</code></value></div>` : ''}
        <div class="field">
          <label>Payload</label>
          <pre class="payload" id="payload-${a.id}">Loading…</pre>
        </div>
        ${actionsHtml}
      </div>
    </div>`;
  }

  async function toggleCard(id) {
    const body = document.getElementById(`body-${id}`);
    const isOpen = body.classList.contains('open');
    if (isOpen) { body.classList.remove('open'); return; }
    body.classList.add('open');
    // Lazy-load payload
    const pre = document.getElementById(`payload-${id}`);
    if (pre.textContent === 'Loading…') {
      const resp = await fetch(`/api/v1/approvals/${id}`, {
        headers: { 'X-API-Key': apiKey() }
      });
      if (resp.ok) {
        const d = await resp.json();
        try {
          pre.textContent = JSON.stringify(JSON.parse(d.payload), null, 2);
        } catch {
          pre.textContent = d.payload;
        }
      } else {
        pre.textContent = `Error: ${resp.status}`;
      }
    }
  }

  // ── Modal ──────────────────────────────────────────────────────────────────
  function openModal(id, action, actionName) {
    pendingModal = { approvalId: id, action };
    const isApprove = action === 'approve';
    document.getElementById('modal-title').textContent =
      isApprove ? `Approve: ${actionName}?` : `Reject: ${actionName}?`;
    document.getElementById('modal-subtitle').textContent =
      isApprove
        ? 'This action will be dispatched to Celery immediately after approval.'
        : 'The action will be cancelled and logged.';
    const btn = document.getElementById('modal-confirm-btn');
    btn.textContent = isApprove ? 'Approve' : 'Reject';
    btn.className = `btn ${isApprove ? 'btn-approve' : 'btn-reject'}`;
    document.getElementById('modal-note').value = '';
    document.getElementById('modal-overlay').classList.remove('hidden');
    document.getElementById('modal-reviewer').focus();
  }

  function closeModal() {
    document.getElementById('modal-overlay').classList.add('hidden');
    pendingModal = null;
  }

  async function confirmModal() {
    if (!pendingModal) return;
    const { approvalId, action } = pendingModal;
    const reviewer = document.getElementById('modal-reviewer').value.trim() || 'Anthony';
    const note = document.getElementById('modal-note').value.trim();
    closeModal();

    const resp = await fetch(`/api/v1/approvals/${approvalId}/${action}`, {
      method: 'POST',
      headers: { 'X-API-Key': apiKey(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ reviewed_by: reviewer, note: note || null }),
    });

    if (resp.ok) {
      showToast(`Action ${action}d ✓`, 'success');
      // Animate card removal
      const card = document.getElementById(`card-${approvalId}`);
      if (card) { card.style.opacity = '0.3'; card.style.transition = 'opacity .4s'; }
      setTimeout(() => loadTab(currentTab, false), 600);
    } else {
      const err = await resp.json().catch(() => ({}));
      showToast(`Error: ${err.detail || resp.status}`, 'error');
    }
  }

  // Keyboard shortcuts
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
  });

  // ── Leads tab ──────────────────────────────────────────────────────────────
  let leadsData = [];          // cache from last fetch
  let leadsStatusFilter = '';  // '' = all active, or specific status string
  let leadsSearch = '';        // name / email / company filter (client-side)

  const ACTIONABLE_STATUSES = ['new','qualified','discovery_done','proposal_sent'];

  async function loadLeadsTab(showLoading = true) {
    const list = document.getElementById('approval-list');
    const loadingMsg = document.getElementById('loading-msg');

    if (showLoading) {
      list.innerHTML = '';
      loadingMsg.style.display = 'block';
    }

    // Build query: fetch up to 200 leads.
    // status_filter param matches leads.py list_leads query param name.
    let url = '/api/v1/leads/?limit=200';
    if (leadsStatusFilter) url += `&status_filter=${encodeURIComponent(leadsStatusFilter)}`;

    const resp = await fetch(url, { headers: { 'X-API-Key': apiKey() } });
    loadingMsg.style.display = 'none';

    if (!resp.ok) { showToast('Failed to load leads.', 'error'); return; }
    leadsData = await resp.json();

    // Update badge — show count of actionable leads (not won/lost/anonymised)
    const actionable = leadsData.filter(l => ACTIONABLE_STATUSES.includes(l.status));
    const badge = document.getElementById('badge-leads');
    if (actionable.length > 0) { badge.textContent = actionable.length; badge.style.display = ''; }
    else { badge.textContent = ''; badge.style.display = 'none'; }

    renderLeadsTab();
  }

  function renderLeadsTab() {
    const list = document.getElementById('approval-list');

    // Client-side search filter
    const q = leadsSearch.toLowerCase();
    const filtered = leadsData.filter(l => {
      if (!q) return true;
      return (l.name||'').toLowerCase().includes(q)
          || (l.email||'').toLowerCase().includes(q)
          || (l.company||'').toLowerCase().includes(q);
    });

    if (filtered.length === 0) {
      list.innerHTML = `
        <div style="margin-bottom:14px;">${leadsToolbarHTML()}</div>
        <div class="empty">No leads match your filter.</div>`;
      bindLeadsToolbar();
      return;
    }

    // Sort: actionable first (by score desc), then won/lost
    const order = { new:0, qualified:1, discovery_done:2, proposal_sent:3,
                    won:4, lost:5, disqualified:6, anonymised:7 };
    filtered.sort((a,b) => {
      const oa = order[a.status] ?? 9, ob = order[b.status] ?? 9;
      if (oa !== ob) return oa - ob;
      return (b.score || 0) - (a.score || 0);
    });

    list.innerHTML = `
      <div class="leads-toolbar" id="leads-toolbar">${leadsToolbarHTML()}</div>
      <div style="overflow-x:auto;">
        <table class="leads-table">
          <thead>
            <tr>
              <th>Lead</th>
              <th>Status</th>
              <th>Score</th>
              <th>Source</th>
              <th>Created</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            ${filtered.map(renderLeadRow).join('')}
          </tbody>
        </table>
      </div>`;
    bindLeadsToolbar();
  }

  function leadsToolbarHTML() {
    return `
      <select id="leads-status-filter" onchange="onLeadsFilterChange()" style="min-width:140px;">
        <option value=""   ${leadsStatusFilter===''?'selected':''}>All leads</option>
        <option value="new"            ${leadsStatusFilter==='new'?'selected':''}>New</option>
        <option value="qualified"      ${leadsStatusFilter==='qualified'?'selected':''}>Qualified</option>
        <option value="discovery_done" ${leadsStatusFilter==='discovery_done'?'selected':''}>Discovery done</option>
        <option value="proposal_sent"  ${leadsStatusFilter==='proposal_sent'?'selected':''}>Proposal sent</option>
        <option value="won"            ${leadsStatusFilter==='won'?'selected':''}>Won</option>
        <option value="lost"           ${leadsStatusFilter==='lost'?'selected':''}>Lost</option>
      </select>
      <input type="text" id="leads-search-input" placeholder="Search name / email / company…"
             value="${esc(leadsSearch)}" style="flex:1;min-width:180px;"
             oninput="onLeadsSearchInput(this.value)">
      <button style="background:var(--surface2);border:1px solid var(--border);color:var(--text);
                     padding:7px 14px;border-radius:6px;cursor:pointer;font-size:13px;"
              onclick="loadLeadsTab(true)">↻ Refresh</button>`;
  }

  function bindLeadsToolbar() {
    // nothing — inline handlers handle it
  }

  function onLeadsFilterChange() {
    const sel = document.getElementById('leads-status-filter');
    if (sel) { leadsStatusFilter = sel.value; loadLeadsTab(false); }
  }

  function onLeadsSearchInput(val) {
    leadsSearch = val;
    renderLeadsTab();
  }

  function renderLeadRow(l) {
    const scoreClass = l.score == null ? 'score-nil'
                     : l.score >= 70 ? 'score-hi'
                     : l.score >= 40 ? 'score-mid' : 'score-lo';
    const scoreLabel = l.score != null ? Math.round(l.score) : '—';
    const created = new Date(l.created_at).toLocaleDateString('en-GB',
                    { day:'2-digit', month:'short', year:'numeric' });

    const canMarkWon = ACTIONABLE_STATUSES.includes(l.status);
    const wonBtn = canMarkWon
      ? `<button class="btn-won" id="won-btn-${l.id}"
                 onclick="markWon('${l.id}', this)">✓ Mark won</button>`
      : `<span style="color:var(--muted);font-size:12px;">${l.status==='won'?'Won ✓':''}</span>`;

    return `
      <tr>
        <td>
          <div class="lead-name">${esc(l.name || '—')}</div>
          <div class="lead-company">${esc(l.email || '')}${l.company ? ' · '+esc(l.company) : ''}</div>
        </td>
        <td><span class="lead-status ls-${l.status}">${l.status.replace('_',' ')}</span></td>
        <td><span class="score-pill ${scoreClass}">${scoreLabel}</span></td>
        <td style="color:var(--muted);">${esc(l.source || '')}</td>
        <td style="color:var(--muted);white-space:nowrap;">${created}</td>
        <td>${wonBtn}</td>
      </tr>`;
  }

  async function markWon(leadId, btn) {
    // Confirm before firing
    if (!confirm(`Mark this lead as WON?\n\nThis will:\n• Set lead status → won\n• Queue a client onboarding email for your approval\n• Create a portal account for the client`)) return;

    btn.disabled = true;
    btn.textContent = '…';

    const resp = await fetch(`/api/v1/admin/deals/${leadId}/mark-won`, {
      method: 'POST',
      headers: { 'X-API-Key': apiKey(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ notes: null }),
    });

    if (resp.ok) {
      const data = await resp.json();
      btn.textContent = '✓ Won';
      btn.style.background = '#2e7d32';
      btn.disabled = true;
      showToast('Lead marked won — onboarding email queued for approval ✓', 'success');
      // Update local cache so the status badge changes immediately
      const lead = leadsData.find(l => l.id === leadId);
      if (lead) lead.status = 'won';
      // Refresh badges
      const actionable = leadsData.filter(l => ACTIONABLE_STATUSES.includes(l.status));
      const badge = document.getElementById('badge-leads');
      badge.textContent = actionable.length > 0 ? actionable.length : '';
      badge.style.display = actionable.length > 0 ? '' : 'none';
    } else {
      btn.disabled = false;
      btn.textContent = '✓ Mark won';
      const err = await resp.json().catch(() => ({}));
      showToast(`Error: ${err.detail || resp.status}`, 'error');
    }
  }

  // ── Toast ──────────────────────────────────────────────────────────────────
  function showToast(msg, type = 'success') {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = `show ${type}`;
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.remove('show'), 3500);
  }

  // ── Utilities ─────────────────────────────────────────────────────────────
  function esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function timeSince(isoStr, future = false) {
    const d = new Date(isoStr);
    const diff = Math.abs(Date.now() - d.getTime());
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return future ? `in ${mins}m` : `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return future ? `in ${hrs}h` : `${hrs}h ago`;
    return future ? `in ${Math.floor(hrs/24)}d` : `${Math.floor(hrs/24)}d ago`;
  }

  // ── Outreach Sequences tab (phase3-005) ──────────────────────────────────────
  let sequencesData = [];

  // phase21-003: read &prospect=<id> from window.location.hash so jump-links
  // from the Inbox tab (phase19-009) can land on the matching sequence card.
  // Returns null when the param is absent or malformed.
  function readProspectFilterFromHash() {
    const hash = (window.location.hash || '').replace(/^#/, '');
    if (!hash) return null;
    const params = new URLSearchParams(hash);
    const id = params.get('prospect');
    // Defensive: only return values that look UUID-shaped to avoid
    // injecting arbitrary attribute matchers downstream.
    if (id && /^[0-9a-fA-F-]{8,}$/.test(id)) return id;
    return null;
  }

  async function loadSequencesTab(showLoading = true) {
    if (showLoading) {
      document.getElementById('approval-list').innerHTML = '';
      document.getElementById('loading-msg').style.display = 'block';
    }
    const resp = await fetch(
      '/api/v1/admin/outreach-sequences?status=pending_approval&limit=50',
      { headers: { 'X-API-Key': apiKey() } }
    );
    document.getElementById('loading-msg').style.display = 'none';
    if (!resp.ok) {
      showToast('Failed to load outreach sequences.', 'error');
      return;
    }
    sequencesData = await resp.json();

    const badge = document.getElementById('badge-sequences');
    if (sequencesData.length > 0) {
      badge.textContent = sequencesData.length;
      badge.style.display = '';
    } else {
      badge.textContent = '';
      badge.style.display = 'none';
    }

    renderSequencesTab();
  }

  function renderSequencesTab() {
    const list = document.getElementById('approval-list');

    // phase21-003: prospect filter from URL hash. When a prospect param is
    // present, narrow the list and surface a "clear filter" affordance so
    // the operator can return to the full view without typing.
    const prospectFilter = readProspectFilterFromHash();
    const rows = prospectFilter
      ? sequencesData.filter(s => s.prospect_id === prospectFilter)
      : sequencesData;

    if (rows.length === 0) {
      const msg = prospectFilter
        ? `<div class="empty">No pending sequences for prospect ${prospectFilter}. <a href="#tab=sequences" onclick="clearProspectFilter();return false;">Clear filter</a></div>`
        : '<div class="empty">No outreach sequences awaiting approval.</div>';
      list.innerHTML = msg;
      return;
    }

    const banner = prospectFilter
      ? `<div style="background:#1a1a1a;padding:8px 12px;border-radius:4px;margin-bottom:10px;font-size:12px;color:#aaa;">
           Filtered to prospect <code>${prospectFilter}</code> · ${rows.length} sequence(s) ·
           <a href="#tab=sequences" onclick="clearProspectFilter();return false;" style="color:#4fc3f7;">Clear filter</a>
         </div>`
      : '';

    list.innerHTML = banner + rows.map(renderSequenceRow).join('');

    // Scroll the (single) filtered card into view + briefly highlight it.
    if (prospectFilter && rows.length > 0) {
      // Defer to next frame so the DOM is painted before we measure.
      requestAnimationFrame(() => {
        const card = list.querySelector(`[data-sequence-id="${rows[0].sequence_id}"]`);
        if (card) {
          card.scrollIntoView({ behavior: 'smooth', block: 'center' });
          card.style.transition = 'box-shadow 0.5s ease';
          card.style.boxShadow = '0 0 0 2px #4fc3f7';
          setTimeout(() => { card.style.boxShadow = ''; }, 2500);
        }
      });
    }
  }

  window.clearProspectFilter = function() {
    window.location.hash = 'tab=sequences';
    renderSequencesTab();
  };

  function renderSequenceRow(s) {
    const company = esc(s.company_name || '(unknown company)');
    const email   = esc(s.contact_email || '');
    const first   = esc(s.contact_first || '');
    const sched   = s.scheduled_at ? timeSince(s.scheduled_at) : '';
    const subj    = esc(s.subject_en || s.subject_de || '(no subject)');
    return `
      <div class="approval-card" data-sequence-id="${esc(s.sequence_id)}">
        <div class="approval-header">
          <div>
            <div class="approval-action">Day-${s.step_number} outreach follow-up · ${company}</div>
            <div class="approval-meta">${first} &lt;${email}&gt; · scheduled ${sched}</div>
            <div class="approval-meta"><em>Subject:</em> ${subj}</div>
          </div>
          <div class="approval-actions">
            <button class="btn btn-success" onclick="sequenceAction('${esc(s.sequence_id)}', 'approve', this)">Approve sequence</button>
            <button class="btn btn-danger"  onclick="sequenceAction('${esc(s.sequence_id)}', 'reject',  this)">Reject</button>
          </div>
        </div>
      </div>
    `;
  }

  async function sequenceAction(sequenceId, action, btn) {
    if (btn) btn.disabled = true;
    const resp = await fetch(
      `/api/v1/admin/outreach-sequences/${sequenceId}/${action}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey() },
        body: JSON.stringify({ reviewed_by: 'admin@dashboard' }),
      }
    );
    if (!resp.ok) {
      showToast(`Failed to ${action} sequence.`, 'error');
      if (btn) btn.disabled = false;
      return;
    }
    const result = await resp.json();
    showToast(
      action === 'approve'
        ? `Approved — ${result.affected_steps} step(s) will be sent on next sweep.`
        : `Rejected — ${result.affected_steps} step(s) cancelled.`,
      'success'
    );
    // Refresh the list
    setTimeout(() => loadSequencesTab(false), 400);
  }

  // ── Funnel tab (phase5-005) ────────────────────────────────────────────────
  let funnelWindowDays = 30;

  async function loadFunnelTab(showLoading = true) {
    if (showLoading) {
      document.getElementById('approval-list').innerHTML = '';
      document.getElementById('loading-msg').style.display = 'block';
    }
    const resp = await fetch(
      `/api/v1/admin/funnel-analytics?window_days=${funnelWindowDays}`,
      { headers: { 'X-API-Key': apiKey() } }
    );
    document.getElementById('loading-msg').style.display = 'none';
    if (!resp.ok) { showToast('Failed to load funnel analytics.', 'error'); return; }
    const data = await resp.json();
    renderFunnel(data);
  }

  // ── Intelligence tab (phase7-002) ──────────────────────────────────────────
  async function loadIntelTab(showLoading = true) {
    if (showLoading) {
      document.getElementById('approval-list').innerHTML = '';
      document.getElementById('loading-msg').style.display = 'block';
    }
    const headers = { 'X-API-Key': apiKey() };
    const [revResp, healthResp, upsellResp] = await Promise.all([
      fetch('/api/v1/admin/client-intelligence/revenue', { headers }),
      fetch('/api/v1/admin/client-intelligence/health',  { headers }),
      fetch('/api/v1/admin/client-intelligence/upsell',  { headers }),
    ]);
    document.getElementById('loading-msg').style.display = 'none';

    const safe = async (r) => (r.ok ? await r.json() : { error: r.status });
    const rev = await safe(revResp);
    const health = await safe(healthResp);
    const upsell = await safe(upsellResp);

    document.getElementById('approval-list').innerHTML = `
      <h3 style="margin:18px 0 8px;">Revenue snapshot</h3>
      <pre style="background:#1a1a1a;padding:10px;border-radius:6px;overflow:auto;font-size:12px;">${JSON.stringify(rev, null, 2)}</pre>
      <h3 style="margin:18px 0 8px;">Client health</h3>
      <pre style="background:#1a1a1a;padding:10px;border-radius:6px;overflow:auto;font-size:12px;">${JSON.stringify(health, null, 2)}</pre>
      <h3 style="margin:18px 0 8px;">Upsell opportunities</h3>
      <pre style="background:#1a1a1a;padding:10px;border-radius:6px;overflow:auto;font-size:12px;">${JSON.stringify(upsell, null, 2)}</pre>`;
  }

  // ── Content tab (phase7-004) ───────────────────────────────────────────────
  async function loadContentTab(showLoading = true) {
    if (showLoading) {
      document.getElementById('approval-list').innerHTML = '';
      document.getElementById('loading-msg').style.display = 'block';
    }
    const resp = await fetch('/api/v1/admin/phase7/content-calendar', { headers: { 'X-API-Key': apiKey() } });
    document.getElementById('loading-msg').style.display = 'none';
    const data = resp.ok ? await resp.json() : { error: resp.status };
    document.getElementById('approval-list').innerHTML = `
      <h3 style="margin:18px 0 8px;">Content calendar — next 14 days</h3>
      <pre style="background:#1a1a1a;padding:10px;border-radius:6px;overflow:auto;font-size:12px;">${JSON.stringify(data, null, 2)}</pre>`;
  }

  // ── Audit tab (phase7-005) ─────────────────────────────────────────────────
  let auditFilter = { event_type: '', agent: '', days: 7 };

  async function loadAuditTab(showLoading = true) {
    if (showLoading) {
      document.getElementById('approval-list').innerHTML = '';
      document.getElementById('loading-msg').style.display = 'block';
    }
    const params = new URLSearchParams({
      days: auditFilter.days,
      limit: 100,
    });
    if (auditFilter.event_type) params.set('event_type', auditFilter.event_type);
    if (auditFilter.agent)      params.set('agent',      auditFilter.agent);

    const resp = await fetch(`/api/v1/admin/audit-timeline?${params}`, { headers: { 'X-API-Key': apiKey() } });
    document.getElementById('loading-msg').style.display = 'none';
    if (!resp.ok) { showToast('Failed to load audit timeline.', 'error'); return; }
    const data = await resp.json();
    renderAudit(data);
  }

  function renderAudit(data) {
    const items = data.items || [];
    const rows = items.map(i => `
      <tr style="border-bottom:1px solid #222;">
        <td style="padding:4px;font-size:11px;color:#888;">${new Date(i.created_at).toLocaleString()}</td>
        <td style="padding:4px;font-weight:600;">${i.event_type}</td>
        <td style="padding:4px;color:#aaa;">${i.agent_name || ''}</td>
        <td style="padding:4px;color:#aaa;">${i.action_name || ''}</td>
        <td style="padding:4px;font-family:monospace;font-size:11px;">${(i.lead_id || '').slice(0,8)}</td>
      </tr>`).join('');
    document.getElementById('approval-list').innerHTML = `
      <div style="margin-bottom:12px;display:flex;gap:8px;">
        <input id="audit-event-filter"  placeholder="event_type filter (optional)" value="${auditFilter.event_type}" style="padding:4px;background:#222;color:#ddd;border:1px solid #333;border-radius:4px;" />
        <input id="audit-agent-filter"  placeholder="agent filter (optional)"      value="${auditFilter.agent}"      style="padding:4px;background:#222;color:#ddd;border:1px solid #333;border-radius:4px;" />
        <select id="audit-days-select" style="padding:4px;background:#222;color:#ddd;border:1px solid #333;border-radius:4px;">
          <option value="1"  ${auditFilter.days === 1 ? 'selected' : ''}>1 day</option>
          <option value="7"  ${auditFilter.days === 7 ? 'selected' : ''}>7 days</option>
          <option value="30" ${auditFilter.days === 30 ? 'selected' : ''}>30 days</option>
          <option value="90" ${auditFilter.days === 90 ? 'selected' : ''}>90 days</option>
        </select>
        <button onclick="applyAuditFilters()">Apply</button>
        <span style="margin-left:auto;color:#777;font-size:12px;">${data.total} total entries</span>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr style="border-bottom:1px solid #333;">
          <th style="text-align:left;padding:4px;">When</th>
          <th style="text-align:left;padding:4px;">Event</th>
          <th style="text-align:left;padding:4px;">Agent</th>
          <th style="text-align:left;padding:4px;">Action</th>
          <th style="text-align:left;padding:4px;">Lead</th>
        </tr></thead>
        <tbody>${rows || '<tr><td colspan="5" style="padding:12px;color:#666;">No entries in window.</td></tr>'}</tbody>
      </table>`;
  }

  // ── Inbox tab (phase19-004) ────────────────────────────────────────────────
  let inboxCategory = "";
  async function loadInboxTab(showLoading = true) {
    if (showLoading) {
      document.getElementById('approval-list').innerHTML = '';
      document.getElementById('loading-msg').style.display = 'block';
    }
    const url = '/api/v1/admin/inbound-emails' + (inboxCategory ? `?category=${inboxCategory}` : '');
    const resp = await fetch(url, { headers: { 'X-API-Key': apiKey() } });
    document.getElementById('loading-msg').style.display = 'none';
    if (!resp.ok) { showToast('Failed to load inbox.', 'error'); return; }
    const data = await resp.json();
    const rows = (data.items || []).map(i => `
      <tr style="border-bottom:1px solid #222;">
        <td style="padding:6px;font-size:11px;color:#888;">${new Date(i.received_at).toLocaleString()}</td>
        <td style="padding:6px;font-weight:600;">${i.from_email}</td>
        <td style="padding:6px;">${(i.subject || '').slice(0,60)}</td>
        <td style="padding:6px;"><span style="padding:2px 8px;background:#222;border-radius:10px;font-size:11px;">${i.category || '—'}</span></td>
        <td style="padding:6px;">${renderMatchedProspectChip(i)}</td>
        <td style="padding:6px;color:#aaa;font-size:12px;">${(i.summary || '').slice(0,80)}</td>
      </tr>`).join('');
    document.getElementById('approval-list').innerHTML = `
      <div style="margin-bottom:12px;">
        Filter:
        <select onchange="inboxCategory = this.value; loadInboxTab(false);">
          <option value="" ${inboxCategory === "" ? 'selected' : ''}>All (${data.total})</option>
          <option value="vendor_bill">vendor_bill</option>
          <option value="prospect_referral">prospect_referral</option>
          <option value="support_question">support_question</option>
          <option value="personal">personal</option>
          <option value="spam">spam</option>
          <option value="other">other</option>
        </select>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr style="border-bottom:1px solid #333;">
          <th style="text-align:left;padding:6px;">Received</th>
          <th style="text-align:left;padding:6px;">From</th>
          <th style="text-align:left;padding:6px;">Subject</th>
          <th style="text-align:left;padding:6px;">Category</th>
          <th style="text-align:left;padding:6px;">Matched prospect</th>
          <th style="text-align:left;padding:6px;">Summary</th>
        </tr></thead>
        <tbody>${rows || '<tr><td colspan="6" style="padding:12px;color:#666;">No emails.</td></tr>'}</tbody>
      </table>`;
  }

  // ── phase19-009: matched-prospect chip + jump-to-sequence link ────────────
  // Renders nothing when matched_prospect_id is null (defensive — most inbox
  // rows aren't tied to a prospect). When present: company chip + a "View
  // sequence" link that opens the Outreach tab filtered to that prospect_id.
  // Suppression count badge appears next to the chip when phase19-006 fired
  // at least once for that prospect.
  function renderMatchedProspectChip(i) {
    if (!i.matched_prospect_id) {
      return '<span style="color:#444;font-size:12px;">—</span>';
    }
    const company = (i.matched_prospect_company || '(unknown company)').slice(0, 40);
    const suppression = (i.suppression_count > 0)
      ? `<span title="Follow-ups auto-cancelled by phase19-006" style="margin-left:6px;padding:1px 6px;border-radius:8px;background:#3b2e0e;color:#ffb74d;font-size:10px;">×${i.suppression_count} suppressed</span>`
      : '';
    return `
      <span style="display:inline-block;padding:2px 8px;background:#0e2a3b;color:#4fc3f7;border-radius:10px;font-size:11px;font-weight:600;">
        ${company}
      </span>
      <a href="#tab=sequences&prospect=${i.matched_prospect_id}"
         onclick="event.preventDefault(); jumpToProspectSequence('${i.matched_prospect_id}');"
         style="margin-left:6px;font-size:11px;color:#4fc3f7;text-decoration:underline;">
        View sequence
      </a>
      ${suppression}`;
  }

  // Switch to the Sequences tab and let phase21-003's hash filter
  // narrow the list to the matching prospect_id, scroll the card into
  // view, and apply a yellow highlight.
  window.jumpToProspectSequence = function(prospectId) {
    window.location.hash = `tab=sequences&prospect=${prospectId}`;
    if (typeof loadTab === 'function') {
      loadTab('sequences');
    }
  };

  // ── LinkedIn tab (phase20-004) ─────────────────────────────────────────────
  async function loadLinkedinTab(showLoading = true) {
    if (showLoading) {
      document.getElementById('approval-list').innerHTML = '';
      document.getElementById('loading-msg').style.display = 'block';
    }
    const resp = await fetch('/api/v1/admin/linkedin-drafts', { headers: { 'X-API-Key': apiKey() } });
    document.getElementById('loading-msg').style.display = 'none';
    if (!resp.ok) { showToast('Failed to load LinkedIn drafts.', 'error'); return; }
    const drafts = await resp.json();
    const cards = drafts.map(d => `
      <div style="background:#1a1a1a;padding:12px;border-radius:6px;margin:8px 0;">
        <div style="display:flex;justify-content:space-between;">
          <div>
            <strong>${d.company || '—'}</strong>
            <span style="color:#888;font-size:12px;margin-left:8px;">${d.contact_name || ''}</span>
          </div>
          <span style="padding:2px 8px;background:#222;border-radius:10px;font-size:11px;">${d.status}</span>
        </div>
        ${d.contact_linkedin ? `<a href="${d.contact_linkedin}" target="_blank" style="font-size:12px;">${d.contact_linkedin}</a>` : ''}
        <pre id="draft-${d.id}" style="background:#0a0a0a;padding:10px;border-radius:4px;font-family:inherit;white-space:pre-wrap;margin:8px 0;font-size:13px;">${d.draft_body}</pre>
        <div style="display:flex;gap:8px;">
          <button onclick="copyDraft('${d.id}')">Copy</button>
          ${d.status === 'draft' ? `<button onclick="markSent('${d.id}')">Mark sent</button>` : ''}
          ${d.status === 'sent' ? `<button onclick="logReply('${d.id}')">Log reply</button>` : ''}
        </div>
      </div>`).join('');
    document.getElementById('approval-list').innerHTML = `
      <h3 style="margin:18px 0 8px;">LinkedIn drafts</h3>
      ${cards || '<p style="color:#666;padding:16px;">No drafts queued. Daily sweep at 12:00 CET will populate.</p>'}`;
  }
  window.copyDraft = function(id) {
    const el = document.getElementById('draft-' + id);
    if (el) { navigator.clipboard.writeText(el.textContent); showToast('Copied to clipboard'); }
  };
  window.markSent = async function(id) {
    const resp = await fetch(`/api/v1/admin/linkedin-drafts/${id}/mark-sent`, {
      method: 'POST', headers: { 'X-API-Key': apiKey() },
    });
    if (resp.ok) { showToast('Marked sent'); loadLinkedinTab(false); }
  };
  window.logReply = async function(id) {
    const reply = prompt('Paste the reply text:');
    if (!reply) return;
    const resp = await fetch(`/api/v1/admin/linkedin-drafts/${id}/log-reply`, {
      method: 'POST', headers: { 'X-API-Key': apiKey(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ reply_text: reply }),
    });
    if (resp.ok) { showToast('Reply logged'); loadLinkedinTab(false); }
  };

  // ── Contracts tab (phase17-004) ────────────────────────────────────────────
  let contractStatusFilter = "";
  async function loadContractsTab(showLoading = true) {
    if (showLoading) {
      document.getElementById('approval-list').innerHTML = '';
      document.getElementById('loading-msg').style.display = 'block';
    }
    const url = '/api/v1/admin/contracts' + (contractStatusFilter ? `?status=${contractStatusFilter}` : '');
    const resp = await fetch(url, { headers: { 'X-API-Key': apiKey() } });
    document.getElementById('loading-msg').style.display = 'none';
    if (!resp.ok) { showToast('Failed to load contracts.', 'error'); return; }
    const rows = await resp.json();
    const html = rows.map(c => `
      <tr style="border-bottom:1px solid #222;">
        <td style="padding:6px;font-size:11px;color:#888;">${new Date(c.created_at).toLocaleString()}</td>
        <td style="padding:6px;font-weight:600;">${c.company || '—'}</td>
        <td style="padding:6px;">${c.contact_email || '—'}</td>
        <td style="padding:6px;">
          <span style="padding:2px 8px;background:#222;border-radius:10px;font-size:12px;">${c.status}</span>
        </td>
      </tr>`).join('');
    document.getElementById('approval-list').innerHTML = `
      <div style="margin-bottom:12px;">
        Filter:
        <select onchange="contractStatusFilter = this.value; loadContractsTab(false);">
          <option value="" ${contractStatusFilter === "" ? 'selected' : ''}>All</option>
          <option value="pending"  ${contractStatusFilter === "pending"  ? 'selected' : ''}>Pending</option>
          <option value="approved" ${contractStatusFilter === "approved" ? 'selected' : ''}>Approved</option>
          <option value="rejected" ${contractStatusFilter === "rejected" ? 'selected' : ''}>Rejected</option>
        </select>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr style="border-bottom:1px solid #333;">
          <th style="text-align:left;padding:6px;">Created</th>
          <th style="text-align:left;padding:6px;">Company</th>
          <th style="text-align:left;padding:6px;">Contact</th>
          <th style="text-align:left;padding:6px;">Status</th>
        </tr></thead>
        <tbody>${html || '<tr><td colspan="4" style="padding:12px;color:#666;">No contracts.</td></tr>'}</tbody>
      </table>`;
  }

  // ── Experiments tab (phase14-005) ──────────────────────────────────────────
  async function loadExperimentsTab(showLoading = true) {
    if (showLoading) {
      document.getElementById('approval-list').innerHTML = '';
      document.getElementById('loading-msg').style.display = 'block';
    }
    const resp = await fetch('/api/v1/admin/experiments', { headers: { 'X-API-Key': apiKey() } });
    document.getElementById('loading-msg').style.display = 'none';
    if (!resp.ok) { showToast('Failed to load experiments.', 'error'); return; }
    const experiments = await resp.json();
    if (!experiments.length) {
      document.getElementById('approval-list').innerHTML =
        '<p style="color:#666;padding:16px;">No experiments running yet. Create one via the API.</p>';
      return;
    }
    const rows = experiments.map(e => `
      <div style="background:#1a1a1a;padding:12px;border-radius:6px;margin:8px 0;">
        <div style="display:flex;justify-content:space-between;">
          <div>
            <strong>${e.name}</strong>
            <span style="color:#888;font-size:12px;margin-left:8px;">(${e.status})</span>
          </div>
          <div style="color:#aaa;font-size:13px;">${e.arm_count} arms · ${e.total_assignments} assignments</div>
        </div>
        <div style="color:#888;font-size:12px;margin-top:4px;">${e.description || ''}</div>
      </div>`).join('');
    document.getElementById('approval-list').innerHTML = `
      <h3 style="margin:18px 0 8px;">Active experiments</h3>${rows}`;
  }

  // ── Quality tab (phase12-004) ──────────────────────────────────────────────
  async function loadQualityTab(showLoading = true) {
    if (showLoading) {
      document.getElementById('approval-list').innerHTML = '';
      document.getElementById('loading-msg').style.display = 'block';
    }
    const resp = await fetch('/api/v1/admin/quality?window_days=14', { headers: { 'X-API-Key': apiKey() } });
    document.getElementById('loading-msg').style.display = 'none';
    if (!resp.ok) { showToast('Failed to load quality data.', 'error'); return; }
    const data = await resp.json();
    const agentRows = (data.by_agent || []).map(a => {
      const color = a.avg_score >= 4 ? '#4caf50' : (a.avg_score >= 3 ? '#ffc107' : '#e57373');
      return `
        <tr style="border-bottom:1px solid #222;">
          <td style="padding:4px;font-weight:600;">${a.agent_name}</td>
          <td style="padding:4px;">${a.sample_count}</td>
          <td style="padding:4px;color:${color};font-weight:600;">${a.avg_score.toFixed(2)}</td>
          <td style="padding:4px;">${a.score_5}/${a.score_4}/${a.score_3}/${a.score_2}/${a.score_1}</td>
        </tr>`;
    }).join('');
    const lowRows = (data.recent_low_scores || []).map(s => `
      <tr style="border-bottom:1px solid #222;">
        <td style="padding:4px;font-size:11px;color:#888;">${new Date(s.judged_at).toLocaleString()}</td>
        <td style="padding:4px;font-weight:600;">${s.agent_name}</td>
        <td style="padding:4px;color:#e57373;font-weight:600;">${s.score}</td>
        <td style="padding:4px;color:#aaa;font-size:12px;">${s.reason || ''}</td>
      </tr>`).join('');
    document.getElementById('approval-list').innerHTML = `
      <h3 style="margin:18px 0 8px;">Agent quality — last 14 days</h3>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr style="border-bottom:1px solid #333;">
          <th style="text-align:left;padding:4px;">Agent</th>
          <th style="text-align:left;padding:4px;">Samples</th>
          <th style="text-align:left;padding:4px;">Avg score</th>
          <th style="text-align:left;padding:4px;">5/4/3/2/1</th>
        </tr></thead>
        <tbody>${agentRows || '<tr><td colspan="4" style="padding:12px;color:#666;">No quality samples yet — sweep runs daily 04:30 CET.</td></tr>'}</tbody>
      </table>
      <h3 style="margin:24px 0 8px;">Recent low scores (≤2)</h3>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr style="border-bottom:1px solid #333;">
          <th style="text-align:left;padding:4px;">When</th>
          <th style="text-align:left;padding:4px;">Agent</th>
          <th style="text-align:left;padding:4px;">Score</th>
          <th style="text-align:left;padding:4px;">Reason</th>
        </tr></thead>
        <tbody>${lowRows || '<tr><td colspan="4" style="padding:12px;color:#666;">No low scores in window.</td></tr>'}</tbody>
      </table>`;
  }

  // ── Cost tab (phase9-004) ──────────────────────────────────────────────────
  let costWindowDays = 30;

  async function loadCostTab(showLoading = true) {
    if (showLoading) {
      document.getElementById('approval-list').innerHTML = '';
      document.getElementById('loading-msg').style.display = 'block';
    }
    const resp = await fetch(
      `/api/v1/admin/llm-cost?window_days=${costWindowDays}`,
      { headers: { 'X-API-Key': apiKey() } }
    );
    document.getElementById('loading-msg').style.display = 'none';
    if (!resp.ok) { showToast('Failed to load LLM cost.', 'error'); return; }
    const data = await resp.json();

    const agentRows = (data.by_agent || []).map(a => `
      <tr style="border-bottom:1px solid #222;">
        <td style="padding:4px;font-weight:600;">${a.agent_name}</td>
        <td style="padding:4px;">${a.call_count}</td>
        <td style="padding:4px;">${a.input_tokens.toLocaleString()}</td>
        <td style="padding:4px;">${a.output_tokens.toLocaleString()}</td>
        <td style="padding:4px;font-weight:600;">€${a.cost_eur.toFixed(4)}</td>
      </tr>`).join('');

    const dayRows = (data.by_day || []).slice(-30).map(d => `
      <tr style="border-bottom:1px solid #222;">
        <td style="padding:4px;font-family:monospace;">${d.day}</td>
        <td style="padding:4px;">${d.call_count}</td>
        <td style="padding:4px;">€${d.cost_eur.toFixed(4)}</td>
      </tr>`).join('');

    document.getElementById('approval-list').innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <div>
          Window:
          <select onchange="costWindowDays = parseInt(this.value); loadCostTab(false);">
            <option value="7"  ${costWindowDays === 7 ? 'selected' : ''}>7 days</option>
            <option value="30" ${costWindowDays === 30 ? 'selected' : ''}>30 days</option>
            <option value="90" ${costWindowDays === 90 ? 'selected' : ''}>90 days</option>
          </select>
        </div>
        <div style="font-size:18px;font-weight:600;">
          Total: <span style="color:#4caf50;">€${(data.total_cost_eur || 0).toFixed(4)}</span>
          <span style="color:#888;font-size:13px;font-weight:400;">across ${data.total_calls} calls</span>
        </div>
      </div>
      <h3 style="margin:18px 0 8px;">By agent</h3>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr style="border-bottom:1px solid #333;">
          <th style="text-align:left;padding:4px;">Agent</th>
          <th style="text-align:left;padding:4px;">Calls</th>
          <th style="text-align:left;padding:4px;">Input tok</th>
          <th style="text-align:left;padding:4px;">Output tok</th>
          <th style="text-align:left;padding:4px;">Cost</th>
        </tr></thead>
        <tbody>${agentRows || '<tr><td colspan="5" style="padding:12px;color:#666;">No LLM calls in window.</td></tr>'}</tbody>
      </table>
      <h3 style="margin:24px 0 8px;">By day</h3>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr style="border-bottom:1px solid #333;">
          <th style="text-align:left;padding:4px;">Day</th>
          <th style="text-align:left;padding:4px;">Calls</th>
          <th style="text-align:left;padding:4px;">Cost</th>
        </tr></thead>
        <tbody>${dayRows || '<tr><td colspan="3" style="padding:12px;color:#666;">No daily data.</td></tr>'}</tbody>
      </table>`;
  }

  // ── Ops tab (phase8-004) ───────────────────────────────────────────────────
  // phase21-002: configurable window for the outreach-analytics widget.
  // 30d is the default to match the phase19-008 endpoint's default.
  let outreachWindowDays = 30;

  async function loadOpsTab(showLoading = true) {
    if (showLoading) {
      document.getElementById('approval-list').innerHTML = '';
      document.getElementById('loading-msg').style.display = 'block';
    }
    const headers = { 'X-API-Key': apiKey() };
    const [agentsResp, autonomyResp, analyticsResp] = await Promise.all([
      fetch('/api/v1/admin/agent-metrics?window_days=7', { headers }),
      fetch('/api/v1/admin/autonomy-metrics',            { headers }),
      fetch(`/api/v1/admin/outreach-analytics?days=${outreachWindowDays}`, { headers }),
    ]);
    document.getElementById('loading-msg').style.display = 'none';
    const agents    = agentsResp.ok    ? await agentsResp.json()    : { error: agentsResp.status };
    const autonomy  = autonomyResp.ok  ? await autonomyResp.json()  : { error: autonomyResp.status };
    const analytics = analyticsResp.ok ? await analyticsResp.json() : { error: analyticsResp.status };

    const agentRows = (agents.agents || []).slice(0, 25).map(a => `
      <tr style="border-bottom:1px solid #222;">
        <td style="padding:4px;font-weight:600;">${a.agent_name}</td>
        <td style="padding:4px;">${a.total_invocations}</td>
        <td style="padding:4px;color:#4caf50;">${a.success_count}</td>
        <td style="padding:4px;color:${a.failure_count > 0 ? '#e57373' : '#666'};">${a.failure_count}</td>
        <td style="padding:4px;">${(a.success_rate * 100).toFixed(1)}%</td>
        <td style="padding:4px;font-size:11px;color:#888;">${a.last_run_at ? new Date(a.last_run_at).toLocaleString() : '—'}</td>
      </tr>`).join('');

    document.getElementById('approval-list').innerHTML = `
      <h3 style="margin:18px 0 8px;">Agent metrics — last 7 days</h3>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr style="border-bottom:1px solid #333;">
          <th style="text-align:left;padding:4px;">Agent</th>
          <th style="text-align:left;padding:4px;">Total</th>
          <th style="text-align:left;padding:4px;">Success</th>
          <th style="text-align:left;padding:4px;">Failure</th>
          <th style="text-align:left;padding:4px;">Rate</th>
          <th style="text-align:left;padding:4px;">Last run</th>
        </tr></thead>
        <tbody>${agentRows || '<tr><td colspan="6" style="padding:12px;color:#666;">No agent activity in window.</td></tr>'}</tbody>
      </table>
      <h3 style="margin:24px 0 8px;">Autonomy gates — last 30 days (phase3-003)</h3>
      ${renderAutonomyMetrics(autonomy)}
      <h3 style="margin:24px 0 8px;">
        Outreach analytics — last ${outreachWindowDays} days (phase19-008)
        ${renderOutreachWindowToggle()}
      </h3>
      ${renderOutreachAnalytics(analytics)}`;
  }

  // ── phase21-002: outreach-analytics widget ────────────────────────────────
  // Renders the phase19-008 funnel as a horizontal bar chart with
  // conversion-rate labels between stages, plus a rate-card row beneath.
  // 7d / 14d / 30d / 90d window toggle reloads loadOpsTab.
  function renderOutreachWindowToggle() {
    const opts = [7, 14, 30, 90];
    const buttons = opts.map(d => {
      const active = (d === outreachWindowDays);
      const style = active
        ? 'background:#4fc3f7;color:#000;font-weight:600;'
        : 'background:#222;color:#888;';
      return `<button onclick="setOutreachWindow(${d})" style="${style}margin-left:4px;padding:2px 8px;border:none;border-radius:3px;font-size:11px;cursor:pointer;">${d}d</button>`;
    }).join('');
    return `<span style="font-size:11px;font-weight:normal;margin-left:8px;">${buttons}</span>`;
  }

  window.setOutreachWindow = function(days) {
    outreachWindowDays = days;
    loadOpsTab(false);
  };

  function renderOutreachAnalytics(analytics) {
    if (!analytics || analytics.error) {
      return `<div style="padding:10px;color:#e57373;">Outreach analytics unavailable (HTTP ${analytics && analytics.error ? analytics.error : '?'}).</div>`;
    }
    const f = analytics.funnel || {};
    const r = analytics.rates  || {};

    // Funnel stages in order. The bar widths are scaled to the largest
    // stage (sequences_started) so visual length encodes drop-off.
    const stages = [
      { key: 'sequences_started', label: 'Sequences started', count: f.sequences_started || 0 },
      { key: 'step_2_sent',       label: 'Step 2 (Day-3)',    count: f.step_2_sent       || 0 },
      { key: 'step_3_sent',       label: 'Step 3 (Day-7)',    count: f.step_3_sent       || 0 },
      { key: 'step_4_sent',       label: 'Step 4 (Day-14)',   count: f.step_4_sent       || 0 },
      { key: 'replies',           label: 'Replies',           count: f.replies           || 0 },
      { key: 'bookings',          label: 'Bookings',          count: f.bookings          || 0 },
    ];
    const max = Math.max(1, ...stages.map(s => s.count));

    const stageRows = stages.map((s, i) => {
      const pct = Math.round((s.count / max) * 100);
      const prev = i > 0 ? stages[i - 1].count : null;
      const conv = (prev !== null && prev > 0)
        ? `<span style="font-size:11px;color:#888;margin-left:8px;">${((s.count / prev) * 100).toFixed(1)}% from ${stages[i-1].label.split(' ')[0].toLowerCase()}</span>`
        : '';
      return `
        <div style="margin:6px 0;">
          <div style="display:flex;justify-content:space-between;font-size:13px;">
            <span><strong>${s.label}</strong>${conv}</span>
            <span>${s.count}</span>
          </div>
          <div style="background:#1a1a1a;height:14px;border-radius:3px;overflow:hidden;">
            <div style="background:#4fc3f7;width:${pct}%;height:100%;"></div>
          </div>
        </div>`;
    }).join('');

    // Rate cards: open / click / reply / booking with green-tinting when
    // reply_rate clears the 5% benchmark (industry-standard for cold B2B
    // outreach; below that the sequence is structurally underperforming).
    const REPLY_RATE_GREEN = 0.05;
    const pct = (n) => ((n || 0) * 100).toFixed(2) + '%';
    const tone = (val, threshold) => (val >= threshold) ? '#4caf50' : '#888';
    const card = (label, val, tonecolor) => `
      <div style="flex:1;background:#1a1a1a;padding:10px;border-radius:6px;text-align:center;min-width:90px;">
        <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.5px;">${label}</div>
        <div style="font-size:18px;font-weight:600;color:${tonecolor};margin-top:4px;">${pct(val)}</div>
      </div>`;
    const cards = `
      <div style="display:flex;gap:8px;margin-top:14px;">
        ${card('Open rate',    r.open_rate,    '#4fc3f7')}
        ${card('Click rate',   r.click_rate,   '#4fc3f7')}
        ${card('Reply rate',   r.reply_rate,   tone(r.reply_rate || 0, REPLY_RATE_GREEN))}
        ${card('Booking rate', r.booking_rate, tone(r.booking_rate || 0, 0.01))}
      </div>`;

    const suppressionsNote = (f.suppressions > 0)
      ? `<div style="font-size:11px;color:#ffb74d;margin-top:8px;">${f.suppressions} follow-ups suppressed (reply / engagement / OOO) in this window.</div>`
      : '';

    return `
      <div>
        ${stageRows}
        ${cards}
        ${suppressionsNote}
      </div>`;
  }

  // ── phase3-003: autonomy-metrics matrix ───────────────────────────────────
  // Renders the per-agent approval/error/rollback scorecard as a colour-coded
  // table sorted by status_color (green > amber > red > no_data) then
  // approval_rate desc. Backend already returns rows in that order; we
  // keep a defensive client-side sort in case the response is reordered.
  function renderAutonomyMetrics(autonomy) {
    if (!autonomy || autonomy.error) {
      return `<div style="padding:10px;color:#e57373;">Autonomy metrics unavailable (HTTP ${autonomy && autonomy.error ? autonomy.error : '?'}).</div>`;
    }
    const colorMap = {
      green:   { bg: '#0e3b1a', fg: '#4caf50', label: 'GREEN'   },
      amber:   { bg: '#3b2e0e', fg: '#ffb74d', label: 'AMBER'   },
      red:     { bg: '#3b0e14', fg: '#e57373', label: 'RED'     },
      no_data: { bg: '#222',    fg: '#888',    label: 'NO DATA' },
    };
    const order = { green: 0, amber: 1, red: 2, no_data: 3 };
    const agents = (autonomy.agents || []).slice().sort((a, b) =>
      (order[a.status_color] - order[b.status_color]) ||
      (b.approval_rate - a.approval_rate) ||
      (b.total_actions - a.total_actions)
    );

    const summary = autonomy.summary || {};
    const summaryHtml = `
      <div style="display:flex;gap:8px;margin-bottom:10px;font-size:12px;">
        <span style="padding:3px 8px;border-radius:4px;background:${colorMap.green.bg};color:${colorMap.green.fg};">green: ${summary.green || 0}</span>
        <span style="padding:3px 8px;border-radius:4px;background:${colorMap.amber.bg};color:${colorMap.amber.fg};">amber: ${summary.amber || 0}</span>
        <span style="padding:3px 8px;border-radius:4px;background:${colorMap.red.bg};color:${colorMap.red.fg};">red: ${summary.red || 0}</span>
        <span style="padding:3px 8px;border-radius:4px;background:${colorMap.no_data.bg};color:${colorMap.no_data.fg};">no data: ${summary.no_data || 0}</span>
        <span style="padding:3px 8px;color:#888;">window: ${autonomy.window_days || 30}d · ${summary.total_agents || 0} agents</span>
      </div>`;

    const rows = agents.map(a => {
      const c = colorMap[a.status_color] || colorMap.no_data;
      const pct = (n) => (n * 100).toFixed(1) + '%';
      return `
        <tr style="border-bottom:1px solid #222;">
          <td style="padding:4px 6px;">
            <span style="display:inline-block;padding:2px 6px;border-radius:3px;background:${c.bg};color:${c.fg};font-weight:600;font-size:11px;">${c.label}</span>
          </td>
          <td style="padding:4px 6px;font-weight:600;">${a.agent_name}</td>
          <td style="padding:4px 6px;text-align:right;color:${c.fg};">${pct(a.approval_rate)}</td>
          <td style="padding:4px 6px;text-align:right;color:#888;">${a.approvals_approved}/${a.approvals_total}</td>
          <td style="padding:4px 6px;text-align:right;color:${a.error_rate > 0.05 ? '#e57373' : '#888'};">${pct(a.error_rate)}</td>
          <td style="padding:4px 6px;text-align:right;color:${a.rollback_rate > 0.02 ? '#e57373' : '#888'};">${pct(a.rollback_rate)}</td>
          <td style="padding:4px 6px;text-align:right;color:#888;">${a.total_actions}</td>
        </tr>`;
    }).join('');

    const emptyRow = `<tr><td colspan="7" style="padding:12px;color:#666;">No agent autonomy data in window.</td></tr>`;
    return `
      ${summaryHtml}
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr style="border-bottom:1px solid #333;">
          <th style="text-align:left;padding:4px 6px;">Status</th>
          <th style="text-align:left;padding:4px 6px;">Agent</th>
          <th style="text-align:right;padding:4px 6px;">Approval rate</th>
          <th style="text-align:right;padding:4px 6px;">Approved/total</th>
          <th style="text-align:right;padding:4px 6px;">Error rate</th>
          <th style="text-align:right;padding:4px 6px;">Rollback rate</th>
          <th style="text-align:right;padding:4px 6px;">Actions</th>
        </tr></thead>
        <tbody>${rows || emptyRow}</tbody>
      </table>`;
  }

  function applyAuditFilters() {
    auditFilter.event_type = document.getElementById('audit-event-filter').value.trim();
    auditFilter.agent      = document.getElementById('audit-agent-filter').value.trim();
    auditFilter.days       = parseInt(document.getElementById('audit-days-select').value);
    loadAuditTab(false);
  }

  function renderFunnel(data) {
    const root = document.getElementById('approval-list');
    const stages = data.stages || [];
    const conversions = data.conversions || [];
    const cohorts = data.cohorts || [];
    const maxCount = Math.max(1, ...stages.map(s => s.count));

    const stageRows = stages.map((s, i) => {
      const pct = Math.round((s.count / maxCount) * 100);
      const conv = i > 0 ? conversions[i - 1] : null;
      const convStr = conv ? `${(conv.rate * 100).toFixed(1)}% from ${conv.from_stage}` : '';
      return `
        <div class="funnel-row" style="margin:8px 0;">
          <div style="display:flex;justify-content:space-between;font-size:13px;">
            <span><strong>${s.stage}</strong></span>
            <span>${s.count} · ${convStr}</span>
          </div>
          <div style="background:#222;height:18px;border-radius:4px;overflow:hidden;">
            <div style="background:#4caf50;width:${pct}%;height:100%;"></div>
          </div>
        </div>`;
    }).join('');

    const cohortRows = cohorts.map(c => `
      <tr>
        <td>${c.week_start}</td>
        <td>${c.prospects_sent}</td>
        <td>${c.prospects_replied}</td>
        <td>${c.leads_converted}</td>
        <td>${c.deals_won}</td>
      </tr>`).join('');

    const rev = data.revenue || {};
    const revHtml = `
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:8px 0 20px;">
        <div style="background:#1a1a1a;padding:10px;border-radius:6px;">
          <div style="font-size:11px;color:#888;text-transform:uppercase;">Revenue won (annualised)</div>
          <div style="font-size:20px;font-weight:600;">€${Math.round(rev.revenue_won_eur || 0).toLocaleString()}</div>
        </div>
        <div style="background:#1a1a1a;padding:10px;border-radius:6px;">
          <div style="font-size:11px;color:#888;text-transform:uppercase;">Active MRR</div>
          <div style="font-size:20px;font-weight:600;">€${Math.round(rev.active_mrr_eur || 0).toLocaleString()}/mo</div>
        </div>
        <div style="background:#1a1a1a;padding:10px;border-radius:6px;">
          <div style="font-size:11px;color:#888;text-transform:uppercase;">Avg deal size</div>
          <div style="font-size:20px;font-weight:600;">€${Math.round(rev.avg_deal_size_eur || 0).toLocaleString()}</div>
        </div>
        <div style="background:#1a1a1a;padding:10px;border-radius:6px;">
          <div style="font-size:11px;color:#888;text-transform:uppercase;">Deals w/ retainer</div>
          <div style="font-size:20px;font-weight:600;">${rev.deals_with_retainer || 0}</div>
        </div>
      </div>`;

    root.innerHTML = `
      <div style="margin-bottom:12px;">
        Window:
        <select onchange="funnelWindowDays = parseInt(this.value); loadFunnelTab(false);">
          <option value="7"  ${funnelWindowDays === 7 ? 'selected' : ''}>7 days</option>
          <option value="30" ${funnelWindowDays === 30 ? 'selected' : ''}>30 days</option>
          <option value="90" ${funnelWindowDays === 90 ? 'selected' : ''}>90 days</option>
          <option value="365" ${funnelWindowDays === 365 ? 'selected' : ''}>365 days</option>
        </select>
        <span style="float:right;color:#777;font-size:12px;">
          Generated ${new Date(data.generated_at).toLocaleString()}
        </span>
      </div>
      ${revHtml}
      <h3 style="margin:18px 0 8px;">Funnel — last ${data.window_days} days</h3>
      ${stageRows}
      <h3 style="margin:24px 0 8px;">Cohort table (last 4 weeks)</h3>
      <table class="cohort-table" style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr style="border-bottom:1px solid #333;">
          <th style="text-align:left;padding:4px;">Week start</th>
          <th style="text-align:left;padding:4px;">Sent</th>
          <th style="text-align:left;padding:4px;">Replied</th>
          <th style="text-align:left;padding:4px;">Converted</th>
          <th style="text-align:left;padding:4px;">Won</th>
        </tr></thead>
        <tbody>${cohortRows}</tbody>
      </table>`;
  }
</script>
</body>
</html>
"""
