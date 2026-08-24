"""
app/services/draft_validator.py
────────────────────────────────
Post-LLM lint for drafter agents.

Three production incidents on 2026-05-29 in a single morning shared one root
cause: a drafter agent prompted Claude to produce structured output that
included `[PLACEHOLDER]` slots the agent was supposed to substitute after the
LLM call. The substitution step either never ran or didn't catch every slot,
and the un-rendered template landed in `approval_requests.payload`.

  03:46 UTC  prospecting_outreach     → "Sehr geehrter Herr Andreas" (Andreas was
                                         the *first* name; salutation needs last)
  09:15 UTC  testimonial_requester    → "Hi [Client Name]," + "[GOOGLE_REVIEW_LINK]"
                                         + "[specific service completed]"
  09:20 UTC  social_media_manager     → "[CLIENT]", "## HOOK_VARIANTS:", "## FINAL_POST:"
                                         leaked scaffold sections into the post body

The P3 human-review gate caught all three before any email/post went out, but
that put the burden on Anthony to spot the bug in every batch. This module is
the cheaper protection: a deterministic regex lint that fails fast at the
agent layer, BEFORE the approval row is created, so the human queue only
contains drafts that have a chance of being correct.

Usage from a drafter agent::

    from app.services.draft_validator import (
        validate_no_placeholders,
        DraftValidationError,
    )

    try:
        validate_no_placeholders(
            agent_name="prospecting_outreach",
            fields={"subject": subject, "body_text": body_text, "body_html": body_html},
        )
    except DraftValidationError as exc:
        log.error("draft.placeholder_lint_failed",
                  fields=list(exc.field_violations.keys()),
                  violations=exc.field_violations)
        # Caller decides: skip / set draft_failed status / retry generation
        raise

The validator does NOT try to detect *every* possible badness — only the
specific bracket / brace / scaffold patterns observed in the 2026-05-29
incidents. False negatives are expected on edge cases; false positives are
expected on legitimate emails that contain bracket text (rare in cold outreach
templates). When in doubt the validator is permissive — better to let a clean
draft through than block real work — but the patterns below are tuned to
catch the obvious LLM-template leaks that crossed the P3 gate today.
"""
from __future__ import annotations

import re
from typing import Mapping


# [Word Or Phrase] when NOT followed by `(` (which would make it a Markdown link).
# Captures: [Client Name], [GOOGLE_REVIEW_LINK], [CLIENT], [specific service completed],
#           [Hook 1 - Relatable pain point], [Comment prompt 1],
#           and multi-line LLM scaffold leaks like
#           [SPECIFIC CAPABILITY—e.g., structured data pipelines /\n edge processing / ...].
# Does NOT capture: [click here](https://...) — that's a real Markdown link.
# Inner content allows any char except `]`, capped at 250 chars to avoid
# pathological matches across very long bodies.
_BRACKET_PLACEHOLDER = re.compile(
    r"\[([A-Za-z][^\]]{0,250}?)\](?!\()",
    re.DOTALL,
)

# Empty or whitespace-only brackets: `[]`, `[ ]`, `[\n]`. These are the
# residue of an LLM template substitution that ran with a None / empty
# string for the slot value and printed the brackets anyway. Production
# bug 2026-05-29: social_media_manager topic "Recent win: successfully
# supported Klaravex with []." passed the placeholder lint
# because the existing _BRACKET_PLACEHOLDER regex requires at least one
# letter inside the brackets. Catch empties explicitly.
_EMPTY_BRACKETS = re.compile(r"\[\s*\](?!\()")

# {placeholder} or {{placeholder}} — Jinja / Mustache / Python str.format style.
_BRACE_PLACEHOLDER = re.compile(
    r"\{\{?\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}?"
)

# Markdown headings that look like prompt-scaffold section labels rather than
# real headings — e.g. "## HOOK_VARIANTS:", "## FINAL_POST:", "## ENGAGEMENT_PLAN:".
# Real content rarely uses ALL_CAPS heading words ending in a colon.
_SCAFFOLD_HEADING = re.compile(
    r"^\s*#{1,3}\s+[A-Z][A-Z_]+\s*:\s*$",
    re.MULTILINE,
)


def find_unfilled_placeholders(text: str) -> list[str]:
    """Return a list of suspected unfilled-template patterns found in `text`.

    Empty list means the text passed the lint. The returned values are the
    raw matched substrings, deduplicated in first-seen order, so they can be
    surfaced verbatim in error logs.
    """
    if not text:
        return []

    found: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        v = value.strip()
        if v and v not in seen:
            seen.add(v)
            found.append(v)

    for m in _BRACKET_PLACEHOLDER.finditer(text):
        _add(m.group(0))
    for m in _EMPTY_BRACKETS.finditer(text):
        _add(m.group(0))
    for m in _BRACE_PLACEHOLDER.finditer(text):
        _add(m.group(0))
    for m in _SCAFFOLD_HEADING.finditer(text):
        _add(m.group(0))

    return found


class DraftValidationError(ValueError):
    """A drafter agent produced output that failed the placeholder lint.

    Carries the per-field violations so the caller can log them and decide
    whether to skip the prospect, retry generation, or surface the issue.
    """

    def __init__(self, agent_name: str, field_violations: Mapping[str, list[str]]):
        self.agent_name = agent_name
        self.field_violations: dict[str, list[str]] = dict(field_violations)
        flat = "; ".join(
            f"{field}=[{', '.join(repr(v) for v in patterns)}]"
            for field, patterns in self.field_violations.items()
        )
        super().__init__(
            f"{agent_name}: unfilled template placeholders — {flat}"
        )


def validate_no_placeholders(
    agent_name: str,
    fields: Mapping[str, str | None],
) -> None:
    """Raise `DraftValidationError` if any text field contains placeholders.

    `fields` is `{field_name: text_value}`. Non-string values are ignored
    (they couldn't possibly contain a template token anyway).
    """
    violations: dict[str, list[str]] = {}
    for field, value in fields.items():
        if not isinstance(value, str):
            continue
        issues = find_unfilled_placeholders(value)
        if issues:
            violations[field] = issues
    if violations:
        raise DraftValidationError(agent_name, violations)
