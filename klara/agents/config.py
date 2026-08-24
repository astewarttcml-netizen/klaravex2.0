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

    # ── Reply-aware suppression (phase19-006) ─────────────────────────────────
    # When True, an inbound reply from a prospect cancels any of that
    # prospect's pending/approved future OutreachSequence steps and
    # auto-rejects their gating ApprovalRequest. Default True — corrective
    # behaviour. Set LOKI_REPLY_SUPPRESSION=false in .env to keep the
    # old behaviour where replied prospects only stop getting NEW steps
    # (via eligible_for_followup) but already-queued steps linger.
    loki_reply_suppression: bool = True

    allowed_origins: List[str] = ["https://klaravex.de", "https://www.klaravex.de", "https://klaravex.eu"]
    trusted_hosts: List[str] = ["api.klaravex.de", "gateway.klaravex.de", "localhost", "127.0.0.1"]

    @field_validator("allowed_origins", "trusted_hosts", mode="before")
    @classmethod
    def parse_string_list(cls, v):
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

    # ── Brand identity (multi-brand deployments) ──────────────────────────────
    # When brand_intake_prompt_override is set, ChatIntakeAgent uses it as the
    # full system prompt instead of the default Klaravex prompt.
    db_schema: str = ""

    brand_name: str = "Klaravex"
    brand_intake_prompt_override: str = ""
    brand_faq_knowledge_override: str = ""
    support_contact_email: str = "hello@klaravex.de"
    support_mailbox: str = "support@klaravex.de"

    # ── GDPR ──────────────────────────────────────────────────────────────────
    gdpr_data_retention_days: int = 730
    gdpr_anonymize_after_days: int = 365

    # ── Client Portal ─────────────────────────────────────────────────────────
    # JWT expiry for portal client sessions (hours).
    portal_jwt_expire_hours: int = 8
    # Microsoft Graph API — transactional email
    ms_graph_tenant_id: str = ""
    ms_graph_client_id: str = ""
    ms_graph_client_secret: str = ""
    ms_graph_sender_email: str = "onboarding@klaravex.de"
    ms_graph_sender_name: str = "Anthony Stewart"

    portal_magic_link_expire_minutes: int = 30
    portal_base_url: str = "https://api.klaravex.de/client-portal"

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
    stripe_success_url: str = "https://api.klaravex.de/client-portal/invoice.html?payment=success&invoice_id={INVOICE_ID}"
    stripe_cancel_url: str = "https://api.klaravex.de/client-portal/invoice.html?payment=cancelled&invoice_id={INVOICE_ID}"

    # ── Resend (cold outreach only) ───────────────────────────────────────────
    resend_api_key: str = ""
    # Transactional sender — noreply@klaravex.de via MS Graph (see below).
    transactional_from_email: str = "noreply@klaravex.de"
    transactional_from_name: str = "Klaravex"
    # Cold outreach sender — outreach.klaravex.de subdomain via Resend.
    # Keeps cold email reputation completely separate from the main domain.
    outreach_from_email: str = "hello@outreach.klaravex.de"
    outreach_from_name: str = "Klaravex"
    # Reply-To routes prospect replies into a real mailbox instead of the
    # outreach subdomain. Matches the in-body signature.
    outreach_reply_to: str = "anthony@klaravex.de"

    # ── Smartlead cold-outreach transport ────────────────────────────────────
    # Switches the prospecting_outreach.send dispatch path. "resend" keeps the
    # existing Resend API send. "smartlead" routes through Smartlead's campaign
    # queue using the M365 OAuth-connected mailbox. Default stays "resend"
    # until the Smartlead mailbox finishes its 14-21 day warmup.
    outreach_transport: str = "resend"
    smartlead_api_key: str = ""
    smartlead_api_base: str = "https://server.smartlead.ai/api/v1"
    # Master campaign that Klara AI adds every drafted prospect to. The campaign
    # template uses {{personalized_body}} as the body variable so each lead
    # carries its own Claude-drafted body. Captured at campaign creation
    # time and pinned via env — never code-discovered (single source of truth).
    smartlead_master_campaign_id: int = 0
    # Webhook secret used to verify inbound POSTs from Smartlead. Generated
    # when Klara AI programmatically registers the webhook with Smartlead.
    smartlead_webhook_secret: str = ""

    # ── Higgsfield AI (image generation for social media posts) ──────────────
    # API key from https://app.higgsfield.ai — Settings → API Keys.
    # soul_id: the Soul character used for all AI-generated social images.
    # Default soul_id is Anthony's "IT Guy" character (Soul V2).
    # instagram_image_aspect: Higgsfield aspect ratio string for IG feed posts
    #   (4:5 portrait recommended — 1080×1350 px).
    higgsfield_api_key: str = ""
    higgsfield_soul_id: str = "ec44ead2-ecbd-4726-aa2a-4d6fe45c4822"
    higgsfield_instagram_aspect: str = "4:5"
    # Higgsfield model used for static social images. soul_cinematic gives
    # cinema-grade rendering; soul_2 / soul_v2 is faster / UGC-style.
    higgsfield_image_model: str = "soul_cinematic"

    # ── Apollo / outbound prospecting (Phase 4.5) ────────────────────────────
    # Set APOLLO_API_KEY to a real key before enabling the prospecting pipeline.
    # All fields default to safe no-op values so startup never fails on missing creds.
    apollo_api_key: str = ""
    prospecting_daily_limit: int = 5          # hard cap; 0 = pipeline disabled
    prospecting_schedule: str = "0 8 * * 1-5" # Celery beat cron; weekdays 08:00
    apollo_min_employees: int = 10
    apollo_max_employees: int = 200
    apollo_location: str = "Berlin, Germany"
    # DACH targeting — pipe-separated locations sent to Apollo person_locations.
    # Country-level keeps Apollo credit usage low; refine to city,country pairs
    # if conversion needs more geographic precision (e.g. "Berlin, Germany|Munich, Germany").
    apollo_locations: str = "Germany|Austria|Switzerland"

    # Apollo organization_ids — pipe-separated 24-char Apollo org IDs.
    # When set, lead_prospector restricts the people search to these specific
    # companies (precise targeting). When empty, falls back to broad
    # title+location search. See loki-vault/knowledge/apollo-target-orgs-*.md
    # for current curated lists.
    apollo_org_ids: str = ""

    # Hunter.io email verification — gates prospecting_outreach.send at approval time.
    # Budget: ~1000 verifications/year on the Data plan. Empty string = fail-open.
    hunter_api_key: str = ""

    # Klara AI vault — git-backed Obsidian vault, kept fresh by /etc/cron.d/loki-vault-pull.
    # Source of truth for shared agent memory. See app/services/notes.py for read API.
    vault_path: str = "/opt/loki-vault"

    # GitHub API — used by RARV agents to write vault files without needing
    # filesystem write access inside the container.
    # Fine-grained PAT: repo=loki-vault, permission=Contents(read+write).
    github_vault_token: str = ""
    github_vault_repo: str = "astewarttcml-netizen/loki-vault"
    github_vault_branch: str = "main"

    # Booking / calendar CTA — injected into cold outreach email body
    booking_url: str = "https://calendly.com/klaravex/45-minute-meeting"

    # ── Freelance platform pipeline ───────────────────────────────────────────
    # Freelancer.com OAuth2 access token — generate at:
    # https://accounts.freelancer.com/settings/develop
    freelancer_access_token: str = ""

    # Freelancermap.com — DACH IT freelance platform. Login-based (no public
    # API). Used by freelance_scout once Freelancermap platform integration
    # lands. Credentials stored here for future use; agent integration is
    # tracked separately.
    freelancermap_email: str = ""
    freelancermap_password: str = ""
    # Freelancermap.de session-cookie auth (no public API). Cookie + IDs
    # captured by logging in via Playwright. Session lifetime ~7 days
    # (REMEMBERME cookie). Renew via /tmp/.creds/fm_login3.py when expired.
    freelancermap_session_cookie: str = ""
    freelancermap_user_id: str = ""              # numeric, e.g. "740455"
    freelancermap_profile_id: str = ""           # numeric, e.g. "340534"

    # Guard rails for autonomous bidding (P2 full_autonomy)
    freelance_min_budget_eur: float = 300.0    # skip projects below this EUR equivalent
    freelance_max_bids_per_day: int = 5         # hard daily cap across all platforms
    freelance_min_fit_score: int = 55           # 0–100 — projects below this are ignored

    # Base URL for admin dashboard links in notification emails
    app_base_url: str = "https://api.klaravex.de"

    # ── Atera PSA/RMM (consumer support pipeline) ────────────────────────────
    # API key from: Atera Admin → API → REST API tab (JWT Bearer token).
    # Leave empty to disable consumer ticket creation (pipeline still runs;
    # atera_ticket_creator returns a graceful fallback message instead).
    atera_api_key: str = ""

    # ── Vapi.ai (AI voice calls) ──────────────────────────────────────────────
    # Sign up at https://vapi.ai — API key from dashboard → Keys
    vapi_api_key: str = ""
    # Phone number ID — purchase an outbound number in Vapi dashboard → Phone Numbers
    vapi_phone_number_id: str = ""
    # Pre-configured Vapi assistant ID — create once in Vapi dashboard → Assistants.
    # If empty, VoiceCallAgent defines the assistant inline on each call (heavier payload).
    vapi_assistant_id: str = ""
    # Dedicated troubleshooting assistant for post-payment consumer callbacks.
    vapi_troubleshoot_assistant_id: str = ""
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

    # Instagram Business Account — Graph API v19.0 two-step publish.
    # instagram_user_id: numeric IG Business Account user ID (from GET /me on Graph API).
    # instagram_access_token: long-lived Page Access Token with instagram_basic +
    #   instagram_content_publish scopes.  Linked Facebook Page must be admin of the IG account.
    # Static images must be publicly reachable (served from /static/ig/ via nginx).
    instagram_user_id: str = ""
    instagram_access_token: str = ""
    # ISO date (YYYY-MM-DD) — used by social_report.py to warn 14 days before expiry.
    instagram_access_token_expires: str = ""
    # Publicly reachable base URL where IG images are served.
    # Nginx serves /opt/loki-agents/static/ig/ at this path.
    instagram_image_base_url: str = "https://api.klaravex.de/static/ig"

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
    # Reddit — Playwright only (Reddit API requires app registration + OAuth which
    # gates posting behind subreddit karma anyway). Posts to the user's profile.
    reddit_username: str = ""
    reddit_password: str = ""
    reddit_default_subreddit: str = ""                  # blank → post to /user/<username> profile
    facebook_email: str = ""
    facebook_password: str = ""
    facebook_page_name: str = "Klaravex"
    xing_email: str = ""
    xing_password: str = ""
    # YouTube Community posts — Playwright only. Requires:
    #   1. Google account creds
    #   2. The channel handle (e.g. "Klaravex")
    #   3. 500+ subscribers on the channel (YouTube gate for community posts)
    youtube_email: str = ""
    youtube_password: str = ""
    youtube_channel_handle: str = ""                    # e.g. "Klaravex"
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
    def ms_graph_configured(self) -> bool:
        """True only when all three MS Graph credentials are set and not placeholders."""
        return bool(
            self.ms_graph_tenant_id
            and not self._is_placeholder(self.ms_graph_tenant_id)
            and self.ms_graph_client_id
            and not self._is_placeholder(self.ms_graph_client_id)
            and self.ms_graph_client_secret
            and not self._is_placeholder(self.ms_graph_client_secret)
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
    def hunter_configured(self) -> bool:
        """True only when HUNTER_API_KEY is set and not a REPLACE_ME placeholder."""
        return bool(self.hunter_api_key and not self._is_placeholder(self.hunter_api_key))

    @property
    def higgsfield_configured(self) -> bool:
        """True only when HIGGSFIELD_API_KEY is set and not a REPLACE_ME placeholder."""
        return bool(
            self.higgsfield_api_key
            and not self._is_placeholder(self.higgsfield_api_key)
        )

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
            "tiktok": False,  # TikTok API not yet implemented
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
    def apollo_locations_list(self) -> List[str]:
        """
        DACH locations sent to Apollo person_locations filter.

        Reads APOLLO_LOCATIONS env var (pipe-separated, e.g. "Germany|Austria|Switzerland").
        Falls back to apollo_location for backward compatibility with the
        single-location config from the Berlin-only days.
        """
        raw = (self.apollo_locations or self.apollo_location or "Germany").strip()
        return [loc.strip() for loc in raw.split("|") if loc.strip()]

    @property
    def apollo_org_ids_list(self) -> List[str]:
        """
        Specific Apollo organization IDs to restrict the people search to.

        Reads APOLLO_ORG_IDS env var (pipe-separated 24-char Apollo IDs).
        Empty list => no org_ids filter (broad title+location search).
        Curated lists live in loki-vault/knowledge/apollo-target-orgs-*.md.
        """
        raw = (self.apollo_org_ids or "").strip()
        return [oid.strip() for oid in raw.split("|") if oid.strip()]

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

    # ── Secret redaction ───────────────────────────────────────────────────────
    # Sensitive fields are typed as plain `str` so every consumer can use them
    # without `.get_secret_value()` boilerplate. The trade-off is that
    # `repr(settings)` exposes the raw values — which is what Rich/structlog
    # dumps into worker tracebacks every time an exception fires (see the
    # cef0f7c9 / 4cbc58c3 social publish failures on 2026-05-29 that leaked
    # `facebook_password='38KE...'` to logs).
    #
    # Overriding __repr__ here scrubs any field whose name contains one of
    # the patterns below, while leaving the underlying attribute access
    # unchanged. structlog's Rich exception formatter calls repr() on locals,
    # so this closes the leak at its actual surface.
    _SECRET_FIELD_PATTERNS: tuple[str, ...] = (
        "_password", "_secret", "_token", "_key", "_cookie",
    )

    def _is_secret_field(self, name: str) -> bool:
        lower = name.lower()
        return any(p in lower for p in self._SECRET_FIELD_PATTERNS)

    def __repr__(self) -> str:
        parts: list[str] = []
        for name in type(self).model_fields:
            value = getattr(self, name, None)
            if self._is_secret_field(name) and value:
                parts.append(f"{name}=...REDACTED({len(str(value))} chars)")
            else:
                parts.append(f"{name}={value!r}")
        return f"Settings({', '.join(parts)})"

    __str__ = __repr__


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton — called via FastAPI Depends."""
    return Settings()
