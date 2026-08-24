"""Klaravex social-media bulk approval dashboard.

A single HTML page that shows every pending draft across every platform on
one screen, with inline approve / reject / preview controls.

Auth: session cookie set by /admin/login/{google,microsoft} OAuth flow
(admin_index.py). The email is checked against ADMIN_EMAILS on every
request. The legacy ?secret=<LOKI_INTERNAL_SECRET> query-string auth has
been removed — old URLs 401 and steer the operator back to /admin/.

Why a separate file:
  - `social_media.py` already serves per-draft approve/reject pages reached
    from per-draft email notifications. Those pages stay as-is for the
    drip-fed approval flow.
  - The dashboard here is for batch review — Anthony opens one URL, sees
    everything pending across every platform, taps approve/reject inline,
    and is done.

Route map (mounted at /admin/social by main.py):
  GET  /admin/social/queue                          → renders dashboard HTML
  POST /admin/social/queue/{draft_id}/approve       → mark approved
  POST /admin/social/queue/{draft_id}/reject        → mark rejected
  POST /admin/social/queue/publish-approved         → publish approved drafts
"""

import html
import logging

from fastapi import APIRouter, Depends, Path
from fastapi.responses import HTMLResponse, RedirectResponse

from .lib.admin_auth import require_admin_session
from .lib.db import get_pool

log = logging.getLogger("klaravex.social_dashboard")
router = APIRouter()

# Same dark-theme tokens + persistent site nav as admin_index.py/admin_inbox.py
# (2026-07-17 redesign follow-through — this legacy page previously had its
# own light inline-styled theme, unrelated to the rest of the admin console).
_STYLE = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Inter:wght@400;500;600&display=swap');
  :root{
    --bg:#06080E; --surface:#0B0D15; --lift:#10131E; --lift2:#151929;
    --white:#F0F4FF; --dim:rgba(240,244,255,0.62); --dim2:rgba(240,244,255,0.32);
    --border:rgba(240,244,255,0.08); --indigo:#6366F1; --indigo2:#818CF8; --violet:#7C3AED;
    --green:#22c55e; --red:#f87171; --amber:#fbbf24;
    --text-2xl:24px; --text-xl:19px; --text-base:14px; --text-sm:13px; --text-xs:12px; --text-2xs:11px;
    --radius-sm:8px; --radius-md:12px;
  }
  *{box-sizing:border-box}
  body{font-family:'Inter',-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);margin:0;padding:0;color:var(--white)}
  .container{max-width:820px;margin:0 auto;padding:28px 20px 60px}
  h1{font-family:'Syne',sans-serif;font-weight:800;letter-spacing:-0.02em;margin:0;font-size:var(--text-2xl)}
  .topbar{display:flex;align-items:center;margin-bottom:20px;gap:14px;flex-wrap:wrap}
  .stat{color:var(--dim2);font-size:var(--text-sm)}
  .btn-publish{background:linear-gradient(135deg,var(--indigo),var(--violet));color:#fff;border:0;
               padding:10px 18px;border-radius:var(--radius-sm);cursor:pointer;font-weight:600;
               font-size:var(--text-sm);font-family:inherit;box-shadow:0 0 20px rgba(99,102,241,0.3)}
  .sigblock{margin-left:auto;color:var(--dim2);font-size:var(--text-xs)}
  .sigblock a{color:var(--indigo2);text-decoration:none;margin-left:6px}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-md);
        padding:16px;margin-bottom:16px}
  .card-head{display:flex;align-items:center;margin-bottom:10px;gap:8px}
  .platform-pill{color:#fff;font-size:var(--text-2xs);font-weight:600;padding:3px 9px;
                  border-radius:10px;text-transform:uppercase}
  .badge{background:rgba(34,197,94,0.15);color:var(--green);font-size:var(--text-2xs);font-weight:600;
         padding:2px 8px;border-radius:10px;text-transform:uppercase}
  .meta{margin-left:auto;color:var(--dim2);font-size:var(--text-xs)}
  .no-image{background:var(--lift);border-radius:8px;padding:24px;text-align:center;
            color:var(--dim2);margin-bottom:12px;font-size:var(--text-sm)}
  .content{font-size:var(--text-sm);line-height:1.5;color:var(--dim);max-height:280px;
           overflow:auto;margin-bottom:14px;white-space:pre-wrap}
  .topic{color:var(--dim2);font-size:var(--text-2xs);margin-bottom:10px}
  .btn{border:0;padding:8px 14px;border-radius:var(--radius-sm);cursor:pointer;font-weight:600;
       font-size:var(--text-sm);font-family:inherit}
  .btn-approve{background:var(--green);color:#04140a}
  .btn-reject{background:var(--lift);color:var(--white);border:1px solid var(--border)}
  .btn-unapprove{background:var(--red);color:#2b0a0a}
  .empty{background:var(--surface);border:1px dashed var(--border);padding:48px;
         border-radius:var(--radius-md);text-align:center;color:var(--dim2);font-size:var(--text-sm)}

  .sitenav{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:22px}
  .sitenav a{color:var(--dim);text-decoration:none;font-size:var(--text-xs);font-weight:600;
             padding:6px 12px;border-radius:999px;border:1px solid var(--border);background:var(--surface);
             display:inline-flex;align-items:center;gap:4px;transition:all .15s}
  .sitenav a:hover{color:var(--white);border-color:var(--indigo)}
  .sitenav a.current{background:var(--indigo);border-color:var(--indigo);color:#fff}
  .sitenav a .ext{opacity:.65;font-size:10px}
</style>
"""

# Duplicated from admin_index.py's _NAV_ITEMS/_site_nav (same pattern already
# used to share the dark-theme style block across these files — no common
# module exists to import from).
_NAV_ITEMS: tuple[tuple[str, str, str, bool], ...] = (
    ("dashboard", "/admin/", "Dashboard", False),
    ("approvals", "/admin/inbox/queue", "Approval Queue", False),
    ("streams", "/admin/inbox/streams", "Streams", False),
    ("portal", "http://100.66.236.56:8010/admin/portal", "Portal", True),
    ("social", "/admin/social/queue", "Social Drafts", False),
)


def _site_nav(current: str) -> str:
    items = []
    for key, href, label, external in _NAV_ITEMS:
        cls = " current" if key == current else ""
        target = ' target="_blank"' if external else ""
        ext_mark = ' <span class="ext">&#8599;</span>' if external else ""
        items.append(f'<a class="{cls.strip()}" href="{href}"{target}>{label}{ext_mark}</a>')
    return f'<nav class="sitenav">{"".join(items)}</nav>'


_PLATFORM_LABEL = {
    "linkedin_personal": "LinkedIn (personal)",
    "linkedin_company": "LinkedIn (company)",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "twitter": "X / Twitter",
    "reddit": "Reddit",
    "tiktok": "TikTok",
    "youtube": "YouTube",
}

_PLATFORM_COLOR = {
    "linkedin_personal": "#0a66c2",
    "linkedin_company": "#0a66c2",
    "facebook": "#1877f2",
    "instagram": "#e4405f",
    "twitter": "#000000",
    "reddit": "#ff4500",
    "tiktok": "#000000",
    "youtube": "#ff0000",
}


@router.get("/queue", response_class=HTMLResponse, include_in_schema=False)
async def social_queue(email: str = Depends(require_admin_session)) -> HTMLResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, platform, content, image_url, topic, status, created_at "
            "FROM klaravex_social_drafts "
            "WHERE status IN ('pending', 'approved') "
            "ORDER BY status DESC, platform, created_at DESC"
        )

    counts = {"pending": 0, "approved": 0}
    cards: list[str] = []
    for r in rows:
        draft_id = str(r["id"])
        platform = r["platform"]
        status = r["status"]
        counts[status] = counts.get(status, 0) + 1
        label = _PLATFORM_LABEL.get(platform, platform)
        color = _PLATFORM_COLOR.get(platform, "#666")
        content = html.escape(r["content"] or "").replace("\n", "<br>")
        image_url = r["image_url"] or ""
        topic = html.escape(r["topic"] or "")
        created = r["created_at"].strftime("%b %d, %H:%M") if r["created_at"] else ""

        img_html = (
            f'<img src="{html.escape(image_url)}" alt="" '
            f'style="width:100%;border-radius:8px;margin-bottom:12px"/>'
            if image_url else
            '<div class="no-image">no image</div>'
        )

        if status == "approved":
            actions = (
                f'<form method="post" action="/admin/social/queue/{draft_id}/reject" style="display:inline">'
                f'<button type="submit" class="btn btn-unapprove">&#8617; Unapprove</button>'
                f'</form>'
            )
        else:
            actions = (
                f'<form method="post" action="/admin/social/queue/{draft_id}/approve" style="display:inline;margin-right:6px">'
                f'<button type="submit" class="btn btn-approve">&check; Approve</button>'
                f'</form>'
                f'<form method="post" action="/admin/social/queue/{draft_id}/reject" style="display:inline">'
                f'<button type="submit" class="btn btn-reject">&cross; Reject</button>'
                f'</form>'
            )

        status_badge = '<span class="badge">approved</span>' if status == "approved" else ""

        cards.append(
            '<div class="card">'
            f'<div class="card-head">'
            f'<span class="platform-pill" style="background:{color}">{html.escape(label)}</span>'
            f'{status_badge}'
            f'<span class="meta">{created}</span>'
            f'</div>'
            f'{img_html}'
            f'<div class="content">{content}</div>'
            f'<div class="topic">{topic}</div>'
            f'{actions}'
            '</div>'
        )

    cards_html = "\n".join(cards) if cards else (
        '<div class="empty">'
        'Queue is empty. Run <code>/internal/social/draft</code> to generate fresh drafts.'
        '</div>'
    )

    publish_button = ""
    if counts.get("approved", 0) > 0:
        publish_button = (
            f'<form method="post" action="/admin/social/queue/publish-approved">'
            f'<button type="submit" class="btn-publish">'
            f'Publish {counts["approved"]} approved now</button></form>'
        )

    signed_in = (
        f'<div class="sigblock">Signed in as {html.escape(email)}'
        f' &middot; <a href="/admin/logout">Sign out</a></div>'
    )

    html_body = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Klaravex social queue</title>{_STYLE}</head>'
        '<body><div class="container">'
        f'{_site_nav("social")}'
        '<div class="topbar">'
        '<h1>Klaravex social queue</h1>'
        f'<span class="stat">{counts.get("pending",0)} pending &middot; {counts.get("approved",0)} approved</span>'
        f'{publish_button}'
        f'{signed_in}'
        '</div>'
        f'{cards_html}'
        '</div></body></html>'
    )
    return HTMLResponse(content=html_body)


@router.post("/queue/{draft_id}/approve", include_in_schema=False)
async def approve_one(
    draft_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex_social_drafts SET status='approved', updated_at=now() WHERE id=$1",
            draft_id,
        )
    log.info("social dashboard approve %s by %s", draft_id, email)
    return RedirectResponse(url="/admin/social/queue", status_code=303)


@router.post("/queue/{draft_id}/reject", include_in_schema=False)
async def reject_one(
    draft_id: str = Path(...),
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE klaravex_social_drafts SET status='rejected', updated_at=now() WHERE id=$1",
            draft_id,
        )
    log.info("social dashboard reject %s by %s", draft_id, email)
    return RedirectResponse(url="/admin/social/queue", status_code=303)


@router.post("/queue/publish-approved", include_in_schema=False)
async def publish_approved_from_dashboard(
    email: str = Depends(require_admin_session),
) -> RedirectResponse:
    # Reuse the existing publish-approved logic by invoking the inner pipeline directly.
    from .social_media import _PUBLISHERS, _PUBLISHERS_ACCEPTING_IMAGE
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, platform, content, image_url FROM klaravex_social_drafts "
            "WHERE status='approved' ORDER BY created_at ASC LIMIT 20"
        )
    for row in rows:
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
                log.warning("publish failed %s %s: %s", platform, draft_id, result["error"])
                continue
            async with pool.acquire() as conn2:
                await conn2.execute(
                    "UPDATE klaravex_social_drafts SET status='published', published_at=now(), "
                    "platform_post_id=$1, updated_at=now() WHERE id=$2",
                    result.get("post_id") or result.get("tweet_id"), draft_id,
                )
            log.info("published from dashboard %s %s by %s", platform, result.get("post_id"), email)
        except Exception as exc:  # noqa: BLE001
            log.exception("publish exception %s %s: %s", platform, draft_id, exc)
    return RedirectResponse(url="/admin/social/queue", status_code=303)
