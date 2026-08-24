"""
app/services/content_audit.py
──────────────────────────────
Content audit service.

Workflow:
  1. Agent identifies a potential change (typo, outdated info, tone issue)
  2. ContentAuditService.propose_change() creates a ContentRevision record + Approval record
  3. Human reviews the diff in the approval dashboard (before/after)
  4. On approve: publish_revision() applies the change
  5. On reject: mark revision as rejected, log reason

All public content changes go through this flow — no silent edits.

Change types: typo_fix, tone_update, factual_update, seo_update, structure_change
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalRequest, ApprovalStatus, RiskLevel
from app.models.audit import AuditLog
from app.models.content_tracking import ContentPage, ContentRevision, RevisionStatus

logger = structlog.get_logger(__name__)

VALID_CHANGE_TYPES = frozenset(
    {"typo_fix", "tone_update", "factual_update", "seo_update", "structure_change"}
)


class ContentAuditService:
    """Service layer for content audit tasks."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    async def propose_change(
        self,
        page_id: str,
        original_content: str,
        proposed_content: str,
        change_type: str,
        rationale: str,
        author_agent: str,
    ) -> tuple[str, str]:
        """
        Propose a content change for a given page.

        Steps:
          1. Validate page_id exists in ContentPage.
          2. Run bilingual validation (imports bilingual_rules to avoid circular dep).
          3. Create ContentRevision with status=pending_approval.
          4. Create linked ApprovalRequest.

        Returns:
            (revision_id, approval_id)

        Raises:
            ValueError: if page_id not found, change_type invalid, or bilingual
                        validation fails with blocking errors.
        """
        # ── Validate change_type ──────────────────────────────────────────────
        if change_type not in VALID_CHANGE_TYPES:
            raise ValueError(
                f"Invalid change_type {change_type!r}. "
                f"Must be one of: {', '.join(sorted(VALID_CHANGE_TYPES))}"
            )

        # ── Validate page exists ──────────────────────────────────────────────
        page_result = await self.db.execute(
            select(ContentPage).where(ContentPage.id == page_id)
        )
        page: Optional[ContentPage] = page_result.scalar_one_or_none()
        if page is None:
            raise ValueError(f"ContentPage not found: {page_id}")

        # ── Bilingual validation ──────────────────────────────────────────────
        from app.services.bilingual_rules import validate_content_revision_data

        validation = validate_content_revision_data(
            page_slug=page.slug,
            page_language=page.language,
            proposed_content=proposed_content,
            change_type=change_type,
        )
        if not validation.passed and validation.errors:
            raise ValueError(
                f"Bilingual validation failed: {'; '.join(validation.errors)}"
            )

        # ── Build diff summary ────────────────────────────────────────────────
        diff_summary = self.get_diff_summary(original_content, proposed_content)

        # ── Create ContentRevision ────────────────────────────────────────────
        revision = ContentRevision(
            id=str(uuid4()),
            page_id=page_id,
            status=RevisionStatus.pending_approval,
            proposed_by=author_agent,
            diff_summary=diff_summary,
            content_snapshot=proposed_content,
        )
        self.db.add(revision)
        await self.db.flush()   # get revision.id before creating Approval

        # ── Create ApprovalRequest ────────────────────────────────────────────
        payload = {
            "page_id": page_id,
            "page_slug": page.slug,
            "page_title": page.title,
            "revision_id": revision.id,
            "change_type": change_type,
            "rationale": rationale,
            "diff_summary": diff_summary,
            "original_content": original_content,
            "proposed_content": proposed_content,
            "bilingual_warnings": validation.warnings,
        }
        approval = ApprovalRequest(
            id=str(uuid4()),
            action_name="publish_content",
            risk_level=RiskLevel.p3,
            payload=json.dumps(payload, ensure_ascii=False),
            justification=rationale,
            requested_by_agent=author_agent,
            status=ApprovalStatus.pending,
        )
        self.db.add(approval)
        await self.db.flush()

        # ── Back-link revision → approval ─────────────────────────────────────
        revision.approval_request_id = approval.id
        self.db.add(revision)

        logger.info(
            "content_audit.change_proposed",
            page_id=page_id,
            page_slug=page.slug,
            change_type=change_type,
            revision_id=revision.id,
            approval_id=approval.id,
            author=author_agent,
        )

        return revision.id, approval.id

    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_diff_summary(original: str, proposed: str) -> str:
        """
        Return a human-readable diff summary (max 500 chars).

        Reports: lines added, lines removed, and up to 3 representative edits.
        Does not require any third-party diff library.
        """
        orig_lines = original.splitlines()
        prop_lines = proposed.splitlines()

        orig_set = set(orig_lines)
        prop_set = set(prop_lines)

        added = [l for l in prop_lines if l not in orig_set and l.strip()]
        removed = [l for l in orig_lines if l not in prop_set and l.strip()]

        parts: list[str] = []
        parts.append(f"+{len(added)} line(s) added, -{len(removed)} line(s) removed.")

        sample_adds = [f'  + "{l[:60]}"' for l in added[:2]]
        sample_removes = [f'  - "{l[:60]}"' for l in removed[:2]]

        if sample_removes:
            parts.append("Removed: " + "; ".join(r.strip() for r in sample_removes))
        if sample_adds:
            parts.append("Added: " + "; ".join(a.strip() for a in sample_adds))

        summary = "  ".join(parts)
        if len(summary) > 500:
            summary = summary[:497] + "..."
        return summary

    # ─────────────────────────────────────────────────────────────────────────

    async def publish_revision(
        self, revision_id: str, approved_by: str
    ) -> str:
        """
        Publish a pending revision.

        - Sets status = published
        - Sets published_at = now (UTC)
        - Updates ContentPage.current_revision_id
        - Logs content.revision_published

        Returns:
            The published content snapshot.

        Raises:
            ValueError: revision not found or not in a publishable state.
        """
        rev_result = await self.db.execute(
            select(ContentRevision).where(ContentRevision.id == revision_id)
        )
        revision: Optional[ContentRevision] = rev_result.scalar_one_or_none()
        if revision is None:
            raise ValueError(f"ContentRevision not found: {revision_id}")
        if revision.status not in (
            RevisionStatus.pending_approval,
            RevisionStatus.approved,
            RevisionStatus.draft,
        ):
            raise ValueError(
                f"Revision {revision_id} is in status={revision.status!r} "
                "and cannot be published."
            )

        now = datetime.now(timezone.utc)
        revision.status = RevisionStatus.published
        revision.published_at = now
        self.db.add(revision)

        # Update the page's current_revision pointer
        page_result = await self.db.execute(
            select(ContentPage).where(ContentPage.id == revision.page_id)
        )
        page: Optional[ContentPage] = page_result.scalar_one_or_none()
        if page:
            page.current_revision_id = revision.id
            self.db.add(page)

        # Audit log
        audit = AuditLog(
            event_type="content.revision_published",
            agent_name="content_audit_service",
            action_name="publish_revision",
            approval_id=revision.approval_request_id,
            details=json.dumps(
                {
                    "revision_id": revision_id,
                    "page_id": revision.page_id,
                    "approved_by": approved_by,
                    "published_at": now.isoformat(),
                },
                ensure_ascii=False,
            ),
            success=True,
        )
        self.db.add(audit)

        logger.info(
            "content.revision_published",
            revision_id=revision_id,
            page_id=revision.page_id,
            approved_by=approved_by,
        )

        return revision.content_snapshot or ""

    # ─────────────────────────────────────────────────────────────────────────

    async def reject_revision(
        self, revision_id: str, rejected_by: str, reason: str
    ) -> None:
        """
        Reject a pending revision.

        - Sets status = rejected
        - Logs content.revision_rejected

        Raises:
            ValueError: revision not found.
        """
        rev_result = await self.db.execute(
            select(ContentRevision).where(ContentRevision.id == revision_id)
        )
        revision: Optional[ContentRevision] = rev_result.scalar_one_or_none()
        if revision is None:
            raise ValueError(f"ContentRevision not found: {revision_id}")

        revision.status = RevisionStatus.rejected
        self.db.add(revision)

        # Audit log
        audit = AuditLog(
            event_type="content.revision_rejected",
            agent_name="content_audit_service",
            action_name="reject_revision",
            approval_id=revision.approval_request_id,
            details=json.dumps(
                {
                    "revision_id": revision_id,
                    "page_id": revision.page_id,
                    "rejected_by": rejected_by,
                    "reason": reason,
                },
                ensure_ascii=False,
            ),
            success=True,
        )
        self.db.add(audit)

        logger.info(
            "content.revision_rejected",
            revision_id=revision_id,
            page_id=revision.page_id,
            rejected_by=rejected_by,
            reason=reason,
        )
