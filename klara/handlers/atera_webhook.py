"""
Atera RMM alert triage agent — enhanced webhook handler.

FastAPI router at /api/v1/atera (replaces the lighter atera_alert.py).

Handles Atera webhook event types:
    agent_offline      — device went offline
    threshold_alert    — CPU/memory/disk threshold breach
    patch_missing      — missing critical patch
    service_stopped    — Windows service stopped unexpectedly
    script_failure     — automation script failed

For each alert this handler:
    1. Parses the Atera JSON payload (PascalCase fields from Atera's webhook schema).
    2. Classifies severity using event type, Atera severity field, and message keywords.
    3. Looks up the client in klaravex_clients by CustomerName (case-insensitive ILIKE).
    4. Creates a ticket in klaravex_tickets — client_id NULL if client not found.
    5. Sends a plain-English client notification email via Microsoft Graph.
    6. Escalates P1/P2 via escalation lib (Telegram + email to Anthony).
    7. Returns {"ticket_id": "...", "severity": "...", "notified": true}.

Optional secret check:
    Set ATERA_WEBHOOK_SECRET env var. If set and the incoming
    X-Atera-Secret header does not match, the request is rejected 401.

Utility:
    GET /api/v1/atera/agents — proxy to Atera REST API, returns agent list.
    Requires ATERA_API_KEY env var.

Mount with:
    from klara.handlers.atera_webhook import router as atera_webhook_router
    app.include_router(atera_webhook_router, prefix="/api/v1/atera", tags=["Atera RMM"])
"""

import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .lib import escalation as escalation_lib
from .lib import tickets as tickets_lib
from .lib.db import get_pool
from .lib.email import send_email

router = APIRouter()

# ── Env vars ──────────────────────────────────────────────────────────────────
_WEBHOOK_SECRET = os.environ.get("ATERA_WEBHOOK_SECRET", "")
_ATERA_API_KEY = os.environ.get("ATERA_API_KEY", "")
_FROM_EMAIL = os.environ.get("MS_GRAPH_SENDER_EMAIL", "noreply@klaravex.com")

# ── Severity tables ───────────────────────────────────────────────────────────

# Atera native severity → Klaravex internal severity label
_ATERA_SEVERITY_MAP: dict[str, str] = {
    "critical": "emergency",   # P1
    "high":     "high",        # P2
    "medium":   "standard",    # P3
    "low":      "low",         # P4
}

# Klaravex internal severity → display priority label
_PRIORITY_LABEL: dict[str, str] = {
    "emergency": "P1",
    "high":      "P2",
    "standard":  "P3",
    "low":       "P4",
}

# Alert types that trigger P2 escalation by default (before message inspection)
_P2_ALERT_TYPES = {"patch_missing", "service_stopped"}

# Alert types that are P3 by default
_P3_ALERT_TYPES = {"agent_offline", "threshold_alert", "script_failure"}

# Keywords in AlertMessage that promote agent_offline to P2
_OFFLINE_ESCALATION_KEYWORDS = (">1 hour", "> 1 hour", "1hr", "more than 1 hour", "over 1 hour")

# Keywords in AlertMessage that force P1 regardless of Atera severity
_P1_KEYWORDS = ("disk full", "disk_full", "disk at 100", "storage full", "no space left")

# Auto-escalate tickets at these severities
_AUTO_ESCALATE = {"emergency", "high"}


# ── Pydantic model ────────────────────────────────────────────────────────────

class AteraWebhookPayload(BaseModel):
    """
    Atera webhook body.  Atera sends PascalCase JSON; we accept both
    PascalCase (Atera native) and snake_case (legacy / testing).
    Fields map to Atera's documented alert webhook schema.
    """

    # Core fields Atera always sends
    AlertID: Optional[str] = Field(default=None, max_length=100)
    AgentID: Optional[str] = Field(default=None, max_length=100)
    CustomerName: Optional[str] = Field(default=None, max_length=200)
    CustomerID: Optional[str] = Field(default=None, max_length=100)
    DeviceName: Optional[str] = Field(default=None, max_length=255)
    AlertMessage: Optional[str] = Field(default=None, max_length=2000)
    AlertType: Optional[str] = Field(default=None, max_length=200)
    # Atera severity string: Critical | High | Medium | Low (case-insensitive)
    Severity: Optional[str] = Field(default=None, max_length=50)
    CreatedOn: Optional[str] = Field(default=None, max_length=50)

    # Snake_case aliases accepted for legacy / test payloads
    alert_id: Optional[str] = Field(default=None, max_length=100)
    agent_id: Optional[str] = Field(default=None, max_length=100)
    customer_name: Optional[str] = Field(default=None, max_length=200)
    device_name: Optional[str] = Field(default=None, max_length=255)
    alert_message: Optional[str] = Field(default=None, max_length=2000)
    alert_type: Optional[str] = Field(default=None, max_length=200)
    severity: Optional[str] = Field(default=None, max_length=50)
    timestamp: Optional[str] = Field(default=None, max_length=50)

    # Resolved helpers — prefer PascalCase, fall back to snake_case
    @property
    def r_alert_id(self) -> str:
        return (self.AlertID or self.alert_id or "").strip()

    @property
    def r_agent_id(self) -> str:
        return (self.AgentID or self.agent_id or "").strip()

    @property
    def r_customer_name(self) -> str:
        return (self.CustomerName or self.customer_name or "Unknown Customer").strip()

    @property
    def r_device_name(self) -> str:
        return (self.DeviceName or self.device_name or "Unknown Device").strip()

    @property
    def r_alert_message(self) -> str:
        return (self.AlertMessage or self.alert_message or "").strip()

    @property
    def r_alert_type(self) -> str:
        return (self.AlertType or self.alert_type or "").strip().lower()

    @property
    def r_severity(self) -> str:
        return (self.Severity or self.severity or "medium").strip().lower()

    @property
    def r_created_on(self) -> str:
        return (self.CreatedOn or self.timestamp or datetime.now(timezone.utc).isoformat()).strip()


# ── Severity classification ───────────────────────────────────────────────────

def _classify_severity(payload: AteraWebhookPayload) -> str:
    """
    Return Klaravex internal severity string for the alert.

    Rules (highest-priority first):
    1. Any P1 keyword in AlertMessage → emergency (P1).
    2. Atera native severity=Critical → emergency (P1).
    3. threshold_alert with disk keyword → emergency (P1).
    4. agent_offline with ">1 hour" keyword → high (P2).
    5. patch_missing → high (P2).
    6. service_stopped → high (P2).
    7. Atera native severity map (High→high, Medium→standard, Low→low).
    8. Default: standard (P3).
    """
    msg_lower = payload.r_alert_message.lower()
    atype = payload.r_alert_type
    atera_sev = payload.r_severity

    # Rule 1: disk full keywords force P1 regardless of Atera severity
    if any(kw in msg_lower for kw in _P1_KEYWORDS):
        print(f"[atera_webhook] P1 forced by disk-full keyword: alert_id={payload.r_alert_id}")
        return "emergency"

    # Rule 2: Atera says Critical
    if atera_sev == "critical":
        return "emergency"

    # Rule 3: threshold_alert on disk → P1
    if atype == "threshold_alert" and ("disk" in msg_lower or "storage" in msg_lower):
        print(f"[atera_webhook] P1 forced by disk threshold: alert_id={payload.r_alert_id}")
        return "emergency"

    # Rule 4: agent_offline > 1 hour → P2
    if atype == "agent_offline" and any(kw in msg_lower for kw in _OFFLINE_ESCALATION_KEYWORDS):
        return "high"

    # Rule 5-6: patch_missing / service_stopped default P2
    if atype in _P2_ALERT_TYPES:
        # But if Atera says High it stays High; Medium/Low would still give P2 here
        # because missing patches and stopped services are operationally significant.
        return "high"

    # Rule 7: map remaining Atera severities
    mapped = _ATERA_SEVERITY_MAP.get(atera_sev)
    if mapped:
        return mapped

    # Rule 8: fallback
    return "standard"


# ── Client lookup ─────────────────────────────────────────────────────────────

async def _lookup_client(customer_name: str) -> Optional[dict[str, Any]]:
    """
    Return the klaravex_clients row matching CustomerName (case-insensitive).
    Returns None when no match is found — caller creates an unlinked ticket.
    """
    if not customer_name or customer_name == "Unknown Customer":
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, email, company_name, metadata, segment
              FROM klaravex_clients
             WHERE company_name ILIKE $1
             LIMIT 1
            """,
            customer_name.strip(),
        )
    if row:
        return dict(row)
    return None


# ── Client notification email ─────────────────────────────────────────────────

def _build_notification_subject(payload: AteraWebhookPayload, priority: str) -> str:
    return f"[{priority}] Alert detected on {payload.r_device_name}"


def _build_notification_body(payload: AteraWebhookPayload, priority: str, ticket_id: str) -> str:
    """
    Plain-English email body for the client.  No technical jargon.
    Time is formatted as human-readable UTC.
    """
    atype = payload.r_alert_type
    device = payload.r_device_name
    ticket_ref = ticket_id[:8].upper()  # short reference, not the full UUID

    # Map alert type to a plain English description
    descriptions: dict[str, str] = {
        "agent_offline":    f"We detected that your device **{device}** went offline.",
        "threshold_alert":  f"We detected a resource usage alert on **{device}**.",
        "patch_missing":    f"We found that **{device}** is missing one or more critical security patches.",
        "service_stopped":  f"A critical service on **{device}** has stopped unexpectedly.",
        "script_failure":   f"An automated maintenance task on **{device}** failed to complete.",
    }
    lead = descriptions.get(atype, f"We detected an alert on **{device}**.")

    # Attempt to parse the timestamp into a readable form
    try:
        dt = datetime.fromisoformat(payload.r_created_on.replace("Z", "+00:00"))
        time_str = dt.strftime("%B %d, %Y at %I:%M %p UTC")
    except Exception:
        time_str = payload.r_created_on or "just now"

    urgency_line = (
        "We are treating this as **urgent** and an engineer has been alerted immediately."
        if priority in ("P1", "P2")
        else "Our team is reviewing this and will follow up shortly."
    )

    return (
        f"Hello,\n\n"
        f"{lead.replace('**', '')} This was detected at {time_str}.\n\n"
        f"{urgency_line}\n\n"
        f"Your support reference is: {ticket_ref}. You do not need to take any action "
        f"right now — we will contact you with an update as soon as we have more information.\n\n"
        f"If you have questions in the meantime, reply to this email or reach us at "
        f"support@klaravex.com.\n\n"
        f"— The Klaravex Team"
    )


# ── Main webhook endpoint ─────────────────────────────────────────────────────

@router.post("/webhook", status_code=200)
async def atera_webhook(
    payload: AteraWebhookPayload,
    x_atera_secret: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """
    Receive an Atera RMM alert webhook, classify it, create a ticket,
    notify the client, and escalate P1/P2.

    Authentication: ATERA_WEBHOOK_SECRET must be set on the server. If
    unset, the endpoint returns 503 — never accepts unauthenticated
    requests. (Was previously fail-open: same defect class as H19.)
    """
    # ── Secret check (fail-CLOSED) ──────────────────────────────────────────
    if not _WEBHOOK_SECRET:
        print("[atera_webhook] rejected: ATERA_WEBHOOK_SECRET not configured on server")
        raise HTTPException(
            status_code=503,
            detail="atera webhook disabled — server secret not configured",
        )
    from secrets import compare_digest
    if not x_atera_secret or not compare_digest(x_atera_secret, _WEBHOOK_SECRET):
        print("[atera_webhook] rejected: invalid X-Atera-Secret header")
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    received_at = datetime.now(timezone.utc).isoformat()
    print(
        f"[atera_webhook] received: alert_id={payload.r_alert_id} "
        f"type={payload.r_alert_type} device={payload.r_device_name} "
        f"customer={payload.r_customer_name} atera_severity={payload.r_severity}"
    )

    # ── Step 1: Classify severity ─────────────────────────────────────────────
    klaravex_severity = _classify_severity(payload)
    priority = _PRIORITY_LABEL[klaravex_severity]
    print(f"[atera_webhook] classified: alert_id={payload.r_alert_id} severity={klaravex_severity} priority={priority}")

    # ── Step 2: Look up client ────────────────────────────────────────────────
    client = await _lookup_client(payload.r_customer_name)
    client_id_str: Optional[str] = str(client["id"]) if client else None
    client_email: Optional[str] = client["email"] if client else None

    if client:
        print(f"[atera_webhook] client matched: id={client_id_str} email={client_email}")
    else:
        print(
            f"[atera_webhook] no client match for CustomerName={payload.r_customer_name!r} — "
            "ticket will be flagged for manual review"
        )

    # ── Step 3: Create ticket ─────────────────────────────────────────────────
    # When the client cannot be found we fall back to a sentinel email so
    # create_ticket can still write the row (it will upsert a placeholder client).
    billing_email = client_email or f"unlinked+{_safe_slug(payload.r_customer_name)}@klaravex.com"

    ticket_metadata: dict[str, Any] = {
        "source_system": "atera",
        "alert_id": payload.r_alert_id,
        "agent_id": payload.r_agent_id,
        "alert_type": payload.r_alert_type,
        "atera_severity": payload.r_severity,
        "customer_name": payload.r_customer_name,
        "customer_id": payload.CustomerID,
        "device_name": payload.r_device_name,
        "alert_message": payload.r_alert_message,
        "atera_timestamp": payload.r_created_on,
        "received_at": received_at,
        "client_linked": client is not None,
        "needs_manual_review": client is None,
    }

    summary = (
        f"[{priority}] {payload.r_alert_type} on {payload.r_device_name} "
        f"({payload.r_customer_name}): {payload.r_alert_message or 'no detail'}"
    )

    # ── Step 3a: Dedup window ────────────────────────────────────────────────
    # Same device + alert_type within the last 30 min = update existing ticket
    # heartbeat instead of creating a new one. Prevents alert-storm spam.
    from .lib.db import get_pool as _get_pool
    dedup_pool = await _get_pool()
    async with dedup_pool.acquire() as _conn:
        existing = await _conn.fetchrow(
            """
            SELECT id::text, metadata
              FROM klaravex_tickets
             WHERE source='workflow'
               AND status='open'
               AND created_at >= now() - interval '30 minutes'
               AND metadata->>'source_system' = 'atera'
               AND metadata->>'alert_type'    = $1
               AND metadata->>'device_name'   = $2
             ORDER BY created_at DESC LIMIT 1
            """,
            payload.r_alert_type, payload.r_device_name,
        )
    if existing:
        async with dedup_pool.acquire() as _conn:
            # Bump a counter in metadata + log the dup event; do NOT create new ticket
            import json as _json
            md = existing["metadata"] or {}
            md["duplicate_count"] = int(md.get("duplicate_count", 0)) + 1
            md["last_duplicate_at"] = received_at
            await _conn.execute(
                "UPDATE klaravex_tickets SET metadata=$1::jsonb, updated_at=now() WHERE id=$2",
                _json.dumps(md), existing["id"],
            )
        print(f"[atera_webhook] DEDUP: existing ticket {existing['id']} - dup count now {md['duplicate_count']}")
        return {
            "status": "dedup",
            "ticket_id": existing["id"],
            "duplicate_count": md["duplicate_count"],
            "message": "matched recent open ticket — heartbeat recorded, no new ticket created",
        }

    ticket_id: Optional[str] = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=billing_email,
            subject=f"[Atera {priority}] {payload.r_alert_type} — {payload.r_device_name}",
            severity=klaravex_severity,
            status="open",
            source="workflow",
            archetype="A3",
            sku=None,
            summary=summary[:500],
            segment_hint="b2b",
            metadata=ticket_metadata,
            initial_event={
                "at": received_at,
                "type": "atera_alert",
                "source": "atera",
                "alert_id": payload.r_alert_id,
                "alert_type": payload.r_alert_type,
                "atera_severity": payload.r_severity,
                "klaravex_severity": klaravex_severity,
                "priority": priority,
                "device_name": payload.r_device_name,
                "customer_name": payload.r_customer_name,
            },
        )
        print(f"[atera_webhook] ticket created: id={ticket_id}")
    except Exception as exc:
        print(f"[atera_webhook] ERROR creating ticket: {exc}")
        raise HTTPException(status_code=500, detail="Failed to create ticket") from exc

    # ── Step 4: Notify client ─────────────────────────────────────────────────
    notified = False
    if client_email:
        try:
            subject = _build_notification_subject(payload, priority)
            body = _build_notification_body(payload, priority, ticket_id)
            await send_email(
                to=client_email,
                subject=subject,
                body=body,
            )
            notified = True
            print(f"[atera_webhook] client notified: email={client_email} ticket={ticket_id}")
        except Exception as exc:
            # Non-fatal — ticket already created; log and continue.
            print(f"[atera_webhook] WARNING client email failed: {exc}")
    else:
        print(
            f"[atera_webhook] skipping client notification — no email on file "
            f"for customer={payload.r_customer_name!r}"
        )

    # ── Step 5: Escalate P1/P2 ───────────────────────────────────────────────
    if klaravex_severity in _AUTO_ESCALATE and ticket_id:
        try:
            await escalation_lib.escalate(
                ticket_id=ticket_id,
                client_email=billing_email,
                severity=klaravex_severity,
                summary=summary,
                attempted=(
                    f"Atera webhook received and ticket {ticket_id[:8].upper()} created. "
                    f"Client notification {'sent' if notified else 'FAILED — no email on file'}."
                ),
                recommended=(
                    f"Investigate immediately. "
                    f"Device: {payload.r_device_name} | "
                    f"Customer: {payload.r_customer_name} | "
                    f"Alert type: {payload.r_alert_type} | "
                    f"Message: {payload.r_alert_message or 'n/a'}"
                ),
            )
            print(f"[atera_webhook] escalated: ticket={ticket_id} severity={klaravex_severity}")
        except Exception as exc:
            # Non-fatal — escalation failure must not block the 200 response.
            print(f"[atera_webhook] WARNING escalation failed: ticket={ticket_id} error={exc}")

    return {
        "ticket_id": ticket_id or "",
        "severity": priority,
        "notified": notified,
        "client_linked": client is not None,
    }


# ── Legacy alias: keep /alert working if old Atera webhooks still point to it ─

@router.post("/alert", status_code=200, include_in_schema=False)
async def atera_alert_compat(
    payload: AteraWebhookPayload,
    x_atera_secret: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Backward-compatible alias — routes to the main webhook handler."""
    return await atera_webhook(payload, x_atera_secret=x_atera_secret)


# ── Utility: list Atera agents ────────────────────────────────────────────────

@router.get("/agents")
async def get_agent_list() -> dict[str, Any]:
    """
    Proxy to Atera REST API — returns the list of registered agents with
    their online status.  Used by the Patch Agent (Phase 6+).

    Requires ATERA_API_KEY env var (Atera → Admin → API Keys).
    """
    if not _ATERA_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="ATERA_API_KEY not configured — cannot proxy Atera agent list",
        )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                "https://app.atera.com/api/v3/agents",
                headers={
                    "Authorization": f"Bearer {_ATERA_API_KEY}",
                    "Accept": "application/json",
                },
            )
        if r.status_code == 401:
            print(f"[atera_webhook] get_agent_list: 401 Unauthorized — check ATERA_API_KEY")
            raise HTTPException(status_code=502, detail="Atera API key rejected")
        if r.status_code >= 400:
            print(f"[atera_webhook] get_agent_list: Atera returned {r.status_code}")
            raise HTTPException(status_code=502, detail=f"Atera API error {r.status_code}")

        data = r.json()
        agents = data if isinstance(data, list) else data.get("items", data.get("agents", []))
        print(f"[atera_webhook] get_agent_list: returned {len(agents)} agent(s)")
        return {"agents": agents, "count": len(agents)}
    except HTTPException:
        raise
    except Exception as exc:
        print(f"[atera_webhook] get_agent_list ERROR: {exc}")
        raise HTTPException(status_code=502, detail=f"Failed to reach Atera API: {exc}") from exc


# ── Health check ──────────────────────────────────────────────────────────────

@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "handler": "atera_webhook"}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _safe_slug(text: str) -> str:
    """Return a URL-safe lowercase slug from any string."""
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-") or "unknown"
