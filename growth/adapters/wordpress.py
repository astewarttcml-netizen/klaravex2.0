"""WordPress adapter — create draft posts on klaravex.com / personal.klaravex.com."""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any

from growth.adapters import not_wired, poc_sandbox
from growth.adapters.credentials import creds_configured, creds_detail, _merged_env
from growth.outreach.wp_markdown import md_to_html
from growth.poc import is_poc_mode

SURFACES = frozenset({"business", "consumer", "seo-blog", "kb"})


def _readonly() -> bool:
    return os.getenv("WORDPRESS_READONLY", "true").lower() in {"1", "true", "yes", "on"}


def _surface_creds(surface: str) -> tuple[str, str, str]:
    env = _merged_env()
    surface = (surface or "business").strip().lower()
    if surface in {"consumer", "personal"}:
        return (
            env.get("PERSONAL_WP_SITE_URL", "https://personal.klaravex.com").rstrip("/"),
            env.get("PERSONAL_WP_APP_USERNAME", "").strip(),
            env.get("PERSONAL_WP_APP_PASSWORD", "").strip(),
        )
    return (
        env.get("WP_SITE_URL", "https://klaravex.com").rstrip("/"),
        (env.get("WP_APP_USERNAME") or env.get("WP_APP_USER") or "").strip(),
        env.get("WP_APP_PASSWORD", "").strip(),
    )


def _auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def _request(
    site: str,
    user: str,
    password: str,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = 30,
) -> Any:
    url = f"{site.rstrip('/')}{path}"
    data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": _auth_header(user, password),
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": os.getenv("WORDPRESS_USER_AGENT", "KlaravexGrowth/2.0 (+growth-api)"),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"WordPress HTTP {exc.code}: {err_body}") from exc


def probe_site(surface: str = "business") -> dict[str, Any]:
    site, user, password = _surface_creds(surface)
    if not (site and user and password):
        raise RuntimeError(f"WordPress creds incomplete for surface={surface}")
    me = _request(site, user, password, "GET", "/wp-json/wp/v2/users/me?context=edit")
    if not isinstance(me, dict):
        return {"ok": True, "site": site, "surface": surface}
    return {
        "ok": True,
        "site": site,
        "surface": surface,
        "user": me.get("slug") or me.get("name"),
        "roles": me.get("roles"),
    }


def create_draft(
    *,
    surface: str,
    title: str,
    content_html: str,
    slug: str = "",
    excerpt: str = "",
    status: str = "draft",
) -> dict[str, Any]:
    site, user, password = _surface_creds(surface)
    if not (site and user and password):
        raise RuntimeError(f"WordPress creds incomplete for surface={surface}")
    if status not in {"draft", "pending", "publish"}:
        raise RuntimeError(f"invalid post status: {status}")
    if status == "publish" and _readonly():
        raise RuntimeError("WORDPRESS_READONLY=true blocks live publish")

    payload: dict[str, Any] = {
        "title": title.strip(),
        "content": content_html,
        "status": status,
    }
    if slug.strip():
        payload["slug"] = slug.strip()
    if excerpt.strip():
        payload["excerpt"] = excerpt.strip()

    data = _request(site, user, password, "POST", "/wp-json/wp/v2/posts", json_body=payload)
    if not isinstance(data, dict):
        raise RuntimeError("WordPress returned empty response")
    return {
        "wp_post_id": data.get("id"),
        "wp_link": data.get("link"),
        "wp_status": data.get("status"),
        "site": site,
        "surface": surface,
    }


def publish(payload: dict[str, Any] | None = None, **_kwargs) -> dict[str, Any]:
    if is_poc_mode():
        return poc_sandbox(
            "wordpress",
            "publish",
            {"site": "klaravex.com", "post_status": "draft", "slug": "poc-seo-post"},
        )

    if not creds_configured("wordpress"):
        return not_wired("wordpress")

    data = dict(payload or {})
    data.update({k: v for k, v in _kwargs.items() if v is not None})

    title = str(data.get("title") or "").strip()
    if title and (data.get("content_html") or data.get("markdown")):
        surface = str(data.get("surface") or "business")
        html = str(data.get("content_html") or md_to_html(str(data.get("markdown") or "")))
        if _readonly() and str(data.get("status", "draft")) == "publish":
            return {
                "adapter": "wordpress",
                "status": "connected",
                "action": "publish",
                "detail": "WORDPRESS_READONLY=true — only draft creation allowed",
                "creds_configured": True,
            }
        try:
            result = create_draft(
                surface=surface,
                title=title,
                content_html=html,
                slug=str(data.get("slug") or ""),
                excerpt=str(data.get("excerpt") or data.get("meta") or ""),
                status=str(data.get("status") or "draft"),
            )
            return {
                "adapter": "wordpress",
                "status": "connected",
                "action": "publish",
                "detail": f"WP draft on {result['site']} — post {result['wp_post_id']} ({result['wp_status']})",
                "sample": result,
                "creds_configured": True,
            }
        except Exception as exc:
            return {
                "adapter": "wordpress",
                "status": "error",
                "action": "publish",
                "detail": f"{creds_detail('wordpress')} — publish failed: {exc}",
            }

    try:
        business = probe_site("business")
        consumer = None
        try:
            consumer = probe_site("consumer")
        except Exception:
            consumer = {"ok": False, "surface": "consumer"}
    except Exception as exc:
        return {
            "adapter": "wordpress",
            "status": "error",
            "action": "publish",
            "detail": f"{creds_detail('wordpress')} — probe failed: {exc}",
        }

    mode = "readonly_probe" if _readonly() else "publish_ready"
    return {
        "adapter": "wordpress",
        "status": "connected",
        "action": "publish",
        "detail": (
            f"WordPress {business.get('site')} as {business.get('user')} — "
            f"personal={'ok' if consumer and consumer.get('ok') else 'skip'}; "
            + ("draft-only until WORDPRESS_READONLY=false" if _readonly() else "live draft/publish enabled")
        ),
        "sample": {"business": business, "consumer": consumer, "mode": mode},
        "creds_configured": True,
    }
