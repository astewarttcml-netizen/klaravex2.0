"""
app/agents/website_deploy.py
WebsiteDeployAgent -- P3 outbound.

Pushes content changes to WordPress via the WP REST API.

Behaviour contract:
  - NEVER sets status: publish on any WP page.  Always status: draft.
  - NEVER auto-executes writes.  Every write goes through the P3 approval gate.
  - Logs every operation (queue, approve, execute, complete, fail) to audit_logger.

The agent exposes two logical operations via input_data['action']:

  "queue"
      Stores a new WebsiteDeployJob with status=PENDING, then returns
      AgentResult.needs_approval() so the caller knows human sign-off is needed.

  "execute"
      Fetches the already-approved job by job_id, performs the WP REST API
      PATCH, and marks the job COMPLETED or FAILED.
      Called exclusively by the /approve/{job_id} admin endpoint after the
      operator has confirmed the action.

WP credentials:
  WP_APP_USERNAME  -- WordPress admin username (env var, sourced from Settings)
  WP_APP_PASSWORD  -- WordPress Application Password (env var, sourced from Settings)

  Authentication: HTTP Basic Auth with WP Application Password.
    All write operations send the Authorization header directly to WP REST API
    (/wp-json/wp/v2/*).  LiteSpeed passes Authorization headers through to
    /wp-json/ endpoints without stripping.  Application Passwords cannot
    authenticate via wp-login.php form POST, so cookie-based auth is not used.
"""
from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime, timezone
from typing import Any

import aiohttp
import structlog

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.website_deploy import DeployJobStatus, WebsiteDeployJob

logger = structlog.get_logger(__name__)


class WebsiteDeployAgent(BaseAgent):
    name = "website_deploy"
    description = (
        "Pushes page content updates to WordPress as drafts via the WP REST API. "
        "All writes require P3 human approval -- never auto-executes."
    )
    permission_level = PermissionLevel.P2

    # -------------------------------------------------------------------------
    # Public entry point
    # -------------------------------------------------------------------------

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        action = input_data.get("action")
        if action == "queue":
            return await self._queue(context, input_data)
        if action == "execute":
            return await self._execute(context, input_data)
        if action == "flush_rewrites":
            return await self._flush_rewrites(context)
        if action == "create_post":
            return await self._create_post(context, input_data)
        return AgentResult.fail(
            f"website_deploy: unknown action '{action}'. Expected 'queue', 'execute', 'create_post', or 'flush_rewrites'.",
            agent=self.name,
        )

    # -------------------------------------------------------------------------
    # Queue operation
    # -------------------------------------------------------------------------

    async def _queue(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        Store a new deploy job with status=PENDING.
        Returns AgentResult.needs_approval() with the job_id.
        """
        log = logger.bind(
            agent=self.name,
            job_action="queue",
            page_id=input_data.get("page_id"),
            request_id=context.request_id,
        )

        page_id = input_data.get("page_id")
        page_title = input_data.get("page_title", "")
        new_content = input_data.get("new_content", "")
        queued_by = input_data.get("queued_by", "api")

        if not page_id:
            return AgentResult.fail("website_deploy.queue: 'page_id' is required.", agent=self.name)
        if not new_content:
            return AgentResult.fail("website_deploy.queue: 'new_content' is required.", agent=self.name)

        # Best-effort: fetch the current page content and store its hash
        old_content_hash = await self._fetch_current_content_hash(
            context, int(page_id)
        )

        job = WebsiteDeployJob(
            page_id=int(page_id),
            page_title=page_title,
            new_content=new_content,
            old_content_hash=old_content_hash,
            status=DeployJobStatus.PENDING,
            queued_by=queued_by,
        )
        context.db.add(job)
        await context.db.flush()

        log.info(
            "website_deploy.queued",
            job_id=job.id,
            page_id=job.page_id,
            status=job.status,
            queued_by=queued_by,
        )

        await self._audit(
            context,
            event_type="website_deploy.queued",
            job_id=job.id,
            page_id=job.page_id,
            status=job.status,
            queued_by=queued_by,
            success=True,
        )

        return AgentResult.needs_approval(
            approval_id=job.id,
            action=f"Push draft to WP page {page_id} ({page_title})",
        )

    # -------------------------------------------------------------------------
    # Execute operation (called post-approval)
    # -------------------------------------------------------------------------

    async def _execute(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        Fetch the APPROVED job, call the WP REST API, mark COMPLETED or FAILED.
        Called only by the admin approve endpoint -- never triggered automatically.
        """
        job_id = input_data.get("job_id")
        if not job_id:
            return AgentResult.fail("website_deploy.execute: 'job_id' is required.", agent=self.name)

        from sqlalchemy import select

        stmt = select(WebsiteDeployJob).where(WebsiteDeployJob.id == job_id)
        result = await context.db.execute(stmt)
        job: WebsiteDeployJob | None = result.scalar_one_or_none()

        if not job:
            return AgentResult.fail(f"website_deploy.execute: job '{job_id}' not found.", agent=self.name)

        if job.status not in (DeployJobStatus.PENDING, DeployJobStatus.APPROVED):
            return AgentResult.fail(
                f"website_deploy.execute: job '{job_id}' has status '{job.status}' -- "
                f"only PENDING or APPROVED jobs can be executed.",
                agent=self.name,
            )

        log = logger.bind(
            agent=self.name,
            job_action="execute",
            job_id=job.id,
            page_id=job.page_id,
            request_id=context.request_id,
        )

        # Mark APPROVED then EXECUTING before the HTTP call
        job.status = DeployJobStatus.APPROVED
        job.approved_at = datetime.now(timezone.utc)
        await context.db.flush()

        job.status = DeployJobStatus.EXECUTING
        await context.db.flush()

        log.info("website_deploy.executing", job_id=job.id, page_id=job.page_id, status=job.status)

        # WP REST API call
        wp_result = await self._push_to_wordpress(context, job)

        if wp_result["ok"]:
            job.status = DeployJobStatus.COMPLETED
            job.executed_at = datetime.now(timezone.utc)
            await context.db.flush()

            log.info(
                "website_deploy.completed",
                job_id=job.id,
                page_id=job.page_id,
                status=job.status,
                wp_draft_id=wp_result.get("wp_id"),
            )

            await self._audit(
                context,
                event_type="website_deploy.completed",
                job_id=job.id,
                page_id=job.page_id,
                status=job.status,
                wp_draft_id=wp_result.get("wp_id"),
                success=True,
            )

            return AgentResult.ok(
                output={
                    "job_id": job.id,
                    "page_id": job.page_id,
                    "page_title": job.page_title,
                    "status": job.status,
                    "wp_draft_id": wp_result.get("wp_id"),
                    "executed_at": job.executed_at.isoformat(),
                }
            )
        else:
            error_msg = wp_result.get("error", "Unknown WP API error")
            job.status = DeployJobStatus.FAILED
            job.executed_at = datetime.now(timezone.utc)
            job.error_message = error_msg
            await context.db.flush()

            log.error(
                "website_deploy.failed",
                job_id=job.id,
                page_id=job.page_id,
                status=job.status,
                error=error_msg,
            )

            await self._audit(
                context,
                event_type="website_deploy.failed",
                job_id=job.id,
                page_id=job.page_id,
                status=job.status,
                error=error_msg,
                success=False,
            )

            return AgentResult.fail(
                error_msg,
                job_id=job.id,
                page_id=job.page_id,
                status=job.status,
            )

    # -------------------------------------------------------------------------
    # Flush WP rewrite rules
    # -------------------------------------------------------------------------

    async def _flush_rewrites(self, context: AgentContext) -> AgentResult:
        """
        Trigger a WordPress rewrite rules flush via the WP REST API settings
        endpoint using Application Password Basic Auth.

        Posting permalink_structure back to /wp-json/wp/v2/settings calls
        flush_rewrite_rules() server-side as a side effect, identical to an
        admin visiting Permalink Settings and clicking Save Changes.
        """
        log = logger.bind(agent=self.name, job_action="flush_rewrites")
        settings = context.settings
        wp_username = getattr(settings, "wp_app_username", "")
        wp_password = getattr(settings, "wp_app_password", "")
        site = settings.wp_site_url.rstrip("/")

        if not wp_username or not wp_password:
            return AgentResult.fail(
                "flush_rewrites: WP_APP_USERNAME or WP_APP_PASSWORD not configured.",
                agent=self.name,
            )

        settings_url = f"{site}/wp-json/wp/v2/settings"
        auth_header = self._basic_auth_header(wp_username, wp_password)

        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession() as http:

                # Read current permalink_structure so we can post it back unchanged
                async with http.get(
                    settings_url,
                    headers={"Authorization": auth_header},
                    timeout=timeout,
                ) as resp:
                    if resp.status != 200:
                        return AgentResult.fail(
                            f"flush_rewrites: GET /wp-json/wp/v2/settings returned HTTP {resp.status}",
                            agent=self.name,
                        )
                    current = await resp.json(content_type=None)
                    permalink_structure = current.get("permalink_structure", "/%postname%/") or "/%postname%/"

                log.info("flush_rewrites.current_structure", permalink_structure=permalink_structure)

                # POST the same value back -- side effect: flush_rewrite_rules()
                async with http.post(
                    settings_url,
                    json={"permalink_structure": permalink_structure},
                    headers={
                        "Authorization": auth_header,
                        "Content-Type": "application/json",
                    },
                    timeout=timeout,
                ) as resp:
                    if resp.status not in (200, 201):
                        return AgentResult.fail(
                            f"flush_rewrites: POST /wp-json/wp/v2/settings returned HTTP {resp.status}",
                            agent=self.name,
                        )

            log.info("flush_rewrites.complete", permalink_structure=permalink_structure)
            await self._audit(
                context,
                event_type="website_deploy.flush_rewrites",
                success=True,
            )

            return AgentResult.ok(
                output={
                    "flushed": True,
                    "permalink_structure": permalink_structure,
                    "message": "WordPress rewrite rules flushed successfully.",
                }
            )

        except aiohttp.ClientError as exc:
            log.error("flush_rewrites.connection_error", error=str(exc))
            return AgentResult.fail(
                f"flush_rewrites: WP connection error: {exc}", agent=self.name
            )
        except Exception as exc:
            log.error("flush_rewrites.unexpected_error", error=str(exc), exc_info=True)
            return AgentResult.fail(
                f"flush_rewrites: unexpected error: {exc}", agent=self.name
            )

    # -------------------------------------------------------------------------
    # WP REST API helper -- Basic Auth
    # -------------------------------------------------------------------------

    async def _push_to_wordpress(
        self, context: AgentContext, job: WebsiteDeployJob
    ) -> dict[str, Any]:
        """
        Push content to an existing WordPress page using Application Password
        Basic Auth against the WP REST API.

        Returns:
            {"ok": True, "wp_id": <int>}    on HTTP 200/201
            {"ok": False, "error": "<msg>"}  on any failure
        """
        settings = context.settings
        wp_username = getattr(settings, "wp_app_username", "")
        wp_password = getattr(settings, "wp_app_password", "")
        site = settings.wp_site_url.rstrip("/")

        if not wp_username or not wp_password:
            return {
                "ok": False,
                "error": "WP_APP_USERNAME or WP_APP_PASSWORD not configured.",
            }

        log = logger.bind(
            agent=self.name,
            job_id=job.id,
            page_id=job.page_id,
        )

        url = f"{site}/wp-json/wp/v2/pages/{job.page_id}"
        payload = {
            "title": job.page_title,
            "content": job.new_content,
            "status": "draft",  # HARD RULE: always draft -- never publish
        }
        auth_header = self._basic_auth_header(wp_username, wp_password)

        try:
            async with aiohttp.ClientSession() as http:
                async with http.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": auth_header,
                        "Content-Type": "application/json",
                    },
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    body = await resp.json(content_type=None)
                    if resp.status in (200, 201):
                        log.info(
                            "website_deploy.wp_api_success",
                            http_status=resp.status,
                            wp_id=body.get("id"),
                            wp_status=body.get("status"),
                        )
                        return {"ok": True, "wp_id": body.get("id")}
                    else:
                        error_detail = body.get("message", str(body))
                        log.error(
                            "website_deploy.wp_api_error",
                            http_status=resp.status,
                            wp_error=error_detail,
                        )
                        return {
                            "ok": False,
                            "error": f"WP API HTTP {resp.status}: {error_detail}",
                        }

        except aiohttp.ClientError as exc:
            log.error("website_deploy.wp_connection_error", error=str(exc))
            return {"ok": False, "error": f"WP connection error: {exc}"}
        except Exception as exc:
            log.error("website_deploy.wp_unexpected_error", error=str(exc), exc_info=True)
            return {"ok": False, "error": f"Unexpected error: {exc}"}

    # -------------------------------------------------------------------------
    # Best-effort: hash existing WP page content
    # -------------------------------------------------------------------------

    async def _fetch_current_content_hash(
        self, context: AgentContext, page_id: int
    ) -> str | None:
        """
        GET the current WP page (unauthenticated public endpoint) and return
        SHA-256 of its rendered content.  Returns None on any failure -- this is
        best-effort only and must never block job creation.

        The public REST endpoint (/wp-json/wp/v2/pages/{id}) returns rendered
        content without authentication for published pages.
        """
        settings = context.settings
        url = f"{settings.wp_site_url.rstrip('/')}/wp-json/wp/v2/pages/{page_id}"
        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        body = await resp.json(content_type=None)
                        rendered = body.get("content", {}).get("rendered", "")
                        return hashlib.sha256(rendered.encode()).hexdigest()
        except Exception:
            pass  # Non-fatal

        return None

    # -------------------------------------------------------------------------
    # Create new WP post/page (SEO content publish, translation create_post)
    # -------------------------------------------------------------------------

    async def _create_post(self, context: AgentContext, input_data: dict) -> AgentResult:
        """
        Create a NEW WordPress post (or page) as a draft from SEO content data.
        Called by execute_approved_action._run_seo_publish after P3 approval.

        Required input_data keys:
          title        -- post title (str)
          content_html -- rendered HTML body (str)

        Optional:
          keyword      -- used to derive the slug (str)
          meta         -- SEO description string used as excerpt (str)
          post_type    -- "post" (default) or "page"
          language     -- "en" or "de" (logged only for now)
        """
        title        = input_data.get("title", "").strip()
        content_html = input_data.get("content_html", "").strip()
        keyword      = input_data.get("keyword", "").strip()
        meta         = input_data.get("meta", "")
        post_type    = input_data.get("post_type", "post")
        language     = input_data.get("language", "en")

        if not title:
            return AgentResult.fail("website_deploy.create_post: 'title' is required.", agent=self.name)
        if not content_html:
            return AgentResult.fail("website_deploy.create_post: 'content_html' is required.", agent=self.name)

        # Derive slug from keyword (fallback to title)
        import re as _re
        slug_source = keyword or title
        slug = _re.sub(r"[^a-z0-9]+", "-", slug_source.lower()).strip("-")

        # meta may be a dict or a plain string depending on the agent that created it
        excerpt = meta if isinstance(meta, str) else (meta.get("description", "") if isinstance(meta, dict) else "")

        log = logger.bind(
            agent=self.name,
            job_action="create_post",
            post_type=post_type,
            language=language,
            slug=slug,
            request_id=context.request_id,
        )
        log.info("website_deploy.create_post_start", title=title, keyword=keyword)

        wp_result = await self._create_wp_post_via_rest(
            context,
            title=title,
            content_html=content_html,
            excerpt=excerpt,
            slug=slug,
            post_type=post_type,
        )

        if wp_result["ok"]:
            wp_post_id = wp_result.get("wp_id")
            log.info("website_deploy.create_post_complete", wp_post_id=wp_post_id)
            await self._audit(
                context,
                event_type="website_deploy.create_post_complete",
                wp_post_id=wp_post_id,
                title=title,
                slug=slug,
                post_type=post_type,
                language=language,
                success=True,
            )
            return AgentResult.ok(
                output={
                    "wp_post_id": wp_post_id,
                    "title": title,
                    "slug": slug,
                    "post_type": post_type,
                    "status": "draft",
                    "note": "WP draft created. Publish manually via WP admin.",
                }
            )
        else:
            error = wp_result.get("error", "Unknown WP error")
            log.error("website_deploy.create_post_failed", error=error)
            await self._audit(
                context,
                event_type="website_deploy.create_post_failed",
                title=title,
                slug=slug,
                error=error,
                success=False,
            )
            return AgentResult.fail(
                f"website_deploy.create_post: WP API error -- {error}",
                agent=self.name,
            )

    async def _create_wp_post_via_rest(
        self,
        context: AgentContext,
        *,
        title: str,
        content_html: str,
        excerpt: str,
        slug: str,
        post_type: str,
    ) -> dict:
        """
        Create a new WP post/page via REST API using Application Password Basic Auth.

        Returns {"ok": True, "wp_id": <int>} or {"ok": False, "error": "<msg>"}
        """
        settings = context.settings
        wp_username = getattr(settings, "wp_app_username", "")
        wp_password = getattr(settings, "wp_app_password", "")
        site = settings.wp_site_url.rstrip("/")

        if not wp_username or not wp_password:
            return {"ok": False, "error": "WP_APP_USERNAME or WP_APP_PASSWORD not configured."}

        # WP REST endpoint differs for posts vs pages
        wp_endpoint = "posts" if post_type != "page" else "pages"
        rest_url = f"{site}/wp-json/wp/v2/{wp_endpoint}"
        auth_header = self._basic_auth_header(wp_username, wp_password)

        log = logger.bind(agent=self.name, rest_url=rest_url, slug=slug)

        post_payload: dict = {
            "title":   title,
            "content": content_html,
            "status":  "draft",   # HARD RULE: always draft -- never publish directly
            "slug":    slug,
        }
        if excerpt:
            post_payload["excerpt"] = excerpt

        try:
            async with aiohttp.ClientSession() as http:
                async with http.post(
                    rest_url,
                    json=post_payload,
                    headers={
                        "Authorization": auth_header,
                        "Content-Type": "application/json",
                    },
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    body = await resp.json(content_type=None)
                    if resp.status in (200, 201):
                        log.info(
                            "website_deploy.create_post_wp_api_success",
                            http_status=resp.status,
                            wp_id=body.get("id"),
                            wp_status=body.get("status"),
                            wp_link=body.get("link"),
                        )
                        return {"ok": True, "wp_id": body.get("id"), "wp_link": body.get("link")}
                    else:
                        error_detail = body.get("message", str(body))
                        log.error(
                            "website_deploy.create_post_wp_api_error",
                            http_status=resp.status,
                            wp_error=error_detail,
                        )
                        return {"ok": False, "error": f"WP API HTTP {resp.status}: {error_detail}"}

        except aiohttp.ClientError as exc:
            log.error("website_deploy.create_post_connection_error", error=str(exc))
            return {"ok": False, "error": f"WP connection error: {exc}"}
        except Exception as exc:
            log.error("website_deploy.create_post_unexpected_error", error=str(exc), exc_info=True)
            return {"ok": False, "error": f"Unexpected error: {exc}"}

    # -------------------------------------------------------------------------
    # Auth helper
    # -------------------------------------------------------------------------

    @staticmethod
    def _basic_auth_header(username: str, password: str) -> str:
        """Return an HTTP Basic Auth header value for the given credentials."""
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        return f"Basic {token}"

    # -------------------------------------------------------------------------
    # Audit helper
    # -------------------------------------------------------------------------

    async def _audit(self, context: AgentContext, **kwargs: Any) -> None:
        """
        Delegate to audit_logger agent.  Swallow any failure -- audit logging
        must never block the main operation.
        """
        from app.agents.registry import registry

        try:
            audit_agent = registry.get("audit_logger")
            event_type = kwargs.pop("event_type")
            await audit_agent(
                context,
                {
                    "event_type": event_type,
                    "agent_name": self.name,
                    "action_name": event_type,
                    "details": kwargs,
                    "success": kwargs.get("success", True),
                    "error_message": kwargs.get("error"),
                },
            )
        except Exception as exc:
            logger.warning(
                "website_deploy.audit_failed",
                error=str(exc),
                agent=self.name,
            )
