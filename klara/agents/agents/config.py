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


class LokiMode(str, Enum):
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
    loki_mode: LokiMode = LokiMode.shadow   # default: shadow (9.2 observe-only)

    allowed_origins: List[str] = ["https://klaravex.de"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",")]
        return v

    # ── Anthropic ─────────────────────────────────────────────────────────────
    anthropic_api_key: str  # required
    anthropic_model: str = "claude-opus-4-6"
    anthropic_max_tokens: int = 4096

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str  # required  e.g. postgresql+asyncpg://...

    # ── Redis / Celery ────────────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # ── WordPress ─────────────────────────────────────────────────────────────
    wp_webhook_secret: str  # required
    wp_site_url: str = "https://klaravex.de"
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
    smtp_from_email: str = "noreply@klaravex.de"
    smtp_from_name: str = "Klaravex"

    # ── Approvals ─────────────────────────────────────────────────────────────
    approval_notify_email: str = "admin@klaravex.de"
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
    stripe_success_url: str = "https://klaravex.de/portal?payment=success"
    stripe_cancel_url: str = "https://klaravex.de/portal?payment=cancelled"

    # ── Resend (transactional + outreach email) ───────────────────────────────
    resend_api_key: str = ""
    # Transactional sender — used only for confirmations, receipts, portal notices
    transactional_from_email: str = "noreply@klaravex.de"
    transactional_from_name: str = "Klaravex"
    # Cold outreach sender — separate subdomain to protect main domain reputation
    outreach_from_email: str = "hello@outreach.klaravex.de"
    outreach_from_name: str = "Klaravex"

    # ── Apollo / outbound prospecting (Phase 4.5) ────────────────────────────
    # Set APOLLO_API_KEY to a real key before enabling the prospecting pipeline.
    # All fields default to safe no-op values so startup never fails on missing creds.
    apollo_api_key: str = ""
    prospecting_daily_limit: int = 5          # hard cap; 0 = pipeline disabled
    prospecting_schedule: str = "0 8 * * 1-5" # Celery beat cron; weekdays 08:00
    apollo_min_employees: int = 10
    apollo_max_employees: int = 200
    apollo_location: str = "Berlin, Germany"

    # Booking / calendar CTA — injected into cold outreach email body
    booking_url: str = "https://calendly.com/klaravex/45-minute-meeting"

    # ── Freelance platform pipeline ───────────────────────────────────────────
    # Freelancer.com OAuth2 access token — generate at:
    # https://accounts.freelancer.com/settings/develop
    freelancer_access_token: str = ""

    # Guard rails for autonomous bidding (P2 full_autonomy)
    freelance_min_budget_eur: float = 300.0    # skip projects below this EUR equivalent
    freelance_max_bids_per_day: int = 5         # hard daily cap across all platforms
    freelance_min_fit_score: int = 55           # 0–100 — projects below this are ignored

    # Base URL for admin dashboard links in notification emails
    app_base_url: str = "https://api.klaravex.de"

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
    # Calendly webhook signing key — set in Calendly developer dashboard.
    # If empty, signature validation is skipped (dev/test only).
    calendly_webhook_signing_key: str = ""

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

    # XING — OAuth 1.0a via XING Developer Hub.
    # Required: status_message.write permission.
    xing_consumer_key: str = ""
    xing_consumer_secret: str = ""
    xing_access_token: str = ""
    xing_access_token_secret: str = ""

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
    xing_email: str = ""
    xing_password: str = ""
    instagram_user_id: str = ""
    instagram_access_token: str = ""
    reddit_username: str = ""
    reddit_password: str = ""
    reddit_default_subreddit: str = ""
    youtube_email: str = ""
    youtube_password: str = ""
    youtube_channel_handle: str = ""
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
            "xing": (
                ok(
                    self.xing_consumer_key, self.xing_consumer_secret,
                    self.xing_access_token, self.xing_access_token_secret,
                )
                or ok(self.xing_email, self.xing_password)
            ),
            "facebook": (
                ok(self.facebook_page_id, self.facebook_page_access_token)
                or ok(self.facebook_email, self.facebook_password)
            ),
            "instagram": ok(self.instagram_user_id, self.instagram_access_token),
            "reddit": ok(self.reddit_username, self.reddit_password),
            "youtube": ok(self.youtube_email, self.youtube_password),
            "tiktok": False,
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

        Covers IT decision-makers at SMBs in Berlin (10–200 employees).
        Weighted toward IT Manager / Head of IT who actually have the budget
        problem we solve, plus C-suite at the smallest firms.
        """
        return [
            "IT Manager",
            "IT Leiter",           # German equivalent — Apollo indexes both
            "Head of IT",
            "IT Director",
            "IT Administrator",
            "System Administrator",
            "Network Administrator",
            "Infrastructure Manager",
            "CTO",
            "Chief Technology Officer",
            "Chief Information Officer",
            "CIO",
            "IT Operations Manager",
            "Technology Manager",
            "IT Project Manager",
            "Managing Director",   # Geschäftsführer at small firms often owns IT
            "Geschäftsführer",
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton — called via FastAPI Depends."""
    return Settings()
