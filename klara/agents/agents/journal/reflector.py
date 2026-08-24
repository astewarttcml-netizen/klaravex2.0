"""
app/agents/journal/reflector.py
────────────────────────────────
RARV Reflector — step 3 of the journal team's RARV cycle.

Reviews the Writer's draft against existing vault notes. Flags concerns
without blocking unless the concern is severe (exact-duplicate).

Inputs
------
input_data:
  {
    "submission_id": int,    -- the row
    "writer_output": {       -- the dict returned by RARVWriterAgent
      "full_md": str,
      "body_md": str,
      "frontmatter": dict,
    }
  }

Outputs
-------
AgentResult.ok output:
  {
    "approved":  bool,       -- false only on hard blockers
    "concerns":  list[str],  -- soft warnings (don't block)
    "blockers":  list[str],  -- hard blockers (force reject)
    "submission_id": int,
  }

Checks
------
- Exact duplicate of an existing daily note (same body_md present)
- Topic file (knowledge/<slug>.md) hasn't been touched in >180 days
  (soft warning — invites a topic refresh, doesn't block)
- Frontmatter is missing the system-required fields the Writer always
  emits (defensive — should never fire in practice)
- Body exceeds 50KB (soft warning — vault prefers short atomic notes)

Reflector uses the read-only notes service (app/services/notes.py).
Never writes; never commits.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.note_submission import NoteSubmission
from klara.rarv.runtime import notes as notes_service

_SOFT_TOPIC_STALE_DAYS = 180
_SOFT_BODY_MAX_BYTES = 50 * 1024  # 50KB
_REQUIRED_FRONTMATTER_KEYS = frozenset(
    {
        "submission_uuid",
        "agent_id",
        "note_kind",
        "topic_slug",
        "created_at",
    }
)


class RARVReflectorAgent(BaseAgent):
    name = "rarv_reflector"
    description = "Reviews the Writer's draft against existing vault notes."
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        submission_id = input_data.get("submission_id")
        writer_output = input_data.get("writer_output") or {}

        if submission_id is None:
            return AgentResult.fail("submission_id required")

        body_md = writer_output.get("body_md") or ""
        frontmatter = writer_output.get("frontmatter") or {}

        if not body_md.strip():
            return AgentResult.fail("writer_output.body_md is empty")

        stmt = select(NoteSubmission).where(NoteSubmission.id == int(submission_id))
        sub = (await context.db.execute(stmt)).scalar_one_or_none()
        if sub is None:
            return AgentResult.fail(f"submission {submission_id} not found")

        concerns: list[str] = []
        blockers: list[str] = []

        # ── Hard blockers ────────────────────────────────────────────────

        missing_keys = _REQUIRED_FRONTMATTER_KEYS - set(frontmatter.keys())
        if missing_keys:
            blockers.append(
                f"frontmatter missing required keys: {sorted(missing_keys)}"
            )

        if self._exact_duplicate_in_recent_dailies(body_md):
            blockers.append(
                "body matches an existing recent daily note exactly — "
                "submission is a duplicate"
            )

        # ── Soft concerns ────────────────────────────────────────────────

        topic_age = self._topic_file_age_days(sub.topic_slug)
        if topic_age is not None and topic_age > _SOFT_TOPIC_STALE_DAYS:
            concerns.append(
                f"topic knowledge/{sub.topic_slug}.md last updated "
                f"{topic_age} days ago — consider a topic refresh pass"
            )

        if len(body_md.encode("utf-8")) > _SOFT_BODY_MAX_BYTES:
            concerns.append(
                f"body is {len(body_md.encode('utf-8'))} bytes (>{_SOFT_BODY_MAX_BYTES}) "
                "— vault prefers short atomic notes; consider splitting"
            )

        approved = not blockers

        return AgentResult.ok(
            {
                "approved": approved,
                "concerns": concerns,
                "blockers": blockers,
                "submission_id": sub.id,
            }
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _exact_duplicate_in_recent_dailies(body_md: str) -> bool:
        """Scan the last 14 days of daily notes for an exact body match."""
        cutoff = date.today() - timedelta(days=14)
        normalized = body_md.strip()
        for d in notes_service.list_daily_notes(since=cutoff):
            existing = notes_service.read_daily(d) or ""
            if normalized in existing:
                return True
        return False

    @staticmethod
    def _topic_file_age_days(topic_slug: str) -> int | None:
        """Days since knowledge/<slug>.md was last modified. None if absent."""
        from pathlib import Path
        from klara.rarv.runtime.notes_service import _vault_root  # internal helper, intentional

        try:
            path = _vault_root() / "knowledge" / f"{topic_slug}.md"
        except Exception:
            return None

        path = Path(path)
        if not path.is_file():
            return None

        import time
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        return int((time.time() - mtime) // 86400)
