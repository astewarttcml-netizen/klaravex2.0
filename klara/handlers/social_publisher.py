"""
klaravex/infra/klara.handlers/social_publisher.py
─────────────────────────────────────────────────
Async social-media publishing service — Playwright fallback for platforms
where Klaravex does not have API tokens.

Ported from itexperts-berlin/loki-agents/app/services/social_publisher.py
on 2026-06-26.

Strategy per platform:
  1. API tokens configured  → use platform REST API   (preferred; see social_media.py)
  2. Email/password set     → use Playwright stealth browser (this file)
  3. Neither                → PublishResult(success=False, error="not_configured")

Klaravex adaptations from source:
  - structlog → stdlib logging
  - app.config.Settings → in-file _Settings shim that reads os.environ
  - app.utils.higgsfield_client → stubbed (we use mcp__higgsfield instead;
    Instagram image generation TODO; raise HiggsFieldError to keep call sites
    happy)

Required env vars (when using Playwright path):
  LINKEDIN_EMAIL / LINKEDIN_PASSWORD
  TWITTER_EMAIL / TWITTER_USERNAME / TWITTER_PASSWORD
  FACEBOOK_EMAIL / FACEBOOK_PASSWORD
  REDDIT_USERNAME / REDDIT_PASSWORD / REDDIT_DEFAULT_SUBREDDIT (optional)
  YOUTUBE_EMAIL / YOUTUBE_PASSWORD / YOUTUBE_CHANNEL_HANDLE (e.g. @klaravex)
  TIKTOK_EMAIL / TIKTOK_PASSWORD
  SOCIAL_SESSIONS_DIR (optional, default: /tmp/social_sessions)

Typical usage:
    from .social_publisher import publish_all, settings
    results = await publish_all(drafts, platforms, settings)
"""


import asyncio
import base64
import hashlib
import hmac
import logging
import os
import time
import urllib.parse
import uuid
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

log = logging.getLogger("klaravex.social_publisher")


# ── structlog shim — adapt structlog.get_logger().info(event, **kwargs) to
# stdlib logger.info("event %r", kwargs). Used by all platform functions.
class _StructLogShim:
    def __init__(self, base): self._log = base
    def info(self, event, **kw): self._log.info("%s %s", event, kw if kw else "")
    def warning(self, event, **kw): self._log.warning("%s %s", event, kw if kw else "")
    def error(self, event, **kw): self._log.error("%s %s", event, kw if kw else "")
    def exception(self, event, **kw): self._log.exception("%s %s", event, kw if kw else "")

logger = _StructLogShim(log)


# ── Settings shim — itexperts-berlin uses an attrs/pydantic Settings class;
# klaravex reads env directly. This shim exposes the same attribute interface
# so the original function bodies (_pw_publish_X(text, settings)) work unchanged.
class _Settings:
    @property
    def linkedin_email(self): return os.environ.get("LINKEDIN_EMAIL", "")
    @property
    def linkedin_password(self): return os.environ.get("LINKEDIN_PASSWORD", "")
    @property
    def linkedin_company_name(self): return os.environ.get("LINKEDIN_COMPANY_NAME", "klaravex")
    @property
    def linkedin_company_token(self): return os.environ.get("LINKEDIN_COMPANY_TOKEN", "")
    @property
    def linkedin_personal_token(self): return os.environ.get("LINKEDIN_PERSONAL_TOKEN", "")
    @property
    def linkedin_personal_urn(self): return os.environ.get("LINKEDIN_PERSONAL_URN", "")
    @property
    def twitter_email(self): return os.environ.get("TWITTER_EMAIL", "")
    @property
    def twitter_password(self): return os.environ.get("TWITTER_PASSWORD", "")
    @property
    def twitter_username(self): return os.environ.get("TWITTER_USERNAME", "")
    @property
    def twitter_api_key(self): return os.environ.get("TWITTER_API_KEY", "")
    @property
    def twitter_api_secret(self): return os.environ.get("TWITTER_API_SECRET", "")
    @property
    def twitter_access_token(self): return os.environ.get("TWITTER_ACCESS_TOKEN", "")
    @property
    def twitter_access_token_secret(self): return os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", "")
    @property
    def facebook_email(self): return os.environ.get("FACEBOOK_EMAIL", "")
    @property
    def facebook_password(self): return os.environ.get("FACEBOOK_PASSWORD", "")
    @property
    def facebook_page_id(self): return os.environ.get("FACEBOOK_PAGE_ID", "")
    @property
    def facebook_page_access_token(self): return os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN", "")
    @property
    def reddit_username(self): return os.environ.get("REDDIT_USERNAME", "")
    @property
    def reddit_password(self): return os.environ.get("REDDIT_PASSWORD", "")
    @property
    def reddit_default_subreddit(self): return os.environ.get("REDDIT_DEFAULT_SUBREDDIT", "klaravex")
    @property
    def youtube_email(self): return os.environ.get("YOUTUBE_EMAIL", "")
    @property
    def youtube_password(self): return os.environ.get("YOUTUBE_PASSWORD", "")
    @property
    def youtube_channel_handle(self): return os.environ.get("YOUTUBE_CHANNEL_HANDLE", "@klaravex")
    @property
    def tiktok_email(self): return os.environ.get("TIKTOK_EMAIL", "")
    @property
    def tiktok_password(self): return os.environ.get("TIKTOK_PASSWORD", "")
    @property
    def social_sessions_dir(self): return os.environ.get("SOCIAL_SESSIONS_DIR", "/tmp/social_sessions")

    def _is_placeholder(self, val) -> bool:
        """Return True if val is empty, None, or contains a placeholder sentinel."""
        if not val:
            return True
        lower = str(val).lower()
        return "placeholder" in lower or "xxx" in lower

    # Configured-checks — True only when BOTH the login email/username AND password
    # are set. The top-level publish_<platform>(text, settings) wrappers in this
    # file test these before invoking the Playwright login flow.
    @property
    def linkedin_pw_configured(self):
        return bool(self.linkedin_email and self.linkedin_password)
    @property
    def twitter_pw_configured(self):
        return bool(self.twitter_email and self.twitter_password)
    @property
    def facebook_pw_configured(self):
        return bool(self.facebook_email and self.facebook_password)
    @property
    def reddit_pw_configured(self):
        return bool(self.reddit_username and self.reddit_password)
    @property
    def youtube_pw_configured(self):
        return bool(self.youtube_email and self.youtube_password)
    @property
    def tiktok_pw_configured(self):
        return bool(self.tiktok_email and self.tiktok_password)
    @property
    def instagram_pw_configured(self):
        # Instagram uses Facebook Graph API + Higgsfield for image gen, not Playwright
        return False
    # Linkedin company URN/name needed by _pw_li_post_company
    @property
    def linkedin_company_urn(self):
        return os.environ.get("LINKEDIN_COMPANY_ORG_ID", "")

settings = _Settings()


# Higgsfield client — ported to klaravex/lib/higgsfield_client.py on
# 2026-06-26. Re-export HiggsFieldError + generate_instagram_image_from_caption
# so the original call sites further down keep working unchanged.
from .lib.higgsfield_client import (  # noqa: E402
    HiggsFieldError,
    generate_instagram_image_from_caption,
)


# ─────────────────────────────────────────────────────────────────────────────
# Result container
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PublishResult:
    platform: str
    success: bool
    post_id: str = ""
    post_url: str = ""
    error: str = ""
    raw: dict = field(default_factory=dict)

    def __str__(self) -> str:
        if self.success:
            return f"{self.platform}: OK  ({self.post_url or self.post_id})"
        return f"{self.platform}: FAIL  ({self.error})"


# ─────────────────────────────────────────────────────────────────────────────
# OAuth 1.0a helper (Twitter/X)
# ─────────────────────────────────────────────────────────────────────────────

def _oauth1_auth_header(
    method: str,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    token: str,
    token_secret: str,
    extra_params: dict | None = None,
) -> str:
    """
    Build an OAuth 1.0a Authorization header using HMAC-SHA1 (RFC 5849 §3.4).
    No third-party OAuth library required.
    """
    oauth_params: dict[str, str] = {
        "oauth_consumer_key":     consumer_key,
        "oauth_nonce":            uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp":        str(int(time.time())),
        "oauth_token":            token,
        "oauth_version":          "1.0",
    }

    all_params = {**oauth_params, **(extra_params or {})}

    def _pct(s: str) -> str:
        return urllib.parse.quote(str(s), safe="")

    param_string = "&".join(
        f"{_pct(k)}={_pct(v)}"
        for k, v in sorted(all_params.items())
    )

    parsed = urllib.parse.urlparse(url)
    base_url = urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, "", "", "")
    )

    signature_base = "&".join([
        _pct(method.upper()),
        _pct(base_url),
        _pct(param_string),
    ])

    signing_key = f"{_pct(consumer_secret)}&{_pct(token_secret)}"
    raw_sig = hmac.new(
        signing_key.encode("utf-8"),
        signature_base.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    signature = base64.b64encode(raw_sig).decode("utf-8")

    oauth_params["oauth_signature"] = signature

    header_parts = ", ".join(
        f'{_pct(k)}="{_pct(v)}"'
        for k, v in sorted(oauth_params.items())
    )
    return f"OAuth {header_parts}"


# ─────────────────────────────────────────────────────────────────────────────
# LinkedIn — API path (OAuth 2.0 Bearer token)
# ─────────────────────────────────────────────────────────────────────────────

def _linkedin_ugc_payload(author_urn: str, text: str) -> dict:
    return {
        "author": author_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        },
    }


async def _api_publish_linkedin(
    author_urn: str,
    token: str,
    text: str,
    platform: str,
) -> PublishResult:
    payload = _linkedin_ugc_payload(author_urn, text)
    url = "https://api.linkedin.com/v2/ugcPosts"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code in (200, 201):
            post_id = resp.headers.get("x-restli-id", "")
            post_url = f"https://www.linkedin.com/feed/update/{post_id}" if post_id else ""
            logger.info(f"{platform}.api.published", post_id=post_id)
            return PublishResult(platform=platform, success=True,
                                 post_id=post_id, post_url=post_url)
        err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        logger.warning(f"{platform}.api.failed", error=err)
        return PublishResult(platform=platform, success=False, error=err)
    except Exception as exc:
        logger.exception(f"{platform}.api.exception", exc=str(exc))
        return PublishResult(platform=platform, success=False, error=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# LinkedIn — Playwright path (email + password)
# ─────────────────────────────────────────────────────────────────────────────

_LI_FEED = "https://www.linkedin.com/feed/"
_LI_LOGIN = "https://www.linkedin.com/login"

# Session is shared for personal + company (same LinkedIn account).
_LI_SESSION_FILE = "linkedin.json"


async def _pw_li_login(page, email: str, password: str) -> bool:
    """
    Navigate to LinkedIn login page and submit credentials.
    Returns True when the feed loads successfully.
    Handles standard login flow; raises on unexpected pages (2FA, captcha).
    """
    import asyncio
    await page.goto(_LI_LOGIN, wait_until="domcontentloaded", timeout=30_000)
    await asyncio.sleep(1.2)

    # Fill email
    await page.fill('input[name="session_key"], input#username', email)
    await asyncio.sleep(0.4)

    # Fill password
    await page.fill('input[name="session_password"], input#password', password)
    await asyncio.sleep(0.6)

    # Submit
    await page.click('button[type="submit"], button[data-litms-control-urn="login-submit"]')

    try:
        await page.wait_for_url("**/feed/**", timeout=15_000)
        logger.info("linkedin.pw.login_success")
        return True
    except Exception:
        current = page.url
        logger.warning("linkedin.pw.login_failed", url=current)
        # Check for known blockers
        if "checkpoint" in current or "challenge" in current:
            logger.error("linkedin.pw.login_checkpoint_required", url=current)
        elif "login" in current:
            logger.error("linkedin.pw.login_bad_credentials")
        return False


async def _pw_li_post_personal(page, text: str) -> str:
    """
    Create a personal LinkedIn post via the Share modal.
    Returns the post URL (empty string if not capturable).
    """
    import asyncio

    await page.goto(_LI_FEED, wait_until="domcontentloaded", timeout=30_000)
    await asyncio.sleep(2)

    # Click "Start a post" trigger — LinkedIn uses several selectors across versions.
    # Try each in order.
    trigger_selectors = [
        "button.share-box-feed-entry__trigger",
        "[data-test-id='share-box-feed-entry__trigger']",
        "button:has-text('Start a post')",
        "button:has-text('Write something')",
    ]
    for sel in trigger_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=3_000):
                await btn.click()
                await asyncio.sleep(1.5)
                break
        except Exception:
            continue
    else:
        raise RuntimeError("Could not find 'Start a post' button on LinkedIn feed")

    # Type into the post editor
    editor_selectors = [
        "div.ql-editor",
        "div[contenteditable='true']",
        "div.editor-content",
        "div[data-test-id='ql-editor']",
    ]
    typed = False
    for sel in editor_selectors:
        try:
            editor = page.locator(sel).first
            if await editor.is_visible(timeout=3_000):
                await editor.click()
                await asyncio.sleep(0.5)
                # Type with realistic delay
                await editor.type(text, delay=18)
                typed = True
                break
        except Exception:
            continue

    if not typed:
        raise RuntimeError("Could not find post editor on LinkedIn share modal")

    await asyncio.sleep(1)

    # Click the Post button
    post_btn_selectors = [
        "button[data-test-id='share-post-button']",
        "button.share-actions__primary-action",
        "button:has-text('Post'):not([disabled])",
    ]
    for sel in post_btn_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=3_000):
                await btn.click()
                await asyncio.sleep(3)
                break
        except Exception:
            continue
    else:
        raise RuntimeError("Could not find Post button on LinkedIn share modal")

    logger.info("linkedin_personal.pw.posted")
    return ""   # URL not easily capturable post-submit without monitoring network


async def _pw_li_post_company(page, text: str, company_name: str) -> str:
    """
    Create a company page post on LinkedIn.
    Navigates to the company admin 'create-post' path.
    Returns the post URL (empty string if not capturable).
    """
    import asyncio
    import urllib.parse

    # Convert company name to LinkedIn slug format (lowercase, hyphenated)
    slug = company_name.lower().replace(" ", "-")
    admin_url = f"https://www.linkedin.com/company/{slug}/admin/create-post/"

    await page.goto(admin_url, wait_until="domcontentloaded", timeout=30_000)
    await asyncio.sleep(2)

    # LinkedIn may redirect to the company page or feed — handle both.
    # If we land on the editor directly, great. If not, look for the post button.
    if "create-post" not in page.url:
        # Try the feed approach via admin page
        admin_home = f"https://www.linkedin.com/company/{slug}/admin/"
        await page.goto(admin_home, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(2)

        # Try clicking "Start a post" or "Create a post"
        for trigger in [
            "button:has-text('Start a post')",
            "button:has-text('Create a post')",
            ".share-box-feed-entry__trigger",
        ]:
            try:
                btn = page.locator(trigger).first
                if await btn.is_visible(timeout=3_000):
                    await btn.click()
                    await asyncio.sleep(1.5)
                    break
            except Exception:
                continue

    # Type into the editor
    editor_selectors = [
        "div.ql-editor",
        "div[contenteditable='true']",
        "div.editor-content",
    ]
    typed = False
    for sel in editor_selectors:
        try:
            editor = page.locator(sel).first
            if await editor.is_visible(timeout=5_000):
                await editor.click()
                await asyncio.sleep(0.5)
                await editor.type(text, delay=18)
                typed = True
                break
        except Exception:
            continue

    if not typed:
        raise RuntimeError("Could not find company post editor on LinkedIn")

    await asyncio.sleep(1)

    # Click Post
    for sel in [
        "button[data-test-id='share-post-button']",
        "button.share-actions__primary-action",
        "button:has-text('Post'):not([disabled])",
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=3_000):
                await btn.click()
                await asyncio.sleep(3)
                break
        except Exception:
            continue
    else:
        raise RuntimeError("Could not find Post button on LinkedIn company editor")

    logger.info("linkedin_company.pw.posted", company_name=company_name)
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Twitter / X — Playwright fallback
# ─────────────────────────────────────────────────────────────────────────────
#
# Reality check: Twitter (X) ToS prohibit automation. This path works in
# practice with stealth + session persistence, but ban risk exists. Use
# sparingly and only when the X API tier isn't available. Anthony should
# review the live X API plans before relying on this long-term.

_TW_HOME = "https://x.com/home"
_TW_LOGIN = "https://x.com/i/flow/login"
_TW_SESSION_FILE = "twitter.json"


async def _pw_tw_login(page, email: str, password: str, username: str = "") -> bool:
    """Submit X login flow. Multi-step: identifier → password (sometimes username challenge)."""
    import asyncio
    await page.goto(_TW_LOGIN, wait_until="domcontentloaded", timeout=30_000)
    await asyncio.sleep(1.5)

    # Step 1 — identifier (email or username)
    try:
        await page.fill('input[autocomplete="username"]', email)
    except Exception:
        # Sometimes the input is name=text
        await page.fill('input[name="text"]', email)
    await asyncio.sleep(0.6)
    await page.click('button:has-text("Next"), div[role="button"]:has-text("Next")')
    await asyncio.sleep(2)

    # Step 2 — sometimes X challenges with username again before password
    if username:
        try:
            challenge = page.locator('input[name="text"], input[autocomplete="username"]')
            if await challenge.first.is_visible(timeout=3_000):
                await challenge.first.fill(username)
                await asyncio.sleep(0.5)
                await page.click('button:has-text("Next"), div[role="button"]:has-text("Next")')
                await asyncio.sleep(2)
        except Exception:
            pass

    # Step 3 — password
    try:
        await page.fill('input[name="password"], input[autocomplete="current-password"]', password)
    except Exception:
        logger.warning("twitter.pw.password_field_missing")
        return False
    await asyncio.sleep(0.5)
    await page.click('button[data-testid="LoginForm_Login_Button"], button:has-text("Log in")')

    try:
        await page.wait_for_url("**/home**", timeout=15_000)
        logger.info("twitter.pw.login_success")
        return True
    except Exception:
        logger.warning("twitter.pw.login_failed", url=page.url)
        return False


# X/Twitter UI selector lists — updated 2026-07-26.
#
# X periodically renames data-testid attributes and restructures the compose
# dialog.  Selectors are ordered from most-specific / most-stable to broadest
# fallback so the first viable match wins quickly.
#
# Composer textarea — the inline home timeline box and the modal dialog share
# the same data-testid family; we match both by prefix.
_TW_COMPOSER_SELECTORS = [
    # Primary inline composer (home timeline, July 2026)
    'div[data-testid="tweetTextarea_0"]',
    # Modal composer opened via the sidebar "Post" button
    'div[data-testid="tweetTextarea_0_label"]',
    # Prefix match covers both _0 and _0_label variants
    'div[data-testid^="tweetTextarea_"][contenteditable="true"]',
    # Aria-label fallbacks — X changed the label text from "Tweet text" to
    # "Post text" in late 2023; both are kept for robustness.
    'div[role="textbox"][aria-label*="Post text"]',
    'div[role="textbox"][aria-label*="Tweet text"]',
    # Broadest safe fallback: any contenteditable textbox inside the compose area
    'div[data-testid="tweetTextarea_0"] div[contenteditable="true"]',
    'div[role="dialog"] div[contenteditable="true"]',
    'div[role="textbox"][contenteditable="true"]',
]

# Submit / Post button — X has used several data-testid values over time.
# tweetButtonInline  = inline home timeline composer submit (pre-2025)
# tweetButton        = modal / standalone composer submit
# Both may appear as <button> or <div role="button">.
_TW_SUBMIT_SELECTORS = [
    # Inline home timeline submit (most common path)
    'button[data-testid="tweetButtonInline"]',
    'div[role="button"][data-testid="tweetButtonInline"]',
    # Modal / dialog submit
    'button[data-testid="tweetButton"]',
    'div[data-testid="tweetButton"]',
    # Aria-label fallbacks — "Post" is the current X copy (was "Tweet" pre-2023)
    'button[aria-label="Post"]',
    'div[role="button"][aria-label="Post"]',
    'button[aria-label="Tweet"]',
]


async def _pw_tw_capture_debug(page, reason: str) -> None:
    """Best-effort screenshot + URL on a compose/submit failure, so the next
    debugging pass has evidence instead of a bare RuntimeError to go on."""
    try:
        debug_dir = Path(os.environ.get("SOCIAL_SESSIONS_DIR", "/tmp/social_sessions")) / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        await page.screenshot(path=str(debug_dir / f"twitter-{reason}-{stamp}.png"))
        logger.warning("twitter.pw.debug_captured", reason=reason, url=page.url)
    except Exception as exc:
        logger.warning("twitter.pw.debug_capture_failed", reason=reason, error=str(exc))


async def _pw_wait_enabled_and_click(page, selectors: list[str], *, timeout_ms: int = 8_000) -> bool:
    """Poll `selectors` until one is visible AND not aria-disabled, then click
    it. A plain is_visible() check accepts X's Post button while it's still
    aria-disabled="true" (before the composer's input handler registers the
    typed text) -- clicking it then is a silent no-op, not a post."""
    import asyncio
    loop = asyncio.get_event_loop()
    deadline = loop.time() + (timeout_ms / 1000)
    while loop.time() < deadline:
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if not await el.is_visible(timeout=500):
                    continue
                if await el.get_attribute("aria-disabled") == "true":
                    continue
                await el.click()
                return True
            except Exception:
                continue
        await asyncio.sleep(0.4)
    return False


async def _pw_tw_post(
    page,
    text: str,
    *,
    submit_timeout_ms: int = 8_000,
    confirm_attempts: int = 10,
    confirm_interval: float = 0.5,
) -> str:
    """Compose + post a tweet via the home timeline composer.

    submit_timeout_ms / confirm_attempts / confirm_interval are overridable
    so tests can exercise the polling loops without real multi-second waits;
    production callers should leave them at the defaults.
    """
    import asyncio
    await page.goto(_TW_HOME, wait_until="domcontentloaded", timeout=30_000)
    await asyncio.sleep(2)

    # X's home page may not show an open composer by default — the left sidebar
    # has a "Post" button (data-testid="SideNav_NewTweet_Button") that opens the
    # compose dialog.  Try to open it if the textarea isn't immediately visible.
    _TW_OPEN_COMPOSER_SELECTORS = [
        'a[data-testid="SideNav_NewTweet_Button"]',
        'button[data-testid="SideNav_NewTweet_Button"]',
        # Floating compose button on smaller viewports
        'a[data-testid="FloatingActionButton_Tweet_Button"]',
        'button[data-testid="FloatingActionButton_Tweet_Button"]',
    ]

    # Only click the open-composer button when the textarea isn't already present.
    textarea_visible = False
    for sel in _TW_COMPOSER_SELECTORS[:3]:  # check the most specific three
        try:
            if await page.locator(sel).first.is_visible(timeout=1_000):
                textarea_visible = True
                break
        except Exception:
            continue

    if not textarea_visible:
        for sel in _TW_OPEN_COMPOSER_SELECTORS:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2_000):
                    await btn.click()
                    await asyncio.sleep(1.2)
                    break
            except Exception:
                continue

    # The composer textarea
    typed = False
    editor = None
    for sel in _TW_COMPOSER_SELECTORS:
        try:
            candidate = page.locator(sel).first
            if await candidate.is_visible(timeout=3_000):
                await candidate.click()
                await asyncio.sleep(0.5)
                await candidate.type(text, delay=22)
                editor = candidate
                typed = True
                break
        except Exception:
            continue
    if not typed:
        await _pw_tw_capture_debug(page, "composer_not_found")
        raise RuntimeError("Could not find tweet composer")

    clicked = await _pw_wait_enabled_and_click(page, _TW_SUBMIT_SELECTORS, timeout_ms=submit_timeout_ms)
    if not clicked:
        await _pw_tw_capture_debug(page, "submit_button_not_clickable")
        raise RuntimeError("Could not find tweet submit button")

    # A click on a button that turned out disabled-in-practice (or was
    # intercepted by an overlay) leaves the composer populated; a real post
    # clears it. Poll for that instead of trusting the click alone.
    posted = False
    for _ in range(confirm_attempts):
        await asyncio.sleep(confirm_interval)
        try:
            remaining = await editor.inner_text()
        except Exception:
            remaining = ""
        if not remaining.strip():
            posted = True
            break
    if not posted:
        await _pw_tw_capture_debug(page, "post_not_confirmed")
        raise RuntimeError("Tweet submit click did not clear the composer -- post not confirmed")

    logger.info("twitter.pw.posted")
    return ""   # URL not captured without network intercept


async def _pw_publish_twitter(text: str, settings: "Settings") -> PublishResult:
    platform = "twitter"
    try:
        from playwright.async_api import async_playwright
        try:
            from playwright_stealth import stealth_async
        except ImportError:
            async def stealth_async(_p): return None  # graceful fallback if stealth lib missing
    except ImportError as exc:
        return PublishResult(platform=platform, success=False, error=f"Playwright not installed: {exc}")

    sessions_dir = Path(settings.social_sessions_dir)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_file = sessions_dir / _TW_SESSION_FILE

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            storage_state=str(session_file) if session_file.exists() else None,
        )
        page = await ctx.new_page()
        await stealth_async(page)
        try:
            await page.goto(_TW_HOME, wait_until="domcontentloaded", timeout=30_000)
            if "login" in page.url or "flow" in page.url:
                ok = await _pw_tw_login(
                    page,
                    settings.twitter_email,
                    settings.twitter_password,
                    getattr(settings, "twitter_username", "") or "",
                )
                if not ok:
                    return PublishResult(platform=platform, success=False,
                                         error="Twitter login failed (check creds, 2FA, or username challenge)")
                await ctx.storage_state(path=str(session_file))

            await _pw_tw_post(page, text)
            await ctx.storage_state(path=str(session_file))
            return PublishResult(platform=platform, success=True, post_url="", post_id="")
        except Exception as exc:
            logger.exception("twitter.pw.error", error=str(exc))
            return PublishResult(platform=platform, success=False, error=str(exc))
        finally:
            await browser.close()


# ─────────────────────────────────────────────────────────────────────────────
# Facebook — Playwright fallback
# ─────────────────────────────────────────────────────────────────────────────

_FB_LOGIN = "https://www.facebook.com/login"
_FB_HOME = "https://www.facebook.com/"
_FB_SESSION_FILE = "facebook.json"


async def _pw_fb_login(page, email: str, password: str) -> bool:
    import asyncio
    await page.goto(_FB_LOGIN, wait_until="domcontentloaded", timeout=30_000)
    await asyncio.sleep(1.2)
    try:
        await page.fill('input#email, input[name="email"]', email)
        await asyncio.sleep(0.4)
        await page.fill('input#pass, input[name="pass"]', password)
        await asyncio.sleep(0.5)
        await page.click('button[name="login"], button[type="submit"]')
    except Exception as exc:
        logger.warning("facebook.pw.login_fields_missing", error=str(exc))
        return False
    try:
        await page.wait_for_url("**/facebook.com/**", timeout=15_000)
        # If login succeeded we should NOT still be on /login
        if "login" in page.url or "checkpoint" in page.url:
            logger.warning("facebook.pw.login_failed", url=page.url)
            return False
        logger.info("facebook.pw.login_success")
        return True
    except Exception:
        logger.warning("facebook.pw.login_timeout", url=page.url)
        return False


async def _pw_fb_post(page, text: str) -> str:
    import asyncio
    await page.goto(_FB_HOME, wait_until="domcontentloaded", timeout=30_000)
    await asyncio.sleep(2)

    # Open composer — "What's on your mind?"
    composer_triggers = [
        'div[role="button"]:has-text("What\'s on your mind")',
        'div[aria-label*="Create a post"]',
        'span:has-text("What\'s on your mind")',
    ]
    for sel in composer_triggers:
        try:
            t = page.locator(sel).first
            if await t.is_visible(timeout=3_000):
                await t.click()
                await asyncio.sleep(1.5)
                break
        except Exception:
            continue

    # Type into the editor
    editor = page.locator('div[role="textbox"][contenteditable="true"]').first
    if not await editor.is_visible(timeout=5_000):
        raise RuntimeError("Could not find Facebook post editor")
    await editor.click()
    await asyncio.sleep(0.5)
    await editor.type(text, delay=20)
    await asyncio.sleep(1)

    # Submit
    for sel in [
        'div[aria-label="Post"][role="button"]',
        'div[role="button"]:has-text("Post"):not([aria-disabled="true"])',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=3_000):
                await btn.click()
                await asyncio.sleep(3)
                break
        except Exception:
            continue
    else:
        raise RuntimeError("Could not find Facebook Post button")

    logger.info("facebook.pw.posted")
    return ""


async def _pw_publish_facebook(text: str, settings: "Settings") -> PublishResult:
    platform = "facebook"
    try:
        from playwright.async_api import async_playwright
        try:
            from playwright_stealth import stealth_async
        except ImportError:
            async def stealth_async(_p): return None  # graceful fallback if stealth lib missing
    except ImportError as exc:
        return PublishResult(platform=platform, success=False, error=f"Playwright not installed: {exc}")

    sessions_dir = Path(settings.social_sessions_dir)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_file = sessions_dir / _FB_SESSION_FILE

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            storage_state=str(session_file) if session_file.exists() else None,
        )
        page = await ctx.new_page()
        await stealth_async(page)
        try:
            await page.goto(_FB_HOME, wait_until="domcontentloaded", timeout=30_000)
            if "login" in page.url or "checkpoint" in page.url:
                ok = await _pw_fb_login(page, settings.facebook_email, settings.facebook_password)
                if not ok:
                    return PublishResult(platform=platform, success=False,
                                         error="Facebook login failed (check creds, 2FA, or checkpoint)")
                await ctx.storage_state(path=str(session_file))

            await _pw_fb_post(page, text)
            await ctx.storage_state(path=str(session_file))
            return PublishResult(platform=platform, success=True, post_url="", post_id="")
        except Exception as exc:
            logger.exception("facebook.pw.error", error=str(exc))
            return PublishResult(platform=platform, success=False, error=str(exc))
        finally:
            await browser.close()


# ─────────────────────────────────────────────────────────────────────────────
# Reddit — Playwright (Reddit API requires app registration + karma gating)
# ─────────────────────────────────────────────────────────────────────────────
#
# Reddit's API is technically free but new accounts can't post via the API
# until they accumulate karma. The web flow has no such restriction. Posts
# default to the user's own profile (u/<username>) which has no subreddit
# moderation. If REDDIT_DEFAULT_SUBREDDIT is set, posts go there instead.
#
# Login strategy (July 2026):
#   1. Try old.reddit.com/login — simpler form, no SPA/shadow DOM, more
#      automation-friendly. This is the primary path.
#   2. Fall back to www.reddit.com/login — the new Shreddit SPA uses a
#      <faceplate-*> web component hierarchy; we target inner inputs via
#      a broader selector sweep.
#
# Post-login challenge handling:
#   - "Suspicious login" / "Verify your account" interstitials are detected
#     and surfaced as a clear error rather than silently failing.
#   - CAPTCHA detection surfaces an actionable message.

_RD_OLD_LOGIN = "https://old.reddit.com/login"
_RD_NEW_LOGIN = "https://www.reddit.com/login"
_RD_HOME = "https://www.reddit.com/"
_RD_OLD_HOME = "https://old.reddit.com/"
_RD_SESSION_FILE = "reddit.json"


async def _pw_rd_login_old(page, username: str, password: str) -> bool:
    """Login via old.reddit.com — simpler form, no SPA, friendlier to automation."""
    import asyncio
    await page.goto(_RD_OLD_LOGIN, wait_until="domcontentloaded", timeout=30_000)
    await asyncio.sleep(1.5)

    # old.reddit has a plain HTML form with predictable field names
    try:
        await page.fill('input[name="user"], input#user', username)
        await asyncio.sleep(0.4)
        await page.fill('input[name="passwd"], input#passwd', password)
        await asyncio.sleep(0.5)
        await page.click('button[type="submit"], input[type="submit"][value*="log in" i], input[type="submit"][value*="login" i]')
    except Exception as exc:
        logger.warning("reddit.pw.old_login_fields_missing", error=str(exc))
        return False

    try:
        await page.wait_for_url(lambda u: "old.reddit.com" in u and "login" not in u, timeout=15_000)
        current = page.url
        # Detect CAPTCHA page (old Reddit shows a captcha interstitial on suspected bots)
        if "captcha" in current.lower():
            logger.error("reddit.pw.old_login_captcha_required", url=current)
            return False
        logger.info("reddit.pw.old_login_success")
        return True
    except Exception:
        current = page.url
        logger.warning("reddit.pw.old_login_failed", url=current)
        # Check for wrong-password indicator (old Reddit stays on /login with an error)
        try:
            err_text = await page.locator(".error, .status").first.text_content(timeout=2_000) or ""
            if err_text.strip():
                logger.error("reddit.pw.old_login_error_text", text=err_text.strip()[:120])
        except Exception:
            pass
        return False


async def _pw_rd_login_new(page, username: str, password: str) -> bool:
    """Login via www.reddit.com/login — Shreddit SPA (July 2026 UI).

    Reddit's new UI wraps form fields in <faceplate-*> custom elements.
    The actual <input> elements are in the light DOM (not shadow DOM) but
    nested inside custom element containers. We use broad input[id] /
    input[name] selectors and fall back to locating by placeholder text.
    """
    import asyncio
    await page.goto(_RD_NEW_LOGIN, wait_until="domcontentloaded", timeout=30_000)
    await asyncio.sleep(2.0)

    # Username field — try in order of specificity
    username_selectors = [
        'input#login-username',
        'input[name="username"]',
        'input[placeholder*="Username" i]',
        'input[autocomplete="username"]',
        'faceplate-text-input[name="username"] input',
    ]
    filled_user = False
    for sel in username_selectors:
        try:
            f = page.locator(sel).first
            if await f.is_visible(timeout=3_000):
                await f.fill(username)
                filled_user = True
                break
        except Exception:
            continue
    if not filled_user:
        logger.warning("reddit.pw.new_login_username_field_missing")
        return False
    await asyncio.sleep(0.4)

    # Password field
    password_selectors = [
        'input#login-password',
        'input[name="password"]',
        'input[type="password"]',
        'input[placeholder*="Password" i]',
        'faceplate-text-input[name="password"] input',
    ]
    filled_pass = False
    for sel in password_selectors:
        try:
            f = page.locator(sel).first
            if await f.is_visible(timeout=3_000):
                await f.fill(password)
                filled_pass = True
                break
        except Exception:
            continue
    if not filled_pass:
        logger.warning("reddit.pw.new_login_password_field_missing")
        return False
    await asyncio.sleep(0.5)

    # Dismiss the consent cookie banner if it covers the form (observed 2026-08-14).
    for _cookie_sel in (
        'button:has-text("Reject Optional Cookies")',
        'button:has-text("Accept All")',
    ):
        try:
            _cb = page.locator(_cookie_sel).first
            if await _cb.is_visible(timeout=2_000):
                await _cb.click()
                break
        except Exception:
            continue

    # Submit — the Log In button is type="button" on the current Shreddit form
    # (2026-08-14), NOT type="submit" and NOT wrapped in faceplate-button. The
    # legacy faceplate/type-submit selectors below are kept as fallbacks.
    submit_selectors = [
        'button[type="button"]:has-text("Log In")',
        'button[type="button"]:has-text("Continue")',
        'faceplate-button[type="submit"] button',
        'button[type="submit"]:has-text("Log In")',
        'button[type="submit"]:has-text("Sign In")',
        'button[type="submit"]:has-text("Continue")',
        'button[type="submit"]',
    ]
    clicked = False
    for sel in submit_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=3_000):
                await btn.click()
                clicked = True
                break
        except Exception:
            continue
    if not clicked:
        logger.warning("reddit.pw.new_login_submit_missing")
        return False

    # Wait for navigation away from the login page
    try:
        await page.wait_for_url(lambda u: "/login" not in u, timeout=20_000)
    except Exception:
        pass  # may land on challenge page — we check below

    current = page.url
    page_content = ""
    try:
        page_content = (await page.locator("body").text_content(timeout=3_000) or "").lower()
    except Exception:
        pass

    # Detect challenge / suspicious login interstitial
    if any(kw in current.lower() for kw in ("challenge", "suspicious", "verify", "confirm")):
        logger.error("reddit.pw.new_login_challenge", url=current)
        return False

    # Detect CAPTCHA
    if "captcha" in page_content or "are you a robot" in page_content:
        logger.error("reddit.pw.new_login_captcha_required", url=current)
        return False

    # Detect "verify your email" or "check your email" interstitial
    if "verify your email" in page_content or "check your email" in page_content:
        logger.error(
            "reddit.pw.new_login_email_verify_required",
            url=current,
            hint="Reddit flagged this login as suspicious and sent a verification email. "
                 "Complete email verification once manually, then the saved session will work.",
        )
        return False

    # Detect still-on-login (wrong creds)
    if "/login" in current:
        logger.error("reddit.pw.new_login_bad_credentials", url=current)
        return False

    logger.info("reddit.pw.new_login_success")
    return True


async def _pw_rd_login(page, username: str, password: str) -> bool:
    """Try old.reddit.com login first; fall back to new Reddit SPA login."""
    import asyncio

    # Primary: old.reddit — simpler DOM, more reliable for automation
    logger.info("reddit.pw.login_attempt_old_reddit")
    ok = await _pw_rd_login_old(page, username, password)
    if ok:
        return True

    # Fallback: new Shreddit SPA
    logger.info("reddit.pw.login_fallback_new_reddit")
    await asyncio.sleep(1.0)
    ok = await _pw_rd_login_new(page, username, password)
    return ok


def _split_reddit_title_body(text: str) -> tuple[str, str]:
    """
    Reddit requires a separate title and body. Convention:
      - First line (up to 300 chars) = title
      - Remaining text = body
    """
    parts = text.split("\n", 1)
    title = parts[0].strip()[:300]
    body = parts[1].strip() if len(parts) > 1 else ""
    return title, body


async def _pw_rd_post(page, text: str, username: str, subreddit: str = "",
                      session_file: str = "") -> str:
    import asyncio
    title, body = _split_reddit_title_body(text)

    # Determine whether we're on old.reddit (after old-reddit login) or new Reddit.
    # Use old.reddit submit URLs when the current session is on old.reddit — they
    # use a simple HTML form that is far easier to automate than the Shreddit SPA.
    current_url = page.url
    use_old = "old.reddit.com" in current_url

    if subreddit:
        if use_old:
            submit_url = f"https://old.reddit.com/r/{subreddit}/submit"
        else:
            submit_url = f"https://www.reddit.com/r/{subreddit}/submit"
    else:
        # Posting to user profile — old Reddit doesn't have a profile submit page;
        # use the new Reddit URL regardless of session origin.
        submit_url = f"https://www.reddit.com/user/{username}/submit"

    await page.goto(submit_url, wait_until="domcontentloaded", timeout=30_000)
    await asyncio.sleep(2)

    # If the submit URL bounced to a login page, the stored session is missing /
    # expired / not honoured. Fail with an actionable message rather than the
    # generic "could not find title field". Expected with a fresh approved
    # session this never triggers.
    if "/login" in page.url:
        raise RuntimeError(
            "Reddit redirected the submit page to login — the stored approved "
            "session is missing or expired. Re-approve: log into Reddit once in "
            "a real browser (as ITExpertsBerlin), let it save the session file at "
            f"{session_file}, then retry. (js_challenge anti-bot blocks headless "
            "login, so an approved session cookie must be supplied.)"
        )

    # Detect CAPTCHA or "suspicious activity" block on the submit page
    try:
        body_text = (await page.locator("body").text_content(timeout=3_000) or "").lower()
        if "captcha" in body_text or "are you a robot" in body_text:
            raise RuntimeError(
                "Reddit CAPTCHA challenge on submit page — automation blocked. "
                "Complete a manual login from the same IP to clear the flag."
            )
        if "something went wrong" in body_text and "login" in body_text:
            raise RuntimeError(
                "Reddit redirected to error/login on submit page — session may be invalid."
            )
    except RuntimeError:
        raise
    except Exception:
        pass

    # Reddit's submit page uses shadow DOM for the title input on the new UI.
    # Try multiple selectors.
    title_field = None
    for sel in [
        'textarea[name="title"]',
        'input[name="title"]',
        'faceplate-textarea-input[name="title"]',
        'shreddit-composer textarea[slot="title"]',
    ]:
        try:
            f = page.locator(sel).first
            if await f.is_visible(timeout=3_000):
                title_field = f
                break
        except Exception:
            continue
    if title_field is None:
        raise RuntimeError("Could not find Reddit title field")

    await title_field.click()
    await asyncio.sleep(0.4)
    await title_field.type(title, delay=20)
    await asyncio.sleep(0.5)

    # Body — only if there's body text. Reddit's body editor is rich-text.
    if body:
        for sel in [
            'div[contenteditable="true"][role="textbox"]',
            'shreddit-composer div[contenteditable="true"]',
            'div.public-DraftEditor-content',
        ]:
            try:
                ed = page.locator(sel).first
                if await ed.is_visible(timeout=3_000):
                    await ed.click()
                    await asyncio.sleep(0.4)
                    await ed.type(body, delay=18)
                    break
            except Exception:
                continue

    await asyncio.sleep(1)
    # Submit
    for sel in [
        'button:has-text("Post"):not([disabled])',
        'button[type="submit"]',
        'faceplate-button:has-text("Post"):not([aria-disabled="true"])',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=3_000):
                await btn.click()
                await asyncio.sleep(4)
                break
        except Exception:
            continue
    else:
        raise RuntimeError("Could not find Reddit Post submit button")

    logger.info("reddit.pw.posted", subreddit=subreddit or f"u/{username}")
    return ""


async def _pw_publish_reddit(text: str, settings: "Settings") -> PublishResult:
    platform = "reddit"
    try:
        from playwright.async_api import async_playwright
        try:
            from playwright_stealth import stealth_async
        except ImportError:
            async def stealth_async(_p): return None  # graceful fallback if stealth lib missing
    except ImportError as exc:
        return PublishResult(platform=platform, success=False, error=f"Playwright not installed: {exc}")

    sessions_dir = Path(settings.social_sessions_dir)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_file = sessions_dir / _RD_SESSION_FILE

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            storage_state=str(session_file) if session_file.exists() else None,
        )
        page = await ctx.new_page()
        await stealth_async(page)
        try:
            # Validate session against new Reddit. old.reddit is bot-flagged and
            # force-redirects to /login with a js_challenge, so we use the new
            # www.reddit.com surface: with a valid approved session cookie the
            # home page loads logged-in and the challenge never fires.
            await page.goto(_RD_HOME, wait_until="domcontentloaded", timeout=30_000)

            # Detect logged-out state. New reddit shows a "Log In" button in the
            # top-right when not authenticated.
            login_required = False
            logged_out_selectors = [
                'a[href="/login"]:has-text("Log In")',
                'shreddit-login-button',
                'button:has-text("Log In")',
            ]
            for sel in logged_out_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=1_500):
                        login_required = True
                        break
                except Exception:
                    continue

            if login_required:
                ok = await _pw_rd_login(page, settings.reddit_username, settings.reddit_password)
                if not ok:
                    return PublishResult(
                        platform=platform, success=False,
                        error=(
                            "Reddit login failed. Possible causes: wrong credentials, "
                            "Reddit email-verification challenge (complete it once manually), "
                            "or CAPTCHA block (automation detected). "
                            "Old.reddit.com login was tried first, then new Reddit SPA."
                        ),
                    )
                await ctx.storage_state(path=str(session_file))

            await _pw_rd_post(
                page, text,
                settings.reddit_username,
                getattr(settings, "reddit_default_subreddit", "") or "",
                session_file=str(session_file),
            )
            await ctx.storage_state(path=str(session_file))
            return PublishResult(platform=platform, success=True, post_url="", post_id="")
        except Exception as exc:
            logger.exception("reddit.pw.error", error=str(exc))
            return PublishResult(platform=platform, success=False, error=str(exc))
        finally:
            await browser.close()


async def publish_reddit(text: str, settings: "Settings") -> PublishResult:
    """Reddit publisher — Playwright only (no API path)."""
    platform = "reddit"
    if not (getattr(settings, "reddit_username", "") and getattr(settings, "reddit_password", "")):
        return PublishResult(
            platform=platform, success=False,
            error="Reddit credentials not configured — set REDDIT_USERNAME + REDDIT_PASSWORD",
        )
    return await _pw_publish_reddit(text, settings)


# ─────────────────────────────────────────────────────────────────────────────
# YouTube Community posts — Playwright (no public API for posts)
# ─────────────────────────────────────────────────────────────────────────────
#
# Important caveats:
#   1. Requires 500+ subscribers on the channel (YouTube gate).
#   2. Google login is the hardest to automate — bot detection is aggressive.
#      Expect captchas, device-grant challenges, and occasional failures.
#   3. Posts go to https://studio.youtube.com/channel/<id>/community (Studio UI)
#      — we detect the channel ID via the configured handle.

_YT_LOGIN = "https://accounts.google.com/signin"
_YT_STUDIO = "https://studio.youtube.com/"
_YT_SESSION_FILE = "youtube.json"


async def _pw_yt_login(page, email: str, password: str) -> bool:
    """Google login flow. Two-step: email → password.
    Returns False on any obstacle (2FA, captcha, device challenge)."""
    import asyncio
    await page.goto(_YT_LOGIN, wait_until="domcontentloaded", timeout=30_000)
    await asyncio.sleep(1.5)
    try:
        await page.fill('input[type="email"], input[name="identifier"]', email)
        await asyncio.sleep(0.5)
        await page.click('button:has-text("Next"), button:has-text("Weiter"), #identifierNext button')
        await asyncio.sleep(2)
        # Password step
        await page.fill('input[type="password"], input[name="Passwd"]', password)
        await asyncio.sleep(0.5)
        await page.click('button:has-text("Next"), button:has-text("Weiter"), #passwordNext button')
    except Exception as exc:
        logger.warning("youtube.pw.login_fields_missing", error=str(exc))
        return False
    try:
        # On success Google redirects to myaccount or back to YouTube
        await page.wait_for_url(lambda u: "signin" not in u and "challenge" not in u, timeout=20_000)
        if "challenge" in page.url or "rejected" in page.url:
            logger.warning("youtube.pw.login_challenge", url=page.url)
            return False
        logger.info("youtube.pw.login_success")
        return True
    except Exception:
        logger.warning("youtube.pw.login_timeout", url=page.url)
        return False


async def _pw_yt_post(page, text: str, channel_handle: str) -> str:
    """Create a Community post in YouTube Studio."""
    import asyncio
    # Navigate to community tab via the handle (handle maps to a channel ID
    # internally; we let the YT redirect resolve it).
    if channel_handle:
        community_url = f"https://www.youtube.com/@{channel_handle}/community"
    else:
        community_url = "https://studio.youtube.com/"
    await page.goto(community_url, wait_until="domcontentloaded", timeout=30_000)
    await asyncio.sleep(2)

    # The community composer is gated by sub count. If we land on a redirect
    # we surface the limitation clearly rather than silently failing.
    if "community" not in page.url.lower():
        # We bounced off — check if it's a sub gate
        body_text = await page.locator("body").text_content() or ""
        if "500" in body_text or "subscribers" in body_text.lower():
            raise RuntimeError(
                "YouTube community posts require 500+ subscribers — channel not eligible yet"
            )

    # Composer trigger — "Create a post" / "Share what's new"
    for sel in [
        'button:has-text("Create a post")',
        'div[aria-label*="post"]',
        'tp-yt-paper-input#post-input',
        'div#post-textarea',
    ]:
        try:
            t = page.locator(sel).first
            if await t.is_visible(timeout=3_000):
                await t.click()
                await asyncio.sleep(1.2)
                break
        except Exception:
            continue

    # Type
    editor_selectors = [
        'div[contenteditable="true"]',
        'tp-yt-paper-input#post-input input',
        'div#post-textarea[contenteditable="true"]',
    ]
    typed = False
    for sel in editor_selectors:
        try:
            ed = page.locator(sel).first
            if await ed.is_visible(timeout=3_000):
                await ed.click()
                await asyncio.sleep(0.4)
                await ed.type(text, delay=22)
                typed = True
                break
        except Exception:
            continue
    if not typed:
        raise RuntimeError("Could not find YouTube community post editor")

    await asyncio.sleep(1)
    # Submit
    for sel in [
        'button:has-text("Post"):not([disabled])',
        'tp-yt-paper-button:has-text("Post")',
        'button:has-text("Veröffentlichen"):not([disabled])',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=3_000):
                await btn.click()
                await asyncio.sleep(4)
                break
        except Exception:
            continue
    else:
        raise RuntimeError("Could not find YouTube Post submit button")

    logger.info("youtube.pw.posted", channel=channel_handle)
    return ""


async def _pw_publish_youtube(text: str, settings: "Settings") -> PublishResult:
    platform = "youtube"
    try:
        from playwright.async_api import async_playwright
        try:
            from playwright_stealth import stealth_async
        except ImportError:
            async def stealth_async(_p): return None  # graceful fallback if stealth lib missing
    except ImportError as exc:
        return PublishResult(platform=platform, success=False, error=f"Playwright not installed: {exc}")

    sessions_dir = Path(settings.social_sessions_dir)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_file = sessions_dir / _YT_SESSION_FILE

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            storage_state=str(session_file) if session_file.exists() else None,
        )
        page = await ctx.new_page()
        await stealth_async(page)
        try:
            await page.goto(_YT_STUDIO, wait_until="domcontentloaded", timeout=30_000)
            if "accounts.google.com" in page.url or "signin" in page.url:
                ok = await _pw_yt_login(page, settings.youtube_email, settings.youtube_password)
                if not ok:
                    return PublishResult(
                        platform=platform, success=False,
                        error="Google login failed — likely 2FA/captcha/device challenge. Use an app password or trusted device.",
                    )
                await ctx.storage_state(path=str(session_file))

            await _pw_yt_post(page, text, settings.youtube_channel_handle)
            await ctx.storage_state(path=str(session_file))
            return PublishResult(platform=platform, success=True, post_url="", post_id="")
        except Exception as exc:
            logger.exception("youtube.pw.error", error=str(exc))
            return PublishResult(platform=platform, success=False, error=str(exc))
        finally:
            await browser.close()


async def publish_youtube(text: str, settings: "Settings") -> PublishResult:
    """YouTube Community post publisher — Playwright only (no public API).

    Requires:
      - YOUTUBE_EMAIL + YOUTUBE_PASSWORD (Google account)
      - YOUTUBE_CHANNEL_HANDLE (e.g. "Klaravex")
      - 500+ subscribers on the channel (YouTube gate, surfaced as error)
    """
    platform = "youtube"
    if not (getattr(settings, "youtube_email", "") and getattr(settings, "youtube_password", "")):
        return PublishResult(
            platform=platform, success=False,
            error="YouTube credentials not configured — set YOUTUBE_EMAIL + YOUTUBE_PASSWORD",
        )
    return await _pw_publish_youtube(text, settings)


async def _pw_publish_linkedin(
    text: str,
    settings: "Settings",
    mode: str,  # "personal" | "company"
) -> PublishResult:
    """
    Launch a stealth Playwright Chromium instance, log into LinkedIn
    (reusing saved session if available), and publish a post.

    Session file: {social_sessions_dir}/linkedin.json
    """
    platform = f"linkedin_{mode}"

    # Lazy import — playwright only available when Dockerfile is built with it.
    try:
        from playwright.async_api import async_playwright
        try:
            from playwright_stealth import stealth_async
        except ImportError:
            async def stealth_async(_p): return None  # graceful fallback if stealth lib missing
    except ImportError as exc:
        return PublishResult(
            platform=platform, success=False,
            error=f"Playwright not installed: {exc}",
        )

    sessions_dir = Path(settings.social_sessions_dir)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_file = sessions_dir / _LI_SESSION_FILE

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            storage_state=str(session_file) if session_file.exists() else None,
        )
        page = await ctx.new_page()
        await stealth_async(page)

        try:
            # Navigate to feed — if session is valid we stay on /feed/
            await page.goto(_LI_FEED, wait_until="domcontentloaded", timeout=30_000)

            # Check if login is required
            if "login" in page.url or "signup" in page.url or "authwall" in page.url:
                logger.info("linkedin.pw.session_expired_or_new", url=page.url)
                logged_in = await _pw_li_login(
                    page,
                    settings.linkedin_email,
                    settings.linkedin_password,
                )
                if not logged_in:
                    return PublishResult(
                        platform=platform, success=False,
                        error="LinkedIn login failed — check credentials or 2FA requirement",
                    )
                # Save fresh session
                await ctx.storage_state(path=str(session_file))

            # Publish
            if mode == "company":
                post_url = await _pw_li_post_company(
                    page, text, settings.linkedin_company_name
                )
            else:
                post_url = await _pw_li_post_personal(page, text)

            # Refresh saved session (extends expiry)
            await ctx.storage_state(path=str(session_file))

            logger.info(
                "linkedin.pw.success",
                platform=platform,
                post_url=post_url,
            )
            return PublishResult(
                platform=platform, success=True,
                post_url=post_url,
                post_id="",
            )

        except Exception as exc:
            logger.exception("linkedin.pw.error", platform=platform, error=str(exc))
            return PublishResult(platform=platform, success=False, error=str(exc))

        finally:
            await browser.close()


# ─────────────────────────────────────────────────────────────────────────────
# LinkedIn — combined dispatch (API preferred, Playwright fallback)
# ─────────────────────────────────────────────────────────────────────────────

async def publish_linkedin_company(text: str, settings: "Settings") -> PublishResult:
    """
    Publish to LinkedIn Company Page.
    API (OAuth 2.0 Bearer) if configured, else Playwright email/password.
    """
    platform = "linkedin_company"
    token = getattr(settings, "linkedin_company_token", "")
    org_id = getattr(settings, "linkedin_company_org_id", "")

    if token and org_id and not settings._is_placeholder(token):
        author_urn = f"urn:li:organization:{org_id}"
        return await _api_publish_linkedin(author_urn, token, text, platform)

    if settings.linkedin_pw_configured:
        return await _pw_publish_linkedin(text, settings, mode="company")

    return PublishResult(platform=platform, success=False,
                         error="LinkedIn Company: no API token or Playwright credentials configured")


async def publish_linkedin_personal(text: str, settings: "Settings") -> PublishResult:
    """
    Publish to LinkedIn Personal Profile.
    API (OAuth 2.0 Bearer) if configured, else Playwright email/password.
    """
    platform = "linkedin_personal"
    token = getattr(settings, "linkedin_personal_token", "")
    author_urn = getattr(settings, "linkedin_personal_urn", "")

    if token and author_urn and not settings._is_placeholder(token):
        return await _api_publish_linkedin(author_urn, token, text, platform)

    if settings.linkedin_pw_configured:
        return await _pw_publish_linkedin(text, settings, mode="personal")

    return PublishResult(platform=platform, success=False,
                         error="LinkedIn Personal: no API token or Playwright credentials configured")


# ─────────────────────────────────────────────────────────────────────────────
# Twitter / X — API path (OAuth 1.0a)
# ─────────────────────────────────────────────────────────────────────────────

_TWEET_RE = re.compile(r"Tweet\s+\d+:\s*", re.IGNORECASE)


def _parse_tweets(text: str) -> list[str]:
    """
    Parse the SocialMediaManagerAgent Twitter format:
        Tweet 1: [text]
        Tweet 2: [text]
    Returns list of clean strings; falls back to single tweet if format not found.
    """
    if _TWEET_RE.search(text):
        parts = _TWEET_RE.split(text)
        return [p.strip() for p in parts if p.strip()]
    return [text.strip()]


async def publish_twitter(text: str, settings: "Settings") -> PublishResult:
    """
    Publish a tweet or thread to Twitter/X.
    OAuth 1.0a, Twitter API v2 (POST /2/tweets).
    Requires: TWITTER_API_KEY, TWITTER_API_SECRET,
              TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET

    Falls back to Playwright with TWITTER_EMAIL + TWITTER_PASSWORD when API
    creds are absent.
    """
    platform = "twitter"
    api_key = getattr(settings, "twitter_api_key", "")
    api_secret = getattr(settings, "twitter_api_secret", "")
    access_token = getattr(settings, "twitter_access_token", "")
    access_token_secret = getattr(settings, "twitter_access_token_secret", "")

    if not all([api_key, api_secret, access_token, access_token_secret]):
        # phase-pw — Playwright fallback
        if getattr(settings, "twitter_email", "") and getattr(settings, "twitter_password", ""):
            return await _pw_publish_twitter(text, settings)
        return PublishResult(
            platform=platform, success=False,
            error="Twitter API credentials not configured and TWITTER_EMAIL/PASSWORD not set for Playwright fallback"
        )

    tweets = _parse_tweets(text)
    url = "https://api.twitter.com/2/tweets"
    first_id = ""
    first_url = ""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            reply_to: str | None = None
            for i, tweet_text in enumerate(tweets):
                payload: dict = {"text": tweet_text}
                if reply_to:
                    payload["reply"] = {"in_reply_to_tweet_id": reply_to}

                auth_header = _oauth1_auth_header(
                    "POST", url, api_key, api_secret, access_token, access_token_secret
                )
                headers = {
                    "Authorization": auth_header,
                    "Content-Type": "application/json",
                }
                resp = await client.post(url, json=payload, headers=headers)

                if resp.status_code not in (200, 201):
                    err = f"tweet {i+1} HTTP {resp.status_code}: {resp.text[:300]}"
                    logger.warning("twitter.api.failed", tweet_index=i, error=err)
                    return PublishResult(platform=platform, success=False, error=err)

                data = resp.json().get("data", {})
                tweet_id = data.get("id", "")
                if i == 0:
                    first_id = tweet_id
                    first_url = f"https://twitter.com/i/web/status/{tweet_id}"
                reply_to = tweet_id
                logger.info("twitter.api.tweet_posted", tweet_index=i, tweet_id=tweet_id)

        return PublishResult(platform=platform, success=True,
                             post_id=first_id, post_url=first_url)
    except Exception as exc:
        logger.exception("twitter.api.exception", exc=str(exc))
        return PublishResult(platform=platform, success=False, error=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Facebook — API path (Graph API)
# ─────────────────────────────────────────────────────────────────────────────

async def publish_facebook(text: str, settings: "Settings") -> PublishResult:
    """
    Publish a post to a Facebook Page.
    POST https://graph.facebook.com/v19.0/{page_id}/feed
    Requires: FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN
    """
    platform = "facebook"
    page_id = getattr(settings, "facebook_page_id", "")
    page_token = getattr(settings, "facebook_page_access_token", "")

    if not page_id or not page_token:
        # phase-pw — Playwright fallback
        if getattr(settings, "facebook_email", "") and getattr(settings, "facebook_password", ""):
            return await _pw_publish_facebook(text, settings)
        return PublishResult(
            platform=platform, success=False,
            error="Facebook credentials not configured and FACEBOOK_EMAIL/PASSWORD not set for Playwright fallback"
        )

    url = f"https://graph.facebook.com/v19.0/{page_id}/feed"
    payload = {"message": text, "access_token": page_token}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, data=payload)

        if resp.status_code in (200, 201):
            data = resp.json()
            post_id = data.get("id", "")
            if "_" in post_id:
                parts = post_id.split("_", 1)
                post_url = f"https://www.facebook.com/{parts[0]}/posts/{parts[1]}"
            else:
                post_url = ""
            logger.info("facebook.api.published", post_id=post_id)
            return PublishResult(platform=platform, success=True,
                                 post_id=post_id, post_url=post_url)
        err = f"HTTP {resp.status_code}: {resp.text[:300]}"
        logger.warning("facebook.api.failed", error=err)
        return PublishResult(platform=platform, success=False, error=err)
    except Exception as exc:
        logger.exception("facebook.api.exception", exc=str(exc))
        return PublishResult(platform=platform, success=False, error=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Instagram — Graph API v19.0 two-step publish
# ─────────────────────────────────────────────────────────────────────────────
#
# Instagram publish requires a publicly reachable image URL.  The image file
# must already be written to /opt/loki-agents/static/ig/ on the server so nginx
# can serve it at https://api.klaravex.com/static/ig/<filename>.
#
# Two-step flow:
#   1. POST /{user_id}/media   → container_id
#      Poll GET /{container_id}?fields=status_code until status_code == FINISHED
#   2. POST /{user_id}/media_publish  {creation_id: container_id}
#
# Text-only Instagram posts are NOT supported by the Graph API — an image_url
# is mandatory.  If no image_url is available, we return a graceful failure
# rather than crashing the publish pipeline.
#
# ─────────────────────────────────────────────────────────────────────────────

_IG_GRAPH_BASE = "https://graph.facebook.com/v19.0"
_IG_POLL_INTERVAL_S = 3      # seconds between status_code polls
_IG_POLL_MAX_ATTEMPTS = 20   # give up after 60 s (20 × 3 s)


async def publish_instagram(text: str, settings: "Settings") -> PublishResult:
    """
    Publish a captioned image post to Instagram Business Account.

    Requires: INSTAGRAM_USER_ID, INSTAGRAM_ACCESS_TOKEN (config.py).

    Image resolution order:
      1. Sentinel in draft text (explicit, highest priority):
             [ig_image_url: https://api.klaravex.com/static/ig/post_abc.jpg]
             <caption text>
      2. Auto-generated by Higgsfield (if HIGGSFIELD_API_KEY is set):
             generate_instagram_image_from_caption(caption, settings) is called,
             which creates a 4:5 Soul character image, saves it to
             /opt/loki-agents/static/ig/<slug>.jpg, and returns its public URL.
      3. Fallback to INSTAGRAM_IMAGE_BASE_URL/latest.jpg (static placeholder)
             if Higgsfield is not configured or generation fails.

    Instagram Graph API requires a publicly reachable HTTPS image URL.
    Text-only posts are not supported.
    """
    platform = "instagram"
    user_id = getattr(settings, "instagram_user_id", "")
    access_token = getattr(settings, "instagram_access_token", "")

    if not user_id or not access_token:
        return PublishResult(
            platform=platform, success=False,
            error="Instagram credentials not configured "
                  "(set INSTAGRAM_USER_ID and INSTAGRAM_ACCESS_TOKEN)",
        )

    # ── Parse image URL from draft sentinel ──────────────────────────────────
    sentinel_re = re.compile(
        r"\[ig_image_url:\s*(https?://[^\]]+)\]\s*",
        re.IGNORECASE,
    )
    sentinel_match = sentinel_re.search(text)
    if sentinel_match:
        # Explicit sentinel — use as-is.
        image_url = sentinel_match.group(1).strip()
        caption = sentinel_re.sub("", text).strip()
    else:
        caption = text

        if getattr(settings, "higgsfield_configured", False):
            # Auto-generate a branded 4:5 image via Higgsfield Soul character.
            try:
                logger.info(
                    "instagram.higgsfield.generating",
                    caption_preview=caption[:80],
                )
                image_url = await generate_instagram_image_from_caption(
                    caption, settings
                )
                logger.info("instagram.higgsfield.generated", image_url=image_url)
            except (HiggsFieldError, Exception) as exc:
                logger.warning(
                    "instagram.higgsfield.failed_fallback_to_latest",
                    error=str(exc),
                )
                base_url = getattr(
                    settings,
                    "instagram_image_base_url",
                    "https://api.klaravex.com/static/ig",
                )
                image_url = f"{base_url.rstrip('/')}/latest.jpg"
        else:
            # Higgsfield not configured — use static placeholder.
            base_url = getattr(
                settings,
                "instagram_image_base_url",
                "https://api.klaravex.com/static/ig",
            )
            image_url = f"{base_url.rstrip('/')}/latest.jpg"

    logger.info("instagram.api.starting",
                user_id=user_id, image_url=image_url,
                caption_len=len(caption))

    try:
        async with httpx.AsyncClient(timeout=30) as client:

            # ── Step 1: Create media container ────────────────────────────────
            container_resp = await client.post(
                f"{_IG_GRAPH_BASE}/{user_id}/media",
                data={
                    "image_url": image_url,
                    "caption": caption,
                    "access_token": access_token,
                },
            )
            if container_resp.status_code not in (200, 201):
                err = f"container create HTTP {container_resp.status_code}: {container_resp.text[:300]}"
                logger.warning("instagram.api.container_failed", error=err)
                return PublishResult(platform=platform, success=False, error=err)

            container_data = container_resp.json()
            container_id = container_data.get("id", "")
            if not container_id:
                err = f"No container ID in response: {container_data}"
                logger.warning("instagram.api.no_container_id", data=container_data)
                return PublishResult(platform=platform, success=False, error=err)

            logger.info("instagram.api.container_created", container_id=container_id)

            # ── Step 2: Poll until container status == FINISHED ───────────────
            for attempt in range(1, _IG_POLL_MAX_ATTEMPTS + 1):
                await asyncio.sleep(_IG_POLL_INTERVAL_S)
                status_resp = await client.get(
                    f"{_IG_GRAPH_BASE}/{container_id}",
                    params={"fields": "status_code", "access_token": access_token},
                )
                if status_resp.status_code != 200:
                    logger.warning("instagram.api.poll_error",
                                   attempt=attempt,
                                   http=status_resp.status_code)
                    continue

                status_code = status_resp.json().get("status_code", "")
                logger.info("instagram.api.poll",
                            attempt=attempt, status_code=status_code)

                if status_code == "FINISHED":
                    break
                if status_code == "ERROR":
                    err = f"Container processing error: {status_resp.text[:300]}"
                    logger.warning("instagram.api.container_error", error=err)
                    return PublishResult(platform=platform, success=False, error=err)
                # IN_PROGRESS or EXPIRED — keep polling
            else:
                err = (f"Container {container_id} did not reach FINISHED "
                       f"after {_IG_POLL_MAX_ATTEMPTS} attempts")
                logger.warning("instagram.api.poll_timeout", container_id=container_id)
                return PublishResult(platform=platform, success=False, error=err)

            # ── Step 3: Publish the container ─────────────────────────────────
            publish_resp = await client.post(
                f"{_IG_GRAPH_BASE}/{user_id}/media_publish",
                data={
                    "creation_id": container_id,
                    "access_token": access_token,
                },
            )
            if publish_resp.status_code not in (200, 201):
                err = f"publish HTTP {publish_resp.status_code}: {publish_resp.text[:300]}"
                logger.warning("instagram.api.publish_failed", error=err)
                return PublishResult(platform=platform, success=False, error=err)

            pub_data = publish_resp.json()
            media_id = pub_data.get("id", "")
            post_url = (
                f"https://www.instagram.com/p/{media_id}/"
                if media_id else ""
            )
            logger.info("instagram.api.published", media_id=media_id)
            return PublishResult(
                platform=platform, success=True,
                post_id=media_id, post_url=post_url,
            )

    except Exception as exc:
        logger.exception("instagram.api.exception", exc=str(exc))
        return PublishResult(platform=platform, success=False, error=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# TikTok — not yet implemented
# ─────────────────────────────────────────────────────────────────────────────

async def publish_tiktok(text: str, settings: "Settings") -> PublishResult:
    """
    TikTok Content Posting API requires video uploads only (no text-only posts).
    Text-only capability was added in Content Posting API v2 but requires partner
    access.  Implementation deferred — return a clear not-configured message so
    the publish pipeline doesn't crash when tiktok appears in the platform list.
    """
    logger.info("tiktok.api.not_configured")
    return PublishResult(
        platform="tiktok",
        success=False,
        error=(
            "TikTok publishing not yet configured. "
            "TikTok Content Posting API v2 requires a partner token. "
            "Configure TIKTOK_ACCESS_TOKEN and implement publish_tiktok() "
            "when the account is eligible."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch table + publish_all
# ─────────────────────────────────────────────────────────────────────────────

_PUBLISHERS = {
    "linkedin_company":  publish_linkedin_company,
    "linkedin_personal": publish_linkedin_personal,
    "twitter":           publish_twitter,
    "facebook":          publish_facebook,
    "instagram":         publish_instagram,
    "tiktok":            publish_tiktok,
    "reddit":            publish_reddit,
    "youtube":           publish_youtube,
}


async def _failed_result(platform: str, error: str) -> PublishResult:
    """Awaitable wrapper for an immediate failure result."""
    return PublishResult(platform=platform, success=False, error=error)


async def publish_all(
    drafts: dict[str, str],
    platforms: list[str],
    settings: "Settings",
) -> list[PublishResult]:
    """
    Publish to all requested platforms concurrently.

    Args:
        drafts:    Dict mapping platform key → draft text.
        platforms: List of platform keys to publish (subset of drafts keys).
        settings:  App settings with social media credentials.

    Returns:
        List[PublishResult] — one per requested platform, order preserved.
        Errors in one platform do NOT abort others.
    """
    tasks = []

    for platform in platforms:
        text = drafts.get(platform, "")
        if not text:
            logger.warning("publish_all.no_draft", platform=platform)
            tasks.append(_failed_result(platform, "No draft text provided"))
            continue

        publisher = _PUBLISHERS.get(platform)
        if publisher is None:
            logger.warning("publish_all.unknown_platform", platform=platform)
            tasks.append(_failed_result(platform, f"Unknown platform: {platform}"))
        else:
            tasks.append(publisher(text, settings))

    results: list[PublishResult] = await asyncio.gather(*tasks, return_exceptions=False)

    for r in results:
        logger.info(
            "publish_all.result",
            platform=r.platform,
            success=r.success,
            post_url=r.post_url or None,
            error=r.error or None,
        )

    return list(results)
