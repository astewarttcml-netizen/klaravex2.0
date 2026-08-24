"""Klaravex unified approval inbox.

ONE dashboard for every human-in-the-loop decision in the system. Replaces
the per-domain mini-dashboards (social_dashboard, the future marketing
dashboard, the future outreach dashboard) with a single page at
`/admin/inbox/queue` that surfaces:

  - Social media post drafts          (klaravex_social_drafts)
  - Marketing AI race actions         (klaravex_marketing_actions WHERE approval_required)
  - Cold outreach email drafts        (klaravex_outreach_approvals)

Auth: session cookie set by /admin/login/{google,microsoft} OAuth flow
(admin_index.py). The email is checked against the ADMIN_EMAILS allowlist
on every request. Legacy ?secret= URLs are gone — a stale link 401s and the
browser is steered back to /admin/ to re-authenticate.

Why ONE dashboard:
  Anthony was about to acquire three bookmarks for three streams. That
  fails the moment ANY new stream lands (B2B intake, deal approvals, etc.)
  This file is the home for all of them — new streams = new section here.

Adding a new stream:
  1. Add a fetch_<stream>_pending() coroutine returning row dicts.
  2. Add a render_<stream>_card(row) returning HTML string.
  3. Wire approve/reject HTTP routes for the new stream.
  4. Include the section in the GET /queue handler.

  Keep each stream's section ~100 lines so this file stays under 600.
"""

import html
import json
import logging
from pathlib import Path as FilePath
from typing import Any

from fastapi import APIRouter, Depends, Form, Path, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .lib.admin_auth import require_admin_session
from .lib.db import get_pool
from services.kb_publisher import publish_draft_to_wp

_templates = Jinja2Templates(
    directory=str(FilePath(__file__).resolve().parent / "templates")
)


def _user_initials_from_email(email: str) -> str:
    name = email.split("@")[0]
    parts = name.replace(".", " ").replace("_", " ").split()
    return "".join(p[0].upper() for p in parts[:2]) or "A"

log = logging.getLogger("klaravex.admin_inbox")
router = APIRouter()


# ─── Stream 1: Social media drafts ─────────────────────────────────────────────

_PLATFORM_LABEL = {
    "linkedin_personal": "LinkedIn (personal)",
    "linkedin_company":  "LinkedIn (company)",
    "facebook":          "Facebook",
    "instagram":         "Instagram",
    "twitter":           "X / Twitter",
    "reddit":            "Reddit",
    "tiktok":            "TikTok",
    "youtube":           "YouTube",
}
_PLATFORM_COLOR = {
    "linkedin_personal": "#0a66c2", "linkedin_company": "#0a66c2",
    "facebook": "#1877f2", "instagram": "#e4405f", "twitter": "#000",
    "reddit": "#ff4500", "tiktok": "#000", "youtube": "#ff0000",
}


async def _fetch_social_pending() -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        # iter-73 (2026-07-14): approving disappears the item immediately per
        # Anthony directive — approved items no longer stay in the queue waiting
        # for publish. In-flight status visible via /admin/inbox/streams.
        return list(await conn.fetch(
            "SELECT id, platform, content, image_url, topic, status, created_at "
            "FROM klaravex_social_drafts "
            "WHERE status='pending' "
            "ORDER BY created_at DESC"
        ))


def _render_social_card(row: Any) -> str:
    draft_id = str(row["id"])
    platform = row["platform"]
    status = row["status"]
    label = _PLATFORM_LABEL.get(platform, platform)
    color = _PLATFORM_COLOR.get(platform, "#666")
    content = html.escape(row["content"] or "").replace("\n", "<br>")
    image_url = row["image_url"] or ""
    topic = html.escape(row["topic"] or "")
    created = row["created_at"].strftime("%b %d %H:%M") if row["created_at"] else ""

    img_html = (
        f'<img src="{html.escape(image_url)}" '
        'style="width:100%;border-radius:8px;margin-bottom:12px"/>'
        if image_url else ""
    )
    status_badge = (
        '<span class="badge approved">approved</span>'
        if status == "approved" else ""
    )
    actions = _action_buttons(f"/admin/inbox/social/{draft_id}", status)
    return (
        '<div class="card">'
        f'<div class="card-head">'
        f'<span class="platform-pill" style="background:{color}">{html.escape(label)}</span>'
        f'{status_badge}<span class="meta">{created}</span></div>'
        f'{img_html}'
        f'<div class="content">{content}</div>'
        f'<div class="topic">{topic}</div>{actions}</div>'
    )


# ─── Stream 2: Marketing race approvals ────────────────────────────────────────

async def _fetch_marketing_pending() -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT a.id, t.team_code, t.display_name, a.action_type, "
            "       a.payload, a.created_at "
            "FROM klaravex_marketing_actions a "
            "JOIN klaravex_marketing_teams t ON t.id=a.team_id "
            "WHERE a.status='pending' AND a.approval_required "
            "ORDER BY a.created_at ASC"
        ))


def _render_marketing_card(row: Any) -> str:
    action_id = str(row["id"])
    team_code = row["team_code"]
    team_color = "#7c3aed" if team_code == "alpha" else "#0891b2"
    # asyncpg returns jsonb columns as strings; parse before .get()
    raw_payload = row["payload"]
    if isinstance(raw_payload, str):
        try:
            payload = json.loads(raw_payload) if raw_payload else {}
        except Exception:
            payload = {}
    else:
        payload = raw_payload or {}
    summary = html.escape(payload.get("summary") or payload.get("reason") or "(no summary)")
    reason = html.escape(payload.get("reason") or "")
    proposed = payload.get("proposed") or {}
    created = row["created_at"].strftime("%b %d %H:%M") if row["created_at"] else ""

    # Concise proposed-action summary (don't dump the whole jsonb)
    proposed_summary = ""
    if isinstance(proposed, dict):
        if "tool" in proposed:
            tool = proposed.get("tool") or ""
            args = proposed.get("args") or {}
            budget = args.get("daily_budget_usd")
            proposed_summary = f"<b>Tool:</b> {html.escape(tool)}"
            if budget:
                proposed_summary += f" &middot; <b>Daily budget:</b> ${budget}"
        else:
            campaigns = [k for k in proposed if k.endswith("_ads")]
            if campaigns:
                total = 0
                for k in campaigns:
                    b = (proposed.get(k) or {}).get("daily_budget_usd") or 0
                    total += float(b)
                proposed_summary = (
                    f"<b>Campaigns:</b> {', '.join(c.replace('_ads','').title() for c in campaigns)} "
                    f"&middot; <b>Daily total:</b> ${total:.0f}"
                )

    actions = _action_buttons(f"/admin/inbox/marketing/{action_id}", "pending")
    reason_html = f'<div class="topic">{reason}</div>' if reason else ""
    proposed_html = (
        f'<div class="topic" style="margin-top:6px;color:#374151">{proposed_summary}</div>'
        if proposed_summary else ""
    )
    return (
        '<div class="card">'
        f'<div class="card-head">'
        f'<span class="platform-pill" style="background:{team_color}">Race · Team {team_code.upper()}</span>'
        f'<span class="meta">{created}</span></div>'
        f'<div class="content"><b>{summary}</b></div>'
        f'{reason_html}{proposed_html}'
        f'{actions}</div>'
    )


# ─── Stream 3: Cold outreach email drafts ──────────────────────────────────────

async def _fetch_outreach_pending() -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        # iter-73: pending-only. Approve now cascades to publish (Anthony
        # directive: "why two buttons") — no need to keep approved-not-sent
        # rows in queue.
        return list(await conn.fetch(
            "SELECT a.id, a.subject, a.body_text, a.status, a.created_at, "
            "       p.company_name, p.contact_first_name, p.contact_last_name, "
            "       p.contact_email, p.contact_title, p.industry "
            "FROM klaravex_outreach_approvals a "
            "JOIN klaravex_prospected_leads p ON p.id=a.prospect_id "
            "WHERE a.status='pending' "
            "ORDER BY a.created_at ASC"
        ))


def _render_outreach_card(row: Any) -> str:
    out_id = str(row["id"])
    status = row["status"]
    subject = html.escape(row["subject"] or "")
    body = html.escape((row["body_text"] or "")[:600]).replace("\n", "<br>")
    company = html.escape(row["company_name"] or "")
    contact = html.escape(f"{row['contact_first_name'] or ''} {row['contact_last_name'] or ''}".strip())
    title = html.escape(row["contact_title"] or "")
    email = html.escape(row["contact_email"] or "")
    industry = html.escape(row["industry"] or "")
    created = row["created_at"].strftime("%b %d %H:%M") if row["created_at"] else ""

    status_badge = (
        '<span class="badge approved">approved · queued to send</span>'
        if status == "approved" else ""
    )
    actions = _action_buttons(f"/admin/inbox/outreach/{out_id}", status)
    return (
        '<div class="card">'
        f'<div class="card-head">'
        f'<span class="platform-pill" style="background:#059669">Cold outreach</span>'
        f'{status_badge}<span class="meta">{created}</span></div>'
        f'<div style="font-size:12px;color:#6b7280;margin-bottom:10px">'
        f'<b>{contact}</b> &middot; {title} at <b>{company}</b> ({industry})<br>'
        f'{email}</div>'
        f'<div style="font-weight:600;margin-bottom:6px">{subject}</div>'
        f'<div class="content" style="max-height:200px">{body}{"&hellip;" if len(row["body_text"] or "") > 600 else ""}</div>'
        f'{actions}</div>'
    )


# ─── Stream 4: Freelance bid approvals ─────────────────────────────────────────

_FREELANCE_PLATFORM_COLOR = {
    "freelancer": "#29b2fe", "freelancermap": "#e30613",
    "peopleperhour": "#4d3aae", "upwork": "#14a800", "guru": "#ff5722",
}


async def _fetch_freelance_bids_pending() -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT b.id AS bid_id, b.cover_letter, b.bid_amount, b.bid_currency, "
            "       b.created_at AS bid_created, "
            "       p.id AS project_id, p.platform, p.title, p.description, "
            "       p.url, p.fit_score, p.fit_rationale, "
            "       p.budget_min, p.budget_max, p.budget_currency AS proj_currency, "
            "       p.budget_type, p.client_location, p.client_rating, "
            "       p.proposals_count, p.posted_at "
            "FROM klaravex_platform_bids b "
            "JOIN klaravex_freelance_projects p ON p.id = b.project_id "
            "WHERE p.status = 'bid_queued' "
            "ORDER BY p.fit_score DESC NULLS LAST, p.posted_at DESC NULLS LAST "
            "LIMIT 100"
        ))


def _render_freelance_card(row: Any) -> str:
    bid_id = str(row["bid_id"])
    project_id = str(row["project_id"])
    platform = row["platform"] or ""
    plat_color = _FREELANCE_PLATFORM_COLOR.get(platform, "#6b7280")
    title = html.escape((row["title"] or "")[:120])
    fit = row["fit_score"] if row["fit_score"] is not None else "—"
    fit_color = (
        "#10b981" if isinstance(fit, int) and fit >= 70 else
        "#f59e0b" if isinstance(fit, int) and fit >= 50 else "#9ca3af"
    )
    rationale = html.escape((row["fit_rationale"] or "")[:200])
    cover = html.escape((row["cover_letter"] or "")[:700]).replace("\n", "<br>")
    bid_amount = row["bid_amount"]
    bid_currency = row["bid_currency"] or "USD"
    project_budget = ""
    if row["budget_min"] or row["budget_max"]:
        currency = row["proj_currency"] or "USD"
        if row["budget_min"] and row["budget_max"]:
            project_budget = f"{currency} {row['budget_min']}–{row['budget_max']}"
        elif row["budget_max"]:
            project_budget = f"{currency} ≤{row['budget_max']}"
        if row["budget_type"]:
            project_budget += f" ({row['budget_type']})"
    location = html.escape(row["client_location"] or "")
    client_rating = row["client_rating"]
    proposals = row["proposals_count"]
    url = row["url"] or ""
    url_html = f'<a href="{html.escape(url)}" target="_blank" rel="noopener" style="color:#1a3a5c">View on {html.escape(platform)} ↗</a>' if url else ""
    posted = row["posted_at"].strftime("%b %d %H:%M") if row["posted_at"] else ""

    rating_html = f" · ⭐ {client_rating}" if client_rating else ""
    proposals_html = f" · {proposals} bids" if proposals else ""

    bid_amt_str = f"{bid_currency} {bid_amount}" if bid_amount else "—"
    actions = _action_buttons(f"/admin/inbox/freelance/{bid_id}", "pending")

    return (
        '<div class="card">'
        f'<div class="card-head">'
        f'<span class="platform-pill" style="background:{plat_color}">{html.escape(platform)}</span>'
        f'<span class="row-pill" style="background:{fit_color}">fit {fit}</span>'
        f'<span class="meta">{posted}</span></div>'
        f'<div style="font-weight:600;font-size:14px;margin-bottom:6px">{title}</div>'
        f'<div style="font-size:12px;color:#6b7280;margin-bottom:10px">'
        f'<b>Budget:</b> {project_budget or "—"} · '
        f'<b>Your bid:</b> {bid_amt_str}{rating_html}{proposals_html}'
        + (f' · {location}' if location else '') + '</div>'
        f'<div class="topic" style="margin-bottom:8px;color:#374151">{rationale}</div>'
        f'<div class="content" style="max-height:240px">{cover}</div>'
        f'<div style="margin:6px 0 12px;font-size:11px">{url_html}</div>'
        f'{actions}</div>'
    )


# ─── Stream 5: Freelance match watch inbox ─────────────────────────────────────

async def _fetch_freelance_matches_pending() -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT id, platform, platform_id, title, description, url, "
            "       budget_min, budget_max, budget_currency, skills, "
            "       client_country, posted_at, fit_score, fit_notes, created_at "
            "FROM klaravex_freelance_matches "
            "WHERE status = 'new' "
            "ORDER BY fit_score DESC NULLS LAST, created_at DESC "
            "LIMIT 50"
        ))


def _render_freelance_match_card(row: Any) -> str:
    match_id = str(row["id"])
    platform = row["platform"] or ""
    plat_color = _FREELANCE_PLATFORM_COLOR.get(platform, "#6b7280")
    title = html.escape((row["title"] or "")[:120])
    fit = row["fit_score"] if row["fit_score"] is not None else "—"
    fit_color = (
        "#10b981" if isinstance(fit, int) and fit >= 60 else
        "#f59e0b" if isinstance(fit, int) and fit >= 40 else "#9ca3af"
    )
    notes = html.escape((row["fit_notes"] or "")[:200])
    budget = ""
    if row["budget_min"] or row["budget_max"]:
        currency = (row["budget_currency"] or "USD").upper()
        if row["budget_min"] and row["budget_max"]:
            budget = f"{currency} {row['budget_min']:.0f}–{row['budget_max']:.0f}"
        elif row["budget_max"]:
            budget = f"{currency} ≤{row['budget_max']:.0f}"
    skills = html.escape((row["skills"] or "")[:120])
    country = html.escape(row["client_country"] or "")
    url = row["url"] or ""
    url_html = (
        f'<a href="{html.escape(url)}" target="_blank" rel="noopener" style="color:#1a3a5c">'
        f'View on {html.escape(platform)} ↗</a>'
        if url else ""
    )
    posted = row["posted_at"].strftime("%b %d %H:%M") if row["posted_at"] else ""
    created = row["created_at"].strftime("%b %d %H:%M") if row["created_at"] else ""
    return (
        '<div class="card">'
        f'<div class="card-head">'
        f'<span class="platform-pill" style="background:{plat_color}">{html.escape(platform)}</span>'
        f'<span class="row-pill" style="background:{fit_color}">fit {fit}</span>'
        f'<span class="meta">{created}</span></div>'
        f'<div style="font-weight:600;font-size:14px;margin-bottom:6px">{title}</div>'
        f'<div style="font-size:12px;color:#6b7280;margin-bottom:8px">'
        f'<b>Budget:</b> {budget or "—"}'
        + (f' · <b>Country:</b> {country}' if country else '')
        + (f' · <b>Posted:</b> {posted}' if posted else '')
        + '</div>'
        f'<div class="topic" style="margin-bottom:6px;color:#374151">{notes}</div>'
        + (f'<div style="font-size:12px;color:#6b7280;margin-bottom:8px">'
           f'<b>Skills:</b> {skills}</div>' if skills else '')
        + f'<div style="margin:6px 0 12px;font-size:11px">{url_html}</div>'
        f'<form method="post" action="/admin/inbox/freelance-match/{match_id}/dismiss"'
        f' style="display:inline">'
        f'<button type="submit" class="btn btn-reject">✗ Dismiss</button></form>'
        f'</div>'
    )


# ─── Stream 6: KB article drafts (T14.27) ────────────────────────────────────

_PILLAR_COLOR = {
    "security-basics": "#ef4444",
    "m365-cloud":      "#0a66c2",
    "business-it":     "#7c3aed",
    "it-readiness":    "#059669",
}


async def _fetch_kb_drafts_pending() -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT id, topic, pillar, title, slug, word_count, quality_score, "
            "       source_cve, created_at, status "
            "FROM klaravex_kb_drafts "
            "WHERE status = 'pending' "
            "ORDER BY created_at DESC LIMIT 20"
        ))


def _render_kb_draft_card(row: Any) -> str:
    draft_id = str(row["id"])
    title = html.escape((row["title"] or row["topic"] or "")[:120])
    pillar = row["pillar"] or "uncategorized"
    pillar_color = _PILLAR_COLOR.get(pillar, "#6b7280")
    wc = row["word_count"] or 0
    quality = row["quality_score"] or 0
    quality_color = "#10b981" if quality >= 70 else "#f59e0b" if quality >= 50 else "#ef4444"
    slug = html.escape(row["slug"] or "")
    cve = row["source_cve"] or ""
    created = row["created_at"].strftime("%b %d %H:%M") if row["created_at"] else ""
    status = row["status"] or "pending"
    base_path = f"/admin/inbox/kb/{draft_id}"
    actions = _action_buttons(base_path, status)
    return (
        '<div class="card">'
        f'<div class="card-head">'
        f'<span class="platform-pill" style="background:{pillar_color}">{html.escape(pillar)}</span>'
        f'<span class="row-pill" style="background:{quality_color}">Q:{quality}</span>'
        f'<span class="meta">{created}</span></div>'
        f'<div style="font-weight:600;font-size:14px;margin-bottom:6px">{title}</div>'
        f'<div style="font-size:12px;color:#6b7280;margin-bottom:8px">'
        f'<b>Slug:</b> /kb/{slug}/ · <b>Words:</b> {wc}'
        + (f' · <b>CVE:</b> {html.escape(cve)}' if cve else '')
        + '</div>'
        f'{actions}'
        f'</div>'
    )


# ─── Shared UI helpers ─────────────────────────────────────────────────────────

def _build_queue_tabs(
    social_rows: list, marketing_rows: list, outreach_rows: list,
    kb_rows: list, freelance_rows: list | None = None,
) -> list[dict]:
    """Convert raw DB rows into the structured tabs list for admin_approvals.html."""

    def _social_item(r: Any) -> dict:
        status = r["status"]
        draft_id = str(r["id"])
        label = _PLATFORM_LABEL.get(r["platform"], r["platform"])
        created = r["created_at"].strftime("%b %d %H:%M") if r["created_at"] else ""
        content = (r["content"] or "")[:80]
        unapprove_url = f"/admin/inbox/social/{draft_id}/reject" if status == "approved" else None
        return {
            "src_class": "ai",
            "src_label": "AI-generated",
            "title": content or "(no content)",
            "sub": f"{label} · {created}",
            "approve_url": None if status == "approved" else f"/admin/inbox/social/{draft_id}/approve",
            "reject_url": None if status == "approved" else f"/admin/inbox/social/{draft_id}/reject",
            "unapprove_url": unapprove_url,
            "preview_url": None,
        }

    def _marketing_item(r: Any) -> dict:
        action_id = str(r["id"])
        raw = r["payload"]
        if isinstance(raw, str):
            try:
                payload = json.loads(raw) if raw else {}
            except Exception:
                payload = {}
        else:
            payload = raw or {}
        summary = (payload.get("summary") or payload.get("reason") or r.get("action_type") or "")[:80]
        team = r.get("display_name") or r.get("team_code") or "?"
        created = r["created_at"].strftime("%b %d %H:%M") if r["created_at"] else ""
        return {
            "src_class": "ai",
            "src_label": "AI-generated",
            "title": summary or "(no summary)",
            "sub": f"Race · Team {team} · {created}",
            "approve_url": f"/admin/inbox/marketing/{action_id}/approve",
            "reject_url": f"/admin/inbox/marketing/{action_id}/reject",
            "unapprove_url": None,
            "preview_url": None,
        }

    def _outreach_item(r: Any) -> dict:
        item_id = str(r["id"])
        subject = (r.get("subject") or "")[:80]
        company = r.get("company_name") or r.get("contact_email") or "—"
        created = r["created_at"].strftime("%b %d %H:%M") if r["created_at"] else ""
        return {
            "src_class": "ai",
            "src_label": "AI-generated",
            "title": subject or "(no subject)",
            "sub": f"Outreach · {company} · {created}",
            "approve_url": f"/admin/inbox/outreach/{item_id}/approve",
            "reject_url": f"/admin/inbox/outreach/{item_id}/reject",
            "unapprove_url": None,
            "preview_url": None,
        }

    def _kb_item(r: Any) -> dict:
        draft_id = str(r["id"])
        title = (r.get("title") or r.get("topic") or "")[:80]
        pillar = r.get("pillar") or ""
        created = r["created_at"].strftime("%b %d %H:%M") if r["created_at"] else ""
        return {
            "src_class": "ai",
            "src_label": "AI-generated",
            "title": title or "(no title)",
            "sub": f"KB · {pillar} · {created}",
            "approve_url": f"/admin/inbox/kb/{draft_id}/approve",
            "reject_url": f"/admin/inbox/kb/{draft_id}/reject",
            "unapprove_url": None,
            "preview_url": None,
        }

    def _freelance_item(r: Any) -> dict:
        bid_id = str(r["bid_id"])
        platform = r.get("platform") or "freelancermap"
        title = (r.get("title") or "")[:80]
        bid_amount = r.get("bid_amount")
        bid_currency = r.get("bid_currency") or "USD"
        bid_str = f"{bid_currency} {bid_amount}" if bid_amount else "—"
        created = r["bid_created"].strftime("%b %d %H:%M") if r.get("bid_created") else ""
        return {
            "src_class": "ai",
            "src_label": "AI-generated",
            "title": title or "(no title)",
            "sub": f"{platform} · bid {bid_str} · {created}",
            "approve_url": f"/admin/inbox/freelance/{bid_id}/approve",
            "reject_url": f"/admin/inbox/freelance/{bid_id}/reject",
            "unapprove_url": None,
            "preview_url": None,
        }

    _freelance = freelance_rows or []

    return [
        {
            "label": "Freelance Bids",
            "count": len(_freelance),
            "urgent": len(_freelance) > 0,
            "entries": [_freelance_item(r) for r in _freelance],
            "approve_all_url": None,
            "reject_all_url": None,
        },
        {
            "label": "Social",
            "count": len(social_rows),
            "urgent": False,
            "entries": [_social_item(r) for r in social_rows],
            "approve_all_url": "/admin/inbox/social/approve-all" if social_rows else None,
            "reject_all_url": "/admin/inbox/social/reject-all" if social_rows else None,
        },
        {
            "label": "Marketing",
            "count": len(marketing_rows),
            "urgent": False,
            "entries": [_marketing_item(r) for r in marketing_rows],
            "approve_all_url": "/admin/inbox/marketing/approve-all" if marketing_rows else None,
            "reject_all_url": None,
        },
        {
            "label": "Outreach",
            "count": len(outreach_rows),
            "urgent": False,
            "entries": [_outreach_item(r) for r in outreach_rows],
            "approve_all_url": "/admin/inbox/outreach/approve-all" if outreach_rows else None,
            "reject_all_url": None,
        },
        {
            "label": "KB Drafts",
            "count": len(kb_rows),
            "urgent": False,
            "entries": [_kb_item(r) for r in kb_rows],
            "approve_all_url": "/admin/inbox/kb/approve-all" if kb_rows else None,
            "reject_all_url": None,
        },
    ]


def _action_buttons(base_path: str, status: str) -> str:
    if status == "approved":
        return (
            f'<form method="post" action="{base_path}/reject" style="display:inline">'
            '<button type="submit" class="btn btn-unapprove">↩ Unapprove</button></form>'
        )
    return (
        f'<form method="post" action="{base_path}/approve" style="display:inline;margin-right:6px">'
        '<button type="submit" class="btn btn-approve">✓ Approve</button></form>'
        f'<form method="post" action="{base_path}/reject" style="display:inline">'
        '<button type="submit" class="btn btn-reject">✗ Reject</button></form>'
    )


# ─── Streams 4-6: ops-visibility sections (ported from .de dashboard 2026-06-25) ──

async def _fetch_access_denials(hours: int, limit: int = 100) -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT id, timestamp, method, path, client_email, response_status "
            "FROM klaravex_loki_audit "
            "WHERE response_status >= 400 "
            "  AND timestamp > now() - ($1 || ' hours')::interval "
            "ORDER BY timestamp DESC LIMIT $2",
            str(hours), limit,
        ))


def _render_denial_row(row: Any) -> str:
    ts = row["timestamp"].strftime("%b %d %H:%M") if row["timestamp"] else "—"
    method = html.escape(row["method"] or "")
    path = html.escape((row["path"] or "")[:90])
    email = html.escape(row["client_email"] or "—")
    status = row["response_status"]
    color = "#ef4444" if status >= 500 else "#f59e0b"
    return (
        f'<div class="row">'
        f'<span class="row-time">{ts}</span>'
        f'<span class="row-pill" style="background:{color}">{status}</span>'
        f'<span class="row-method">{method}</span>'
        f'<span class="row-path">{path}</span>'
        f'<span class="row-email">{email}</span>'
        f'</div>'
    )


async def _fetch_webhook_events(hours: int, limit: int = 100) -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT event_id, event_type, received_at, status, error "
            "FROM klaravex_stripe_events "
            "WHERE received_at > now() - ($1 || ' hours')::interval "
            "ORDER BY received_at DESC LIMIT $2",
            str(hours), limit,
        ))


def _render_webhook_row(row: Any) -> str:
    ts = row["received_at"].strftime("%b %d %H:%M") if row["received_at"] else "—"
    eid = html.escape((row["event_id"] or "")[:14])
    etype = html.escape(row["event_type"] or "")
    status = row["status"] or "—"
    error = html.escape((row["error"] or "")[:110])
    color = "#10b981" if status == "processed" else ("#ef4444" if status in ("failed", "error") else "#6b7280")
    err_html = f'<span class="row-err">{error}</span>' if error else ""
    return (
        f'<div class="row">'
        f'<span class="row-time">{ts}</span>'
        f'<span class="row-pill" style="background:{color}">{html.escape(str(status))}</span>'
        f'<span class="row-method">{etype}</span>'
        f'<span class="row-path">{eid}</span>'
        f'{err_html}'
        f'</div>'
    )


async def _fetch_failed_automations(hours: int, limit: int = 100) -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT id, run_kind, status, error, started_at, finished_at "
            "FROM klaravex_marketing_runs "
            "WHERE (status='failed' OR error IS NOT NULL) "
            "  AND COALESCE(finished_at, started_at) > now() - ($1 || ' hours')::interval "
            "ORDER BY COALESCE(finished_at, started_at) DESC LIMIT $2",
            str(hours), limit,
        ))


def _render_failure_row(row: Any) -> str:
    ts_raw = row["finished_at"] or row["started_at"]
    ts = ts_raw.strftime("%b %d %H:%M") if ts_raw else "—"
    kind = html.escape(row["run_kind"] or "")
    status = html.escape(row["status"] or "—")
    error = html.escape((row["error"] or "")[:140])
    return (
        f'<div class="row">'
        f'<span class="row-time">{ts}</span>'
        f'<span class="row-pill" style="background:#ef4444">{status}</span>'
        f'<span class="row-method">{kind}</span>'
        f'<span class="row-err">{error}</span>'
        f'</div>'
    )


def _lookback_bar(slug: str, current: int) -> str:
    options = [(24, "24h"), (48, "48h"), (168, "7d")]
    links = " ".join(
        f'<a href="?{slug}_hours={h}#sec-{slug}" class="{ "active" if h == current else ""}">{label}</a>'
        for h, label in options
    )
    return f'<div class="lookback-bar">Look-back: {links}</div>'


_BASE_STYLE = """
<style>
  :root{
    --navy:#0A1628;--navy-mid:#0F2040;--navy-light:#162B54;--navy-card:#132446;
    --blue:#1E6FD9;--blue-light:#3B8FFF;--amber:#D4A853;
    --white:#F8F9FC;--gray-200:#CBD5E1;--gray-400:#94A3B8;--gray-600:#475569;
    --green:#22C55E;--red:#EF4444;--red-dark:#991B1B;--amber-dark:#B8860B;
    --border:rgba(255,255,255,0.07);--border-strong:rgba(255,255,255,0.14);
  }
  *{box-sizing:border-box}
  body{font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;background:var(--navy);margin:0;padding:0;color:var(--white);min-height:100vh}
  .nav{position:sticky;top:0;height:68px;background:rgba(10,22,40,0.92);backdrop-filter:blur(12px);border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 32px;gap:32px;z-index:100}
  .nav-brand{font-weight:700;font-size:20px;letter-spacing:-.02em}
  .nav-brand .accent{color:var(--amber)}
  .nav-tabs{display:flex;gap:4px;flex:1;flex-wrap:wrap}
  .nav-tabs a{color:var(--gray-200);text-decoration:none;padding:8px 14px;border-radius:6px;font-size:13px;font-weight:500;transition:background .15s,color .15s}
  .nav-tabs a:hover{background:var(--navy-light);color:var(--white)}
  .nav-tabs a.active{background:var(--blue);color:var(--white)}
  .nav-user{color:var(--gray-400);font-size:12px}
  .nav-user a{color:var(--amber);text-decoration:none;margin-left:10px}
  .container{max-width:1120px;margin:0 auto;padding:32px 24px}
  h1{margin:0 0 6px;font-size:28px;font-weight:700;letter-spacing:-.02em}
  h2{margin:0;font-size:18px;font-weight:600;color:var(--white)}
  .subhead{color:var(--gray-400);font-size:14px;margin-bottom:24px}
  .kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin:24px 0 40px}
  .kpi{background:var(--navy-card);border:1px solid var(--border);border-radius:12px;padding:18px 20px;transition:transform .15s,border-color .15s}
  .kpi:hover{transform:translateY(-2px);border-color:var(--border-strong)}
  .kpi-label{color:var(--gray-400);font-size:11px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px;font-weight:600}
  .kpi-value{font-size:28px;font-weight:700;color:var(--white);letter-spacing:-.02em}
  .kpi-value.warn{color:var(--amber)}
  .kpi-value.bad{color:var(--red)}
  .kpi-value.good{color:var(--green)}
  .kpi-sub{color:var(--gray-400);font-size:11px;margin-top:4px}
  .stat{background:var(--navy-mid);border:1px solid var(--border);padding:8px 14px;border-radius:8px;font-size:13px;color:var(--gray-200)}
  .card{background:var(--navy-card);border:1px solid var(--border);border-radius:12px;padding:18px 20px;margin-bottom:14px;transition:border-color .15s}
  .card:hover{border-color:var(--border-strong)}
  .card-head{display:flex;align-items:center;margin-bottom:12px;gap:8px;flex-wrap:wrap}
  .platform-pill{color:#fff;font-size:11px;font-weight:600;padding:3px 9px;border-radius:10px;text-transform:uppercase;letter-spacing:.04em}
  .badge{background:rgba(34,197,94,0.15);color:var(--green);font-size:11px;font-weight:600;padding:3px 9px;border-radius:10px;text-transform:uppercase;letter-spacing:.04em;border:1px solid rgba(34,197,94,0.3)}
  .badge.warn{background:rgba(212,168,83,0.15);color:var(--amber);border-color:rgba(212,168,83,0.3)}
  .badge.bad{background:rgba(239,68,68,0.15);color:var(--red);border-color:rgba(239,68,68,0.3)}
  .badge.info{background:rgba(30,111,217,0.15);color:var(--blue-light);border-color:rgba(30,111,217,0.3)}
  .meta{margin-left:auto;color:var(--gray-400);font-size:12px}
  .content{font-size:13px;line-height:1.5;max-height:280px;overflow:auto;margin-bottom:14px;white-space:pre-wrap;color:var(--gray-200);background:var(--navy);padding:12px;border-radius:8px;border:1px solid var(--border)}
  .topic{color:var(--gray-400);font-size:11px;margin-bottom:10px}
  .btn{border:0;padding:8px 16px;border-radius:6px;cursor:pointer;font-weight:600;font-size:13px;transition:background .15s,transform .15s}
  .btn:hover{transform:translateY(-1px)}
  .btn-approve{background:var(--green);color:var(--navy)}
  .btn-reject{background:transparent;color:var(--gray-200);border:1px solid var(--border-strong)}
  .btn-reject:hover{background:var(--navy-light);color:var(--white)}
  .btn-unapprove{background:var(--red);color:#fff}
  .btn-publish{background:var(--blue);color:#fff;padding:10px 18px;border-radius:8px}
  .btn-publish:hover{background:var(--blue-light)}
  .btn-approve-all{background:var(--green);color:var(--navy);padding:10px 18px;border-radius:8px;font-weight:700}
  .btn-approve-all:hover{background:#4ade80}
  .btn-reject-all{background:transparent;color:var(--red);padding:8px 14px;border-radius:8px;border:1px solid var(--red)}
  .btn-reject-all:hover{background:rgba(239,68,68,0.1)}
  .section-hdr{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:32px 0 16px;padding-bottom:12px;border-bottom:1px solid var(--border)}
  .section-hdr h2{margin:0}
  .section-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  .section-approve-all{margin:0}
  .section-approve-all button{font-size:13px;padding:8px 14px}
  .empty{background:var(--navy-card);border:1px dashed var(--border-strong);padding:32px;border-radius:12px;text-align:center;color:var(--gray-400);font-size:13px}
  .sigblock{color:var(--gray-400);font-size:12px}
  .sigblock a{color:var(--amber);text-decoration:none;margin-left:8px}
  .row{display:flex;gap:10px;align-items:center;padding:10px 14px;background:var(--navy-card);border:1px solid var(--border);border-radius:8px;margin-bottom:6px;font-size:13px;flex-wrap:wrap;color:var(--gray-200)}
  .row-time{color:var(--gray-400);font-family:'SF Mono',Menlo,monospace;font-size:11px;min-width:80px}
  .row-pill{color:#fff;font-weight:600;font-size:11px;padding:2px 8px;border-radius:6px}
  .row-method{font-family:'SF Mono',Menlo,monospace;font-size:12px;color:var(--amber);background:var(--navy);padding:2px 8px;border-radius:4px}
  .row-path{color:var(--gray-200);font-family:'SF Mono',Menlo,monospace;font-size:12px;flex:1;overflow:hidden;text-overflow:ellipsis}
  .row-email{color:var(--gray-400);font-size:12px}
  .row-err{color:var(--red);font-size:12px;font-family:'SF Mono',Menlo,monospace}
  .lookback-bar{display:flex;gap:8px;align-items:center;margin:8px 0 12px;font-size:12px;color:var(--gray-400)}
  .lookback-bar a{color:var(--gray-200);text-decoration:none;padding:4px 12px;border:1px solid var(--border-strong);border-radius:6px;transition:background .15s}
  .lookback-bar a:hover{background:var(--navy-light);color:var(--white)}
  .lookback-bar a.active{background:var(--blue);color:#fff;border-color:var(--blue)}
  a{color:var(--blue-light)}
  a:hover{color:var(--white)}
  .table{width:100%;border-collapse:collapse;background:var(--navy-card);border-radius:8px;overflow:hidden;font-size:13px}
  .table th{text-align:left;padding:10px 14px;background:var(--navy-mid);color:var(--gray-400);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--border)}
  .table td{padding:10px 14px;border-bottom:1px solid var(--border);color:var(--gray-200)}
  .table tr:last-child td{border-bottom:0}
  .table tr:hover{background:var(--navy-light)}
</style>
"""


# ─── iter-74: KPI + leads + history fetches for expanded dashboard ────────────
async def _fetch_kpis() -> dict[str, Any]:
    """Top-of-page KPI snapshot. All counts are cheap SELECTs; no joins.
    Time windows are UTC-relative to keep the dashboard timezone-agnostic.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
              (SELECT count(*) FROM klaravex_social_drafts WHERE status='pending')            AS social_pending,
              (SELECT count(*) FROM klaravex_outreach_approvals WHERE status='pending')       AS outreach_pending,
              (SELECT count(*) FROM klaravex_marketing_actions
                WHERE status='pending' AND approval_required)                                 AS marketing_pending,
              (SELECT count(*) FROM klaravex_prospected_leads
                WHERE created_at > now() - interval '24 hours')                               AS leads_24h,
              (SELECT count(*) FROM klaravex_prospected_leads
                WHERE created_at > now() - interval '7 days')                                 AS leads_7d,
              (SELECT count(*) FROM klaravex_outreach_approvals
                WHERE sent_at > now() - interval '24 hours')                                  AS sent_24h,
              (SELECT count(*) FROM klaravex_kb_drafts WHERE status='pending')                AS kb_pending,
              (SELECT count(*) FROM klaravex_social_drafts
                WHERE status='published' AND published_at > now() - interval '24 hours')      AS published_24h
            """
        )
    r = rows[0]
    return {
        "social_pending": r["social_pending"],
        "outreach_pending": r["outreach_pending"],
        "marketing_pending": r["marketing_pending"],
        "leads_24h": r["leads_24h"],
        "leads_7d": r["leads_7d"],
        "sent_24h": r["sent_24h"],
        "kb_pending": r["kb_pending"],
        "published_24h": r["published_24h"],
    }


async def _fetch_leads_snapshot(limit: int = 25) -> list[Any]:
    """iter-74 render. iter-78-hotfix: dropped `source` from SELECT because the
    column doesn't yet exist on public.klaravex_prospected_leads (iter-72
    Hunter-as-source migration 028 never landed). Render substitutes literal
    'apollo' since all rows currently come from Apollo. When migration 028
    ships, re-add the column."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, company_name, contact_email, contact_first_name, contact_last_name,
                   contact_title, status, fit_score, industry, employee_count,
                   location, created_at
              FROM klaravex_prospected_leads
             ORDER BY created_at DESC
             LIMIT $1
            """,
            limit,
        )
        # Coerce Record → dict-with-source so the render loop is unchanged
        return [{**dict(r), "source": "apollo"} for r in rows]


async def _fetch_history_summary(days: int = 30) -> dict[str, dict[str, int]]:
    """Approved / rejected / pending counts per stream over the trailing window."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        social = await conn.fetch(
            "SELECT status, count(*) AS n FROM klaravex_social_drafts "
            f"WHERE created_at > now() - interval '{int(days)} days' GROUP BY status"
        )
        outreach = await conn.fetch(
            "SELECT status, count(*) AS n FROM klaravex_outreach_approvals "
            f"WHERE created_at > now() - interval '{int(days)} days' GROUP BY status"
        )
        kb = await conn.fetch(
            "SELECT status, count(*) AS n FROM klaravex_kb_drafts "
            f"WHERE created_at > now() - interval '{int(days)} days' GROUP BY status"
        )
    return {
        "social": {r["status"]: r["n"] for r in social},
        "outreach": {r["status"]: r["n"] for r in outreach},
        "kb": {r["status"]: r["n"] for r in kb},
    }


def _render_kpi_grid(kpis: dict[str, Any]) -> str:
    def tile(label: str, value: Any, klass: str = "", sub: str = "") -> str:
        return (
            f'<div class="kpi"><div class="kpi-label">{html.escape(label)}</div>'
            f'<div class="kpi-value {klass}">{html.escape(str(value))}</div>'
            + (f'<div class="kpi-sub">{html.escape(sub)}</div>' if sub else "")
            + '</div>'
        )
    total_pending = kpis["social_pending"] + kpis["outreach_pending"] + kpis["marketing_pending"] + kpis["kb_pending"]
    return (
        '<div class="kpi-grid">'
        + tile("Awaiting approval", total_pending,
               klass="warn" if total_pending > 0 else "good",
               sub=f'social {kpis["social_pending"]} · outreach {kpis["outreach_pending"]} · marketing {kpis["marketing_pending"]} · kb {kpis["kb_pending"]}')
        + tile("Leads captured 24h", kpis["leads_24h"],
               klass="good" if kpis["leads_24h"] > 0 else "",
               sub=f'{kpis["leads_7d"]} past 7 days')
        + tile("Cold emails sent 24h", kpis["sent_24h"],
               klass="good" if kpis["sent_24h"] > 0 else "",
               sub="via Smartlead")
        + tile("Social posts published 24h", kpis["published_24h"],
               klass="good" if kpis["published_24h"] > 0 else "",
               sub="cross-platform")
        + '</div>'
    )


_LEAD_STATUS_COLOR = {
    "new": "info", "qualified": "good", "sent": "info",
    "queued_smartlead": "info", "replied": "good", "meeting_booked": "good",
    "won": "good", "lost": "bad", "rejected": "bad", "bounced": "bad",
    "unsubscribed": "warn",
}


def _render_leads_table(rows: list[Any]) -> str:
    if not rows:
        return '<div class="empty">No prospects captured yet.</div>'
    body = []
    for r in rows:
        name = f'{r["contact_first_name"] or ""} {r["contact_last_name"] or ""}'.strip() or "—"
        company = html.escape(r["company_name"] or "—")
        email = html.escape(r["contact_email"] or "—")
        title = html.escape((r["contact_title"] or "")[:40])
        status = (r["status"] or "new").lower()
        badge_cls = _LEAD_STATUS_COLOR.get(status, "info")
        fit = r["fit_score"]
        fit_str = f'{fit:.2f}' if isinstance(fit, (int, float)) else "—"
        source = html.escape(r["source"] or "apollo")
        loc = html.escape((r["location"] or "")[:24])
        emp = r["employee_count"] or ""
        ago = _humanize_ago(r["created_at"]) if r["created_at"] else ""
        body.append(
            f'<tr>'
            f'<td>{html.escape(name)}<div style="color:var(--gray-400);font-size:11px">{title}</div></td>'
            f'<td>{company}<div style="color:var(--gray-400);font-size:11px">{loc}{" · " if loc and emp else ""}{emp}{" emp" if emp else ""}</div></td>'
            f'<td><span style="font-family:SF Mono,Menlo,monospace;font-size:12px">{email}</span></td>'
            f'<td><span class="badge {badge_cls}">{html.escape(status)}</span></td>'
            f'<td>{fit_str}</td>'
            f'<td>{source}</td>'
            f'<td style="color:var(--gray-400);font-size:11px">{ago}</td>'
            f'</tr>'
        )
    return (
        '<table class="table"><thead><tr>'
        '<th>Contact</th><th>Company</th><th>Email</th><th>Status</th>'
        '<th>Fit</th><th>Source</th><th>Captured</th>'
        '</tr></thead><tbody>'
        + "\n".join(body)
        + '</tbody></table>'
    )


def _humanize_ago(dt: Any) -> str:
    """cheap relative-time renderer; returns '3h ago', '2d ago', etc."""
    from datetime import datetime, timezone
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
    except Exception:  # noqa: BLE001
        return str(dt)[:16]
    s = int(delta.total_seconds())
    if s < 60: return f"{s}s ago"
    if s < 3600: return f"{s//60}m ago"
    if s < 86400: return f"{s//3600}h ago"
    return f"{s//86400}d ago"


def _render_history_summary(summary: dict[str, dict[str, int]], days: int) -> str:
    def row(stream_label: str, counts: dict[str, int]) -> str:
        pending = counts.get("pending", 0)
        approved = counts.get("approved", 0) + counts.get("published", 0) + counts.get("sent", 0)
        rejected = counts.get("rejected", 0)
        total = pending + approved + rejected
        rate = f"{(approved/total*100):.0f}%" if total else "—"
        return (
            f'<tr><td><strong>{html.escape(stream_label)}</strong></td>'
            f'<td>{total}</td>'
            f'<td><span class="badge">{approved}</span></td>'
            f'<td><span class="badge bad">{rejected}</span></td>'
            f'<td><span class="badge warn">{pending}</span></td>'
            f'<td>{rate}</td></tr>'
        )
    return (
        f'<table class="table"><thead><tr>'
        f'<th>Stream</th><th>Total {days}d</th><th>Approved / Sent</th>'
        f'<th>Rejected</th><th>Pending</th><th>Approval rate</th>'
        f'</tr></thead><tbody>'
        + row("Social drafts", summary["social"])
        + row("Cold outreach", summary["outreach"])
        + row("KB articles", summary["kb"])
        + '</tbody></table>'
    )


def _render_nav(active: str, email: str) -> str:
    tabs = [
        ("queue", "Queue", "/admin/inbox/queue"),
        ("leads", "Leads", "/admin/inbox/queue#leads"),
        ("clients", "Clients", "/admin/inbox/clients"),
        ("invoices", "Invoices", "/admin/inbox/invoices"),
        ("contracts", "Contracts", "/admin/inbox/contracts"),
        ("approvals", "Approvals", "/admin/inbox/approvals"),
        ("loki-console", "Klara AI Console", "/admin/inbox/loki-console"),
        ("history", "History", "/admin/inbox/queue#history"),
        ("ops", "Ops", "/admin/inbox/queue#sec-denials"),
        ("streams", "Streams", "/admin/inbox/streams"),
    ]
    parts = []
    for key, label, href in tabs:
        cls = ' class="active"' if active == key else ''
        parts.append(f'<a href="{href}"{cls}>{label}</a>')
    tab_html = "".join(parts)
    return (
        '<div class="nav">'
        '<div class="nav-brand">klara<span class="accent">vex</span> <span style="color:var(--gray-400);font-weight:400;font-size:13px;margin-left:8px">admin</span></div>'
        f'<div class="nav-tabs">{tab_html}</div>'
        f'<div class="nav-user">{html.escape(email)}<a href="/admin/logout">sign out</a></div>'
        '</div>'
    )


# ─── Klara AI Agent Monitoring Console ──────────────────────────────────────────
# Report Priority-1 gap (klaravex-admin-portal-review_20260717.md) + the
# artifact reference (https://claude.ai/code/artifact/58bc42b8-...). Reads
# klaravex_agent_runs (migration 034) -- a generalized run table with no
# existing writers yet. This page is real (not mocked), it will just show
# empty states until agents are instrumented to write to it -- see
# .loki/specs/2026-07-17-admin-console-rebuild-reference.md for that
# follow-on work.

async def _fetch_agent_run_kpis() -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
              (SELECT count(*) FROM klaravex_agent_runs WHERE status='running')                AS running_now,
              (SELECT count(*) FROM klaravex_agent_runs WHERE status='queued')                  AS queued,
              (SELECT count(*) FROM klaravex_agent_runs
                WHERE status='completed' AND finished_at > date_trunc('day', now()))            AS completed_today,
              (SELECT count(*) FROM klaravex_agent_runs
                WHERE status='failed' AND finished_at > date_trunc('day', now()))                AS failed_today
            """
        )
    r = rows[0]
    completed = r["completed_today"] or 0
    failed = r["failed_today"] or 0
    total_finished = completed + failed
    sla_pct = round(100 * completed / total_finished) if total_finished else None
    return {
        "running_now": r["running_now"] or 0,
        "queued": r["queued"] or 0,
        "completed_today": completed,
        "failed_today": failed,
        "sla_pct": sla_pct,
    }


async def _fetch_active_agent_runs(limit: int = 50) -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT id, agent_id, job_kind, trigger_type, client_id, status, started_at "
            "FROM klaravex_agent_runs WHERE status IN ('running','queued') "
            "ORDER BY started_at ASC LIMIT $1",
            limit,
        ))


async def _fetch_completed_agent_runs(limit: int = 30) -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT id, agent_id, job_kind, trigger_type, client_id, status, "
            "       output_ref, error, started_at, finished_at "
            "FROM klaravex_agent_runs WHERE status IN ('completed','failed','cancelled') "
            "ORDER BY finished_at DESC NULLS LAST LIMIT $1",
            limit,
        ))


def _render_agent_run_kpi_grid(k: dict[str, Any]) -> str:
    def tile(label: str, value: Any, klass: str = "", sub: str = "") -> str:
        return (
            f'<div class="kpi"><div class="kpi-label">{html.escape(label)}</div>'
            f'<div class="kpi-value {klass}">{html.escape(str(value))}</div>'
            + (f'<div class="kpi-sub">{html.escape(sub)}</div>' if sub else "")
            + '</div>'
        )
    sla_display = f'{k["sla_pct"]}%' if k["sla_pct"] is not None else "—"
    return (
        '<div class="kpi-grid">'
        + tile("Running now", k["running_now"], klass="good" if k["running_now"] else "")
        + tile("Queued", k["queued"], klass="warn" if k["queued"] else "")
        + tile("Completed today", k["completed_today"],
               klass="good" if k["completed_today"] else "",
               sub=f'{k["failed_today"]} failed' if k["failed_today"] else "0 failed")
        + tile("SLA compliance", sla_display,
               klass="good" if (k["sla_pct"] or 0) >= 95 else ("warn" if k["sla_pct"] is not None else ""),
               sub="no runs finished today" if k["sla_pct"] is None else "")
        + '</div>'
    )


def _render_agent_run_row(row: Any, *, terminal: bool) -> str:
    agent = html.escape(row["agent_id"] or "")
    kind = html.escape(row["job_kind"] or "")
    trigger = html.escape(row["trigger_type"] or "")
    client = html.escape(row["client_id"] or "") if row["client_id"] else ""
    status = row["status"] or ""
    status_class = {"running": "info", "queued": "warn", "completed": "good",
                     "failed": "bad", "cancelled": "warn"}.get(status, "")
    started = row["started_at"].strftime("%b %d %H:%M") if row["started_at"] else "—"
    sub_bits = [f"trigger: {trigger}"]
    if client:
        sub_bits.append(f"client: {client}")
    sub_bits.append(f"started {started}")
    if terminal:
        finished = row["finished_at"].strftime("%b %d %H:%M") if row["finished_at"] else "—"
        sub_bits.append(f"finished {finished}")
        if row["output_ref"]:
            sub_bits.append(f'output: {html.escape(row["output_ref"])}')
        if row["error"]:
            sub_bits.append(f'error: {html.escape((row["error"] or "")[:120])}')
    actions = ""
    if not terminal:
        run_id = str(row["id"])
        actions = (
            f'<form method="post" action="/admin/inbox/loki-console/{run_id}/cancel" style="display:inline">'
            f'<button type="submit" class="btn-cancel">Cancel</button></form>'
        )
    return (
        '<div class="run-row">'
        f'<div class="run-main"><div class="run-name">{agent} · {kind}</div>'
        f'<div class="run-sub">{" · ".join(sub_bits)}</div></div>'
        f'<span class="badge {status_class}">{html.escape(status)}</span>'
        f'{actions}'
        '</div>'
    )


@router.get("/loki-console", response_class=HTMLResponse, include_in_schema=False)
async def inbox_loki_console(
    email: str = Depends(require_admin_session),
) -> HTMLResponse:
    """Cross-agent job monitoring. Reads klaravex_agent_runs (migration 034) --
    a brand-new table with no writers yet, so this will show real empty
    states (not fake data) until agents are instrumented to write run
    records. See .loki/specs/2026-07-17-admin-console-rebuild-reference.md.
    """
    kpis = await _fetch_agent_run_kpis()
    active_rows = await _fetch_active_agent_runs()
    completed_rows = await _fetch_completed_agent_runs()

    active_html = (
        "\n".join(_render_agent_run_row(r, terminal=False) for r in active_rows)
        if active_rows else '<div class="empty">No agents running or queued right now.</div>'
    )
    completed_html = (
        "\n".join(_render_agent_run_row(r, terminal=True) for r in completed_rows)
        if completed_rows else '<div class="empty">No completed runs yet -- agents are not '
        'instrumented to write to klaravex_agent_runs yet (migration 034 is new).</div>'
    )

    sections = [
        _render_agent_run_kpi_grid(kpis),
        '<div class="section-hdr"><h2>Active jobs</h2></div>',
        active_html,
        '<div class="section-hdr"><h2>Completed jobs</h2></div>',
        completed_html,
    ]
    page = (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Klaravex admin — Klara AI console</title>{_BASE_STYLE}</head><body>'
        + _render_nav("loki-console", email)
        + '<div class="container">'
        + '<h1>Klara AI Console</h1>'
        + f'<div class="subhead">Cross-agent job monitoring · signed in as {html.escape(email)}</div>'
        + "\n".join(sections)
        + '</div></body></html>'
    )
    return HTMLResponse(content=page)


@router.post("/loki-console/{run_id}/cancel", include_in_schema=False)
async def cancel_agent_run(
    run_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex_agent_runs SET status='cancelled', finished_at=now() "
            "WHERE id=$1 AND status IN ('running','queued')",
            run_id,
        )
    log.info("loki-console cancel run %s by %s", run_id, email)
    return RedirectResponse(url="/admin/inbox/loki-console", status_code=303)


# ─── iter-77: Clients (main customer records + portal login accounts) ─────────
async def _fetch_main_clients(limit: int = 200) -> list[Any]:
    """Main customer records — the paying customers. Source of truth for
    Stripe billing and customer_code identity."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT id, email, name, company, segment, stripe_customer_id, "
            "       customer_code, timezone, skip_payment, phone, "
            "       welcome_sent_at, created_at "
            "FROM public.klaravex_clients "
            "ORDER BY created_at DESC LIMIT $1",
            limit,
        ))


async def _fetch_portal_clients(limit: int = 200) -> list[Any]:
    """Portal login accounts — clients who can sign into the customer portal."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT id, name, email, company, is_active, language_preference, "
            "       internal_notes, last_login_at, created_at "
            "FROM klaravex.portal_clients "
            "ORDER BY created_at DESC LIMIT $1",
            limit,
        ))


async def _fetch_client_kpis() -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
              (SELECT count(*) FROM public.klaravex_clients)                                AS main_ct,
              (SELECT count(*) FROM public.klaravex_clients
                WHERE stripe_customer_id IS NOT NULL)                                       AS stripe_linked,
              (SELECT count(DISTINCT segment) FROM public.klaravex_clients)                 AS segments,
              (SELECT count(*) FROM klaravex.portal_clients)                                AS portal_ct,
              (SELECT count(*) FROM klaravex.portal_clients WHERE is_active)                AS portal_active,
              (SELECT count(*) FROM klaravex.portal_clients
                WHERE last_login_at > now() - interval '30 days')                           AS portal_recent
            """
        )
    r = rows[0]
    return {
        "main_ct": r["main_ct"], "stripe_linked": r["stripe_linked"],
        "segments": r["segments"], "portal_ct": r["portal_ct"],
        "portal_active": r["portal_active"], "portal_recent": r["portal_recent"],
    }


def _render_main_clients_table(rows: list[Any]) -> str:
    if not rows:
        return '<div class="empty">No customer records yet.</div>'
    body = []
    for r in rows:
        stripe = ('<span class="badge good">stripe</span>'
                  if r["stripe_customer_id"] else '<span class="badge warn">no stripe</span>')
        skip = ' <span class="badge warn">skip pay</span>' if r["skip_payment"] else ""
        welcome = ('<span class="badge">welcomed</span>'
                   if r["welcome_sent_at"] else '<span class="badge warn">pending</span>')
        code = html.escape(r["customer_code"] or "—")
        seg = html.escape((r["segment"] or "").lower())
        seg_cls = "info" if seg == "b2b" else ("warn" if seg == "consumer" else "")
        phone_html = (f'<div style="color:var(--gray-400);font-size:11px">{html.escape(r["phone"])}</div>'
                      if r["phone"] else "")
        detail_url = f'/admin/inbox/clients/{r["id"]}'
        display_name = html.escape(r["name"] or r["company"] or r["email"] or "—")
        body.append(
            f'<tr onclick="window.location=\'{detail_url}\'" style="cursor:pointer">'
            f'<td><a href="{detail_url}" style="color:var(--white);text-decoration:none;font-weight:600">{display_name}</a>'
            f'<div style="color:var(--gray-400);font-size:11px">{html.escape(r["company"] or "")}</div></td>'
            f'<td><span style="font-family:SF Mono,Menlo,monospace;font-size:12px">{html.escape(r["email"])}</span>'
            f'{phone_html}</td>'
            f'<td><span class="badge {seg_cls}">{seg or "—"}</span></td>'
            f'<td><span style="font-family:SF Mono,Menlo,monospace;font-size:12px">{code}</span></td>'
            f'<td>{stripe}{skip}</td>'
            f'<td>{welcome}</td>'
            f'<td style="color:var(--gray-400);font-size:11px">{_humanize_ago(r["created_at"])}</td>'
            f'</tr>'
        )
    return (
        '<table class="table"><thead><tr>'
        '<th>Name</th><th>Contact</th><th>Segment</th><th>Code</th>'
        '<th>Billing</th><th>Welcome</th><th>Added</th>'
        '</tr></thead><tbody>' + "\n".join(body) + '</tbody></table>'
    )


def _render_portal_clients_table(rows: list[Any]) -> str:
    if not rows:
        return ('<div class="empty">No portal accounts yet. Portal accounts let clients sign in '
                'to their own dashboard; create one when a customer needs self-service access.</div>')
    body = []
    for r in rows:
        active = ('<span class="badge good">active</span>'
                  if r["is_active"] else '<span class="badge bad">disabled</span>')
        last_login = _humanize_ago(r["last_login_at"]) if r["last_login_at"] else "never"
        cid = str(r["id"])
        toggle_url = (f"/admin/inbox/clients/portal/{cid}/"
                      f"{'deactivate' if r['is_active'] else 'activate'}")
        toggle_label = "disable" if r["is_active"] else "enable"
        actions = (
            f'<form method="post" action="{toggle_url}" style="display:inline">'
            f'<button type="submit" class="btn btn-reject" style="padding:4px 10px;font-size:11px">{toggle_label}</button></form>'
        )
        body.append(
            f'<tr>'
            f'<td>{html.escape(r["name"] or "—")}'
            f'<div style="color:var(--gray-400);font-size:11px">{html.escape(r["company"] or "")}</div></td>'
            f'<td><span style="font-family:SF Mono,Menlo,monospace;font-size:12px">{html.escape(r["email"])}</span></td>'
            f'<td>{active}</td>'
            f'<td>{html.escape((r["language_preference"] or "en"))}</td>'
            f'<td style="color:var(--gray-400);font-size:11px">{last_login}</td>'
            f'<td style="color:var(--gray-400);font-size:11px">{_humanize_ago(r["created_at"])}</td>'
            f'<td>{actions}</td>'
            f'</tr>'
        )
    return (
        '<table class="table"><thead><tr>'
        '<th>Name</th><th>Email</th><th>Status</th><th>Lang</th>'
        '<th>Last login</th><th>Added</th><th>Actions</th>'
        '</tr></thead><tbody>' + "\n".join(body) + '</tbody></table>'
    )


def _render_client_kpi_grid(k: dict[str, Any]) -> str:
    def tile(label: str, value: Any, klass: str = "", sub: str = "") -> str:
        return (
            f'<div class="kpi"><div class="kpi-label">{html.escape(label)}</div>'
            f'<div class="kpi-value {klass}">{html.escape(str(value))}</div>'
            + (f'<div class="kpi-sub">{html.escape(sub)}</div>' if sub else "")
            + '</div>'
        )
    return (
        '<div class="kpi-grid">'
        + tile("Customer records", k["main_ct"],
               klass="good" if k["main_ct"] > 0 else "",
               sub=f'{k["segments"]} segments')
        + tile("Stripe-linked", k["stripe_linked"],
               klass="good" if k["stripe_linked"] > 0 else "warn",
               sub=f'of {k["main_ct"]}')
        + tile("Portal accounts", k["portal_ct"],
               sub=f'{k["portal_active"]} active')
        + tile("Portal logins 30d", k["portal_recent"],
               klass="good" if k["portal_recent"] > 0 else "",
               sub="active users")
        + '</div>'
    )


# ─── iter-78: Client detail fetches ───────────────────────────────────────────
async def _fetch_client_by_id(client_id: str) -> Any:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT id, email, name, company, segment, stripe_customer_id, "
            "       customer_code, timezone, skip_payment, phone, metadata, "
            "       welcome_sent_at, attribution_team, csat_survey_sent_at, "
            "       created_at, updated_at "
            "FROM public.klaravex_clients WHERE id=$1",
            client_id,
        )


async def _fetch_client_related(email: str) -> dict[str, list[Any]]:
    """Pull everything tied to a given client email across schemas. Uses
    email match (not FK) because portal_invoices.client_id points to
    portal_clients not klaravex_clients — no direct FK exists."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # iter-78-hotfix: source column doesn't exist yet — omit + inject literal 'apollo' below
        prospected_raw = await conn.fetch(
            "SELECT id, company_name, contact_email, contact_first_name, "
            "       contact_last_name, contact_title, status, "
            "       fit_score, industry, employee_count, location, created_at "
            "FROM klaravex_prospected_leads WHERE lower(contact_email)=lower($1) "
            "ORDER BY created_at DESC LIMIT 20",
            email,
        )
        prospected = [{**dict(r), "source": "apollo"} for r in prospected_raw]
        outreach = await conn.fetch(
            "SELECT a.id, a.subject, a.status, a.approved_at, a.sent_at, "
            "       a.created_at, p.contact_email "
            "FROM klaravex_outreach_approvals a "
            "JOIN klaravex_prospected_leads p ON p.id = a.prospect_id "
            "WHERE lower(p.contact_email)=lower($1) "
            "ORDER BY a.created_at DESC LIMIT 20",
            email,
        )
        gen_invoices = await conn.fetch(
            "SELECT id, invoice_number, service_description, amount_gross, "
            "       currency, status, issued_date, due_date, paid_at, created_at "
            "FROM klaravex.generated_invoices WHERE lower(client_email)=lower($1) "
            "ORDER BY created_at DESC LIMIT 20",
            email,
        )
        portal_client = await conn.fetchrow(
            "SELECT id, is_active, last_login_at, language_preference "
            "FROM klaravex.portal_clients WHERE lower(email)=lower($1)",
            email,
        )
    return {
        "prospected": list(prospected),
        "outreach": list(outreach),
        "gen_invoices": list(gen_invoices),
        "portal_client": portal_client,
    }


def _render_client_detail_card(c: Any) -> str:
    def field(label: str, value: Any) -> str:
        v = html.escape(str(value)) if value is not None and value != "" else '<span style="color:var(--gray-600)">—</span>'
        return (
            f'<div><div class="kpi-label">{html.escape(label)}</div>'
            f'<div style="font-size:14px;color:var(--white);margin-top:4px">{v}</div></div>'
        )
    seg_cls = "info" if (c["segment"] or "").lower() == "b2b" else ("warn" if (c["segment"] or "").lower() == "consumer" else "")
    stripe_row = ""
    if c["stripe_customer_id"]:
        stripe_row = (
            f'<a href="https://dashboard.stripe.com/customers/{html.escape(c["stripe_customer_id"])}" '
            f'target="_blank" style="color:var(--amber);font-family:SF Mono,Menlo,monospace;font-size:12px">'
            f'{html.escape(c["stripe_customer_id"])} ↗</a>'
        )
    else:
        stripe_row = '<span style="color:var(--gray-600)">— not linked</span>'
    return (
        '<div class="card" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px">'
        + field("Name", c["name"])
        + field("Email", c["email"])
        + field("Company", c["company"])
        + f'<div><div class="kpi-label">Segment</div>'
          f'<div style="margin-top:4px"><span class="badge {seg_cls}">{html.escape((c["segment"] or "—").lower())}</span></div></div>'
        + field("Customer code", c["customer_code"])
        + field("Phone", c["phone"])
        + field("Timezone", c["timezone"])
        + field("Attribution team", c["attribution_team"])
        + f'<div><div class="kpi-label">Stripe customer</div>'
          f'<div style="margin-top:4px">{stripe_row}</div></div>'
        + field("Welcome sent", _fmt_date(c["welcome_sent_at"]) if c["welcome_sent_at"] else "pending")
        + field("CSAT sent", _fmt_date(c["csat_survey_sent_at"]) if c["csat_survey_sent_at"] else "not yet")
        + field("Skip payment", "yes" if c["skip_payment"] else "no")
        + field("Created", _humanize_ago(c["created_at"]))
        + field("Updated", _humanize_ago(c["updated_at"]))
        + '</div>'
    )


def _render_client_portal_status(portal: Any) -> str:
    if not portal:
        return ('<div class="empty">No portal login account for this client. '
                'Create one when they need self-service dashboard access.</div>')
    active = ('<span class="badge good">active</span>'
              if portal["is_active"] else '<span class="badge bad">disabled</span>')
    last = _humanize_ago(portal["last_login_at"]) if portal["last_login_at"] else "never"
    cid = str(portal["id"])
    toggle_url = f"/admin/inbox/clients/portal/{cid}/{'deactivate' if portal['is_active'] else 'activate'}"
    toggle_label = "disable" if portal["is_active"] else "enable"
    return (
        f'<div class="card" style="display:flex;align-items:center;gap:24px;flex-wrap:wrap">'
        f'<div>Status: {active}</div>'
        f'<div style="color:var(--gray-400);font-size:13px">Language: {html.escape(portal["language_preference"] or "en")}</div>'
        f'<div style="color:var(--gray-400);font-size:13px">Last login: {last}</div>'
        f'<form method="post" action="{toggle_url}" style="margin-left:auto">'
        f'<button type="submit" class="btn btn-reject">{toggle_label} portal login</button></form>'
        f'</div>'
    )


def _render_client_related_leads(rows: list[Any]) -> str:
    if not rows:
        return '<div class="empty">No prospect records for this email.</div>'
    body = []
    for r in rows:
        status = (r["status"] or "new").lower()
        cls = _LEAD_STATUS_COLOR.get(status, "info")
        body.append(
            f'<tr>'
            f'<td>{html.escape(r["company_name"] or "—")}</td>'
            f'<td><span class="badge {cls}">{html.escape(status)}</span></td>'
            f'<td>{html.escape(r["source"] or "apollo")}</td>'
            f'<td>{(r["fit_score"] or 0):.2f}</td>'
            f'<td style="color:var(--gray-400);font-size:11px">{_humanize_ago(r["created_at"])}</td>'
            f'</tr>'
        )
    return (
        '<table class="table"><thead><tr>'
        '<th>Company</th><th>Status</th><th>Source</th><th>Fit</th><th>Captured</th>'
        '</tr></thead><tbody>' + "\n".join(body) + '</tbody></table>'
    )


def _render_client_related_outreach(rows: list[Any]) -> str:
    if not rows:
        return '<div class="empty">No outreach emails sent to this address.</div>'
    body = []
    for r in rows:
        status = (r["status"] or "").lower()
        cls = _INVOICE_STATUS_COLOR.get(status, "info")
        sent = _humanize_ago(r["sent_at"]) if r["sent_at"] else "not sent"
        body.append(
            f'<tr>'
            f'<td>{html.escape((r["subject"] or "")[:80])}</td>'
            f'<td><span class="badge {cls}">{html.escape(status)}</span></td>'
            f'<td style="color:var(--gray-400);font-size:11px">{sent}</td>'
            f'<td style="color:var(--gray-400);font-size:11px">{_humanize_ago(r["created_at"])}</td>'
            f'</tr>'
        )
    return (
        '<table class="table"><thead><tr>'
        '<th>Subject</th><th>Status</th><th>Sent</th><th>Drafted</th>'
        '</tr></thead><tbody>' + "\n".join(body) + '</tbody></table>'
    )


def _render_client_related_invoices(rows: list[Any]) -> str:
    if not rows:
        return '<div class="empty">No invoices for this client yet.</div>'
    body = []
    for r in rows:
        label, cls = _invoice_row_status(r["status"], r["due_date"])
        body.append(
            f'<tr>'
            f'<td><span style="font-family:SF Mono,Menlo,monospace;font-size:12px">{html.escape(r["invoice_number"] or "")}</span></td>'
            f'<td>{html.escape((r["service_description"] or "")[:80])}</td>'
            f'<td>{_fmt_money(r["amount_gross"], r["currency"])}</td>'
            f'<td><span class="badge {cls}">{html.escape(label)}</span></td>'
            f'<td>{_fmt_date(r["due_date"])}</td>'
            f'<td>{_invoice_actions("generated", str(r["id"]), r["status"])}</td>'
            f'</tr>'
        )
    return (
        '<table class="table"><thead><tr>'
        '<th>#</th><th>Service</th><th>Amount</th><th>Status</th>'
        '<th>Due</th><th>Actions</th>'
        '</tr></thead><tbody>' + "\n".join(body) + '</tbody></table>'
    )


# ─── iter-79: Contracts (approval_requests filtered by action_name) ──────────
_CONTRACT_ACTION_NAMES = ("contract.send", "contract.generate", "contract.renewal",
                         "deal.send_contract", "deal.generate_contract")


async def _fetch_contracts(status_filter: str | None = None, limit: int = 100) -> list[Any]:
    """Contracts are approval_requests rows with contract-related action names."""
    pool = await get_pool()
    where_clauses = ["a.action_name = ANY($1::varchar[])"]
    params: list[Any] = [list(_CONTRACT_ACTION_NAMES)]
    if status_filter:
        where_clauses.append(f"a.status = ${len(params)+1}")
        params.append(status_filter)
    where_sql = " AND ".join(where_clauses)
    query = (
        f"SELECT a.id, a.action_name, a.risk_level, a.payload, a.justification, "
        f"       a.requested_by_agent, a.lead_id, a.status, a.reviewed_by, "
        f"       a.review_note, a.created_at, a.expires_at, a.reviewed_at, "
        f"       p.company_name AS lead_company, p.contact_email AS lead_email, "
        f"       p.contact_first_name AS lead_first, p.contact_last_name AS lead_last "
        f"FROM klaravex.approval_requests a "
        f"LEFT JOIN klaravex_prospected_leads p ON p.id::varchar = a.lead_id "
        f"WHERE {where_sql} "
        f"ORDER BY a.created_at DESC LIMIT {int(limit)}"
    )
    async with pool.acquire() as conn:
        return list(await conn.fetch(query, *params))


async def _fetch_contract_kpis() -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT status, count(*) AS n FROM klaravex.approval_requests "
            "WHERE action_name = ANY($1::varchar[]) GROUP BY status",
            list(_CONTRACT_ACTION_NAMES),
        )
    counts = {r["status"]: r["n"] for r in rows}
    return {
        "pending": counts.get("pending", 0),
        "approved": counts.get("approved", 0),
        "rejected": counts.get("rejected", 0),
        "expired": counts.get("expired", 0),
        "total": sum(counts.values()),
    }


def _render_contract_kpi_grid(k: dict[str, Any]) -> str:
    def tile(label: str, value: Any, klass: str = "", sub: str = "") -> str:
        return (
            f'<div class="kpi"><div class="kpi-label">{html.escape(label)}</div>'
            f'<div class="kpi-value {klass}">{html.escape(str(value))}</div>'
            + (f'<div class="kpi-sub">{html.escape(sub)}</div>' if sub else "")
            + '</div>'
        )
    return (
        '<div class="kpi-grid">'
        + tile("Pending review", k["pending"], klass="warn" if k["pending"] > 0 else "good",
               sub="awaiting your call")
        + tile("Approved", k["approved"], klass="good" if k["approved"] > 0 else "",
               sub="signed and sent")
        + tile("Rejected", k["rejected"], klass="bad" if k["rejected"] > 0 else "",
               sub="killed at review")
        + tile("Expired", k["expired"], klass="warn" if k["expired"] > 0 else "",
               sub="review window lapsed")
        + '</div>'
    )


def _contract_payload_preview(payload: str | None) -> str:
    """Extract key fields from JSON payload for row display."""
    if not payload:
        return "—"
    try:
        import json as _json
        d = _json.loads(payload)
    except Exception:  # noqa: BLE001
        return html.escape(str(payload)[:120])
    parts = []
    for key in ("amount", "amount_gross", "price", "value", "currency",
                "term_months", "term", "pdf_path", "pdf_url", "subject", "title"):
        if key in d and d[key] not in (None, ""):
            parts.append(f'<span style="color:var(--gray-400)">{key}:</span> {html.escape(str(d[key])[:40])}')
    if not parts:
        # fallback: show top-level keys
        return html.escape(", ".join(d.keys())[:120])
    return " · ".join(parts)


def _render_contracts_table(rows: list[Any]) -> str:
    if not rows:
        return ('<div class="empty">No contracts. Contract approvals appear here when an agent '
                'proposes a contract for a lead (action_name contract.send / contract.generate / '
                'deal.generate_contract).</div>')
    body = []
    for r in rows:
        status = (r["status"] or "").lower()
        s_cls = _INVOICE_STATUS_COLOR.get(status, "info")
        risk_cls = "bad" if r["risk_level"] in ("high", "critical") else ("warn" if r["risk_level"] == "medium" else "info")
        contact = f'{r["lead_first"] or ""} {r["lead_last"] or ""}'.strip() or "—"
        company = html.escape(r["lead_company"] or "—")
        email_addr = html.escape(r["lead_email"] or "")
        cid = str(r["id"])
        preview = _contract_payload_preview(r["payload"])
        actions = ""
        if status == "pending":
            actions = (
                f'<form method="post" action="/admin/inbox/contracts/{cid}/approve" style="display:inline">'
                f'<button type="submit" class="btn btn-approve" style="padding:4px 10px;font-size:11px">approve</button></form> '
                f'<form method="post" action="/admin/inbox/contracts/{cid}/reject" style="display:inline" '
                f'onsubmit="return confirm(\'Reject this contract? Cannot be undone.\');">'
                f'<button type="submit" class="btn btn-reject" style="padding:4px 10px;font-size:11px">reject</button></form>'
            )
        body.append(
            f'<tr>'
            f'<td>{html.escape(r["action_name"])}'
            f'<div style="color:var(--gray-400);font-size:11px">{html.escape(r["requested_by_agent"] or "")}</div></td>'
            f'<td>{company}<div style="color:var(--gray-400);font-size:11px">{html.escape(contact)}{" · " + email_addr if email_addr else ""}</div></td>'
            f'<td>{preview}</td>'
            f'<td><span class="badge {risk_cls}">{html.escape(r["risk_level"] or "—")}</span></td>'
            f'<td><span class="badge {s_cls}">{html.escape(status)}</span></td>'
            f'<td style="color:var(--gray-400);font-size:11px">{_humanize_ago(r["created_at"])}</td>'
            f'<td>{actions}</td>'
            f'</tr>'
        )
    return (
        '<table class="table"><thead><tr>'
        '<th>Action</th><th>Lead / company</th><th>Payload preview</th>'
        '<th>Risk</th><th>Status</th><th>Created</th><th>Actions</th>'
        '</tr></thead><tbody>' + "\n".join(body) + '</tbody></table>'
    )


# ─── Approvals (all non-contract approval_requests: outreach, social, etc.) ──
# Fixes a gap found 2026-07-18: the P3/P4/P5 approval_requests rows created by
# prospecting_outreach.send / social_media_manager.publish / etc. had no
# reachable review page. The overview "Approval Queue" card previously pointed
# at /admin/inbox/queue, which only covers the separate content-draft queue
# (social/marketing/bids/outreach-content/kb) and never included these rows.

async def _fetch_approvals(status_filter: str | None = None, limit: int = 200) -> list[Any]:
    """Non-contract approval_requests rows (contracts have their own page)."""
    pool = await get_pool()
    where_clauses = ["NOT (a.action_name = ANY($1::varchar[]))"]
    params: list[Any] = [list(_CONTRACT_ACTION_NAMES)]
    if status_filter:
        where_clauses.append(f"a.status = ${len(params)+1}")
        params.append(status_filter)
    where_sql = " AND ".join(where_clauses)
    query = (
        f"SELECT a.id, a.action_name, a.risk_level, a.payload, a.justification, "
        f"       a.requested_by_agent, a.lead_id, a.status, a.reviewed_by, "
        f"       a.review_note, a.created_at, a.expires_at, a.reviewed_at, "
        f"       p.company_name AS lead_company, p.contact_email AS lead_email, "
        f"       p.contact_first_name AS lead_first, p.contact_last_name AS lead_last "
        f"FROM klaravex.approval_requests a "
        f"LEFT JOIN klaravex_prospected_leads p ON p.id::varchar = a.lead_id "
        f"WHERE {where_sql} "
        f"ORDER BY a.created_at DESC LIMIT {int(limit)}"
    )
    async with pool.acquire() as conn:
        return list(await conn.fetch(query, *params))


async def _fetch_approval_kpis() -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT status, count(*) AS n FROM klaravex.approval_requests "
            "WHERE NOT (action_name = ANY($1::varchar[])) GROUP BY status",
            list(_CONTRACT_ACTION_NAMES),
        )
    counts = {r["status"]: r["n"] for r in rows}
    return {
        "pending": counts.get("pending", 0),
        "approved": counts.get("approved", 0),
        "rejected": counts.get("rejected", 0),
        "expired": counts.get("expired", 0),
        "total": sum(counts.values()),
    }


def _render_approval_kpi_grid(k: dict[str, Any]) -> str:
    def tile(label: str, value: Any, klass: str = "", sub: str = "") -> str:
        return (
            f'<div class="kpi"><div class="kpi-label">{html.escape(label)}</div>'
            f'<div class="kpi-value {klass}">{html.escape(str(value))}</div>'
            + (f'<div class="kpi-sub">{html.escape(sub)}</div>' if sub else "")
            + '</div>'
        )
    return (
        '<div class="kpi-grid">'
        + tile("Pending review", k["pending"], klass="warn" if k["pending"] > 0 else "good",
               sub="awaiting your call")
        + tile("Approved", k["approved"], klass="good" if k["approved"] > 0 else "",
               sub="actioned")
        + tile("Rejected", k["rejected"], klass="bad" if k["rejected"] > 0 else "",
               sub="killed at review")
        + tile("Expired", k["expired"], klass="warn" if k["expired"] > 0 else "",
               sub="review window lapsed")
        + '</div>'
    )


def _render_approvals_table(rows: list[Any]) -> str:
    if not rows:
        return ('<div class="empty">No pending approvals. Actions from agents like '
                'prospecting_outreach and social_media_manager appear here when they '
                'need your review.</div>')
    body = []
    for r in rows:
        status = (r["status"] or "").lower()
        s_cls = _INVOICE_STATUS_COLOR.get(status, "info")
        risk_cls = "bad" if r["risk_level"] in ("high", "critical") else ("warn" if r["risk_level"] == "medium" else "info")
        contact = f'{r["lead_first"] or ""} {r["lead_last"] or ""}'.strip() or "—"
        company = html.escape(r["lead_company"] or "—")
        email_addr = html.escape(r["lead_email"] or "")
        aid = str(r["id"])
        preview = _contract_payload_preview(r["payload"])
        actions = ""
        if status == "pending":
            actions = (
                f'<form method="post" action="/admin/inbox/approvals/{aid}/approve" style="display:inline">'
                f'<button type="submit" class="btn btn-approve" style="padding:4px 10px;font-size:11px">approve</button></form> '
                f'<form method="post" action="/admin/inbox/approvals/{aid}/reject" style="display:inline" '
                f'onsubmit="return confirm(\'Reject this action? Cannot be undone.\');">'
                f'<button type="submit" class="btn btn-reject" style="padding:4px 10px;font-size:11px">reject</button></form>'
            )
        body.append(
            f'<tr>'
            f'<td>{html.escape(r["action_name"])}'
            f'<div style="color:var(--gray-400);font-size:11px">{html.escape(r["requested_by_agent"] or "")}</div></td>'
            f'<td>{company}<div style="color:var(--gray-400);font-size:11px">{html.escape(contact)}{" · " + email_addr if email_addr else ""}</div></td>'
            f'<td>{html.escape((r["justification"] or "—")[:140])}</td>'
            f'<td><span class="badge {risk_cls}">{html.escape(r["risk_level"] or "—")}</span></td>'
            f'<td><span class="badge {s_cls}">{html.escape(status)}</span></td>'
            f'<td style="color:var(--gray-400);font-size:11px">{_humanize_ago(r["created_at"])}</td>'
            f'<td>{actions}</td>'
            f'</tr>'
        )
    return (
        '<table class="table"><thead><tr>'
        '<th>Action</th><th>Lead / company</th><th>Justification</th>'
        '<th>Risk</th><th>Status</th><th>Created</th><th>Actions</th>'
        '</tr></thead><tbody>' + "\n".join(body) + '</tbody></table>'
    )


# ─── iter-75: Invoices fetches + renders ──────────────────────────────────────
async def _fetch_invoice_kpis() -> dict[str, Any]:
    """Single-shot invoice KPI snapshot across all three invoice tables +
    payments. Numbers are lifetime; can add rolling-window later.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
              (SELECT count(*) FROM klaravex.portal_invoices)                            AS portal_ct,
              (SELECT count(*) FROM klaravex.loki_invoices)                              AS loki_ct,
              (SELECT count(*) FROM klaravex.generated_invoices)                         AS gen_ct,
              (SELECT count(*) FROM klaravex.payments)                                   AS payments_ct,
              (SELECT COALESCE(sum(amount),0) FROM klaravex.portal_invoices
                WHERE status NOT IN ('paid','cancelled','void'))                         AS portal_outstanding,
              (SELECT COALESCE(sum(amount_eur),0) FROM klaravex.loki_invoices
                WHERE status NOT IN ('paid','cancelled','void'))                         AS loki_outstanding,
              (SELECT COALESCE(sum(amount_gross),0) FROM klaravex.generated_invoices
                WHERE status NOT IN ('paid','cancelled','void'))                         AS gen_outstanding,
              (SELECT COALESCE(sum(amount),0) FROM klaravex.payments
                WHERE status='succeeded' AND created_at > now() - interval '30 days')    AS paid_30d,
              (SELECT count(*) FROM klaravex.portal_invoices
                WHERE status NOT IN ('paid','cancelled','void') AND due_date < CURRENT_DATE) +
              (SELECT count(*) FROM klaravex.loki_invoices
                WHERE status NOT IN ('paid','cancelled','void') AND due_date < CURRENT_DATE) +
              (SELECT count(*) FROM klaravex.generated_invoices
                WHERE status NOT IN ('paid','cancelled','void') AND due_date < CURRENT_DATE) AS overdue_ct
            """
        )
    r = rows[0]
    return {
        "portal_ct": r["portal_ct"], "loki_ct": r["loki_ct"], "gen_ct": r["gen_ct"],
        "payments_ct": r["payments_ct"],
        "portal_outstanding": float(r["portal_outstanding"] or 0),
        "loki_outstanding": float(r["loki_outstanding"] or 0),
        "gen_outstanding": float(r["gen_outstanding"] or 0),
        "paid_30d": float(r["paid_30d"] or 0),
        "overdue_ct": r["overdue_ct"] or 0,
    }


async def _fetch_portal_invoices(limit: int = 100) -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT id, client_id, project_id, reference, amount, currency, status, "
            "       payment_link, due_date, created_at "
            "FROM klaravex.portal_invoices ORDER BY created_at DESC LIMIT $1",
            limit,
        ))


async def _fetch_loki_invoices(limit: int = 100) -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT id, lead_id, invoice_ref, amount_eur, description, "
            "       issue_date, due_date, status, reminder_count, "
            "       reminder_sent_at, created_at "
            "FROM klaravex.loki_invoices ORDER BY created_at DESC LIMIT $1",
            limit,
        ))


async def _fetch_generated_invoices(limit: int = 100) -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT id, invoice_number, client_name, client_email, client_company, "
            "       service_description, amount_net, vat_amount, amount_gross, currency, "
            "       issued_date, due_date, status, pdf_path, sent_at, paid_at, created_at "
            "FROM klaravex.generated_invoices ORDER BY created_at DESC LIMIT $1",
            limit,
        ))


async def _fetch_payments(limit: int = 100) -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT id, invoice_id, client_id, stripe_session_id, "
            "       stripe_payment_intent_id, amount, currency, status, created_at "
            "FROM klaravex.payments ORDER BY created_at DESC LIMIT $1",
            limit,
        ))


_INVOICE_STATUS_COLOR = {
    "paid": "good", "sent": "info", "draft": "warn",
    "cancelled": "bad", "void": "bad", "overdue": "bad",
    "pending": "warn", "issued": "info",
    "succeeded": "good", "failed": "bad", "refunded": "warn",
}


def _fmt_money(amount: Any, currency: str | None = "EUR") -> str:
    if amount is None:
        return "—"
    try:
        return f"{float(amount):,.2f} {currency or ''}".strip()
    except Exception:  # noqa: BLE001
        return str(amount)


def _fmt_date(d: Any) -> str:
    if not d:
        return "—"
    try:
        return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
    except Exception:  # noqa: BLE001
        return str(d)


def _invoice_row_status(status: str | None, due_date: Any) -> tuple[str, str]:
    """Returns (label, badge_class), auto-flagging overdue for unpaid rows."""
    s = (status or "").lower()
    if s not in ("paid", "cancelled", "void", "refunded") and due_date:
        try:
            from datetime import date
            if hasattr(due_date, "date"):
                due = due_date.date()
            else:
                due = due_date
            if due < date.today():
                return ("overdue", "bad")
        except Exception:  # noqa: BLE001
            pass
    return (s or "—", _INVOICE_STATUS_COLOR.get(s, "info"))


def _invoice_actions(stream: str, invoice_id: str, status: str | None) -> str:
    """Renders per-row Mark paid / Cancel forms. Hidden once terminal."""
    s = (status or "").lower()
    if s in ("paid", "cancelled", "void", "refunded"):
        return ""
    return (
        f'<form method="post" action="/admin/inbox/invoices/{stream}/{invoice_id}/mark-paid" style="display:inline">'
        f'<button type="submit" class="btn btn-approve" style="padding:4px 10px;font-size:11px">mark paid</button></form> '
        f'<form method="post" action="/admin/inbox/invoices/{stream}/{invoice_id}/cancel" style="display:inline" '
        f'onsubmit="return confirm(\'Cancel this invoice? Status will be set to cancelled.\');">'
        f'<button type="submit" class="btn btn-reject" style="padding:4px 10px;font-size:11px">cancel</button></form>'
    )


def _render_portal_invoices_table(rows: list[Any]) -> str:
    if not rows:
        return '<div class="empty">No client portal invoices yet.</div>'
    body = []
    for r in rows:
        label, cls = _invoice_row_status(r["status"], r["due_date"])
        pay = f'<a href="{html.escape(r["payment_link"])}" target="_blank">pay link</a>' if r["payment_link"] else "—"
        body.append(
            f'<tr>'
            f'<td><span style="font-family:SF Mono,Menlo,monospace;font-size:12px">{html.escape(r["reference"] or "")}</span></td>'
            f'<td>{_fmt_money(r["amount"], r["currency"])}</td>'
            f'<td><span class="badge {cls}">{html.escape(label)}</span></td>'
            f'<td>{_fmt_date(r["due_date"])}</td>'
            f'<td>{pay}</td>'
            f'<td style="color:var(--gray-400);font-size:11px">{_humanize_ago(r["created_at"])}</td>'
            f'<td>{_invoice_actions("portal", str(r["id"]), r["status"])}</td>'
            f'</tr>'
        )
    return (
        '<table class="table"><thead><tr>'
        '<th>Reference</th><th>Amount</th><th>Status</th><th>Due</th>'
        '<th>Payment link</th><th>Created</th><th>Actions</th>'
        '</tr></thead><tbody>' + "\n".join(body) + '</tbody></table>'
    )


def _render_loki_invoices_table(rows: list[Any]) -> str:
    if not rows:
        return '<div class="empty">No Klara AI-generated invoices yet.</div>'
    body = []
    for r in rows:
        label, cls = _invoice_row_status(r["status"], r["due_date"])
        rem = f'{r["reminder_count"]}×' if r["reminder_count"] else "—"
        body.append(
            f'<tr>'
            f'<td><span style="font-family:SF Mono,Menlo,monospace;font-size:12px">{html.escape(r["invoice_ref"] or "")}</span></td>'
            f'<td>{html.escape((r["description"] or "")[:60])}</td>'
            f'<td>{_fmt_money(r["amount_eur"], "EUR")}</td>'
            f'<td><span class="badge {cls}">{html.escape(label)}</span></td>'
            f'<td>{_fmt_date(r["due_date"])}</td>'
            f'<td>{rem}</td>'
            f'<td style="color:var(--gray-400);font-size:11px">{_humanize_ago(r["created_at"])}</td>'
            f'<td>{_invoice_actions("loki", str(r["id"]), r["status"])}</td>'
            f'</tr>'
        )
    return (
        '<table class="table"><thead><tr>'
        '<th>Ref</th><th>Description</th><th>Amount</th><th>Status</th>'
        '<th>Due</th><th>Reminders</th><th>Created</th><th>Actions</th>'
        '</tr></thead><tbody>' + "\n".join(body) + '</tbody></table>'
    )


def _render_generated_invoices_table(rows: list[Any]) -> str:
    if not rows:
        return '<div class="empty">No auto-generated invoices yet.</div>'
    body = []
    for r in rows:
        label, cls = _invoice_row_status(r["status"], r["due_date"])
        pdf = f'<a href="{html.escape(r["pdf_path"])}" target="_blank">pdf</a>' if r["pdf_path"] else "—"
        body.append(
            f'<tr>'
            f'<td><span style="font-family:SF Mono,Menlo,monospace;font-size:12px">{html.escape(r["invoice_number"] or "")}</span></td>'
            f'<td>{html.escape(r["client_company"] or r["client_name"] or "—")}'
            f'<div style="color:var(--gray-400);font-size:11px">{html.escape(r["client_email"] or "")}</div></td>'
            f'<td>{_fmt_money(r["amount_gross"], r["currency"])}'
            f'<div style="color:var(--gray-400);font-size:11px">net {_fmt_money(r["amount_net"], "")} · vat {_fmt_money(r["vat_amount"], "")}</div></td>'
            f'<td><span class="badge {cls}">{html.escape(label)}</span></td>'
            f'<td>{_fmt_date(r["due_date"])}</td>'
            f'<td>{pdf}</td>'
            f'<td style="color:var(--gray-400);font-size:11px">{_humanize_ago(r["created_at"])}</td>'
            f'<td>{_invoice_actions("generated", str(r["id"]), r["status"])}</td>'
            f'</tr>'
        )
    return (
        '<table class="table"><thead><tr>'
        '<th>#</th><th>Client</th><th>Amount (gross)</th><th>Status</th>'
        '<th>Due</th><th>PDF</th><th>Created</th><th>Actions</th>'
        '</tr></thead><tbody>' + "\n".join(body) + '</tbody></table>'
    )


def _render_create_invoice_form(client_options: list[Any] | None = None) -> str:
    """iter-76: minimal Create-invoice form. Writes to generated_invoices
    (no client FK required). Sits at top of Invoices page inside a card.
    iter-77: added client picker dropdown that auto-fills name/email/company
    from existing klaravex_clients records via inline JS.
    """
    picker_html = ""
    js_data_map = "{}"
    if client_options:
        import json as _json
        opts = ['<option value="">— manual entry —</option>']
        data_map: dict[str, dict[str, str]] = {}
        for c in client_options:
            cid = str(c["id"])
            display = f'{c["name"] or c["email"]} · {c["company"] or ""}'.strip(" ·")
            opts.append(f'<option value="{cid}">{html.escape(display)}</option>')
            data_map[cid] = {
                "name": c["name"] or "",
                "email": c["email"] or "",
                "company": c["company"] or "",
            }
        js_data_map = _json.dumps(data_map)
        picker_html = (
            '<label style="grid-column:1/-1;display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--amber)">'
            'Pick existing client (auto-fills fields below, or leave blank to type manually)'
            '<select id="klx-client-picker" onchange="klxPickClient(this.value)"'
            ' style="padding:8px;background:var(--navy);border:1px solid var(--amber);color:var(--white);border-radius:6px">'
            + "".join(opts)
            + '</select></label>'
        )
    return f"""
<div class="card" style="margin-bottom:24px">
  <details>
    <summary style="cursor:pointer;font-weight:600;color:var(--amber)">＋ Create new invoice (generated / manual PDF workflow)</summary>
    <form method="post" action="/admin/inbox/invoices/generated/create"
          style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px">
      {picker_html}
      <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--gray-400)">Client name *
        <input id="klx-inv-name" name="client_name" required style="padding:8px;background:var(--navy);border:1px solid var(--border-strong);color:var(--white);border-radius:6px"></label>
      <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--gray-400)">Client email *
        <input id="klx-inv-email" type="email" name="client_email" required style="padding:8px;background:var(--navy);border:1px solid var(--border-strong);color:var(--white);border-radius:6px"></label>
      <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--gray-400)">Client company
        <input id="klx-inv-company" name="client_company" style="padding:8px;background:var(--navy);border:1px solid var(--border-strong);color:var(--white);border-radius:6px"></label>
      <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--gray-400)">Client address
        <input name="client_address" style="padding:8px;background:var(--navy);border:1px solid var(--border-strong);color:var(--white);border-radius:6px"></label>
      <label style="grid-column:1/-1;display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--gray-400)">Service description *
        <textarea name="service_description" required rows="2" style="padding:8px;background:var(--navy);border:1px solid var(--border-strong);color:var(--white);border-radius:6px;font-family:inherit"></textarea></label>
      <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--gray-400)">Amount (net) *
        <input type="number" step="0.01" name="amount_net" required style="padding:8px;background:var(--navy);border:1px solid var(--border-strong);color:var(--white);border-radius:6px"></label>
      <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--gray-400)">VAT rate %
        <input type="number" step="0.01" name="vat_rate" value="0.00" style="padding:8px;background:var(--navy);border:1px solid var(--border-strong);color:var(--white);border-radius:6px"></label>
      <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--gray-400)">Currency
        <select name="currency" style="padding:8px;background:var(--navy);border:1px solid var(--border-strong);color:var(--white);border-radius:6px">
          <option value="USD">USD</option><option value="EUR">EUR</option><option value="GBP">GBP</option>
        </select></label>
      <label style="display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--gray-400)">Due (days from today)
        <input type="number" name="due_days" value="14" style="padding:8px;background:var(--navy);border:1px solid var(--border-strong);color:var(--white);border-radius:6px"></label>
      <label style="grid-column:1/-1;display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--gray-400)">Notes (internal)
        <textarea name="notes" rows="2" style="padding:8px;background:var(--navy);border:1px solid var(--border-strong);color:var(--white);border-radius:6px;font-family:inherit"></textarea></label>
      <div style="grid-column:1/-1;display:flex;justify-content:flex-end;gap:8px">
        <button type="submit" class="btn btn-publish">Create invoice (draft)</button>
      </div>
    </form>
    <script>
      const KLX_CLIENTS = {js_data_map};
      function klxPickClient(id) {{
        const c = KLX_CLIENTS[id];
        if (!c) return;
        document.getElementById('klx-inv-name').value = c.name;
        document.getElementById('klx-inv-email').value = c.email;
        document.getElementById('klx-inv-company').value = c.company;
      }}
    </script>
  </details>
</div>
"""


def _render_payments_table(rows: list[Any]) -> str:
    if not rows:
        return '<div class="empty">No Stripe payments recorded yet.</div>'
    body = []
    for r in rows:
        s = (r["status"] or "").lower()
        cls = _INVOICE_STATUS_COLOR.get(s, "info")
        pi = r["stripe_payment_intent_id"] or r["stripe_session_id"] or ""
        pi_short = f'{pi[:20]}…' if len(pi) > 20 else (pi or "—")
        body.append(
            f'<tr>'
            f'<td><span style="font-family:SF Mono,Menlo,monospace;font-size:11px">{html.escape(pi_short)}</span></td>'
            f'<td>{_fmt_money(r["amount"], r["currency"])}</td>'
            f'<td><span class="badge {cls}">{html.escape(s or "—")}</span></td>'
            f'<td style="color:var(--gray-400);font-size:11px">{_humanize_ago(r["created_at"])}</td>'
            f'</tr>'
        )
    return (
        '<table class="table"><thead><tr>'
        '<th>Stripe ref</th><th>Amount</th><th>Status</th><th>Received</th>'
        '</tr></thead><tbody>' + "\n".join(body) + '</tbody></table>'
    )


def _render_invoice_kpi_grid(k: dict[str, Any]) -> str:
    def tile(label: str, value: Any, klass: str = "", sub: str = "") -> str:
        return (
            f'<div class="kpi"><div class="kpi-label">{html.escape(label)}</div>'
            f'<div class="kpi-value {klass}">{html.escape(str(value))}</div>'
            + (f'<div class="kpi-sub">{html.escape(sub)}</div>' if sub else "")
            + '</div>'
        )
    total_outstanding_eur = k["portal_outstanding"] + k["loki_outstanding"] + k["gen_outstanding"]
    return (
        '<div class="kpi-grid">'
        + tile("Outstanding (EUR)", f'{total_outstanding_eur:,.2f}',
               klass="warn" if total_outstanding_eur > 0 else "good",
               sub=f'portal {k["portal_outstanding"]:.0f} · loki {k["loki_outstanding"]:.0f} · gen {k["gen_outstanding"]:.0f}')
        + tile("Overdue invoices", k["overdue_ct"],
               klass="bad" if k["overdue_ct"] > 0 else "good",
               sub="past due-date, unpaid")
        + tile("Paid last 30d", f'{k["paid_30d"]:,.2f}',
               klass="good" if k["paid_30d"] > 0 else "",
               sub="Stripe succeeded")
        + tile("Total invoices", k["portal_ct"] + k["loki_ct"] + k["gen_ct"],
               sub=f'{k["payments_ct"]} payment events')
        + '</div>'
    )


# ─── Routes ────────────────────────────────────────────────────────────────────

def _clamp_hours(v: int) -> int:
    return 24 if v not in (24, 48, 168) else v


@router.get("/invoices", response_class=HTMLResponse, include_in_schema=False)
async def inbox_invoices(
    email: str = Depends(require_admin_session),
) -> HTMLResponse:
    """iter-75: Invoices tab. Read-only union of portal_invoices,
    loki_invoices, generated_invoices + payments. Actions (mark-paid,
    cancel, create) deferred to next iter after Anthony validates shape.
    """
    kpis = await _fetch_invoice_kpis()
    portal_rows = await _fetch_portal_invoices()
    loki_rows = await _fetch_loki_invoices()
    gen_rows = await _fetch_generated_invoices()
    pay_rows = await _fetch_payments()
    client_options = await _fetch_main_clients(limit=500)

    sections = [
        _render_create_invoice_form(client_options=client_options),
        _render_invoice_kpi_grid(kpis),
        '<div class="section-hdr"><h2>💳 Portal invoices — client-billed</h2>'
        f'<div class="section-actions"><span class="stat">{kpis["portal_ct"]} total</span></div></div>',
        _render_portal_invoices_table(portal_rows),
        '<div class="section-hdr"><h2>🧾 Klara AI-generated invoices — automated</h2>'
        f'<div class="section-actions"><span class="stat">{kpis["loki_ct"]} total</span></div></div>',
        _render_loki_invoices_table(loki_rows),
        '<div class="section-hdr"><h2>📄 Manually-generated invoices — PDF workflow</h2>'
        f'<div class="section-actions"><span class="stat">{kpis["gen_ct"]} total</span></div></div>',
        _render_generated_invoices_table(gen_rows),
        '<div class="section-hdr"><h2>💰 Payments — Stripe reconciliation</h2>'
        f'<div class="section-actions"><span class="stat">{kpis["payments_ct"]} events</span></div></div>',
        _render_payments_table(pay_rows),
    ]
    page = (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Klaravex admin — invoices</title>{_BASE_STYLE}</head><body>'
        + _render_nav("invoices", email)
        + '<div class="container">'
        + '<h1>Invoices</h1>'
        + f'<div class="subhead">Client billing, automated reminders, Stripe reconciliation · signed in as {html.escape(email)}</div>'
        + "\n".join(sections)
        + '</div></body></html>'
    )
    return HTMLResponse(content=page)


async def _invoice_action(table: str, invoice_id: str, new_status: str, email: str,
                          paid_ts: bool = False) -> None:
    """iter-76: shared mark-paid / cancel worker across the three invoice tables.
    Only these three tables are permitted; other names are rejected to prevent
    an accidental UPDATE that lands on the wrong table via URL manipulation.
    """
    allowed = {
        "klaravex.portal_invoices": ("id", None),
        "klaravex.loki_invoices": ("id", None),
        "klaravex.generated_invoices": ("id", "paid_at"),
    }
    if table not in allowed:
        raise ValueError(f"invoice action not permitted for table {table!r}")
    id_col, paid_col = allowed[table]
    pool = await get_pool()
    async with pool.acquire() as conn:
        if paid_ts and paid_col:
            await conn.execute(
                f"UPDATE {table} SET status=$1, {paid_col}=now(), updated_at=now() "
                f"WHERE {id_col}=$2",
                new_status, invoice_id,
            )
        else:
            await conn.execute(
                f"UPDATE {table} SET status=$1, updated_at=now() "
                f"WHERE {id_col}=$2",
                new_status, invoice_id,
            )
    log.info("invoice %s %s → %s by %s", table, invoice_id, new_status, email)


def _redirect_to_invoices() -> RedirectResponse:
    return RedirectResponse(url="/admin/inbox/invoices", status_code=303)


@router.post("/invoices/portal/{invoice_id}/mark-paid", include_in_schema=False)
async def portal_invoice_mark_paid(
    invoice_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    await _invoice_action("klaravex.portal_invoices", invoice_id, "paid", email)
    return _redirect_to_invoices()


@router.post("/invoices/portal/{invoice_id}/cancel", include_in_schema=False)
async def portal_invoice_cancel(
    invoice_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    await _invoice_action("klaravex.portal_invoices", invoice_id, "cancelled", email)
    return _redirect_to_invoices()


@router.post("/invoices/loki/{invoice_id}/mark-paid", include_in_schema=False)
async def loki_invoice_mark_paid(
    invoice_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    await _invoice_action("klaravex.loki_invoices", invoice_id, "paid", email)
    return _redirect_to_invoices()


@router.post("/invoices/loki/{invoice_id}/cancel", include_in_schema=False)
async def loki_invoice_cancel(
    invoice_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    await _invoice_action("klaravex.loki_invoices", invoice_id, "cancelled", email)
    return _redirect_to_invoices()


@router.post("/invoices/generated/{invoice_id}/mark-paid", include_in_schema=False)
async def generated_invoice_mark_paid(
    invoice_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    await _invoice_action("klaravex.generated_invoices", invoice_id, "paid", email, paid_ts=True)
    return _redirect_to_invoices()


@router.post("/invoices/generated/{invoice_id}/cancel", include_in_schema=False)
async def generated_invoice_cancel(
    invoice_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    await _invoice_action("klaravex.generated_invoices", invoice_id, "cancelled", email)
    return _redirect_to_invoices()


@router.post("/invoices/generated/create", include_in_schema=False)
async def generated_invoice_create(
    client_name: str = Form(...),
    client_email: str = Form(...),
    service_description: str = Form(...),
    amount_net: float = Form(...),
    vat_rate: float = Form(default=0.0),
    currency: str = Form(default="EUR"),
    due_days: int = Form(default=14),
    client_company: str = Form(default=""),
    client_address: str = Form(default=""),
    notes: str = Form(default=""),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    """iter-76: minimal invoice creator. Only touches generated_invoices
    (no client FK required). Auto-computes: invoice_number, vat_amount,
    amount_gross, issued_date=today, due_date=today+due_days.
    """
    from datetime import date, timedelta
    from uuid import uuid4
    vat_amount = round(amount_net * (vat_rate / 100.0), 2)
    amount_gross = round(amount_net + vat_amount, 2)
    issued = date.today()
    due = issued + timedelta(days=int(due_days))
    invoice_number = f"KLX-{issued.strftime('%Y%m%d')}-{str(uuid4())[:6].upper()}"
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO klaravex.generated_invoices ("
            "  id, invoice_number, client_name, client_email, client_company, "
            "  client_address, service_description, amount_net, vat_rate, vat_amount, "
            "  amount_gross, currency, issued_date, due_date, status, notes"
            ") VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,'draft',$15) "
            "RETURNING id, invoice_number",
            str(uuid4()), invoice_number, client_name, client_email,
            client_company or None, client_address or None, service_description,
            amount_net, vat_rate, vat_amount, amount_gross, currency.upper(),
            issued, due, notes or None,
        )
    log.info("invoice generated created %s by %s", row["invoice_number"], email)
    return _redirect_to_invoices()


@router.get("/clients", response_class=HTMLResponse, include_in_schema=False)
async def inbox_clients(
    email: str = Depends(require_admin_session),
) -> HTMLResponse:
    """iter-77: Clients page. Two tables — main customer records
    (public.klaravex_clients, source of truth for Stripe/billing) and
    portal login accounts (klaravex.portal_clients, self-service dashboard
    users). Actions: activate/deactivate portal accounts.
    """
    kpis = await _fetch_client_kpis()
    main_rows = await _fetch_main_clients()
    portal_rows = await _fetch_portal_clients()
    sections = [
        _render_client_kpi_grid(kpis),
        '<div class="section-hdr"><h2>💎 Customer records — Stripe source of truth</h2>'
        f'<div class="section-actions"><span class="stat">{kpis["main_ct"]} clients · {kpis["stripe_linked"]} Stripe-linked</span></div></div>',
        _render_main_clients_table(main_rows),
        '<div class="section-hdr"><h2>🔐 Portal accounts — self-service dashboard logins</h2>'
        f'<div class="section-actions"><span class="stat">{kpis["portal_active"]} of {kpis["portal_ct"]} active</span></div></div>',
        _render_portal_clients_table(portal_rows),
    ]
    page = (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Klaravex admin — clients</title>{_BASE_STYLE}</head><body>'
        + _render_nav("clients", email)
        + '<div class="container">'
        + '<h1>Clients</h1>'
        + f'<div class="subhead">Customer records and portal login accounts · signed in as {html.escape(email)}</div>'
        + "\n".join(sections)
        + '</div></body></html>'
    )
    return HTMLResponse(content=page)


@router.get("/clients/{client_id}", response_class=HTMLResponse, include_in_schema=False)
async def inbox_client_detail(
    client_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> HTMLResponse:
    """iter-78: Client detail page. Full record + related activity (leads,
    outreach, invoices) matched by email since there's no direct FK from
    klaravex_clients to the operational tables (yet)."""
    from uuid import UUID
    try:
        UUID(client_id)
    except ValueError:
        return HTMLResponse(content="<h1>Bad client id</h1>", status_code=400)
    c = await _fetch_client_by_id(client_id)
    if not c:
        return HTMLResponse(content="<h1>Client not found</h1>", status_code=404)
    related = await _fetch_client_related(c["email"])
    display_name = c["name"] or c["company"] or c["email"]
    sections = [
        '<div class="section-hdr"><h2>📇 Customer record</h2></div>',
        _render_client_detail_card(c),
        '<div class="section-hdr"><h2>🔐 Portal login account</h2></div>',
        _render_client_portal_status(related["portal_client"]),
        f'<div class="section-hdr"><h2>🧾 Invoices ({len(related["gen_invoices"])})</h2>'
        f'<div class="section-actions"><a href="/admin/inbox/invoices" style="color:var(--amber);font-size:13px">→ all invoices</a></div></div>',
        _render_client_related_invoices(related["gen_invoices"]),
        f'<div class="section-hdr"><h2>🎯 Prospect records ({len(related["prospected"])})</h2></div>',
        _render_client_related_leads(related["prospected"]),
        f'<div class="section-hdr"><h2>✉ Cold outreach history ({len(related["outreach"])})</h2></div>',
        _render_client_related_outreach(related["outreach"]),
    ]
    page = (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Klaravex admin — {html.escape(display_name)}</title>{_BASE_STYLE}</head><body>'
        + _render_nav("clients", email)
        + '<div class="container">'
        + '<div style="color:var(--gray-400);font-size:12px;margin-bottom:8px">'
        + '<a href="/admin/inbox/clients" style="color:var(--amber)">← all clients</a></div>'
        + f'<h1>{html.escape(display_name)}</h1>'
        + f'<div class="subhead">Client detail · '
        + f'<span style="font-family:SF Mono,Menlo,monospace;font-size:12px">{html.escape(str(c["id"]))}</span></div>'
        + "\n".join(sections)
        + '</div></body></html>'
    )
    return HTMLResponse(content=page)


@router.post("/clients/portal/{client_id}/activate", include_in_schema=False)
async def portal_client_activate(
    client_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex.portal_clients SET is_active=true, updated_at=now() WHERE id=$1",
            client_id,
        )
    log.info("portal client %s activated by %s", client_id, email)
    return RedirectResponse(url="/admin/inbox/clients", status_code=303)


@router.post("/clients/portal/{client_id}/deactivate", include_in_schema=False)
async def portal_client_deactivate(
    client_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex.portal_clients SET is_active=false, updated_at=now() WHERE id=$1",
            client_id,
        )
    log.info("portal client %s deactivated by %s", client_id, email)
    return RedirectResponse(url="/admin/inbox/clients", status_code=303)


@router.get("/contracts", response_class=HTMLResponse, include_in_schema=False)
async def inbox_contracts(
    email: str = Depends(require_admin_session),
    status: str = Query(default=""),
) -> HTMLResponse:
    """iter-79: Contracts page. Reads klaravex.approval_requests where
    action_name matches contract-related actions; each pending row can be
    approved or rejected inline. Status filter query param optional.
    """
    kpis = await _fetch_contract_kpis()
    status_filter = status if status in ("pending", "approved", "rejected", "expired") else None
    rows = await _fetch_contracts(status_filter=status_filter)
    filter_bar_parts = ['<div class="lookback-bar"><span>Filter:</span>']
    for f in ("", "pending", "approved", "rejected", "expired"):
        label = "all" if f == "" else f
        active_cls = ' class="active"' if (status_filter or "") == f else ""
        filter_bar_parts.append(
            f'<a href="/admin/inbox/contracts{f"?status=" + f if f else ""}"{active_cls}>{label}</a>'
        )
    filter_bar_parts.append('</div>')
    sections = [
        _render_contract_kpi_grid(kpis),
        "".join(filter_bar_parts),
        f'<div class="section-hdr"><h2>📜 Contract approval requests ({len(rows)} shown)</h2>'
        f'<div class="section-actions"><span class="stat">{kpis["total"]} total lifetime</span></div></div>',
        _render_contracts_table(rows),
    ]
    page = (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Klaravex admin — contracts</title>{_BASE_STYLE}</head><body>'
        + _render_nav("contracts", email)
        + '<div class="container">'
        + '<h1>Contracts</h1>'
        + f'<div class="subhead">Contract approval requests from agents · signed in as {html.escape(email)}</div>'
        + "\n".join(sections)
        + '</div></body></html>'
    )
    return HTMLResponse(content=page)


@router.post("/contracts/{contract_id}/approve", include_in_schema=False)
async def contract_approve(
    contract_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex.approval_requests SET status='approved', "
            "reviewed_by=$1, reviewed_at=now() "
            "WHERE id=$2 AND status='pending' AND action_name = ANY($3::varchar[])",
            email, contract_id, list(_CONTRACT_ACTION_NAMES),
        )
    log.info("contract approve %s by %s", contract_id, email)
    return RedirectResponse(url="/admin/inbox/contracts", status_code=303)


@router.post("/contracts/{contract_id}/reject", include_in_schema=False)
async def contract_reject(
    contract_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex.approval_requests SET status='rejected', "
            "reviewed_by=$1, reviewed_at=now() "
            "WHERE id=$2 AND status='pending' AND action_name = ANY($3::varchar[])",
            email, contract_id, list(_CONTRACT_ACTION_NAMES),
        )
    log.info("contract reject %s by %s", contract_id, email)
    return RedirectResponse(url="/admin/inbox/contracts", status_code=303)


@router.get("/approvals", response_class=HTMLResponse, include_in_schema=False)
async def inbox_approvals(
    email: str = Depends(require_admin_session),
    status: str = Query(default=""),
) -> HTMLResponse:
    """Review page for approval_requests rows not covered by the Contracts
    page (prospecting_outreach.send, social_media_manager.publish, etc.).
    """
    kpis = await _fetch_approval_kpis()
    status_filter = status if status in ("pending", "approved", "rejected", "expired") else None
    rows = await _fetch_approvals(status_filter=status_filter)
    filter_bar_parts = ['<div class="lookback-bar"><span>Filter:</span>']
    for f in ("", "pending", "approved", "rejected", "expired"):
        label = "all" if f == "" else f
        active_cls = ' class="active"' if (status_filter or "") == f else ""
        filter_bar_parts.append(
            f'<a href="/admin/inbox/approvals{f"?status=" + f if f else ""}"{active_cls}>{label}</a>'
        )
    filter_bar_parts.append('</div>')
    sections = [
        _render_approval_kpi_grid(kpis),
        "".join(filter_bar_parts),
        f'<div class="section-hdr"><h2>⚡ Approval requests ({len(rows)} shown)</h2>'
        f'<div class="section-actions"><span class="stat">{kpis["total"]} total lifetime</span></div></div>',
        _render_approvals_table(rows),
    ]
    page = (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Klaravex admin — approvals</title>{_BASE_STYLE}</head><body>'
        + _render_nav("approvals", email)
        + '<div class="container">'
        + '<h1>Approvals</h1>'
        + f'<div class="subhead">Actions from Klara AI agents awaiting your review · signed in as {html.escape(email)}</div>'
        + "\n".join(sections)
        + '</div></body></html>'
    )
    return HTMLResponse(content=page)


@router.post("/approvals/{approval_id}/approve", include_in_schema=False)
async def approval_approve(
    approval_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex.approval_requests SET status='approved', "
            "reviewed_by=$1, reviewed_at=now() "
            "WHERE id=$2 AND status='pending' AND NOT (action_name = ANY($3::varchar[]))",
            email, approval_id, list(_CONTRACT_ACTION_NAMES),
        )
    log.info("approval approve %s by %s", approval_id, email)
    return RedirectResponse(url="/admin/inbox/approvals", status_code=303)


@router.post("/approvals/{approval_id}/reject", include_in_schema=False)
async def approval_reject(
    approval_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex.approval_requests SET status='rejected', "
            "reviewed_by=$1, reviewed_at=now() "
            "WHERE id=$2 AND status='pending' AND NOT (action_name = ANY($3::varchar[]))",
            email, approval_id, list(_CONTRACT_ACTION_NAMES),
        )
    log.info("approval reject %s by %s", approval_id, email)
    return RedirectResponse(url="/admin/inbox/approvals", status_code=303)


@router.get("/queue", response_class=HTMLResponse, include_in_schema=False)
async def inbox_queue(
    email: str = Depends(require_admin_session),
    denials_hours: int = Query(default=24, ge=1, le=168),
    webhooks_hours: int = Query(default=24, ge=1, le=168),
    failures_hours: int = Query(default=24, ge=1, le=168),
    err: str | None = Query(default=None),
) -> HTMLResponse:
    social_rows = await _fetch_social_pending()
    marketing_rows = await _fetch_marketing_pending()
    outreach_rows = await _fetch_outreach_pending()
    kb_draft_rows = await _fetch_kb_drafts_pending()
    freelance_rows = await _fetch_freelance_bids_pending()

    tabs = _build_queue_tabs(social_rows, marketing_rows, outreach_rows, kb_draft_rows, freelance_rows)
    total_pending = sum(t["count"] for t in tabs)

    tmpl = _templates.env.get_template("admin_approvals.html")
    return HTMLResponse(tmpl.render(
        tabs=tabs,
        total_pending=total_pending,
        user_email=email,
        user_initials=_user_initials_from_email(email),
        content_badge=total_pending or None,
        flash_error=err,
    ))


# ─── /streams — viewing page for current pipeline state ─────────────────────────
# This is the "I want to see what's happening" page (vs /queue which is "approve").
# Shows recent activity across social, freelance, leads, outreach with status badges.

async def _fetch_social_recent(days: int = 30) -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT id, platform, status, left(content, 220) AS snip, image_url, "
            "       created_at, published_at "
            "FROM klaravex_social_drafts "
            "WHERE created_at > now() - ($1 || ' days')::interval "
            "ORDER BY created_at DESC",
            str(days),
        ))


async def _fetch_freelance_recent(days: int = 7) -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT id, platform, title, status, fit_score, fit_rationale, "
            "       budget_min, budget_max, budget_currency, client_location, "
            "       url, posted_at, bid_submitted_at, created_at "
            "FROM klaravex_freelance_projects "
            "WHERE created_at > now() - ($1 || ' days')::interval "
            "ORDER BY fit_score DESC NULLS LAST, created_at DESC LIMIT 100",
            str(days),
        ))


async def _fetch_leads_recent(days: int = 30) -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT id, company_name, contact_first_name, contact_last_name, "
            "       contact_title, contact_email, industry, status, signal, created_at "
            "FROM klaravex_prospected_leads "
            "WHERE created_at > now() - ($1 || ' days')::interval "
            "ORDER BY created_at DESC",
            str(days),
        ))


async def _fetch_outreach_history(days: int = 30) -> list[Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return list(await conn.fetch(
            "SELECT a.id, a.subject, a.status, a.created_at, a.sent_at, "
            "       p.company_name, p.contact_email "
            "FROM klaravex_outreach_approvals a "
            "LEFT JOIN klaravex_prospected_leads p ON p.id = a.prospect_id "
            "WHERE a.created_at > now() - ($1 || ' days')::interval "
            "ORDER BY a.created_at DESC LIMIT 100",
            str(days),
        ))


def _status_pill(status: str) -> str:
    colors = {
        "published": "#10b981", "approved": "#3b82f6", "pending": "#f59e0b",
        "rejected": "#ef4444", "sent": "#10b981", "draft": "#9ca3af",
        "ignored": "#9ca3af", "new": "#3b82f6", "bid_submitted": "#10b981",
        "bid_queued": "#f59e0b", "won": "#059669", "lost": "#6b7280",
    }
    color = colors.get(status, "#6b7280")
    return f'<span class="row-pill" style="background:{color}">{html.escape(status)}</span>'


_PILL_CLASS = {
    "published": "g", "approved": "b", "sent": "g", "won": "g",
    "pending": "a", "bid_queued": "a", "bid_submitted": "g",
    "rejected": "r", "lost": "n", "draft": "n", "ignored": "n", "new": "b",
}


def _pill_class(status: str) -> str:
    return _PILL_CLASS.get(status, "n")


def _social_row_dict(row: Any) -> dict:
    ts = row["created_at"].strftime("%b %d %H:%M") if row["created_at"] else "—"
    pub = row["published_at"].strftime("%b %d") if row["published_at"] else ""
    snip = (row["snip"] or "").replace("\n", " · ")[:220]
    name = snip or "(no content)"
    sub = f'{row["platform"] or ""}'
    meta = f"pub {pub}" if pub else ""
    return {"name": name, "sub": sub, "meta": meta, "status": row["status"] or "", "pill_class": _pill_class(row["status"] or ""), "ts": ts}


def _freelance_row_dict(row: Any) -> dict:
    ts = row["created_at"].strftime("%b %d") if row["created_at"] else "—"
    title = (row["title"] or "")[:90]
    fit = row["fit_score"] if row["fit_score"] is not None else "—"
    budget = ""
    if row["budget_min"] or row["budget_max"]:
        cur = (row["budget_currency"] or "").upper()
        if row["budget_min"] and row["budget_max"]:
            budget = f" {cur} {row['budget_min']}-{row['budget_max']}"
        elif row["budget_max"]:
            budget = f" {cur} ≤{row['budget_max']}"
    loc = f" · {row['client_location']}" if row["client_location"] else ""
    bid = " ✓ bid" if row["bid_submitted_at"] else ""
    sub = f'{row["platform"] or ""}{budget}{loc}{bid}'
    meta = f"fit {fit}"
    return {"name": title or "(untitled)", "sub": sub, "meta": meta, "status": row["status"] or "", "pill_class": _pill_class(row["status"] or ""), "ts": ts}


def _lead_row_dict(row: Any) -> dict:
    ts = row["created_at"].strftime("%b %d %H:%M") if row["created_at"] else "—"
    name = f"{row['contact_first_name'] or ''} {row['contact_last_name'] or ''}".strip() or "—"
    company = row["company_name"] or "—"
    title = row["contact_title"] or ""
    email_val = row["contact_email"] or "—"
    industry = row["industry"] or ""
    signal = (row["signal"] or "")[:60]
    sub_parts = [p for p in [title, industry, email_val, f"signal: {signal}" if signal else ""] if p]
    return {"name": f"{name} @ {company}", "sub": " · ".join(sub_parts), "meta": "", "status": row["status"] or "", "pill_class": _pill_class(row["status"] or ""), "ts": ts}


def _outreach_row_dict(row: Any) -> dict:
    ts = row["created_at"].strftime("%b %d %H:%M") if row["created_at"] else "—"
    sent = row["sent_at"].strftime("%b %d") if row["sent_at"] else ""
    company = row["company_name"] or "—"
    email_val = row["contact_email"] or "—"
    subject = (row["subject"] or "")[:80]
    sub_parts = [email_val]
    if sent:
        sub_parts.append(f"sent {sent}")
    return {"name": subject or "(no subject)", "sub": " · ".join(sub_parts), "meta": company, "status": row["status"] or "", "pill_class": _pill_class(row["status"] or ""), "ts": ts}


def _render_social_stream_row(row: Any) -> str:
    ts = row["created_at"].strftime("%b %d %H:%M") if row["created_at"] else "—"
    pub = row["published_at"].strftime("%b %d") if row["published_at"] else ""
    platform = html.escape(row["platform"] or "")
    snip = html.escape((row["snip"] or "").replace("\n", " · "))[:220]
    pub_badge = f' <span style="color:#10b981;font-size:11px">→ pub {pub}</span>' if pub else ""
    return (
        f'<div class="row">'
        f'<span class="row-time">{ts}</span>'
        f'{_status_pill(row["status"])}'
        f'<span class="row-method">{platform}</span>'
        f'<span class="row-path">{snip}{pub_badge}</span>'
        f'</div>'
    )


def _render_freelance_stream_row(row: Any) -> str:
    ts = row["created_at"].strftime("%b %d") if row["created_at"] else "—"
    platform = html.escape(row["platform"] or "")
    title = html.escape((row["title"] or "")[:90])
    fit = row["fit_score"] if row["fit_score"] is not None else "—"
    fit_color = "#10b981" if isinstance(fit, int) and fit >= 70 else ("#f59e0b" if isinstance(fit, int) and fit >= 40 else "#9ca3af")
    budget = ""
    if row["budget_min"] or row["budget_max"]:
        currency = (row["budget_currency"] or "").upper()
        if row["budget_min"] and row["budget_max"]:
            budget = f" {currency} {row['budget_min']}-{row['budget_max']}"
        elif row["budget_max"]:
            budget = f" {currency} ≤{row['budget_max']}"
    loc = f" · {html.escape(row['client_location'])}" if row["client_location"] else ""
    bid_badge = ' <span style="color:#10b981;font-size:11px">✓ bid</span>' if row["bid_submitted_at"] else ""
    url = row["url"] or ""
    title_html = f'<a href="{html.escape(url)}" target="_blank" style="color:#1a3a5c">{title}</a>' if url else title
    return (
        f'<div class="row">'
        f'<span class="row-time">{ts}</span>'
        f'<span class="row-pill" style="background:{fit_color}">fit {fit}</span>'
        f'{_status_pill(row["status"])}'
        f'<span class="row-method">{platform}</span>'
        f'<span class="row-path">{title_html}{budget}{loc}{bid_badge}</span>'
        f'</div>'
    )


def _render_lead_stream_row(row: Any) -> str:
    ts = row["created_at"].strftime("%b %d %H:%M") if row["created_at"] else "—"
    name = f"{row['contact_first_name'] or ''} {row['contact_last_name'] or ''}".strip() or "—"
    company = html.escape(row["company_name"] or "—")
    title = html.escape(row["contact_title"] or "")
    email = html.escape(row["contact_email"] or "—")
    industry = html.escape(row["industry"] or "")
    signal = html.escape((row["signal"] or "")[:60])
    return (
        f'<div class="row">'
        f'<span class="row-time">{ts}</span>'
        f'{_status_pill(row["status"])}'
        f'<span class="row-method">{html.escape(name)}</span>'
        f'<span class="row-path"><strong>{company}</strong> · {title} · {industry} · {email}'
        + (f' · signal: {signal}' if signal else '') +
        f'</span>'
        f'</div>'
    )


def _render_outreach_history_row(row: Any) -> str:
    ts = row["created_at"].strftime("%b %d %H:%M") if row["created_at"] else "—"
    sent = row["sent_at"].strftime("%b %d") if row["sent_at"] else ""
    company = html.escape(row["company_name"] or "—")
    email = html.escape(row["contact_email"] or "—")
    subject = html.escape((row["subject"] or "")[:80])
    sent_badge = f' <span style="color:#10b981;font-size:11px">→ sent {sent}</span>' if sent else ""
    return (
        f'<div class="row">'
        f'<span class="row-time">{ts}</span>'
        f'{_status_pill(row["status"])}'
        f'<span class="row-method">{company}</span>'
        f'<span class="row-path">{subject} · {email}{sent_badge}</span>'
        f'</div>'
    )


@router.get("/streams", response_class=HTMLResponse, include_in_schema=False)
async def inbox_streams(
    email: str = Depends(require_admin_session),
    social_days: int = Query(default=30, ge=1, le=180),
    freelance_days: int = Query(default=7, ge=1, le=90),
    leads_days: int = Query(default=30, ge=1, le=180),
    outreach_days: int = Query(default=30, ge=1, le=180),
) -> HTMLResponse:
    social_raw = await _fetch_social_recent(social_days)
    freelance_raw = await _fetch_freelance_recent(freelance_days)
    leads_raw = await _fetch_leads_recent(leads_days)
    outreach_raw = await _fetch_outreach_history(outreach_days)

    social_by_status: dict[str, int] = {}
    for r in social_raw:
        social_by_status[r["status"]] = social_by_status.get(r["status"], 0) + 1
    social_counts = " · ".join(f"{v} {k}" for k, v in sorted(social_by_status.items(), key=lambda x: -x[1])) or ""

    freelance_by_status: dict[str, int] = {}
    for r in freelance_raw:
        freelance_by_status[r["status"]] = freelance_by_status.get(r["status"], 0) + 1
    freelance_counts = " · ".join(f"{v} {k}" for k, v in sorted(freelance_by_status.items(), key=lambda x: -x[1])) or ""

    tmpl = _templates.env.get_template("admin_streams.html")
    return HTMLResponse(tmpl.render(
        social_rows=[_social_row_dict(r) for r in social_raw],
        social_count=len(social_raw),
        social_days=social_days,
        social_counts=social_counts,
        freelance_rows=[_freelance_row_dict(r) for r in freelance_raw],
        freelance_count=len(freelance_raw),
        freelance_days=freelance_days,
        freelance_counts=freelance_counts,
        leads_rows=[_lead_row_dict(r) for r in leads_raw],
        leads_count=len(leads_raw),
        leads_days=leads_days,
        outreach_rows=[_outreach_row_dict(r) for r in outreach_raw],
        outreach_count=len(outreach_raw),
        outreach_days=outreach_days,
        user_email=email,
        user_initials=_user_initials_from_email(email),
    ))


# Generic approve/reject — one route per stream so we hit the right table.

async def _set_status(table: str, row_id: str, new_status: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if table == "klaravex_marketing_actions" and new_status == "approved":
            await conn.execute(
                f"UPDATE {table} SET status='approved', approved_by='anthony', "
                f"approved_at=now() WHERE id=$1", row_id,
            )
        elif new_status == "approved" and table == "klaravex_outreach_approvals":
            await conn.execute(
                f"UPDATE {table} SET status='approved', approved_at=now() WHERE id=$1", row_id,
            )
        else:
            updated = "updated_at" if table == "klaravex_social_drafts" else None
            extra = f", {updated}=now()" if updated else ""
            await conn.execute(
                f"UPDATE {table} SET status=$1{extra} WHERE id=$2", new_status, row_id,
            )


def _redirect_to_inbox(error: str | None = None) -> RedirectResponse:
    url = "/admin/inbox/queue"
    if error:
        from urllib.parse import quote
        url += "?err=" + quote(error, safe="")
    return RedirectResponse(url=url, status_code=303)


@router.post("/social/{draft_id}/approve", include_in_schema=False)
async def approve_social(
    draft_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    # iter-73: approve cascades directly to publish. No two-step.
    await _set_status("klaravex_social_drafts", draft_id, "approved")
    try:
        await _publish_single_social(draft_id, email)
    except Exception as exc:  # noqa: BLE001
        log.exception("inbox social approve publish cascade failed %s: %s", draft_id, exc)
    return _redirect_to_inbox()


async def _publish_single_social(draft_id: str, email: str) -> None:
    from .social_media import _PUBLISHERS, _PUBLISHERS_ACCEPTING_IMAGE
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, platform, content, image_url, status "
            "FROM klaravex_social_drafts WHERE id=$1",
            draft_id,
        )
    if not row or row["status"] != "approved":
        return
    platform = row["platform"]
    publisher = _PUBLISHERS.get(platform)
    if not publisher:
        log.warning("inbox social publish %s: no publisher for %s", draft_id, platform)
        return
    if platform in _PUBLISHERS_ACCEPTING_IMAGE:
        result = await publisher(row["content"], image_url=row["image_url"])
    else:
        result = await publisher(row["content"])
    if "error" in result:
        log.warning("inbox social publish %s %s failed: %s", platform, draft_id, result["error"])
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex_social_drafts SET status='published', "
            "published_at=now(), platform_post_id=$1, updated_at=now() WHERE id=$2",
            result.get("post_id") or result.get("tweet_id"), draft_id,
        )
    log.info("inbox social approve+publish %s %s by %s", platform, draft_id, email)


@router.post("/social/{draft_id}/reject", include_in_schema=False)
async def reject_social(
    draft_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    await _set_status("klaravex_social_drafts", draft_id, "rejected")
    log.info("inbox social reject %s by %s", draft_id, email)
    return _redirect_to_inbox()


@router.post("/marketing/{action_id}/approve", include_in_schema=False)
async def approve_marketing(
    action_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    await _set_status("klaravex_marketing_actions", action_id, "approved")
    log.info("inbox marketing approve %s by %s", action_id, email)
    return _redirect_to_inbox()


@router.post("/marketing/{action_id}/reject", include_in_schema=False)
async def reject_marketing(
    action_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    await _set_status("klaravex_marketing_actions", action_id, "blocked")
    log.info("inbox marketing reject %s by %s", action_id, email)
    return _redirect_to_inbox()


@router.post("/outreach/{out_id}/approve", include_in_schema=False)
async def approve_outreach(
    out_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    """Approve a cold-outreach draft → hand the prospect off to Smartlead.

    Smartlead handles WHEN to actually send (per-recipient timezone, warmup
    schedule, deliverability optimization). We never send cold outreach
    directly from this stack — that would put klaravex.com domain reputation
    at risk again.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT a.id, a.subject, a.body_text, a.body_html, a.status,
                   p.contact_email, p.contact_first_name, p.contact_last_name,
                   p.contact_title, p.company_name
              FROM klaravex_outreach_approvals a
              JOIN klaravex_prospected_leads p ON p.id = a.prospect_id
             WHERE a.id = $1
            """,
            out_id,
        )
    if not row:
        log.warning("inbox outreach approve %s: not found", out_id)
        return _redirect_to_inbox()
    if row["status"] != "pending":
        log.info("inbox outreach approve %s: already %s", out_id, row["status"])
        return _redirect_to_inbox()

    # Lazy import to avoid pulling prospecting's heavy deps at module load.
    from .prospecting import _send_via_smartlead

    ok, detail = await _send_via_smartlead(
        contact_email=row["contact_email"],
        first_name=row["contact_first_name"] or "",
        last_name=row["contact_last_name"] or "",
        company_name=row["company_name"] or "",
        contact_title=row["contact_title"] or "",
        subject=row["subject"] or "",
        body_text=row["body_text"] or "",
        body_html=row["body_html"] or "",
    )

    if ok:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE klaravex_outreach_approvals SET status='approved', approved_at=now(), sent_at=now() WHERE id=$1",
                out_id,
            )
            await conn.execute(
                "UPDATE klaravex_prospected_leads SET status='queued_smartlead', updated_at=now() "
                "WHERE id=(SELECT prospect_id FROM klaravex_outreach_approvals WHERE id=$1)",
                out_id,
            )
        log.info("inbox outreach approve %s by %s → Smartlead: %s", out_id, email, detail)
    else:
        log.warning("inbox outreach approve %s by %s → Smartlead FAILED: %s", out_id, email, detail)
        # Don't mark approved — let Anthony see it's still pending and retry.

    return _redirect_to_inbox()


@router.post("/outreach/{out_id}/reject", include_in_schema=False)
async def reject_outreach(
    out_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    await _set_status("klaravex_outreach_approvals", out_id, "rejected")
    log.info("inbox outreach reject %s by %s", out_id, email)
    return _redirect_to_inbox()


@router.post("/social/reject-all", include_in_schema=False)
async def reject_all_social(
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    """iter-73.1: nuke every pending social draft. Confirmation gated in UI."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "UPDATE klaravex_social_drafts SET status='rejected', updated_at=now() "
            "WHERE status='pending' RETURNING id"
        )
    log.info("inbox social reject-all n=%d by %s", len(rows), email)
    return _redirect_to_inbox()


@router.post("/approve-all", include_in_schema=False)
async def approve_all_pending(
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    """Bulk-approve every pending row across all three streams AND
    immediately publish. iter-73 (2026-07-14): approve now cascades into
    publish per Anthony directive ('why two buttons approve should auto
    publish'). Two-step approve->publish confused the UX; one tap = done.

    Cascade order:
      1. UPDATE all pending rows to approved (in a single txn)
      2. Immediately call the publish pipeline for each stream that has one
         (social publishers, outreach hand-off to Smartlead worker via
         status flip, marketing agent picks up on next tick)
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex_social_drafts "
            "SET status='approved', updated_at=now() WHERE status='pending'"
        )
        await conn.execute(
            "UPDATE klaravex_marketing_actions "
            "SET status='approved', approved_by='anthony', approved_at=now() "
            "WHERE status='pending' AND approval_required"
        )
        await conn.execute(
            "UPDATE klaravex_outreach_approvals "
            "SET status='approved', approved_at=now() WHERE status='pending'"
        )
    log.info("inbox approve-all by %s", email)
    # Cascade into publish immediately (iter-73)
    try:
        await _publish_all_approved(email)
    except Exception as exc:  # noqa: BLE001
        log.exception("inbox approve-all publish cascade failed: %s", exc)
    return _redirect_to_inbox()


async def _publish_all_approved(email: str) -> None:
    """Extracted from publish_approved_all — reusable by cascade + manual."""
    from .social_media import _PUBLISHERS, _PUBLISHERS_ACCEPTING_IMAGE

    pool = await get_pool()
    async with pool.acquire() as conn:
        social_rows = await conn.fetch(
            "SELECT id, platform, content, image_url FROM klaravex_social_drafts "
            "WHERE status='approved' ORDER BY created_at ASC LIMIT 20"
        )
    for row in social_rows:
        draft_id = str(row["id"])
        platform = row["platform"]
        publisher = _PUBLISHERS.get(platform)
        if not publisher:
            continue
        try:
            if platform in _PUBLISHERS_ACCEPTING_IMAGE:
                result = await publisher(row["content"], image_url=row["image_url"])
            else:
                result = await publisher(row["content"])
            if "error" in result:
                log.warning("inbox publish failed %s %s: %s", platform, draft_id, result["error"])
                continue
            async with pool.acquire() as conn2:
                await conn2.execute(
                    "UPDATE klaravex_social_drafts SET status='published', "
                    "published_at=now(), platform_post_id=$1, updated_at=now() WHERE id=$2",
                    result.get("post_id") or result.get("tweet_id"), draft_id,
                )
            log.info("inbox published %s %s by %s", platform, result.get("post_id"), email)
        except Exception as exc:  # noqa: BLE001
            log.exception("inbox publish exception %s %s: %s", platform, draft_id, exc)


@router.post("/publish-approved", include_in_schema=False)
async def publish_approved_all(
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    """Legacy manual publish sweep. iter-73: approve cascades into publish so
    this button is now redundant on the happy path — kept as a manual retry
    for approved-but-unpublished rows created by a failed cascade or by an
    older revision that did not cascade.
    """
    await _publish_all_approved(email)
    return _redirect_to_inbox()


@router.post("/social/approve-all", include_in_schema=False)
async def approve_all_social(
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    """iter-73: per-section approve-all for social drafts. Cascades to publish."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "UPDATE klaravex_social_drafts SET status='approved', updated_at=now() "
            "WHERE status='pending' RETURNING id"
        )
    log.info("inbox social approve-all n=%d by %s", len(rows), email)
    try:
        await _publish_all_approved(email)
    except Exception as exc:  # noqa: BLE001
        log.exception("inbox social approve-all publish cascade failed: %s", exc)
    return _redirect_to_inbox()


@router.post("/marketing/approve-all", include_in_schema=False)
async def approve_all_marketing(
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    """iter-73: per-section approve-all for marketing actions. Marketing agent
    picks up 'approved' on next tick and fires the campaign — no direct fire
    from this endpoint."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "UPDATE klaravex_marketing_actions "
            "SET status='approved', approved_by=$1, approved_at=now() "
            "WHERE status='pending' AND approval_required RETURNING id",
            email,
        )
    log.info("inbox marketing approve-all n=%d by %s", len(rows), email)
    return _redirect_to_inbox()


@router.post("/outreach/approve-all", include_in_schema=False)
async def approve_all_outreach(
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    """iter-73: per-section approve-all for outreach approvals. Each approved
    row hands off to Smartlead one-by-one (per-recipient Smartlead API call)
    so a rate-limit hit doesn't wedge the whole batch.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        pending_ids = [str(r["id"]) for r in await conn.fetch(
            "SELECT id FROM klaravex_outreach_approvals WHERE status='pending' "
            "ORDER BY created_at ASC LIMIT 50"
        )]
    from .prospecting import _send_via_smartlead
    approved_ct = 0
    failed_ct = 0
    for out_id in pending_ids:
        pool2 = await get_pool()
        async with pool2.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT a.id, a.subject, a.body_text, a.body_html, "
                "       p.contact_email, p.contact_first_name, p.contact_last_name, "
                "       p.contact_title, p.company_name "
                "FROM klaravex_outreach_approvals a "
                "JOIN klaravex_prospected_leads p ON p.id = a.prospect_id "
                "WHERE a.id=$1 AND a.status='pending'",
                out_id,
            )
        if not row:
            continue
        ok, detail = await _send_via_smartlead(
            contact_email=row["contact_email"],
            first_name=row["contact_first_name"] or "",
            last_name=row["contact_last_name"] or "",
            company_name=row["company_name"] or "",
            contact_title=row["contact_title"] or "",
            subject=row["subject"] or "",
            body_text=row["body_text"] or "",
            body_html=row["body_html"] or "",
        )
        if ok:
            approved_ct += 1
            async with pool2.acquire() as conn:
                await conn.execute(
                    "UPDATE klaravex_outreach_approvals SET status='approved', "
                    "approved_at=now(), sent_at=now() WHERE id=$1",
                    out_id,
                )
                await conn.execute(
                    "UPDATE klaravex_prospected_leads SET status='queued_smartlead', "
                    "updated_at=now() WHERE id=(SELECT prospect_id FROM "
                    "klaravex_outreach_approvals WHERE id=$1)",
                    out_id,
                )
        else:
            failed_ct += 1
            log.warning("inbox outreach approve-all %s → Smartlead FAILED: %s", out_id, detail)
    log.info("inbox outreach approve-all ok=%d fail=%d by %s", approved_ct, failed_ct, email)
    return _redirect_to_inbox()


@router.post("/kb/approve-all", include_in_schema=False)
async def approve_all_kb(
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    """iter-73: per-section approve-all for KB drafts. Each approved draft
    publishes to WordPress inline."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        pending_ids = [str(r["id"]) for r in await conn.fetch(
            "SELECT id FROM klaravex_kb_drafts WHERE status='pending' "
            "ORDER BY created_at ASC LIMIT 20"
        )]
    published_ct = 0
    failed_ct = 0
    for draft_id in pending_ids:
        result = await publish_draft_to_wp(draft_id)
        if "error" in result:
            failed_ct += 1
            log.warning("inbox kb approve-all %s failed: %s", draft_id, result["error"])
        else:
            published_ct += 1
    log.info("inbox kb approve-all ok=%d fail=%d by %s", published_ct, failed_ct, email)
    return _redirect_to_inbox()


@router.post("/freelance-match/{match_id}/dismiss", include_in_schema=False)
async def dismiss_freelance_match(
    match_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex_freelance_matches "
            "SET status='dismissed', updated_at=now() WHERE id=$1",
            match_id,
        )
    log.info("inbox freelance-match dismiss %s by %s", match_id, email)
    return _redirect_to_inbox()


@router.post("/kb/{draft_id}/approve", include_in_schema=False)
async def approve_kb_draft(
    draft_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    result = await publish_draft_to_wp(draft_id)
    if "error" in result:
        log.warning("kb approve publish failed %s: %s", draft_id, result["error"])
        return _redirect_to_inbox(error=f"KB publish failed: {result['error']}")
    log.info("inbox kb approve %s by %s → wp_post_id=%s", draft_id, email, result.get("wp_post_id"))
    return _redirect_to_inbox()


@router.post("/kb/{draft_id}/reject", include_in_schema=False)
async def reject_kb_draft(
    draft_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex_kb_drafts SET status='rejected', updated_at=now() WHERE id=$1",
            draft_id,
        )
    log.info("inbox kb reject %s by %s", draft_id, email)
    return _redirect_to_inbox()
