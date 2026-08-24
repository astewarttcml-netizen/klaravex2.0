"""
app/main.py
───────────
FastAPI application entry point.

Startup order:
  1. Load settings (fail fast if secrets missing)
  2. Optionally init Sentry
  3. Register routers
  4. Expose /health for load-balancer probes
"""
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from klara.rarv.runtime import get_settings
from klara.rarv.runtime import configure_logging

# Configure structlog BEFORE importing routers/agents, because the agent
# registry bootstraps at import time and emits a debug log per agent. If
# configuration is deferred to the lifespan handler, those early loggers
# materialize against structlog's default PrintLoggerFactory and get cached,
# which then crashes the `add_logger_name` processor at runtime
# (PrintLogger has no `.name`).
configure_logging(debug=get_settings().app_debug)

from app.api import admin_dashboard, agents, approvals, beat_trigger, chat, content_approvals, deal_admin, invoices_admin, known_problems, leads, messages_admin, notes_admin, playbooks, portal_clients_admin, portal_files_admin, portal_invoices_admin, portal_projects_admin, proposals, prospecting_admin, reports, reports_admin, seo_content_admin, social_media, social_media_admin, translation_admin, translation_sync, webhooks, webhooks_stripe, website_deploy_admin
from app.api import freelance_admin, vapi_webhook, webhooks_calendly
from app.api import tracking as engagement_tracking
from app.api import webhooks_email
from app.api import webhooks_didww, webhooks_smartlead
from app.api import outreach_sequences_admin
from app.api import suppression_admin
from app.api import proposals_admin
from app.api import funnel_analytics
from app.api import audit_timeline
from app.api import agent_metrics
from app.api import gdpr_sar
from app.api import llm_cost_admin
from app.api import status_page
from app.api import kb_public
from app.api import gdpr_erase
from app.api import quality_admin
from app.api import forecast
from app.api import kb_landing
from app.api import agent_activity
from app.api import experiments_admin
from app.api import testimonials_public
from app.api import openapi_export
from app.api import leads_bulk
from app.api import admin_self_test
from app.api import contracts_admin
from app.api import public_pricing
from app.api import referrals_admin
from app.api import webhooks_inbound
from app.api import inbox_admin
from app.api import linkedin_admin
from app.api import client_intelligence_admin
from app.api import sales_division_admin, engineering_division_admin, design_division_admin
from app.api import invoice_generator_admin
from app.api import phase7_admin
from app.api.portal import router as portal_router

logger = structlog.get_logger(__name__)


_REQUIRED_PRODUCTION_VARS = [
    "APP_SECRET_KEY",
    "ANTHROPIC_API_KEY",
    "DATABASE_URL",
    "WP_WEBHOOK_SECRET",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    import os
    settings = get_settings()

    if settings.is_production:
        missing = [v for v in _REQUIRED_PRODUCTION_VARS if not os.getenv(v)]
        if missing:
            raise RuntimeError(
                f"Required env vars missing in production: {', '.join(missing)}. "
                "Check .env file on the server."
            )
        logger.info("app.env_vars_validated", checked=_REQUIRED_PRODUCTION_VARS)

    if settings.sentry_dsn:
        import sentry_sdk
        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.app_env)
        logger.info("sentry.initialized", env=settings.app_env)

    logger.info("app.startup", env=settings.app_env, model=settings.anthropic_model)
    yield
    logger.info("app.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Klara AI Agents — Klaravex",
        description=(
            "Multi-agent backend for klaravex.de. "
            "Provides chat intake, lead qualification, proposal drafting, "
            "and approval-gated automation."
        ),
        version="2026.05.29",
        docs_url="/docs" if (not settings.is_production or settings.show_docs) else None,
        redoc_url="/redoc" if (not settings.is_production or settings.show_docs) else None,
        openapi_url="/openapi.json" if (not settings.is_production or settings.show_docs) else None,
        lifespan=lifespan,
    )

    # ── Security middleware ───────────────────────────────────────────────────
    # phase15-003 — security headers on every response
    from app.core.security_headers import SecurityHeadersMiddleware
    app.add_middleware(SecurityHeadersMiddleware)
    # phase15-002 — public-endpoint rate limiting
    from app.core.rate_limit import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH"],
        allow_headers=["*"],
    )

    # In production, only accept traffic from our own domain / reverse proxy
    if settings.is_production:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.trusted_hosts,
        )

    # ── Request ID middleware ─────────────────────────────────────────────────
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        import uuid
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # ── Portal: noindex middleware ─────────────────────────────────────────────
    @app.middleware("http")
    async def portal_noindex(request: Request, call_next):
        """
        All portal API responses must not be indexed by search engines.
        Adds X-Robots-Tag header on every /api/v1/portal/ response.
        """
        response = await call_next(request)
        if request.url.path.startswith("/api/v1/portal/"):
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response


    # ── Portal: access-denial logger ──────────────────────────────────────────
    @app.middleware("http")
    async def log_portal_access_denials(request: Request, call_next):
        """
        Log 401 and 403 responses on portal paths for security monitoring.
        This runs AFTER auth dependencies have raised HTTPException, so the
        response status code here reflects the actual auth outcome.
        """
        response = await call_next(request)
        if (
            request.url.path.startswith("/api/v1/portal/")
            and response.status_code in (401, 403)
        ):
            logger.warning(
                "portal.access_denied",
                path=request.url.path,
                method=request.method,
                status=response.status_code,
                client=request.client.host if request.client else "unknown",
            )
        return response

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(chat.router,      prefix="/api/v1/chat",      tags=["chat"])
    app.include_router(leads.router,     prefix="/api/v1/leads",     tags=["leads"])
    app.include_router(webhooks.router,         prefix="/api/v1/webhooks",  tags=["webhooks"])
    app.include_router(webhooks_stripe.router,  prefix="/api/v1/webhooks",  tags=["stripe-webhooks"])
    app.include_router(webhooks_calendly.router, prefix="/api/v1/webhooks", tags=["calendly-webhooks"])
    # ── phase3-002 ────────────────────────────────────────────────────────────
    app.include_router(engagement_tracking.router, prefix="/api/v1",          tags=["engagement-tracking"])
    app.include_router(webhooks_email.router,      prefix="/api/v1/webhooks", tags=["email-webhooks"])
    app.include_router(webhooks_didww.router,     prefix="/api/v1/webhooks", tags=["didww-webhooks"])
    app.include_router(webhooks_smartlead.router,  prefix="/api/v1/webhooks", tags=["smartlead-webhooks"])
    # ── phase3-005 — sequence-approval admin ──────────────────────────────────
    app.include_router(
        outreach_sequences_admin.router,
        prefix="/api/v1/admin/outreach-sequences",
        tags=["admin-outreach-sequences"],
    )
    # ── phase4-005 — suppression-list admin ───────────────────────────────────
    app.include_router(
        suppression_admin.router,
        prefix="/api/v1/admin/suppression-list",
        tags=["admin-suppression-list"],
    )
    # ── phase5-003 — proposal lifecycle admin ─────────────────────────────────
    app.include_router(
        proposals_admin.router,
        prefix="/api/v1/admin/proposals",
        tags=["admin-proposals"],
    )
    # ── phase5-004 — funnel analytics ─────────────────────────────────────────
    app.include_router(
        funnel_analytics.router,
        prefix="/api/v1/admin/funnel-analytics",
        tags=["admin-funnel-analytics"],
    )
    # ── phase7-005 — audit timeline ──────────────────────────────────────────
    app.include_router(
        audit_timeline.router,
        prefix="/api/v1/admin/audit-timeline",
        tags=["admin-audit-timeline"],
    )
    # ── phase8-001 — agent metrics ───────────────────────────────────────────
    app.include_router(
        agent_metrics.router,
        prefix="/api/v1/admin/agent-metrics",
        tags=["admin-agent-metrics"],
    )
    # ── phase8-005 — GDPR SAR endpoint ───────────────────────────────────────
    app.include_router(
        gdpr_sar.router,
        prefix="/api/v1/admin/gdpr/sar",
        tags=["admin-gdpr-sar"],
    )
    # ── phase9-002 — LLM cost analytics ──────────────────────────────────────
    app.include_router(
        llm_cost_admin.router,
        prefix="/api/v1/admin/llm-cost",
        tags=["admin-llm-cost"],
    )
    # ── phase10-005 — public status page ─────────────────────────────────────
    app.include_router(
        status_page.router,
        prefix="/status",
        tags=["public-status"],
    )
    # ── phase11-003 — public KB search ───────────────────────────────────────
    app.include_router(
        kb_public.router,
        prefix="/api/v1/kb-public",
        tags=["public-kb"],
    )
    # ── phase11-004 — GDPR erase endpoint ────────────────────────────────────
    app.include_router(
        gdpr_erase.router,
        prefix="/api/v1/admin/gdpr/erase",
        tags=["admin-gdpr-erase"],
    )
    # ── phase12-004 — quality endpoint ──────────────────────────────────────
    app.include_router(
        quality_admin.router,
        prefix="/api/v1/admin/quality",
        tags=["admin-quality"],
    )
    # ── phase13-003 — pipeline forecast ─────────────────────────────────────
    app.include_router(
        forecast.router,
        prefix="/api/v1/admin/forecast",
        tags=["admin-forecast"],
    )
    # ── phase13-004 — public KB landing ─────────────────────────────────────
    app.include_router(
        kb_landing.router,
        prefix="/kb",
        tags=["public-kb-landing"],
    )
    # ── phase13-005 — agent activity audit ──────────────────────────────────
    app.include_router(
        agent_activity.router,
        prefix="/api/v1/admin/agent-activity",
        tags=["admin-agent-activity"],
    )
    # ── phase14-002 — experiments admin ─────────────────────────────────────
    app.include_router(
        experiments_admin.router,
        prefix="/api/v1/admin/experiments",
        tags=["admin-experiments"],
    )
    # ── phase14-003 — public testimonials ───────────────────────────────────
    app.include_router(
        testimonials_public.router,
        prefix="",
        tags=["public-testimonials"],
    )
    # ── phase15-004 — OpenAPI export (X-API-Key gated) ──────────────────────
    app.include_router(
        openapi_export.router,
        prefix="/api/v1/admin",
        tags=["admin-openapi"],
    )
    # ── phase15-005 — bulk lead annotation ──────────────────────────────────
    app.include_router(
        leads_bulk.router,
        prefix="/api/v1/admin/leads",
        tags=["admin-leads-bulk"],
    )
    # ── phase17-003 — admin self-test ───────────────────────────────────────
    app.include_router(
        admin_self_test.router,
        prefix="/api/v1/admin/self-test",
        tags=["admin-self-test"],
    )
    # ── phase17-004 — admin contracts overview ──────────────────────────────
    app.include_router(
        contracts_admin.router,
        prefix="/api/v1/admin/contracts",
        tags=["admin-contracts"],
    )
    # ── phase18-001/002 — public pricing + case studies ────────────────────
    app.include_router(
        public_pricing.router,
        prefix="",
        tags=["public-marketing"],
    )
    # ── phase18-003 — referral attribution admin ───────────────────────────
    app.include_router(
        referrals_admin.router,
        prefix="/api/v1/admin/referrals",
        tags=["admin-referrals"],
    )
    # ── phase19-003 — inbound email webhook ────────────────────────────────
    app.include_router(
        webhooks_inbound.router,
        prefix="/api/v1/webhooks",
        tags=["webhooks-inbound"],
    )
    # ── phase19-004 — inbox admin ──────────────────────────────────────────
    app.include_router(
        inbox_admin.router,
        prefix="/api/v1/admin/inbound-emails",
        tags=["admin-inbox"],
    )
    # ── phase20-003 — LinkedIn drafts admin ────────────────────────────────
    app.include_router(
        linkedin_admin.router,
        prefix="/api/v1/admin/linkedin-drafts",
        tags=["admin-linkedin"],
    )
    app.include_router(approvals.router, prefix="/api/v1/approvals", tags=["approvals"])
    app.include_router(content_approvals.router, prefix="/api/v1/approvals", tags=["content-approvals"])
    app.include_router(proposals.router, prefix="/api/v1/proposals", tags=["proposals"])
    app.include_router(reports.router,   prefix="/api/v1/reports",   tags=["reports"])
    app.include_router(agents.router,    prefix="/api/v1/agents",    tags=["agents"])
    app.include_router(portal_router,    prefix="/api/v1/portal",    tags=["portal"])
    app.include_router(reports_admin.router, prefix="/api/v1/admin", tags=["admin-reports"])
    app.include_router(
        known_problems.router,
        prefix="/api/v1/known-problems",
        tags=["known-problems"],
    )
    app.include_router(
        playbooks.router,
        prefix="/api/v1/playbooks",
        tags=["playbooks"],
    )
    app.include_router(
        portal_files_admin.router,
        prefix="/api/v1/admin/files",
        tags=["admin-portal-files"],
    )
    # admin_dashboard routes are already fully-qualified (/admin, /api/v1/survey/nps)
    app.include_router(admin_dashboard.router, tags=["admin-dashboard"])
    app.include_router(
        deal_admin.router,
        prefix="/api/v1/admin/deals",
        tags=["admin-deals"],
    )
    app.include_router(
        invoices_admin.router,
        prefix="/api/v1/admin/invoices",
        tags=["admin-invoices"],
    )
    app.include_router(
        invoice_generator_admin.router,
        prefix="/api/v1/admin/generated-invoices",
        tags=["admin-generated-invoices"],
    )
    app.include_router(
        social_media.router,
        prefix="/api/v1/social-media",
        tags=["social-media"],
    )
    app.include_router(
        social_media_admin.router,
        prefix="/api/v1/admin/social-media",
        tags=["admin-social-media"],
    )
    app.include_router(
        prospecting_admin.router,
        prefix="/api/v1/admin/prospecting",
        tags=["admin-prospecting"],
    )
    app.include_router(
        messages_admin.router,
        prefix="/api/v1/admin/messages",
        tags=["admin-messages"],
    )
    app.include_router(
        notes_admin.router,
        prefix="/api/v1/admin/projects",
        tags=["admin-notes"],
    )
    app.include_router(
        website_deploy_admin.router,
        prefix="/api/v1/admin/website-deploy",
        tags=["admin-website-deploy"],
    )
    app.include_router(
        translation_sync.router,
        prefix="/api/v1/admin/translation-sync",
        tags=["admin-translation-sync"],
    )
    app.include_router(
        translation_admin.router,
        prefix="/api/v1/admin/translation",
        tags=["admin-translation"],
    )
    app.include_router(
        seo_content_admin.router,
        prefix="/api/v1/admin/seo-content",
        tags=["admin-seo-content"],
    )
    app.include_router(
        portal_clients_admin.router,
        prefix="/api/v1/admin/portal/clients",
        tags=["admin-portal-clients"],
    )
    app.include_router(
        portal_projects_admin.router,
        prefix="/api/v1/admin/portal/projects",
        tags=["admin-portal-projects"],
    )
    app.include_router(
        portal_invoices_admin.router,
        prefix="/api/v1/admin/portal/invoices",
        tags=["admin-portal-invoices"],
    )
    # ── Freelance platform pipeline (Phase 5) ────────────────────────────────
    app.include_router(
        freelance_admin.router,
        prefix="/api/v1",
        tags=["admin-freelance"],
    )
    app.include_router(
        vapi_webhook.router,
        prefix="/api/v1",
        tags=["vapi-webhook"],
    )
    # ── Division coordinators ─────────────────────────────────────────────────
    app.include_router(
        sales_division_admin.router,
        prefix="/api/v1/admin/sales-division",
        tags=["admin-sales-division"],
    )
    app.include_router(
        engineering_division_admin.router,
        prefix="/api/v1/admin/engineering-division",
        tags=["admin-engineering-division"],
    )
    app.include_router(
        design_division_admin.router,
        prefix="/api/v1/admin/design-division",
        tags=["admin-design-division"],
    )
    app.include_router(
        client_intelligence_admin.router,
        prefix="/api/v1/admin/client-intelligence",
        tags=["admin-client-intelligence"],
    )
    app.include_router(
        phase7_admin.router,
        prefix="/api/v1/admin/phase7",
        tags=["admin-phase7"],
    )

    # ── n8n + cron trigger surface (replaces Celery beat) ─────────────────────
    app.include_router(
        beat_trigger.router,
        prefix="/api/v1/admin/trigger",
        tags=["beat-trigger"],
        dependencies=[],   # auth handled inside the router via Depends(verify_api_key)
    )

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok", "service": "loki-agents"}

    # ── Global exception handler ──────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception):
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error. Please contact support."},
        )

    return app


app = create_app()
