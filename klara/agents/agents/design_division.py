"""
app/agents/design_division.py
───────────────────────────────
DesignDivisionAgent — P3 coordinator for the content and design pipeline.

Orchestrates content creation, publishing, and translation workflows by
sequencing the appropriate sub-agents based on the trigger type:

  seo_content_brief   → seo_content_writer (drafts → P3 approval for publish)
  social_post         → social_media_manager (schedule or immediate)
  website_update      → website_deploy (always P3 approval — never auto-publishes)
  translation_sync    → translation_sync (read-only scan + email report)
  full_content_push   → seo_content_writer → social_media_manager → website_deploy

Permission level: P3 — the division coordinator operates at the highest
permission of any sub-agent it may invoke.  website_deploy never auto-
publishes; it always creates WordPress drafts and requires human review.
social_media_manager schedules posts on approval.

Callers should expect approval_required=True for website_update and
full_content_push triggers in production.
"""
from __future__ import annotations

import structlog

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel

logger = structlog.get_logger(__name__)

# ── Trigger constants ─────────────────────────────────────────────────────────
TRIGGER_SEO_CONTENT_BRIEF = "seo_content_brief"
TRIGGER_SOCIAL_POST       = "social_post"
TRIGGER_WEBSITE_UPDATE    = "website_update"
TRIGGER_TRANSLATION_SYNC  = "translation_sync"
TRIGGER_FULL_CONTENT_PUSH = "full_content_push"

VALID_TRIGGERS = {
    TRIGGER_SEO_CONTENT_BRIEF,
    TRIGGER_SOCIAL_POST,
    TRIGGER_WEBSITE_UPDATE,
    TRIGGER_TRANSLATION_SYNC,
    TRIGGER_FULL_CONTENT_PUSH,
}


class DesignDivisionAgent(BaseAgent):
    name = "design_division"
    description = (
        "High-level content and design coordinator. Accepts a trigger "
        "(seo_content_brief | social_post | website_update | translation_sync | "
        "full_content_push) and orchestrates the correct sub-agent sequence. "
        "P3 — website_update always creates WP drafts and requires approval. "
        "full_content_push sequences SEO → social → website deploy."
    )
    permission_level = PermissionLevel.P3

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        trigger: str = input_data.get("trigger", TRIGGER_SEO_CONTENT_BRIEF)

        log.info("design_division.start", trigger=trigger)

        if trigger not in VALID_TRIGGERS:
            return AgentResult.fail(
                error=f"Unknown trigger '{trigger}'. Valid: {sorted(VALID_TRIGGERS)}"
            )

        from app.agents.registry import registry

        # ── Dispatch table ─────────────────────────────────────────────────────
        if trigger == TRIGGER_SEO_CONTENT_BRIEF:
            return await self._run_seo_content_brief(context, input_data, registry, log)

        elif trigger == TRIGGER_SOCIAL_POST:
            return await self._run_social_post(context, input_data, registry, log)

        elif trigger == TRIGGER_WEBSITE_UPDATE:
            return await self._run_website_update(context, input_data, registry, log)

        elif trigger == TRIGGER_TRANSLATION_SYNC:
            return await self._run_translation_sync(context, input_data, registry, log)

        elif trigger == TRIGGER_FULL_CONTENT_PUSH:
            return await self._run_full_content_push(context, input_data, registry, log)

        return AgentResult.fail(error=f"Unhandled trigger: {trigger}")

    # ── Trigger handlers ───────────────────────────────────────────────────────

    async def _run_seo_content_brief(self, context, input_data, registry, log) -> AgentResult:
        """
        Generate an SEO content draft.
        input_data should include: topic, target_keyword, language ('en'|'de')
        Draft is stored in DB — requires separate approval to publish.
        """
        topic: str = input_data.get("topic", "")
        if not topic:
            return AgentResult.fail(error="seo_content_brief trigger requires 'topic'")

        try:
            writer = registry.get("seo_content_writer")
            result = await writer(context, input_data)
            log.info(
                "design_division.seo_content_ok",
                success=result.success,
                topic=topic,
            )

            if result.approval_required:
                return AgentResult.needs_approval(
                    approval_id=result.approval_id,
                    action="seo_content_writer.publish",
                )

            return AgentResult.ok(
                output={
                    "trigger": TRIGGER_SEO_CONTENT_BRIEF,
                    "steps_completed": ["seo_content_writer"],
                    "content": result.output,
                    "note": "Content is drafted. Use website_update trigger to push to WordPress.",
                }
            )
        except Exception as exc:
            log.error("design_division.seo_content_error", error=str(exc))
            return AgentResult.fail(error=f"SEO content generation failed: {exc}")

    async def _run_social_post(self, context, input_data, registry, log) -> AgentResult:
        """
        Create and schedule a social media post.
        input_data should include: platform, content (or topic), scheduled_at (optional)
        Requires social_media_manager — content goes through approval queue.
        """
        if not (input_data.get("content") or input_data.get("topic")):
            return AgentResult.fail(
                error="social_post trigger requires 'content' or 'topic'"
            )

        try:
            social = registry.get("social_media_manager")
            result = await social(context, input_data)

            if result.approval_required:
                return AgentResult.needs_approval(
                    approval_id=result.approval_id,
                    action="social_media_manager.publish",
                )

            log.info("design_division.social_post_ok", success=result.success)
            return AgentResult.ok(
                output={
                    "trigger": TRIGGER_SOCIAL_POST,
                    "steps_completed": ["social_media_manager"],
                    "post": result.output,
                }
            )
        except Exception as exc:
            log.error("design_division.social_post_error", error=str(exc))
            return AgentResult.fail(error=f"Social post failed: {exc}")

    async def _run_website_update(self, context, input_data, registry, log) -> AgentResult:
        """
        Push content to WordPress as a draft.
        NEVER auto-publishes. Always creates a WP draft via REST API.
        Requires P3 approval gate in production.
        input_data should include: page_slug (or page_id), content, title
        """
        if not (input_data.get("page_slug") or input_data.get("page_id")):
            return AgentResult.fail(
                error="website_update trigger requires 'page_slug' or 'page_id'"
            )

        if not input_data.get("content"):
            return AgentResult.fail(error="website_update trigger requires 'content'")

        # P3 approval gate in production
        if context.settings.is_production:
            try:
                from app.agents.registry import registry as reg
                approval_mgr = reg.get("approval_manager")
                approval_result = await approval_mgr(
                    context,
                    {
                        "action": "create",
                        "action_name": "website_deploy.push_draft",
                        "risk_level": "P3",
                        "payload": input_data,
                        "justification": (
                            f"Website update: {input_data.get('title', 'untitled')} "
                            f"→ /{input_data.get('page_slug', input_data.get('page_id'))}"
                        ),
                        "requested_by": self.name,
                    },
                )
                if approval_result.success:
                    return AgentResult.needs_approval(
                        approval_id=approval_result.output["approval_id"],
                        action="website_deploy.push_draft",
                    )
            except Exception as exc:
                log.error("design_division.website_approval_error", error=str(exc))
                return AgentResult.fail(error=f"Approval gate error: {exc}")

        # Dev/staging: fire immediately
        try:
            deploy = registry.get("website_deploy")
            result = await deploy(context, input_data)
            log.info("design_division.website_update_ok", success=result.success)
            return AgentResult.ok(
                output={
                    "trigger": TRIGGER_WEBSITE_UPDATE,
                    "steps_completed": ["website_deploy"],
                    "deploy": result.output,
                    "note": "WP draft created. Must be reviewed and published manually.",
                }
            )
        except Exception as exc:
            log.error("design_division.website_update_error", error=str(exc))
            return AgentResult.fail(error=f"Website update failed: {exc}")

    async def _run_translation_sync(self, context, input_data, registry, log) -> AgentResult:
        """
        Scan /de/ pages for untranslated English blocks and email report to Anthony.
        Read-only. Never modifies any content.
        """
        try:
            sync = registry.get("translation_sync")
            result = await sync(context, input_data)
            log.info("design_division.translation_sync_ok", success=result.success)
            return AgentResult.ok(
                output={
                    "trigger": TRIGGER_TRANSLATION_SYNC,
                    "steps_completed": ["translation_sync"],
                    "report": result.output,
                }
            )
        except Exception as exc:
            log.error("design_division.translation_sync_error", error=str(exc))
            return AgentResult.fail(error=f"Translation sync failed: {exc}")

    async def _run_full_content_push(self, context, input_data, registry, log) -> AgentResult:
        """
        End-to-end content publishing sequence.
        Generates SEO content → schedules social post → pushes WP draft.
        All three steps run sequentially.  A failure in SEO generation aborts
        the sequence.  Social and website steps are attempted independently.

        Required input_data keys: topic, target_keyword, language
        Optional: platform (social), page_slug (WP target)
        """
        topic: str = input_data.get("topic", "")
        if not topic:
            return AgentResult.fail(error="full_content_push trigger requires 'topic'")

        steps_completed: list[str] = []
        output: dict = {"trigger": TRIGGER_FULL_CONTENT_PUSH}

        # Step 1: SEO content (required)
        try:
            writer = registry.get("seo_content_writer")
            seo_result = await writer(context, input_data)
            if seo_result.success and seo_result.output:
                output["seo_content"] = seo_result.output
                steps_completed.append("seo_content_writer")
                log.info("design_division.full_push_seo_ok", topic=topic)
            else:
                return AgentResult.fail(
                    error=f"SEO content generation failed: {seo_result.error}",
                    steps_completed=steps_completed,
                )
        except Exception as exc:
            log.error("design_division.full_push_seo_error", error=str(exc))
            return AgentResult.fail(error=f"SEO content error: {exc}")

        # Step 2: Social post (non-fatal; uses SEO content as source material)
        social_payload = {
            **input_data,
            "content": (
                seo_result.output.get("summary") or seo_result.output.get("content", "")[:280]
            ),
            "source_type": "seo_content",
        }
        try:
            social = registry.get("social_media_manager")
            social_result = await social(context, social_payload)
            if social_result.success:
                output["social_post"] = social_result.output
                steps_completed.append("social_media_manager")
                log.info("design_division.full_push_social_ok")
            elif social_result.approval_required:
                output["social_approval_id"] = social_result.approval_id
                steps_completed.append("social_media_manager:pending_approval")
            else:
                log.warning("design_division.full_push_social_failed", error=social_result.error)
        except Exception as exc:
            log.warning("design_division.full_push_social_error", error=str(exc))

        # Step 3: Website deploy (P3 gate — will return needs_approval in production)
        if input_data.get("page_slug") or input_data.get("page_id"):
            website_payload = {
                **input_data,
                "content": seo_result.output.get("content", ""),
                "title": seo_result.output.get("title", topic),
            }
            # P3 approval gate
            if context.settings.is_production:
                try:
                    approval_mgr = registry.get("approval_manager")
                    approval_result = await approval_mgr(
                        context,
                        {
                            "action": "create",
                            "action_name": "website_deploy.push_draft",
                            "risk_level": "P3",
                            "payload": website_payload,
                            "justification": (
                                f"Full content push: {topic} → "
                                f"/{input_data.get('page_slug', input_data.get('page_id'))}"
                            ),
                            "requested_by": self.name,
                        },
                    )
                    if approval_result.success:
                        output["website_approval_id"] = approval_result.output["approval_id"]
                        steps_completed.append("website_deploy:pending_approval")
                        log.info("design_division.full_push_website_approval_queued")
                except Exception as exc:
                    log.warning("design_division.full_push_website_approval_error", error=str(exc))
            else:
                try:
                    deploy = registry.get("website_deploy")
                    deploy_result = await deploy(context, website_payload)
                    if deploy_result.success:
                        output["website_deploy"] = deploy_result.output
                        steps_completed.append("website_deploy")
                except Exception as exc:
                    log.warning("design_division.full_push_website_error", error=str(exc))

        output["steps_completed"] = steps_completed
        log.info("design_division.full_push_complete", steps=steps_completed)
        return AgentResult.ok(output=output)
