"""PlatformClientConverter — won bid → klaravex_clients lead + onboarding handoff.

Original: itexperts-berlin/loki-agents/app/agents/platform_client_converter.py

Klaravex schema differences:
  - itexperts-berlin used a Lead model with status/score/source/message fields.
  - Klaravex uses klaravex_clients (id, email UNIQUE, name, segment, company,
    phone, metadata jsonb). Lead-specific fields go in metadata.

Flow:
  1. Load platform_bid + freelance_project.
  2. Idempotency check: existing client with same email?
  3. If new: INSERT klaravex_clients with segment='b2b' and metadata={
       source: 'freelance_<platform>', score: 90, message: '...', won_at: ...
     }.
  4. Link platform_bid.lead_id → client id. Set status='won'.
  5. Set freelance_project.status='won'.
  6. Best-effort: trigger onboarding email via lib.welcome.send_post_signup_welcome.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from ..db import get_pool

log = logging.getLogger("klaravex.freelance.converter")


async def convert_won_bid(
    bid_id: str,
    client_name: Optional[str] = None,
    client_email: Optional[str] = None,
    client_phone: Optional[str] = None,
) -> dict[str, Any]:
    """Convert a won platform bid into a klaravex_clients row.

    Idempotent on client email — re-running for the same bid + email returns
    the existing client id without creating a duplicate.

    Caller responsibility: ensure bid_id is a valid uuid and the bid actually
    belongs in 'won' state (this fn enforces the transition but does not vet
    the original win signal).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        bid = await conn.fetchrow(
            "SELECT id, project_id, platform, cover_letter, bid_amount, status, lead_id "
            "  FROM klaravex_platform_bids WHERE id = $1",
            bid_id,
        )
        if not bid:
            return {"ok": False, "error": f"bid {bid_id} not found"}

        project = await conn.fetchrow(
            "SELECT id, platform, platform_id, title, description, url, "
            "       client_name, client_location "
            "  FROM klaravex_freelance_projects WHERE id = $1",
            bid["project_id"],
        )
        if not project:
            return {"ok": False, "error": f"project {bid['project_id']} not found"}

        resolved_name = (client_name or project["client_name"] or "Client").strip()
        resolved_email = (client_email or "").strip().lower() or None
        resolved_phone = (client_phone or "").strip() or None

        platform_label = (bid["platform"] or "platform").title()
        source = f"freelance_{bid['platform']}"
        message = (
            f"[{platform_label} Project] {project['title']}\n\n"
            f"{(project['description'] or '')[:500]}"
        )

        # ── Idempotency: existing client with this email? ─────────────────
        existing: Optional[UUID] = None
        was_duplicate = False
        if resolved_email:
            existing = await conn.fetchval(
                "SELECT id FROM klaravex_clients WHERE lower(email) = $1",
                resolved_email,
            )
        if existing:
            client_id = existing
            was_duplicate = True
            log.info("converter.duplicate bid_id=%s existing_client=%s", bid_id, client_id)
        else:
            if not resolved_email:
                # No email available — generate a placeholder so the row can be
                # created without violating the UNIQUE constraint. Operator can
                # update it later from the project URL.
                resolved_email = (
                    f"unknown+{bid['platform']}-{project['platform_id']}@klaravex-leads.local"
                )
            metadata = {
                "source": source,
                "lead_score": 90,
                "lead_status": "HOT",
                "message": message,
                "project_title": project["title"],
                "project_url": project["url"],
                "platform": bid["platform"],
                "platform_id": project["platform_id"],
                "client_location": project["client_location"],
                "won_at": datetime.now(tz=timezone.utc).isoformat(),
                "gdpr_consent": True,
                "gdpr_ip": "platform_api",
            }
            client_id = await conn.fetchval(
                """
                INSERT INTO klaravex_clients
                    (email, name, segment, company, phone, metadata)
                VALUES ($1, $2, 'b2b', $3, $4, $5::jsonb)
                RETURNING id
                """,
                resolved_email, resolved_name,
                resolved_name if not project["client_name"] else project["client_name"],
                resolved_phone, json.dumps(metadata),
            )
            log.info(
                "converter.lead_created bid_id=%s client_id=%s email=%s platform=%s",
                bid_id, client_id, resolved_email, bid["platform"],
            )

        # Link bid → client, mark won
        await conn.execute(
            """
            UPDATE klaravex_platform_bids
               SET status = 'won',
                   lead_id = $1,
                   won_at = now(),
                   updated_at = now()
             WHERE id = $2
            """,
            client_id, bid_id,
        )
        await conn.execute(
            """
            UPDATE klaravex_freelance_projects
               SET status = 'won',
                   won_at = now(),
                   updated_at = now()
             WHERE id = $1
            """,
            bid["project_id"],
        )

    onboarding_triggered = False
    try:
        from ..welcome import send_post_signup_welcome  # type: ignore
        await send_post_signup_welcome(
            email=resolved_email,
            name=resolved_name,
            sku="freelance_project",
            segment="b2b",
            force=False,
        )
        onboarding_triggered = True
    except Exception as exc:
        log.warning("converter.onboarding_skipped err=%s", exc)

    return {
        "ok": True,
        "lead_id": str(client_id),
        "was_duplicate": was_duplicate,
        "onboarding_triggered": onboarding_triggered,
        "platform": bid["platform"],
        "project_title": project["title"],
        "client_name": resolved_name,
        "client_email": resolved_email,
    }
