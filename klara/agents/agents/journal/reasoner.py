"""
app/agents/journal/reasoner.py
───────────────────────────────
RARV Reasoner — step 1 of the journal team's RARV cycle.

Validates an incoming note_submissions row and decides:
  accept   -> hand off to the Writer
  reject   -> terminal; set rejection_reason + reject_code on the row
  clarify  -> NOT IMPLEMENTED in v1; collapses to "reject" with
              reject_code="needs_clarification" so the submitting agent
              can re-submit with more context

Pure analysis. No DB writes, no IO. Returns its decision; the heartbeat
applies it.

Inputs
------
input_data:
  {
    "submission_id": int    -- required, the note_submissions.id to evaluate
  }

Outputs
-------
AgentResult.ok output:
  {
    "decision": "accept" | "reject",
    "reject_code": str | None,
    "reason": str | None,
  }

Reject codes
------------
- empty_content        -- content field blank or whitespace only
- empty_title          -- title field blank
- invalid_topic_slug   -- topic_slug fails kebab-case validation
- invalid_note_kind    -- note_kind not in NoteKind.ALL (relaxed: any
                          non-empty string is allowed; this only fires
                          if note_kind is missing/empty)
- unknown_agent        -- agent_id is empty
- already_terminal     -- submission is already written/rejected/failed
- sha256_invalid       -- content_sha256 not 64 hex chars
- duplicate_in_flight  -- same content_sha256 already in pending/claimed/
                          processing state for the same topic
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.note_submission import NoteSubmission, SubmissionStatus

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RARVReasonerAgent(BaseAgent):
    name = "rarv_reasoner"
    description = "Validates a note_submissions row and decides accept / reject."
    permission_level = PermissionLevel.P2  # internal DB read only

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        submission_id = input_data.get("submission_id")
        if submission_id is None:
            return AgentResult.fail("submission_id required")

        sub = await self._fetch(context.db, int(submission_id))
        if sub is None:
            return AgentResult.fail(f"submission {submission_id} not found")

        # Hard-stop: already terminal
        if sub.status in SubmissionStatus.TERMINAL:
            return self._reject("already_terminal", f"status={sub.status}")

        # Structural checks
        if not (sub.agent_id or "").strip():
            return self._reject("unknown_agent", "agent_id is empty")

        if not (sub.title or "").strip():
            return self._reject("empty_title", "title is empty")

        if not (sub.content or "").strip():
            return self._reject("empty_content", "content is empty")

        if not (sub.note_kind or "").strip():
            return self._reject("invalid_note_kind", "note_kind is empty")

        if not _SLUG_RE.match(sub.topic_slug or ""):
            return self._reject(
                "invalid_topic_slug",
                f"topic_slug {sub.topic_slug!r} is not lowercase-kebab",
            )

        if not _SHA256_RE.match((sub.content_sha256 or "").lower()):
            return self._reject(
                "sha256_invalid",
                f"content_sha256 {sub.content_sha256!r} is not 64 hex chars",
            )

        # In-flight dedupe: another row with same (topic, sha256) already queued
        dupe = await self._find_in_flight_duplicate(context.db, sub)
        if dupe is not None:
            return self._reject(
                "duplicate_in_flight",
                f"submission {dupe.id} has the same (topic, content_sha256)",
            )

        return AgentResult.ok(
            {
                "decision": "accept",
                "reject_code": None,
                "reason": None,
                "submission_id": sub.id,
            }
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _reject(reject_code: str, reason: str) -> AgentResult:
        return AgentResult.ok(
            {
                "decision": "reject",
                "reject_code": reject_code,
                "reason": reason,
            }
        )

    async def _fetch(self, db: AsyncSession, submission_id: int):
        stmt = select(NoteSubmission).where(NoteSubmission.id == submission_id)
        return (await db.execute(stmt)).scalar_one_or_none()

    async def _find_in_flight_duplicate(
        self, db: AsyncSession, sub: NoteSubmission
    ):
        """Find another non-terminal submission with the same (topic, sha)."""
        stmt = (
            select(NoteSubmission)
            .where(NoteSubmission.id != sub.id)
            .where(NoteSubmission.topic_slug == sub.topic_slug)
            .where(NoteSubmission.content_sha256 == sub.content_sha256)
            .where(
                NoteSubmission.status.in_(
                    [
                        SubmissionStatus.pending,
                        SubmissionStatus.claimed,
                        SubmissionStatus.processing,
                    ]
                )
            )
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()
