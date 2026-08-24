"""A9 Vapi tool: start_troubleshooting.

Called by Vapi assistant once payment confirmed. Opens a ticket in
klaravex_tickets and returns the first KB-grounded troubleshooting prompt
for the assistant to read aloud. See WORKFLOWS.md §A9.5.
"""

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..lib import kb as kb_lib
from ..lib import tickets as tickets_lib

log = logging.getLogger("klaravex.vapi.start_troubleshooting")
router = APIRouter()


class TroubleshootRequest(BaseModel):
    call_sid: str = Field(default="")
    caller_email: str | None = None
    issue_description: str = Field(default="")
    sku: str = Field(default="per-incident")
    test: bool = Field(default=False, alias="_test")


@router.post("/start_troubleshooting")
async def start_troubleshooting(req: TroubleshootRequest) -> dict[str, Any]:
    if req.test:
        return {"status": "ok", "test": True, "first_step": "Walk me through what you're seeing."}

    ticket_id = None
    if req.caller_email:
        try:
            ticket_id = await tickets_lib.create_ticket(
                client_email=req.caller_email,
                subject=f"A9 call ticket — {req.sku}",
                severity="standard",
                status="open",
                source="vapi",
                archetype="A9",
                sku=req.sku,
                summary=req.issue_description[:500],
                segment_hint="consumer",
                metadata={"call_sid": req.call_sid},
                initial_event={"type": "call.payment_confirmed", "source": "vapi"},
            )
        except Exception as e:  # noqa: BLE001
            log.warning("ticket create failed: %s", e)

    citations: list[dict[str, Any]] = []
    first_step = "Walk me through what you're seeing on screen right now."
    if req.issue_description:
        try:
            hits = await kb_lib.search(req.issue_description, k=2)
            citations = [{"title": h.get("source_title"), "url": h.get("source_url")} for h in hits]
            if hits and hits[0].get("content"):
                title = (hits[0].get("source_title") or "our support guide").strip()
                first_step = (
                    f"I found a support guide on that — {title}. "
                    "Let's start with what you're seeing on screen right now."
                )
        except Exception as e:  # noqa: BLE001
            log.warning("kb lookup failed: %s", e)

    return {
        "status": "ok",
        "ticket_id": ticket_id,
        "first_step": first_step,
        "citations": citations,
    }
