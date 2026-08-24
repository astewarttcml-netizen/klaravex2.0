"""Smartlead adapter — add approved prospects to the master campaign."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from growth.adapters import not_wired, poc_sandbox
from growth.adapters.credentials import creds_configured, creds_detail, _merged_env
from growth.poc import is_poc_mode

SMARTLEAD_BASE = "https://server.smartlead.ai/api/v1"
VOICE_BANNED = ("anthony", "anthony@klaravex.com", "our founder", "as the founder", "loki")


def _api_key() -> str | None:
    return _merged_env().get("SMARTLEAD_API_KEY", "").strip() or None


def _campaign_id() -> int:
    raw = _merged_env().get("SMARTLEAD_MASTER_CAMPAIGN_ID", "").strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _readonly() -> bool:
    raw = (_merged_env().get("SMARTLEAD_READONLY") or os.getenv("SMARTLEAD_READONLY") or "true").strip()
    return raw.lower() in {"1", "true", "yes", "on"}


def _request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = 25,
) -> Any:
    key = _api_key()
    if not key:
        raise RuntimeError("SMARTLEAD_API_KEY not configured")

    params = urllib.parse.urlencode({"api_key": key})
    url = f"{SMARTLEAD_BASE}{path}?{params}"
    data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
    # Cloudflare on Smartlead rejects generic bot UAs (1010); use a browser-like UA.
    ua = os.getenv(
        "SMARTLEAD_USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 KlaravexGrowth/2.0",
    )
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": ua,
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if resp.status == 204 or not raw:
                return None
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Smartlead HTTP {exc.code}: {err_body}") from exc


def probe_campaign() -> dict[str, Any]:
    cid = _campaign_id()
    if not cid:
        campaigns = _request("GET", "/campaigns/")
        count = len(campaigns) if isinstance(campaigns, list) else 0
        return {"ok": True, "campaigns": count, "master_campaign_id": None}
    campaign = _request("GET", f"/campaigns/{cid}")
    if not isinstance(campaign, dict):
        return {"ok": True, "master_campaign_id": cid}
    return {
        "ok": True,
        "master_campaign_id": cid,
        "name": campaign.get("name"),
        "status": campaign.get("status"),
    }


def _text_to_html(text: str) -> str:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    if not paras:
        return ""
    return "".join(f"<p>{p.replace(chr(10), '<br/>')}</p>" for p in paras)


def _preflight(*, subject: str, body_text: str, body_html: str, email: str) -> str | None:
    if not email or "@" not in email:
        return "invalid email"
    if not subject.strip():
        return "empty subject"
    if not body_html.strip() and not body_text.strip():
        return "empty body"
    for fld_name, fld_val in (
        ("subject", subject),
        ("body_text", body_text),
        ("body_html", body_html),
    ):
        if "{{" in fld_val or "}}" in fld_val:
            return f"{fld_name} contains template syntax"
    blob = f"{subject} {body_text} {body_html}".lower()
    hits = [t for t in VOICE_BANNED if t in blob]
    if hits:
        return f"voice-policy hits {hits}"
    return None


def add_lead_to_campaign(
    *,
    email: str,
    first_name: str = "",
    last_name: str = "",
    company_name: str = "",
    contact_title: str = "",
    subject: str,
    body_text: str = "",
    body_html: str = "",
) -> dict[str, Any]:
    """Add one lead to SMARTLEAD_MASTER_CAMPAIGN_ID. Raises RuntimeError on failure."""
    cid = _campaign_id()
    if not cid:
        raise RuntimeError("SMARTLEAD_MASTER_CAMPAIGN_ID not configured")

    html = body_html.strip() or _text_to_html(body_text)
    text = body_text.strip() or re.sub(r"<[^>]+>", " ", html)
    err = _preflight(subject=subject, body_text=text, body_html=html, email=email)
    if err:
        raise RuntimeError(f"pre-flight failed: {err}")

    lead = {
        "email": email.strip().lower(),
        "first_name": (first_name or "")[:80],
        "last_name": (last_name or "")[:80],
        "company_name": (company_name or "")[:120],
        "custom_fields": {
            "subject": subject.strip()[:200],
            "body_text": text[:8000],
            "body_html": html[:16000],
            "personalized_body": html[:16000],
            "contact_title": (contact_title or "")[:120],
        },
    }
    body = _request(
        "POST",
        f"/campaigns/{cid}/leads",
        json_body={"lead_list": [lead]},
    )
    upload = 0
    duplicate = 0
    if isinstance(body, dict):
        upload = int(body.get("upload_count") or body.get("inserted") or 0)
        duplicate = int(body.get("already_added_to_campaign") or body.get("duplicate") or 0)
    return {
        "campaign_id": cid,
        "email": lead["email"],
        "upload_count": upload,
        "duplicate_count": duplicate,
        "ok": upload > 0 or duplicate > 0,
    }


def enqueue(payload: dict[str, Any] | None = None, **_kwargs) -> dict[str, Any]:
    if is_poc_mode():
        return poc_sandbox(
            "smartlead",
            "enqueue",
            {"campaign_id": _campaign_id() or "launchpad-nurture", "leads_queued": 1},
        )

    if not creds_configured("smartlead"):
        return not_wired("smartlead")

    data = dict(payload or {})
    data.update({k: v for k, v in _kwargs.items() if v is not None})

    # Live single-lead enqueue when payload includes email + subject.
    if data.get("email") and data.get("subject"):
        if _readonly():
            return {
                "adapter": "smartlead",
                "status": "connected",
                "action": "enqueue",
                "detail": "SMARTLEAD_READONLY=true — set false to enqueue live leads",
                "creds_configured": True,
                "sample": {"email": data.get("email"), "dry_run": True},
            }
        try:
            result = add_lead_to_campaign(
                email=str(data["email"]),
                first_name=str(data.get("first_name") or ""),
                last_name=str(data.get("last_name") or ""),
                company_name=str(data.get("company_name") or ""),
                contact_title=str(data.get("contact_title") or ""),
                subject=str(data["subject"]),
                body_text=str(data.get("body_text") or data.get("body") or ""),
                body_html=str(data.get("body_html") or ""),
            )
            return {
                "adapter": "smartlead",
                "status": "connected",
                "action": "enqueue",
                "detail": f"Smartlead campaign {result['campaign_id']} — "
                f"upload={result['upload_count']} duplicate={result['duplicate_count']}",
                "sample": result,
                "creds_configured": True,
            }
        except Exception as exc:
            return {
                "adapter": "smartlead",
                "status": "error",
                "action": "enqueue",
                "detail": f"{creds_detail('smartlead')} — enqueue failed: {exc}",
            }

    try:
        probe = probe_campaign()
    except Exception as exc:
        return {
            "adapter": "smartlead",
            "status": "error",
            "action": "enqueue",
            "detail": f"{creds_detail('smartlead')} — probe failed: {exc}",
        }

    cid = probe.get("master_campaign_id")
    mode = "readonly_probe" if _readonly() else "enqueue_ready"
    return {
        "adapter": "smartlead",
        "status": "connected",
        "action": "enqueue",
        "detail": (
            f"Smartlead master campaign {cid or '(unset)'} — "
            f"{probe.get('name') or probe.get('campaigns', '?')} campaigns visible"
            + ("; set SMARTLEAD_READONLY=false + APPROVED draft to enqueue" if _readonly() else "")
        ),
        "sample": {**probe, "mode": mode},
        "creds_configured": True,
    }
