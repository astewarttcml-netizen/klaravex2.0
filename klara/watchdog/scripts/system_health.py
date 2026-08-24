#!/usr/bin/env python3
"""Klaravex comprehensive daily system health check.

Runs every 4h via host cron. Probes 4 dimensions:

  1. EXTERNAL  — Twilio, Stripe, Microsoft Graph, OpenAI, Resend, Vapi,
                 Atera, Telegram bot, Cloud Postgres reachability
  2. SURFACE   — klaravex.com, klaravex.io, api/healthz,
                 /admin/, chat /start + /message
  3. VAPI      — assistant + phone-number assignment (catches the
                 +14243486010 outage class)
  4. PIPELINES — staleness per critical DB table (the original watchdog)

Each failure emits a Telegram + email escalation via the
escalate_to_anthony handler. Aggregates all failures per run into a
SINGLE escalation (not one-per-failure spam).

Read-only. Exit 0 always. Errors self-report.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# --- config from env ---
DB_HOST = os.environ["KLX_DB_HOST"]
DB_USER = os.environ["KLX_DB_USER"]
DB_PASS = os.environ["KLX_DB_PASS"]
DB_NAME = os.environ.get("KLX_DB_NAME", "klaravex")
API_BASE = os.environ.get("KLX_API_BASE", "https://api.klaravex.com")
VAPI_SECRET = os.environ["KLX_VAPI_SHARED_SECRET"]
VAPI_API_KEY = os.environ["KLX_VAPI_API_KEY"]
TWILIO_SID = os.environ.get("KLX_TWILIO_ACCOUNT_SID", "")
TWILIO_TOK = os.environ.get("KLX_TWILIO_AUTH_TOKEN", "")
STRIPE_KEY = os.environ.get("KLX_STRIPE_SECRET_KEY", "")
MS_TENANT = os.environ.get("KLX_MS_GRAPH_TENANT_ID", "")
MS_CID = os.environ.get("KLX_MS_GRAPH_CLIENT_ID", "")
MS_SEC = os.environ.get("KLX_MS_GRAPH_CLIENT_SECRET", "")
OAI_KEY = os.environ.get("KLX_OPENAI_API_KEY", "")
RESEND_KEY = os.environ.get("KLX_RESEND_API_KEY", "")
ATERA_KEY = os.environ.get("KLX_ATERA_API_KEY", "")
TG_TOKEN = os.environ.get("KLX_TELEGRAM_BOT_TOKEN", "")

VAPI_NUMBERS_REQUIRED = [
    ("Klaravex Main Line", "+14243486010"),
]

PIPELINES = [
    ("social_drafts",      "klaravex_social_drafts",      timedelta(days=4)),
    ("freelance_projects", "klaravex_freelance_projects", timedelta(days=2)),
    ("prospected_leads",   "klaravex_prospected_leads",   timedelta(days=2)),
    ("marketing_actions",  "klaravex_marketing_actions",  timedelta(days=2)),
    ("tickets",            "klaravex_tickets",            timedelta(days=14)),
]


def http(method: str, url: str, *, timeout: int = 10, **kw) -> tuple[int, str]:
    """Tiny HTTP helper. Returns (status_code, body or error)."""
    headers = kw.pop("headers", {}) or {}
    headers.setdefault("User-Agent", "klaravex-system-health/1.0 (+watchdog; contact astewart@klaravex.com)")
    req = urllib.request.Request(url, method=method, headers=headers, **kw)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(8192).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(8192).decode("utf-8", "replace")
    except Exception as exc:
        return 0, str(exc)


def b64basic(user: str, pwd: str) -> str:
    import base64
    return "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()


def check_external() -> list[tuple[str, str]]:
    issues = []
    # Twilio
    if TWILIO_SID and TWILIO_TOK:
        code, body = http("GET", f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}.json",
                          headers={"Authorization": b64basic(TWILIO_SID, TWILIO_TOK)})
        if code != 200:
            issues.append(("twilio", f"HTTP {code}: {body[:200]}"))
    else:
        issues.append(("twilio", "credentials missing"))

    # Stripe
    if STRIPE_KEY:
        code, body = http("GET", "https://api.stripe.com/v1/balance",
                          headers={"Authorization": "Bearer " + STRIPE_KEY})
        if code != 200:
            issues.append(("stripe", f"HTTP {code}: {body[:200]}"))
    else:
        issues.append(("stripe", "STRIPE_SECRET_KEY missing"))

    # MS Graph token
    if MS_TENANT and MS_CID and MS_SEC:
        data = urllib.parse.urlencode({
            "client_id": MS_CID, "client_secret": MS_SEC,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        }).encode()
        code, body = http("POST", f"https://login.microsoftonline.com/{MS_TENANT}/oauth2/v2.0/token",
                          data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        if code != 200:
            issues.append(("ms_graph", f"token HTTP {code}: {body[:200]}"))
    else:
        issues.append(("ms_graph", "MS_GRAPH_* missing"))

    # OpenAI
    if OAI_KEY:
        code, body = http("GET", "https://api.openai.com/v1/models",
                          headers={"Authorization": "Bearer " + OAI_KEY})
        if code != 200:
            issues.append(("openai", f"HTTP {code}: {body[:200]}"))
    else:
        issues.append(("openai", "OPENAI_API_KEY missing"))

    # Resend
    if RESEND_KEY:
        code, body = http("GET", "https://api.resend.com/domains",
                          headers={"Authorization": "Bearer " + RESEND_KEY})
        if code != 200:
            issues.append(("resend", f"HTTP {code}: {body[:200]}"))

    # Vapi
    code, body = http("GET", "https://api.vapi.ai/assistant?limit=1",
                      headers={"Authorization": "Bearer " + VAPI_API_KEY})
    if code != 200:
        issues.append(("vapi", f"HTTP {code}: {body[:200]}"))

    # Atera
    if ATERA_KEY:
        code, body = http("GET", "https://app.atera.com/api/v3/agents?itemsInPage=1",
                          headers={"X-Api-Key": ATERA_KEY})
        if code != 200:
            issues.append(("atera", f"HTTP {code}: {body[:200]}"))

    # Telegram
    if TG_TOKEN:
        code, body = http("GET", f"https://api.telegram.org/bot{TG_TOKEN}/getMe")
        if code != 200:
            issues.append(("telegram_bot", f"HTTP {code}: {body[:200]}"))
    else:
        issues.append(("telegram_bot", "TELEGRAM_BOT_TOKEN missing — Telegram escalations NOT delivered"))

    return issues


def check_surface() -> list[tuple[str, str]]:
    issues = []
    SURFACES = [
        ("klaravex.com",                "https://klaravex.com/",                [200]),
        ("klaravex.com",                "https://klaravex.com/",                [200]),
        ("klaravex.io_redirect",        "https://klaravex.io/",                 [301, 302]),
        ("api.healthz",                 "https://api.klaravex.com/healthz",     [200]),
        ("api.admin_landing",           "https://api.klaravex.com/admin/",      [200]),
        ("api.chat_start",              "https://api.klaravex.com/api/v1/chat/start", [200, 405]),
        ("api.chat_message_apex",       "https://api.klaravex.com/api/v1/chat/message", [200, 405, 403]),
        ("api.chat_message_fallback",   "https://api.klaravex.com/api/v1/chat/message", [200, 405]),
    ]
    for name, url, ok_codes in SURFACES:
        code, body = http("GET", url, timeout=10)
        if code not in ok_codes:
            issues.append((f"surface.{name}", f"HTTP {code} (expected {ok_codes}): {body[:120]}"))
    return issues


def check_vapi() -> list[tuple[str, str]]:
    issues = []
    code, body = http("GET", "https://api.vapi.ai/phone-number",
                      headers={"Authorization": "Bearer " + VAPI_API_KEY})
    if code != 200:
        issues.append(("vapi.phone_numbers", f"HTTP {code}: {body[:200]}"))
        return issues
    try:
        nums = json.loads(body)
    except Exception as exc:
        issues.append(("vapi.phone_numbers_parse", str(exc)))
        return issues
    by_number = {n.get("number"): n for n in nums}
    for label, e164 in VAPI_NUMBERS_REQUIRED:
        info = by_number.get(e164)
        if not info:
            issues.append((f"vapi.{label}", f"phone {e164} not present in Vapi account"))
            continue
        if not info.get("assistantId"):
            issues.append((f"vapi.{label}", f"phone {e164} has no assistantId — calls will fail with call.start.error-get-assistant"))

    # Recent calls with start-error
    code, body = http("GET", "https://api.vapi.ai/call?limit=20",
                      headers={"Authorization": "Bearer " + VAPI_API_KEY})
    if code == 200:
        try:
            calls = json.loads(body)
        except Exception:
            calls = []
        if isinstance(calls, list):
            err_calls = [c for c in calls if "error" in str(c.get("endedReason", ""))]
            if err_calls:
                issues.append((
                    "vapi.recent_call_errors",
                    f"{len(err_calls)}/{len(calls)} recent calls ended with errors: " + ", ".join(sorted(set(c.get("endedReason") for c in err_calls)))[:200]
                ))
    return issues


def check_pipelines() -> list[tuple[str, str]]:
    issues = []
    try:
        import psycopg2
    except ImportError:
        issues.append(("pipeline.psycopg2", "psycopg2 not installed"))
        return issues
    try:
        conn = psycopg2.connect(host=DB_HOST, user=DB_USER, password=DB_PASS,
                                dbname=DB_NAME, port=5432, sslmode="require",
                                connect_timeout=10)
    except Exception as exc:
        issues.append(("pipeline.db_connect", str(exc)[:200]))
        return issues
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        for name, table, threshold in PIPELINES:
            try:
                cur.execute(f"SELECT MAX(created_at) FROM {table}")
                row = cur.fetchone()
                last_at = row[0] if row else None
            except Exception as exc:
                issues.append((f"pipeline.{name}", f"query failed: {str(exc)[:150]}"))
                conn.rollback()
                continue
            if last_at is None:
                issues.append((f"pipeline.{name}", "table EMPTY (no rows ever)"))
                continue
            age = now - last_at
            if age > threshold:
                d = age.days
                h = int(age.total_seconds() // 3600) - d * 24
                issues.append((f"pipeline.{name}", f"{d}d {h}h stale (last {last_at:%Y-%m-%d %H:%M UTC})"))
    conn.close()
    return issues


def escalate(severity: str, reason: str, summary: str) -> None:
    payload = json.dumps({
        "call_sid": "system_health",
        "reason": reason, "severity": severity, "summary": summary,
    }).encode()
    code, body = http("POST", f"{API_BASE}/api/v1/vapi/escalate_to_anthony",
                      data=payload,
                      headers={"x-vapi-secret": VAPI_SECRET, "content-type": "application/json"},
                      timeout=15)
    if code != 200:
        print(f"[system_health] escalate failed: HTTP {code}: {body[:200]}", file=sys.stderr)


def main() -> int:
    all_issues = []
    all_issues += [("EXT.{}".format(n), v) for n, v in check_external()]
    all_issues += [("SUR.{}".format(n), v) for n, v in check_surface()]
    all_issues += [("VAP.{}".format(n), v) for n, v in check_vapi()]
    all_issues += [("PIP.{}".format(n), v) for n, v in check_pipelines()]

    if not all_issues:
        now = datetime.now(timezone.utc)
        if now.weekday() == 0 and now.hour < 12:
            escalate("normal", "Klaravex system health — ALL GREEN",
                     "Daily checks (external APIs, surfaces, Vapi, pipelines) all healthy.")
        return 0

    by_dim = {}
    for name, msg in all_issues:
        dim = name.split(".", 1)[0]
        by_dim.setdefault(dim, []).append(f"  - {name}: {msg}")

    lines = [f"System health detected {len(all_issues)} issues:\n"]
    for dim in ("EXT", "SUR", "VAP", "PIP"):
        if dim in by_dim:
            label = {"EXT":"EXTERNAL APIs","SUR":"PUBLIC SURFACES","VAP":"VAPI","PIP":"PIPELINES"}[dim]
            lines.append(f"\n{label}:")
            lines.extend(by_dim[dim])
    lines.append(f"\nDetails: ssh klaravex-hetzner; tail /var/log/klaravex-system-health.log")

    severity = "high" if any(n.startswith(("SUR.","EXT.","VAP.")) for n, _ in all_issues) else "normal"
    escalate(severity, f"Klaravex system health: {len(all_issues)} issue(s)", "\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
