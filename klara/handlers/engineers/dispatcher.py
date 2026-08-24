"""Ticket-to-engineer routing for the 5 pillar engineers.

Each engineer owns one website pillar. The dispatcher picks the highest-scoring
owner for a ticket. If the owner is unavailable (LLM error, capacity, opt-out),
the ticket falls through to that pillar's declared `backup_pillars` in order.

Backup logic = T-shaped engineers actually picking up each other's load.
"""

import logging
from typing import Any, Optional

from ..lib import tickets as tickets_lib
from ..lib.db import get_pool
from .ai_adoption import AIAdoptionEngineer
from .infrastructure_support import InfrastructureSupportEngineer
from .managed_security import ManagedSecurityEngineer
from .microsoft_365 import Microsoft365Engineer
from .regulatory_readiness import RegulatoryReadinessEngineer
from .strategic_advisory import StrategicAdvisoryEngineer

log = logging.getLogger("klaravex.engineers.dispatcher")

# Order matters: ties go to the first one defined here.
# Readiness + Advisory before M365 / ManagedSec / AI so that high-severity
# strategy/regulatory tickets win over keyword-only matches.
# Infrastructure & Support sits last so the more-specialised pillars win on
# overlapping keywords; it absorbs the helpdesk / on-prem / backup default.
ENGINEERS = [
    RegulatoryReadinessEngineer(),
    StrategicAdvisoryEngineer(),
    Microsoft365Engineer(),
    ManagedSecurityEngineer(),
    AIAdoptionEngineer(),
    InfrastructureSupportEngineer(),
]

PILLAR_TO_ENGINEER = {e.pillar: e for e in ENGINEERS}


# ── Website pillar copy (used to seed gap analyses) ───────────────────────────
# Source: klaravex.com hero + verticals strip + WHY section. When the website
# copy changes, update here and re-run /engineers/seed-gap-analyses.
PILLAR_WEBSITE_COPY: dict[str, str] = {
    "managed_security": (
        "Enterprise-grade security for businesses that can't build an internal "
        "security team. Managed Security covers Foundation (RMM + patch + EDR "
        "+ tier-1 helpdesk), Assurance (proactive monitoring + backup/DR + "
        "SIEM + UniFi segmentation), and Directive (24/7 MDR + onsite SLA). "
        "Ubiquiti UniFi firewall & network management included in all tiers. "
        "Atera RMM for endpoint visibility; Huntress MDR for Assurance and "
        "Directive."
    ),
    "regulatory_readiness": (
        "Readiness-native, not readiness-adjacent. We speak HIPAA, SOC 2, and "
        "ISO 27001 as primary languages — not afterthoughts bolted onto a "
        "helpdesk practice. Scope-limited by design: we provide readiness and "
        "advisory — not certification conduct. Every SOW defines exactly where "
        "our work ends and yours begins. Directive tier includes multi-state "
        "US privacy advisory (CCPA/CDPA/VCDPA) and Entra ID identity "
        "governance."
    ),
    "microsoft_365": (
        "Microsoft 365 depth — Entra ID architecture, Purview data governance, "
        "Defender for Business, Copilot deployment — the full tenant, hardened. "
        "Most SMB M365 tenants ship with defaults that fail a SOC 2 audit and "
        "leak data through over-permissioned guest access. Entra ID conditional "
        "access, Purview DLP, and Defender for Business are the controls that "
        "move the needle. We also cover Google Workspace and AWS for clients "
        "on those stacks."
    ),
    "ai_adoption": (
        "AI Adoption — the third pillar in Klaravex's hero promise: 'Managed "
        "Security · Regulatory Readiness · AI Adoption'. We deploy Microsoft "
        "365 Copilot with Purview sensitivity labels + DLP enforced, design "
        "Copilot Studio agents for client workflows, integrate AI workflow "
        "automation across Klara AI + Atera + n8n, and draft AI usage policies "
        "with prompt-injection defense baked in. Klara AI is the AI-first MSP "
        "differentiator — first-line client support that triages, diagnoses, "
        "and escalates to engineers when human judgment is required."
    ),
    "strategic_advisory": (
        "Senior expertise on call — without the senior salary. vCISO advisory, "
        "strategic IT roadmap, board-level security reporting, cyber-insurance "
        "questionnaire support, vendor evaluation, incident response planning, "
        "tabletop facilitation. The vCIO/vCISO seat is what Directive-tier "
        "clients buy to get senior judgment when their leadership team needs "
        "to make a decision without hiring a CISO."
    ),
    "infrastructure_support": (
        "Infrastructure & Support — Pillar 04 of the website's four-pillar "
        "model. The on-prem and hybrid foundation. Windows Server, Active "
        "Directory, backup/DR (Veeam + M365 backup), PowerShell automation, "
        "Atera RMM monitoring + alert tuning, patch management policy, "
        "hardware lifecycle, and the day-to-day helpdesk + remote-support "
        "execution via the RustDesk relay that keeps clients running while "
        "the other pillars do strategy."
    ),
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_engineer(name: str):
    """Lookup by `engineer_*` name."""
    for e in ENGINEERS:
        if e.name == name:
            return e
    return None


def get_engineer_by_pillar(pillar: str):
    return PILLAR_TO_ENGINEER.get(pillar)


def best_engineer_for_ticket(ticket: dict[str, Any]):
    """Return the engineer with the highest matches_ticket score.

    Tie-breaker: ENGINEERS list order (deterministic). Returns None when every
    score is 0.
    """
    scored = [(e, e.matches_ticket(ticket)) for e in ENGINEERS]
    scored.sort(key=lambda x: x[1], reverse=True)
    if scored and scored[0][1] > 0:
        return scored[0][0]
    return None


def backup_chain_for(engineer) -> list:
    """Returns the engineer + their backup pillars in priority order, resolved
    to engineer instances. Used when the primary fails or is over capacity."""
    chain = [engineer]
    for pillar in engineer.backup_pillars:
        backup = PILLAR_TO_ENGINEER.get(pillar)
        if backup is not None and backup not in chain:
            chain.append(backup)
    return chain


# ── Public surface ───────────────────────────────────────────────────────────

async def dispatch_open_tickets(limit: int = 20) -> dict[str, Any]:
    """Process every open ticket that hasn't received an engineer action yet.

    For each ticket: pick the best engineer; if their `reason_about_ticket`
    raises, fall back through `backup_pillars` until someone succeeds or the
    chain is exhausted (then it lands in skipped).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.id::text, t.severity, t.status, t.source, t.archetype,
                   t.sku, t.subject, t.summary, t.client_email, t.created_at
              FROM klaravex_tickets t
              LEFT JOIN klaravex_engineer_actions a ON a.ticket_id = t.id
             WHERE t.status IN ('open', 'in_progress', 'escalated')
               AND a.id IS NULL
             ORDER BY t.created_at DESC
             LIMIT $1
            """,
            limit,
        )

    dispatched = []
    skipped = []
    by_engineer: dict[str, int] = {}
    backup_takeovers = 0

    for row in rows:
        ticket = dict(row)
        primary = best_engineer_for_ticket(ticket)
        if primary is None:
            skipped.append({"id": ticket["id"], "reason": "no engineer match"})
            continue

        chain = backup_chain_for(primary)
        action = None
        action_owner = None
        last_error = None
        for i, candidate in enumerate(chain):
            try:
                action = await candidate.reason_about_ticket(ticket)
                action_owner = candidate
                if i > 0:
                    backup_takeovers += 1
                break
            except Exception as exc:
                last_error = str(exc)
                log.warning(
                    "engineer %s failed on ticket %s (attempt %d/%d): %s",
                    candidate.name, ticket["id"], i + 1, len(chain), exc,
                )

        if action is None or action_owner is None:
            skipped.append({"id": ticket["id"], "reason": last_error or "all backups failed"})
            continue

        try:
            action_id = await action_owner.queue_action(
                action=action,
                ticket_id=ticket["id"],
                client_email=ticket.get("client_email"),
            )
            # AG1: bind the ticket record to the engineer that actually took
            # it. Previously assignee stayed hardcoded at "loki" forever --
            # this was fully built (pillar routing) but never wired to the
            # ticket row. status is passed unchanged (not a real transition);
            # update_status's own notify-on-change email (built for N2)
            # already includes the assignee in its body, so this also
            # satisfies AG2 (engineer notification on assignment) without a
            # second, redundant email path.
            try:
                await tickets_lib.update_status(
                    ticket["id"], status=ticket["status"], assignee=action_owner.name,
                )
            except Exception as exc:
                log.warning("assignee update failed for ticket %s: %s", ticket["id"], exc)
            dispatched.append({
                "ticket_id": ticket["id"],
                "engineer": action_owner.name,
                "pillar": action_owner.pillar,
                "was_backup": action_owner is not primary,
                "action_id": action_id,
                "action_type": action.get("action_type"),
            })
            by_engineer[action_owner.name] = by_engineer.get(action_owner.name, 0) + 1
        except Exception as exc:
            log.exception("queue_action failed for ticket %s: %s", ticket["id"], exc)
            skipped.append({"id": ticket["id"], "reason": f"queue: {exc}"})

    return {
        "dispatched_count": len(dispatched),
        "by_engineer": by_engineer,
        "backup_takeovers": backup_takeovers,
        "skipped_count": len(skipped),
        "dispatched": dispatched,
        "skipped": skipped,
    }


async def seed_gap_analyses() -> dict[str, Any]:
    """Foundational deliverable per engineer: a gap analysis of their pillar.

    Each engineer audits their pillar against the website's promise +
    documentation_targets + cross-pillar dependencies. Idempotent: skips
    engineers that already have a gap_analysis row.
    """
    pool = await get_pool()
    seeded = []
    skipped = []
    for engineer in ENGINEERS:
        async with pool.acquire() as conn:
            existing = await conn.fetchval(
                """
                SELECT 1 FROM klaravex_engineer_actions
                 WHERE engineer = $1 AND action_type = 'gap_analysis'
                 LIMIT 1
                """,
                engineer.name,
            )
        if existing:
            skipped.append({"engineer": engineer.name, "reason": "gap analysis already exists"})
            continue
        try:
            website_copy = PILLAR_WEBSITE_COPY.get(engineer.pillar, "")
            action = await engineer.first_gap_analysis(website_pillar_copy=website_copy)
            action_id = await engineer.queue_action(action=action)
            seeded.append({
                "engineer": engineer.name,
                "pillar": engineer.pillar,
                "action_id": action_id,
            })
        except Exception as exc:
            log.exception("gap-analysis seed failed for %s: %s", engineer.name, exc)
            skipped.append({"engineer": engineer.name, "reason": str(exc)})
    return {"seeded": seeded, "skipped": skipped}


async def seed_playbooks() -> dict[str, Any]:
    """Legacy: also generate service playbooks. Optional follow-up after gap
    analysis. Idempotent on action_type = 'playbook'.
    """
    pool = await get_pool()
    seeded = []
    skipped = []
    for engineer in ENGINEERS:
        async with pool.acquire() as conn:
            existing = await conn.fetchval(
                """
                SELECT 1 FROM klaravex_engineer_actions
                 WHERE engineer = $1 AND action_type = 'playbook'
                 LIMIT 1
                """,
                engineer.name,
            )
        if existing:
            skipped.append({"engineer": engineer.name, "reason": "playbook already exists"})
            continue
        try:
            action = await engineer.first_playbook()
            action_id = await engineer.queue_action(action=action)
            seeded.append({"engineer": engineer.name, "action_id": action_id})
        except Exception as exc:
            log.exception("playbook seed failed for %s: %s", engineer.name, exc)
            skipped.append({"engineer": engineer.name, "reason": str(exc)})
    return {"seeded": seeded, "skipped": skipped}


async def produce_pending_docs(limit_per_engineer: int = 2) -> dict[str, Any]:
    """Loop through each engineer's gap-analysis backlog and produce the next
    N documentation artifacts. Reads `proposed_payload.documentation_backlog`
    from the engineer's gap_analysis row.

    Idempotent on (engineer, action_type='delivery_artifact', title) — if a
    doc with that title already exists we skip it.
    """
    pool = await get_pool()
    produced = []
    skipped = []

    for engineer in ENGINEERS:
        async with pool.acquire() as conn:
            ga = await conn.fetchrow(
                """
                SELECT proposed_payload, body_markdown
                  FROM klaravex_engineer_actions
                 WHERE engineer = $1 AND action_type = 'gap_analysis'
                 ORDER BY created_at DESC LIMIT 1
                """,
                engineer.name,
            )
        if not ga:
            skipped.append({"engineer": engineer.name, "reason": "no gap analysis yet"})
            continue

        payload = ga["proposed_payload"] or {}
        backlog = payload.get("documentation_backlog", []) if isinstance(payload, dict) else []
        backlog = sorted(
            backlog,
            key=lambda d: {"P0": 0, "P1": 1, "P2": 2}.get((d or {}).get("priority", "P2"), 2),
        )
        gap_context = ga["body_markdown"]

        produced_for_engineer = 0
        for item in backlog:
            if produced_for_engineer >= limit_per_engineer:
                break
            title = (item or {}).get("title", "").strip()
            if not title:
                continue
            async with pool.acquire() as conn:
                exists = await conn.fetchval(
                    """
                    SELECT 1 FROM klaravex_engineer_actions
                     WHERE engineer = $1
                       AND action_type = 'delivery_artifact'
                       AND title = $2
                     LIMIT 1
                    """,
                    engineer.name, title,
                )
            if exists:
                skipped.append({"engineer": engineer.name, "title": title, "reason": "already produced"})
                continue
            try:
                action = await engineer.produce_documentation(
                    doc_target=title,
                    gap_context=gap_context[:6000],  # bound LLM input
                )
                action_id = await engineer.queue_action(action=action)
                produced.append({
                    "engineer": engineer.name,
                    "pillar": engineer.pillar,
                    "title": title,
                    "action_id": action_id,
                })
                produced_for_engineer += 1
            except Exception as exc:
                log.exception("doc production failed for %s/%s: %s", engineer.name, title, exc)
                skipped.append({"engineer": engineer.name, "title": title, "reason": str(exc)})

    return {"produced": produced, "skipped": skipped}
