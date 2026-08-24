"""
app/config.py
─────────────
Central settings loaded from environment / .env file.
All secrets come from environment variables — never hardcoded.
"""
from enum import Enum
from functools import lru_cache
from typing import List

from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class KlaravexMode(str, Enum):
    shadow             = "shadow"              # 9.2: observe only, no execution
    assisted           = "assisted"            # 9.3: drafts and internal updates only
    selective_autonomy = "selective_autonomy"  # 9.4: low-risk auto, high-risk gated
    full_autonomy      = "full_autonomy"       # 9.5: all P1/P2 auto-execute; P3+ still approval-gated


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: str = "production"
    app_debug: bool = False
    app_secret_key: str  # required — no default; sourced from APP_SECRET_KEY env var
    show_docs: bool = False  # set SHOW_DOCS=true to enable /docs via SSH tunnel

    # ── Rollout mode ──────────────────────────────────────────────────────────
    klaravex_mode: KlaravexMode = KlaravexMode.shadow   # default: shadow (9.2 observe-only)

    allowed_origins: List[str] = ["https://klaravex.com"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",")]
        return v

    # ── Anthropic ─────────────────────────────────────────────────────────────
    anthropic_api_key: str  # required
    anthropic_base_url: str = ""  # empty = default api.anthropic.com; set to proxy URL for local models
    anthropic_model: str = "smart"  # 2026-08-21: LiteLLM dispatch group (migrated off fcc-server)
    anthropic_max_tokens: int = 4096

    # ── LLM proxy (LiteLLM, rig-local :8000; Anthropic /v1/messages served) ───
    litellm_base_url: str = "http://host.docker.internal:8000"

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str  # required  e.g. postgresql+asyncpg://...

    # ── Redis / Celery ────────────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # ── WordPress ─────────────────────────────────────────────────────────────
    wp_webhook_secret: str  # required
    wp_site_url: str = "https://klaravex.com"
    # WP Application Password credentials for the WebsiteDeployAgent (P3).
    # Generate via: WP Admin → Users → Profile → Application Passwords.
    # Leave empty in dev to disable WP API calls gracefully.
    wp_app_username: str = ""
    wp_app_password: str = ""

    # ── SMTP (outreach email) ─────────────────────────────────────────────────
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "no-reply@klaravex.com"
    smtp_from_name: str = "Klaravex"

    # ── Approvals ─────────────────────────────────────────────────────────────
    approval_notify_email: str = "astewart@klaravex.com"
    approval_timeout_seconds: int = 86400

    # ── GDPR ──────────────────────────────────────────────────────────────────
    gdpr_data_retention_days: int = 730
    gdpr_anonymize_after_days: int = 365

    # ── Client Portal ─────────────────────────────────────────────────────────
    # JWT expiry for portal client sessions (hours).
    portal_jwt_expire_hours: int = 8

    # Base directory where client files are stored on the server.
    # Must be an absolute path outside the web root.
    # Example: /var/loki/client_files
    portal_files_base_path: str = "/var/loki/client_files"

    # ── Stripe ────────────────────────────────────────────────────────────────
    # stripe_secret_key: required in production; starts with sk_live_ or sk_test_
    # stripe_webhook_secret: required; starts with whsec_
    # stripe_publishable_key: sent to frontend; starts with pk_
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_publishable_key: str = ""
    # URLs Stripe redirects to after checkout (must be absolute, HTTPS in production)
    stripe_success_url: str = "https://klaravex.com/portal?payment=success"
    stripe_cancel_url: str = "https://klaravex.com/portal?payment=cancelled"

    # ── Resend (transactional + outreach email) ───────────────────────────────
    resend_api_key: str = ""
    # Transactional sender — used only for confirmations, receipts, portal notices
    transactional_from_email: str = "no-reply@klaravex.com"
    transactional_from_name: str = "Klaravex"
    # Cold outreach sender — separate subdomain to protect main domain reputation
    outreach_from_email: str = "anthony@outreach.klaravex.com"
    outreach_from_name: str = "Klaravex"

    # ── Apollo / outbound prospecting (Phase 4.5) ────────────────────────────
    # Set APOLLO_API_KEY to a real key before enabling the prospecting pipeline.
    # All fields default to safe no-op values so startup never fails on missing creds.
    apollo_api_key: str = ""
    prospecting_daily_limit: int = 5          # hard cap; 0 = pipeline disabled
    prospecting_schedule: str = "0 8 * * 1-5" # Celery beat cron; weekdays 08:00
    apollo_min_employees: int = 10
    apollo_max_employees: int = 200
    apollo_location: str = "United States"

    # Booking / calendar CTA — injected into cold outreach email body.
    # iter-69 (2026-07-14): set CALENDLY_BOOKING_URL env to override. Default
    # is klaravex.com-branded. The legacy itexperts URL was a pre-brand-split
    # default that should NOT appear in klaravex.com outreach. Anthony must
    # provision an actual klaravex-branded Calendly (or set the env var to
    # whatever booking tool klaravex.com uses).
    booking_url: str = "https://calendly.com/klaravex/30min"

    # ── Freelance platform pipeline ───────────────────────────────────────────
    # Freelancer.com OAuth2 access token — generate at:
    # https://accounts.freelancer.com/settings/develop
    freelancer_access_token: str = ""

    # Guard rails for autonomous bidding (P2 full_autonomy)
    freelance_min_budget_eur: float = 300.0    # skip projects below this EUR equivalent
    freelance_max_bids_per_day: int = 5         # hard daily cap across all platforms
    freelance_min_fit_score: int = 55           # 0–100 — projects below this are ignored

    # Base URL for admin dashboard links in notification emails
    app_base_url: str = "https://api.klaravex.com"

    # ── Vapi.ai (AI voice calls) ──────────────────────────────────────────────
    # Sign up at https://vapi.ai — API key from dashboard → Keys
    vapi_api_key: str = ""
    # Phone number ID — purchase an outbound number in Vapi dashboard → Phone Numbers
    vapi_phone_number_id: str = ""
    # Pre-configured Vapi assistant ID — create once in Vapi dashboard → Assistants.
    # If empty, VoiceCallAgent defines the assistant inline on each call (heavier payload).
    vapi_assistant_id: str = ""
    # Webhook HMAC secret — set in Vapi dashboard → Webhooks → Signing Secret
    vapi_webhook_secret: str = ""

    # ── Notion (CRM leads database) ───────────────────────────────────────────
    notion_api_key: str = ""
    notion_leads_db_id: str = ""

    # ── Observability ─────────────────────────────────────────────────────────
    sentry_dsn: str = ""

    # ── Social Media Publishing ───────────────────────────────────────────────
    # All fields default to "" so startup never fails when credentials are absent.
    # social_configured property (below) drives whether the publish path is live.

    # LinkedIn Company Page — OAuth 2.0 Bearer token.
    # Generate at: LinkedIn Developer Portal → OAuth 2.0 → w_organization_social scope.
    # org_id: numeric ID of the company page (visible in the page admin URL).
    linkedin_company_token: str = ""
    linkedin_company_org_id: str = ""

    # LinkedIn Personal Profile — OAuth 2.0 Bearer token.
    # Requires w_member_social scope.  personal_urn must be full URN:
    #   urn:li:person:{id}  — find id via GET https://api.linkedin.com/v2/me
    linkedin_personal_token: str = ""
    linkedin_personal_urn: str = ""
    # ISO date (YYYY-MM-DD) when the personal OAuth token expires — used by
    # social_report.py to warn 14 days before expiry.
    linkedin_personal_token_expires: str = ""

    # Twitter / X — OAuth 1.0a (User Context) via Twitter Developer Portal.
    # Required scopes: tweet.write, tweet.read, users.read.
    # api_key / api_secret: from app Keys & Tokens → Consumer Keys
    # access_token / access_token_secret: from app Keys & Tokens → Access Token & Secret
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_access_token: str = ""
    twitter_access_token_secret: str = ""

    # Facebook Page — Page Access Token (never-expiring via System User recommended).
    # page_id: numeric Facebook page ID (found in page About → Page ID).
    # page_access_token: generate via Graph API Explorer with pages_manage_posts scope.
    facebook_page_id: str = ""
    facebook_page_access_token: str = ""

    # ── Social Media — Playwright browser publisher (email/password fallback) ──
    # Used when OAuth/API tokens above are not set.  Playwright launches headless
    # Chromium on the Hetzner server, logs in with these credentials, posts via the
    # web UI, and saves session cookies to social_sessions_dir for reuse.
    # Set only the platforms you want to publish to — unset platforms are skipped.
    linkedin_email: str = ""
    linkedin_password: str = ""
    linkedin_company_name: str = "Klaravex"   # used for company page navigation
    twitter_email: str = ""
    twitter_password: str = ""
    twitter_username: str = ""                          # @handle without @, used for session nav
    facebook_email: str = ""
    facebook_password: str = ""
    facebook_page_name: str = "Klaravex"
    social_sessions_dir: str = "/app/data/sessions"    # where Playwright stores cookies

    # ── Placeholder sentinel ──────────────────────────────────────────────────
    @staticmethod
    def _is_placeholder(value: str) -> bool:
        """Return True if the value is an unset REPLACE_ME stub from .env.example.

        Guards against the common mistake of deploying with template placeholders
        still in place. A non-empty string that starts with REPLACE_ME_ is treated
        as unconfigured rather than as a real credential.
        """
        return value.startswith("REPLACE_ME")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def stripe_configured(self) -> bool:
        """True only when all required Stripe secrets are present and not placeholders."""
        return bool(
            self.stripe_secret_key
            and not self._is_placeholder(self.stripe_secret_key)
            and self.stripe_webhook_secret
            and not self._is_placeholder(self.stripe_webhook_secret)
            and self.stripe_publishable_key
            and not self._is_placeholder(self.stripe_publishable_key)
        )

    @property
    def resend_configured(self) -> bool:
        """True only when RESEND_API_KEY is set and not a REPLACE_ME placeholder."""
        return bool(self.resend_api_key and not self._is_placeholder(self.resend_api_key))

    @property
    def apollo_configured(self) -> bool:
        """True only when APOLLO_API_KEY is set and not a REPLACE_ME placeholder."""
        return bool(self.apollo_api_key and not self._is_placeholder(self.apollo_api_key))

    @property
    def social_configured(self) -> dict[str, bool]:
        """
        Per-platform readiness flags — True when required credentials are present
        and not REPLACE_ME placeholders.  The publish handler uses this to skip
        unconfigured platforms rather than attempting and failing.

        Checks API tokens first (preferred), then Playwright email/password (fallback).

        Example:
            { "linkedin_company": True, "twitter": False, ... }
        """
        def ok(*vals: str) -> bool:
            return all(v and not self._is_placeholder(v) for v in vals)

        # API token paths
        li_creds = ok(self.linkedin_email, self.linkedin_password)
        return {
            "linkedin_company": (
                ok(self.linkedin_company_token, self.linkedin_company_org_id)
                or li_creds
            ),
            "linkedin_personal": (
                ok(self.linkedin_personal_token, self.linkedin_personal_urn)
                or li_creds
            ),
            "twitter": (
                ok(
                    self.twitter_api_key, self.twitter_api_secret,
                    self.twitter_access_token, self.twitter_access_token_secret,
                )
                or ok(self.twitter_email, self.twitter_password)
            ),
            "facebook": (
                ok(self.facebook_page_id, self.facebook_page_access_token)
                or ok(self.facebook_email, self.facebook_password)
            ),
        }

    @property
    def linkedin_pw_configured(self) -> bool:
        """True when LinkedIn Playwright credentials are set."""
        return bool(
            self.linkedin_email
            and self.linkedin_password
            and not self._is_placeholder(self.linkedin_email)
            and not self._is_placeholder(self.linkedin_password)
        )

    @property
    def apollo_titles_list(self) -> List[str]:
        """
        ICP target job titles sent to Apollo's person_titles filter.

        iter-70 (2026-07-14): flipped from IT-role bias to vertical-decision-
        makers. Klaravex ICP is 5-50 seat professional services firms — law,
        accounting, medical/dental, consulting — where IT budget is owned by
        the Managing Partner / Practice Administrator / Firm Admin, NOT a
        dedicated IT staffer (those firms don't have one; that's the whole
        thesis). Prior title list was IT-role bias which pulled tech SaaS
        companies with dedicated IT staff — wrong ICP.

        Env override: APOLLO_TITLES (comma-separated) if set.
        """
        env = os.environ.get("APOLLO_TITLES", "").strip()
        if env:
            return [t.strip() for t in env.split(",") if t.strip()]
        return [
            # Law firm decision-makers
            "Managing Partner",
            "Firm Administrator",
            "Chief Operating Officer",
            "Director of Operations",
            # Accounting firm decision-makers
            "Partner",
            "Managing Director",
            # Medical / dental practice decision-makers
            "Practice Administrator",
            "Practice Manager",
            "Office Manager",
            "Physician Owner",
            "Dentist Owner",
            # Consulting firm decision-makers
            "Founder",
            "Owner",
            "President",
            # Mission-driven org decision-makers (foundations, hospitals,
            # legal aid, nonprofits, municipalities)
            "Executive Director",
            "Director of Development",
            "Development Director",
            "Chief Development Officer",
            "Program Director",
            "Chief Information Officer",
            "Director of Information Technology",
            "City Manager",
            "Town Administrator",
            "Chief Information Security Officer",
            "Director of Grants",
            "Grants Manager",
            # Small-firm generalist decision-makers
            "CEO",
            "Chief Executive Officer",
            "CFO",
            "Chief Financial Officer",
            "COO",
        ]

    @property
    def apollo_industries_list(self) -> List[str]:
        """
        iter-70 (2026-07-14): Apollo organization_industry_tag_ids filter.

        Env-driven via APOLLO_INDUSTRIES (comma-separated Apollo industry
        tag IDs — see apollo.io/api-documentation). Defaults to law +
        accounting + medical/dental practice + consulting.

        Apollo tag IDs commonly used for ICP:
          - Law Practice / Legal Services
          - Accounting
          - Medical Practice / Hospital & Health Care
          - Dental / Dentistry
          - Management Consulting / Professional Services
        """
        env = os.environ.get("APOLLO_INDUSTRIES", "").strip()
        if env:
            return [i.strip() for i in env.split(",") if i.strip()]
        # Default keyword tags (Apollo accepts free-text industry names too;
        # the API resolves to internal tag ids). Anthony can replace with
        # explicit tag IDs via APOLLO_INDUSTRIES env when needed.
        return [
            "law practice",
            "legal services",
            "accounting",
            "medical practice",
            "hospital & health care",
            "dentist",
            "management consulting",
            "non-profit organization management",
            "philanthropy",
            "civic & social organization",
            "government administration",
            "libraries",
            "museums and institutions",
            "higher education",
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton — called via FastAPI Depends."""
    return Settings()
