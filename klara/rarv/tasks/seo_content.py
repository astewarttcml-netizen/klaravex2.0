"""
app/tasks/seo_content.py
─────────────────────────
Celery task: generate a daily SEO blog post draft for both Klaravex domains.

Schedule: daily 06:30 Europe/Berlin (see celery_app.py beat schedule).

Generates two posts per run:
  1. klaravex.com       — MSP/security/compliance verticals
  2. personal.klaravex.com — tech leadership, AI, software, career

Auto-selects a keyword per domain, avoiding recent repeats.
"""
from __future__ import annotations

import asyncio
import random
import uuid

import structlog

from app.tasks.celery_app import celery_app
from app.database import db_context
from app.config import get_settings
from app.agents.base import AgentContext
from app.agents.registry import registry

logger = structlog.get_logger(__name__)

# ── Keyword pool for klaravex.com (MSP business verticals) ─────────────────
_KOM_KEYWORD_POOL = [
    # HIPAA / healthcare IT
    "HIPAA compliance checklist for small medical practices",
    "healthcare data security best practices",
    "HIPAA risk assessment for medical offices",
    "secure patient data in the cloud",
    "HIPAA email compliance for doctors",
    "medical office cybersecurity",
    "telehealth security requirements",
    "HIPAA breach notification rules",
    # SOC 2 / ISO 27001 readiness
    "SOC 2 readiness for startups",
    "ISO 27001 certification cost for small businesses",
    "SOC 2 Type II audit preparation",
    "information security policy template",
    "vendor risk management for SMBs",
    "security compliance roadmap",
    # M365 / Google Workspace / AWS
    "Microsoft 365 security hardening",
    "M365 Defender setup guide",
    "Google Workspace security settings",
    "AWS security best practices for SMBs",
    "Azure AD conditional access policies",
    "Intune device management setup",
    "Microsoft Entra ID security",
    "M365 backup strategy",
    # Managed IT / MSP
    "managed IT services for law firms",
    "outsourced IT support for accounting firms",
    "IT support for small businesses",
    "managed security services for SMBs",
    "remote IT support benefits",
    "IT disaster recovery planning",
    "business continuity plan for small business",
    "endpoint detection and response for SMBs",
    # Network / Ubiquiti UniFi
    "UniFi network setup for small office",
    "small business firewall best practices",
    "network segmentation for compliance",
    "Wi-Fi security for business",
    "zero trust network access for SMBs",
    # General cybersecurity
    "phishing prevention training for employees",
    "multi-factor authentication setup guide",
    "ransomware prevention for small business",
    "password manager for business teams",
    "cybersecurity insurance requirements",
    "dark web monitoring for businesses",
    "incident response plan template",
    "security awareness training ROI",
]

# ── Keyword pool for personal.klaravex.com (tech leadership / AI / career) ─
_PERSONAL_KEYWORD_POOL = [
    # AI / ML engineering
    "AI agent orchestration patterns",
    "building production AI systems",
    "LLM evaluation and observability",
    "AI-powered software development workflows",
    "multi-agent system architecture",
    "local LLM deployment for developers",
    "RAG pipeline design for production",
    "AI tool calling best practices",
    # Software engineering leadership
    "leading remote engineering teams",
    "code review culture and best practices",
    "engineering team productivity metrics",
    "technical debt management strategies",
    "building internal developer platforms",
    "platform engineering team structure",
    "CI/CD pipeline design patterns",
    "incident response engineering culture",
    # Cloud / infrastructure
    "Kubernetes vs serverless decision framework",
    "infrastructure as code best practices",
    "database migration strategies for production",
    "observability stack design",
    "cloud cost optimization for engineering teams",
    "zero-downtime deployment patterns",
    "container orchestration at scale",
    "edge computing architecture patterns",
    # Developer tools / open source
    "building developer tools that engineers love",
    "open source contribution guide for teams",
    "VS Code extension development workflow",
    "API design best practices",
    "Rust vs Go systems programming comparison",
    "TypeScript type system deep dive",
    "command-line tool design principles",
    "developer experience metrics",
    # Tech career / growth
    "senior engineer career path",
    "from IC to engineering manager transition",
    "technical writing for engineers",
    "building a personal brand as a developer",
    "tech conference speaking guide",
    "open source portfolio building",
    "negotiating engineering offers",
    "mentorship in engineering organizations",
    # Architecture / systems design
    "event-driven architecture patterns",
    "microservices vs monolith decision guide",
    "distributed systems design principles",
    "eventual consistency patterns",
    "CQRS and event sourcing in practice",
    "API gateway design patterns",
    "service mesh adoption guide",
    "database sharding strategies",
]


async def _pick_keyword(db, domain: str) -> str:
    """Pick a keyword not used in the last 30 days for the given domain."""
    pool = _KOM_KEYWORD_POOL if domain == "klaravex.com" else _PERSONAL_KEYWORD_POOL
    try:
        recent = await db.fetch(
            "SELECT DISTINCT payload->>'keyword' AS kw "
            "FROM klaravex.approval_requests "
            "WHERE action_name = 'seo_content_writer.publish' "
            "  AND (payload->>'domain') = $1 "
            "  AND created_at > now() - interval '30 days'",
            domain,
        )
        used = {r["kw"] for r in recent if r["kw"]}
    except Exception:
        used = set()

    available = [k for k in pool if k not in used]
    if not available:
        available = pool  # full rotation complete, start over
    return random.choice(available)


@celery_app.task(name="app.tasks.seo_content.run_seo_content", bind=True, max_retries=2, default_retry_delay=300)
def run_seo_content(self, triggered_by: str = "beat"):
    """Generate daily SEO blog post drafts for both klaravex domains."""
    log = logger.bind(task="seo_content", triggered_by=triggered_by)
    log.info("seo_content.task_start")

    async def _run():
        settings = get_settings()
        async with db_context() as db:
            results = {}
            # Generate one post per domain
            for domain, domain_label in [
                ("klaravex.com", "klaravex"),
                ("personal.klaravex.com", "personal"),
            ]:
                keyword = await _pick_keyword(db, domain)
                log.info("seo_content.keyword_selected",
                         domain=domain, keyword=keyword)

                context = AgentContext(
                    db=db,
                    settings=settings,
                    conversation_id=uuid.uuid4(),
                    request_id=uuid.uuid4(),
                    lead_id=None,
                )
                agent = registry.get("seo_content_writer")
                if not agent:
                    log.error("seo_content.agent_not_found")
                    try:
                        from app.services.pipeline_alert import pipeline_alert
                        await pipeline_alert("seo", "agent_not_found", "critical",
                                             "SEO agent not found in registry — no posts will be generated")
                    except Exception:
                        pass
                    continue

                result = await agent(context, {
                    "keyword": keyword,
                    "domain": domain,
                })
                status = "ok"
                if result.success or result.approval_required:
                    log.info("seo_content.task_complete",
                             domain=domain, keyword=keyword,
                             status=result.output.get("status", "needs_approval") if result.output else "needs_approval")
                else:
                    log.error("seo_content.task_failed",
                              domain=domain, keyword=keyword,
                              error=result.error)
                    status = "error"
                results[domain_label] = {"keyword": keyword, "status": status}

            # ── Daily summary alert ─────────────────────────────────
            try:
                from app.services.pipeline_alert import pipeline_alert
                kom = results.get("klaravex", {})
                per = results.get("personal", {})
                await pipeline_alert(
                    "seo", "daily_summary", "info",
                    f"SEO posts generated:\n"
                    f"• klaravex.com: {kom.get('keyword','—')} [{kom.get('status','?')}]\n"
                    f"• personal.klaravex.com: {per.get('keyword','—')} [{per.get('status','?')}]"
                )
            except Exception:
                pass
            return results

    try:
        return asyncio.run(_run())
    except Exception as exc:
        log.error("seo_content.task_error", error=str(exc))
        try:
            import asyncio as _asyncio
            from app.services.pipeline_alert import pipeline_alert
            _asyncio.run(pipeline_alert(
                "seo", "task_error", "critical",
                f"SEO task failed (will retry): {exc}"
            ))
        except Exception:
            pass
        raise self.retry(exc=exc)
