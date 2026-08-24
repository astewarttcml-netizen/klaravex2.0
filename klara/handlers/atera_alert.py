"""
Atera RMM alert webhook handler — T6.6.4.

FastAPI router at /api/v1/atera/alert.
Receives Atera webhook payloads, maps severity, creates a klaravex_ticket,
and escalates P1/P2 via the escalation lib.

Atera severity mapping:
    critical → P1 (emergency)
    high     → P2 (high)
    medium   → P3 (standard)
    low      → P4 (low)

Returns:
    {"ticket_id": uuid}

Atera webhook body fields (from Atera alert webhooks):
    device_name    — machine display name
    alert_type     — e.g. "Disk Usage", "Service Down", "Patch Failed"
    severity       — critical | high | medium | low
    customer_name  — the Atera customer/company name
    message        — alert message (optional)
    timestamp      — ISO timestamp (optional)

Mount with:
    from infra.klara.handlers.atera_alert import router as atera_alert_router
    app.include_router(atera_alert_router, prefix="/api/v1/atera")
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

from secrets import compare_digest

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .lib import escalation as escalation_lib
from .lib import tickets as tickets_lib

log = logging.getLogger("klaravex.atera_alert")
router = APIRouter()

# Severity mapping: Atera → Klaravex ticket severity
_SEVERITY_MAP: dict[str, str] = {
    "critical": "emergency",   # P1
    "high":     "high",        # P2
    "medium":   "standard",    # P3
    "low":      "low",         # P4
}

# Priority label for display / summary
_PRIORITY_LABEL: dict[str, str] = {
    "emergency": "P1",
    "high":      "P2",
    "standard":  "P3",
    "low":       "P4",
}

# Escalate tickets at P1 (emergency) and P2 (high) automatically.
_AUTO_ESCALATE_SEVERITIES = {"emergency", "high"}

ATERA_WEBHOOK_SECRET = os.environ.get("ATERA_WEBHOOK_SECRET", "")


class AteraAlertPayload(BaseModel):
    device_name: str = Field(min_length=1, max_length=255)
    alert_type: str = Field(min_length=1, max_length=200)
    severity: str = Field(
        description="critical | high | medium | low",
        pattern="^(critical|high|medium|low)$",
    )
    customer_name: str = Field(min_length=1, max_length=200)
    message: str | None = Field(default=None, max_length=2000)
    timestamp: str | None = Field(default=None, max_length=50)
    # Additional Atera fields — accepted but not required
    alert_id: str | None = Field(default=None, max_length=100)
    agent_id: str | None = Field(default=None, max_length=100)
    customer_id: str | None = Field(default=None, max_length=100)


@router.post("/alert", status_code=201)
async def atera_alert(
    payload: AteraAlertPayload,
    x_atera_secret: str | None = Header(default=None),
) -> dict[str, str]:
    """Receive an Atera RMM alert, create a ticket, escalate if P1/P2.

    2026-07-19 (system-wide security check): this legacy handler read
    ATERA_WEBHOOK_SECRET but never checked it — fully unauthenticated,
    creating real tickets and auto-escalating (paging Anthony) P1/P2
    severities for anyone on the open internet. Fail-CLOSED to match the
    pattern already used by the modern atera_webhook.py handler.
    """
    if not ATERA_WEBHOOK_SECRET:
        log.error("ATERA_WEBHOOK_SECRET unset; refusing legacy Atera alert webhook")
        raise HTTPException(
            status_code=503,
            detail="atera alert webhook disabled — server secret not configured",
        )
    if not x_atera_secret or not compare_digest(x_atera_secret, ATERA_WEBHOOK_SECRET):
        log.warning("Atera legacy alert webhook: invalid or missing secret")
        raise HTTPException(status_code=401, detail="invalid webhook secret")

    klaravex_severity = _SEVERITY_MAP.get(payload.severity.lower(), "standard")
    priority = _PRIORITY_LABEL.get(klaravex_severity, "P3")
    received_at = datetime.now(timezone.utc).isoformat()

    # Use customer_name as a proxy for client email lookup. In a full
    # integration this would resolve Atera customer ID → klaravex_clients.
    # For now we construct a deterministic placeholder email so the ticket
    # round-trips correctly.
    safe_company = "".join(c if c.isalnum() else "-" for c in payload.customer_name.lower()).strip("-")
    client_email = f"atera-alert+{safe_company}@klaravex.com"

    summary = (
        f"[{priority}] {payload.alert_type} on {payload.device_name} "
        f"({payload.customer_name}): {payload.message or 'no additional details'}"
    )

    ticket_id: str | None = None
    try:
        ticket_id = await tickets_lib.create_ticket(
            client_email=client_email,
            subject=f"[Atera {priority}] {payload.alert_type} — {payload.device_name}",
            severity=klaravex_severity,
            status="open",
            source="workflow",
            archetype="A3",
            sku=None,
            summary=summary[:500],
            segment_hint="b2b",
            metadata={
                "source_system": "atera",
                "device_name": payload.device_name,
                "alert_type": payload.alert_type,
                "atera_severity": payload.severity,
                "customer_name": payload.customer_name,
                "message": payload.message,
                "atera_timestamp": payload.timestamp,
                "atera_alert_id": payload.alert_id,
                "atera_agent_id": payload.agent_id,
                "atera_customer_id": payload.customer_id,
                "received_at": received_at,
            },
            initial_event={
                "at": received_at,
                "type": "atera_alert",
                "source": "atera",
                "severity": payload.severity,
                "priority": priority,
                "device_name": payload.device_name,
                "alert_type": payload.alert_type,
            },
        )
    except Exception as e:  # noqa: BLE001
        log.exception("Failed to create Atera alert ticket: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create ticket")

    # Auto-escalate P1 and P2
    if klaravex_severity in _AUTO_ESCALATE_SEVERITIES and ticket_id:
        try:
            await escalation_lib.escalate(
                ticket_id=ticket_id,
                client_email=client_email,
                severity=klaravex_severity,
                summary=summary,
                attempted=f"Atera alert received and ticket created ({ticket_id})",
                recommended=(
                    "Investigate immediately. "
                    f"Device: {payload.device_name} | Customer: {payload.customer_name} | "
                    f"Alert: {payload.alert_type}"
                ),
            )
        except Exception as e:  # noqa: BLE001
            log.exception("Escalation failed for Atera alert (ticket %s): %s", ticket_id, e)

    log.info(
        "Atera alert processed: priority=%s device=%s customer=%s ticket=%s",
        priority, payload.device_name, payload.customer_name, ticket_id,
    )

    return {"ticket_id": ticket_id or ""}
