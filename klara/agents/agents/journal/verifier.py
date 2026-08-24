"""
app/agents/journal/verifier.py
───────────────────────────────
RARV Verifier — step 4 (final) of the journal team's RARV cycle.

Computes the target vault path based on note_kind, runs final
governance checks, and returns a go / no-go verdict. The heartbeat
task does the actual file write + git commit using the path the
Verifier returns.

Inputs
------
input_data:
  {
    "submission_id":    int,
    "writer_output":    dict (full_md / frontmatter / body_md),
    "reflector_output": dict (approved / concerns / blockers),
  }

Outputs
-------
AgentResult.ok output:
  {
    "go":           bool,
    "vault_path":   str  | None,
    "write_mode":   "append" | "replace" | None,
    "reject_code":  str | None,
    "reason":       str | None,
    "submission_id": int,
  }

Routing by note_kind
--------------------
- decision / finding / incident / learning / blocker / artifact_pointer
    -> append to daily/<today-Berlin>.md (chronological log)
- backstory_update
    -> replace knowledge/agents/<title>.md (Marcus_LeadQualifier style)

Vault path normalization
------------------------
- Slugs are lowercase-kebab (Reasoner already validated)
- For backstory_update, title is sanitized to PascalCase_PascalCase
- All paths are vault-relative (no leading slash)
"""
from __future__ import annotations

import re
from datetime import date

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.note_submission import NoteKind
from klara.rarv.runtime import notes as notes_service

_BACKSTORY_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*_[A-Za-z][A-Za-z0-9]*$")

_APPEND_NOTE_KINDS = frozenset(
    {
        NoteKind.decision,
        NoteKind.finding,
        NoteKind.incident,
        NoteKind.learning,
        NoteKind.blocker,
        NoteKind.artifact_pointer,
    }
)


class RARVVerifierAgent(BaseAgent):
    name = "rarv_verifier"
    description = "Computes vault path and final go/no-go before commit."
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        submission_id = input_data.get("submission_id")
        writer_output = input_data.get("writer_output") or {}
        reflector_output = input_data.get("reflector_output") or {}

        if submission_id is None:
            return AgentResult.fail("submission_id required")

        frontmatter = writer_output.get("frontmatter") or {}
        note_kind = frontmatter.get("note_kind", "")
        topic_slug = frontmatter.get("topic_slug", "")
        title = (frontmatter.get("title") or "").strip()

        # Reflector blockers veto the commit
        if not reflector_output.get("approved", False):
            blockers = reflector_output.get("blockers") or []
            return self._no_go(
                "reflector_blocked",
                "; ".join(blockers) or "reflector did not approve",
                submission_id,
            )

        # Validate note_kind routing
        if note_kind in _APPEND_NOTE_KINDS or note_kind == "daily":
            vault_path = f"daily/{_today_berlin_iso()}.md"
            write_mode = "append"
        elif note_kind == NoteKind.backstory_update or note_kind == "people":
            name = _backstory_filename(title)
            if name is None:
                return self._no_go(
                    "backstory_title_invalid",
                    f"{note_kind} title {title!r} is not Name_Role shape",
                    submission_id,
                )
            vault_path = f"knowledge/agents/{name}.md"
            write_mode = "replace"
        elif note_kind == "knowledge":
            # Topic-keyed knowledge file: knowledge/<topic_slug>.md.
            # Requires a topic_slug; rejected upstream if missing.
            if not topic_slug:
                return self._no_go(
                    "knowledge_missing_slug",
                    "note_kind 'knowledge' requires a topic_slug",
                    submission_id,
                )
            vault_path = f"knowledge/{topic_slug}.md"
            write_mode = "replace"
        elif note_kind == "context":
            # Operational context / handoff documents land under context/<slug>.md
            # to keep them separate from durable knowledge.
            if not topic_slug:
                return self._no_go(
                    "context_missing_slug",
                    "note_kind 'context' requires a topic_slug",
                    submission_id,
                )
            vault_path = f"context/{topic_slug}.md"
            write_mode = "replace"
        else:
            return self._no_go(
                "unrouted_note_kind",
                f"note_kind {note_kind!r} has no vault-path routing rule",
                submission_id,
            )

        # Topic slug sanity (Reasoner already validated, but defensive)
        if topic_slug and not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", topic_slug):
            return self._no_go(
                "topic_slug_invalid_late",
                f"topic_slug {topic_slug!r} failed late validation",
                submission_id,
            )

        return AgentResult.ok(
            {
                "go": True,
                "vault_path": vault_path,
                "write_mode": write_mode,
                "reject_code": None,
                "reason": None,
                "submission_id": submission_id,
                "concerns": reflector_output.get("concerns") or [],
            }
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _no_go(reject_code: str, reason: str, submission_id: int) -> AgentResult:
        return AgentResult.ok(
            {
                "go": False,
                "vault_path": None,
                "write_mode": None,
                "reject_code": reject_code,
                "reason": reason,
                "submission_id": submission_id,
            }
        )


# ── Module helpers ───────────────────────────────────────────────────────


def _today_berlin_iso() -> str:
    """YYYY-MM-DD in Europe/Berlin — vault convention for daily notes."""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
    except Exception:
        return date.today().isoformat()


def _backstory_filename(title: str) -> str | None:
    """
    Accept titles like 'Marcus_LeadQualifier' verbatim; reject anything
    that doesn't match the Name_Role convention.
    """
    if not title:
        return None
    if _BACKSTORY_NAME_RE.match(title):
        return title
    return None
