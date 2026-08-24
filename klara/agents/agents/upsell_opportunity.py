"""
app/agents/upsell_opportunity.py
─────────────────────────────────
UpsellOpportunityAgent (P2)

Scans completed engagements to surface expansion opportunities for existing
clients.  Uses Claude to analyse service history, NPS signals, and project
outcomes, then generates ranked upsell recommendations with draft outreach
copy.

Upsell signals evaluated:
  • Completed portal projects with high NPS (≥8)
  • Long-tenured clients (>90 days) without a recent proposal
  • Clients using only one service vertical who match profiles for another
  • Clients with satisfaction_score ≥ 8 but no referral/testimonial sent

Input:
  { "lead_id": "<uuid>" }          — single client
  {}  or  { "all_clients": true }  — scan all lead.status = "client"
  { "min_nps": 7 }                 — only clients with NPS ≥ threshold (default 7)

Output (AgentResult.data):
  {
    "opportunities": [
      {
        "lead_id": str,
        "name": str,
        "email": str,
        "company": str | null,
        "nps": float | null,
        "completed_projects": int,
        "days_as_client": int,
        "upsell_type": str,
        "confidence": "high"|"medium"|"low",
        "rationale": str,
        "recommended_next_service": str,
        "draft_message_subject": str,
        "draft_message_body": str,
      },
      ...
    ],
    "generated_at": str,
    "scanned": int,
    "opportunities_found": int,
  }
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent, PermissionLevel
from klara.rarv.lead import Lead, LeadStatus
from klara.rarv.portal import Client, Project, ProjectStatus

logger = structlog.get_logger(__name__)

# Services Klaravex offers — used in Claude prompt for recommendations
IT_EXPERTS_SERVICES = [
    "Network infrastructure assessment & design",
    "Microsoft 365 migration & administration",
    "Azure cloud setup & governance",
    "Endpoint management (Intune / MDM)",
    "Cybersecurity audit & hardening",
    "Managed monitoring & patch compliance",
    "IT helpdesk / on-call support retainer",
    "IT project management & vendor coordination",
]


class UpsellOpportunityAgent(BaseAgent):
    name = "upsell_opportunity"
    description = (
        "Scans completed client engagements for expansion signals.  "
        "Uses Claude to rank upsell opportunities and generate draft outreach copy.  "
        "Targets clients with high NPS or multiple completed projects.  P2."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        db       = context.db
        settings = context.settings
        now      = datetime.now(timezone.utc)

        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )
        log.info("upsell_opportunity.start", input=input_data)

        min_nps: float = float(input_data.get("min_nps", 7.0))
        lead_id: str | None = input_data.get("lead_id")

        try:
            # ── Load target leads ─────────────────────────────────────────────
            if lead_id:
                leads_r = await db.execute(
                    select(Lead).where(
                        Lead.id == lead_id,
                        Lead.status == LeadStatus.won.value,
                    )
                )
            else:
                leads_r = await db.execute(
                    select(Lead).where(Lead.status == LeadStatus.won.value)
                )
            leads = leads_r.scalars().all()

            if not leads:
                return AgentResult.ok({
                    "opportunities": [],
                    "generated_at": now.isoformat(),
                    "scanned": 0,
                    "opportunities_found": 0,
                })

            # ── Gather per-client signals ─────────────────────────────────────
            client_profiles: list[dict] = []

            for lead in leads:
                days_as_client = (now - lead.created_at.replace(tzinfo=timezone.utc)
                                  if lead.created_at.tzinfo is None
                                  else now - lead.created_at).days

                # Portal projects
                portal_client_r = await db.execute(
                    select(Client).where(Client.email == lead.email).limit(1)
                )
                portal_client = portal_client_r.scalar_one_or_none()

                completed_projects: list[str] = []
                active_projects: list[str] = []
                if portal_client:
                    proj_r = await db.execute(
                        select(Project).where(Project.client_id == portal_client.id)
                    )
                    for p in proj_r.scalars().all():
                        if p.status == ProjectStatus.complete.value:
                            completed_projects.append(p.title)
                        else:
                            active_projects.append(p.title)

                nps = lead.satisfaction_score

                # Basic eligibility filter — skip low-NPS unless specifically requested
                has_completed = bool(completed_projects)
                long_tenured  = days_as_client >= 90
                high_nps      = nps is not None and nps >= min_nps
                no_active     = len(active_projects) == 0

                # Must meet at least one positive signal
                if not (has_completed or long_tenured or high_nps):
                    continue

                client_profiles.append({
                    "lead_id":            lead.id,
                    "name":               lead.name or "Unknown",
                    "email":              lead.email or "",
                    "company":            lead.company,
                    "nps":                nps,
                    "days_as_client":     days_as_client,
                    "completed_projects": completed_projects,
                    "active_projects":    active_projects,
                    "services_interest":  lead.services_interest,
                    "testimonial_sent":   lead.testimonial_sent_at is not None,
                    "referral_sent":      lead.referral_sent_at is not None,
                })

            if not client_profiles:
                return AgentResult.ok({
                    "opportunities": [],
                    "generated_at": now.isoformat(),
                    "scanned": len(leads),
                    "opportunities_found": 0,
                })

            # ── Claude analysis ───────────────────────────────────────────────
            services_list = "\n".join(f"  - {s}" for s in IT_EXPERTS_SERVICES)
            profiles_json = json.dumps(client_profiles, ensure_ascii=False, indent=2)

            prompt = f"""You are analysing client data for Klaravex — an independent IT \
consulting firm run by Anthony Stewart.

Here are the services offered:
{services_list}

Here are the client profiles to analyse:
{profiles_json}

For EACH client, identify the best upsell opportunity.  Consider:
1. Completed projects reveal what services they already consumed — recommend adjacent services.
2. High NPS (≥8) clients are most receptive.  Low/no NPS = treat as neutral.
3. Clients with no active project + completed history = prime re-engagement window.
4. Long-tenured clients (≥90 days) without recent activity need re-engagement.
5. If a client hasn't been asked for a testimonial/referral yet — that's also an upsell lever.

Return a JSON array (no markdown, no explanation — only the JSON):
[
  {{
    "lead_id": "<same lead_id from input>",
    "upsell_type": "<category: cross-sell | expansion | re-engagement | referral>",
    "confidence": "<high | medium | low>",
    "rationale": "<1-2 sentences on why>",
    "recommended_next_service": "<one of the services listed above>",
    "draft_message_subject": "<email subject line, ≤60 chars>",
    "draft_message_body": "<email body, 3-4 paragraphs, professional, not salesy, \
signed 'Best regards,\\nAnthony Stewart\\nKlaravex'>"
  }},
  ...
]

Rules:
- Include ALL clients from the input (one entry per client).
- Keep draft_message_body under 350 words.
- confidence = high if NPS ≥8 AND has completed projects; medium if only one signal; low otherwise.
- Write in English. Professional, warm, not generic.
"""

            anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
            log.info("upsell_opportunity.claude_call", clients=len(client_profiles))

            response = await anthropic_client.messages.create(
                model=settings.anthropic_model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            try:
                from klara.rarv.runtime.llm_cost import track_response
                await track_response(
                    context.db, agent_name=self.name,
                    model=settings.anthropic_model,
                    response=response, lead_id=getattr(context, 'lead_id', None),
                )
            except Exception:
                pass

            raw = response.content[0].text.strip()

            # Strip markdown code fence if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            try:
                claude_results: list[dict] = json.loads(raw)
            except json.JSONDecodeError as exc:
                log.error("upsell_opportunity.json_error", error=str(exc), raw=raw[:300])
                return AgentResult.fail(error=f"Claude returned invalid JSON: {exc}")

            # ── Merge Claude output with profile metadata ─────────────────────
            profile_map = {p["lead_id"]: p for p in client_profiles}
            opportunities: list[dict] = []

            for item in claude_results:
                lid = item.get("lead_id", "")
                profile = profile_map.get(lid, {})
                opportunities.append({
                    "lead_id":                  lid,
                    "name":                     profile.get("name", ""),
                    "email":                    profile.get("email", ""),
                    "company":                  profile.get("company"),
                    "nps":                      profile.get("nps"),
                    "completed_projects":       len(profile.get("completed_projects", [])),
                    "days_as_client":           profile.get("days_as_client", 0),
                    "upsell_type":              item.get("upsell_type", ""),
                    "confidence":               item.get("confidence", "medium"),
                    "rationale":                item.get("rationale", ""),
                    "recommended_next_service": item.get("recommended_next_service", ""),
                    "draft_message_subject":    item.get("draft_message_subject", ""),
                    "draft_message_body":       item.get("draft_message_body", ""),
                })

            # Sort: high confidence first, then by NPS desc
            confidence_order = {"high": 0, "medium": 1, "low": 2}
            opportunities.sort(
                key=lambda x: (
                    confidence_order.get(x["confidence"], 2),
                    -(x["nps"] or 0),
                )
            )

            log.info(
                "upsell_opportunity.done",
                scanned=len(leads),
                analysed=len(client_profiles),
                opportunities=len(opportunities),
            )
            return AgentResult.ok({
                "opportunities":      opportunities,
                "generated_at":       now.isoformat(),
                "scanned":            len(leads),
                "opportunities_found": len(opportunities),
            })

        except Exception as exc:
            log.error("upsell_opportunity.error", error=str(exc), exc_info=True)
            return AgentResult.fail(error=str(exc))
