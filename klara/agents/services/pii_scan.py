"""
app/services/pii_scan.py
─────────────────────────
phase10-004 — pattern-based PII detection for outbound drafts.

Used by reply_draft + proposal_send paths to flag drafts that may
contain personal data BEFORE Anthony approves. Pure regex — fast,
no LLM call needed.

Returns a list of detected_patterns (pattern names, not the matched
values themselves — we deliberately don't echo the PII back).
"""
from __future__ import annotations

import re
from typing import List

# Conservative patterns. Each entry: (name, compiled regex).
# Patterns deliberately avoid catching things that are obviously legitimate
# (e.g. company VAT IDs are NOT flagged — only "looks-like-personal" PII).
_PATTERNS = [
    ("iban_de",         re.compile(r"\bDE\d{2}\s?(?:\d{4}\s?){4}\d{2}\b")),
    ("iban_generic",    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")),
    ("credit_card",     re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
    ("passport_de",     re.compile(r"\b[CFGHJK][0-9CFGHJ-NPRTV-Z]{8}\b")),
    ("personalausweis", re.compile(r"\bT\d{8}[A-Z]\b")),   # German ID card pattern
    ("dob_iso",         re.compile(r"\b(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")),
    ("phone_e164",      re.compile(r"\+\d{10,15}\b")),
    ("ssn_us",          re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
]


def scan_outbound_text(text: str) -> List[str]:
    """
    Return a list of pattern names that fired against ``text``.

    Examples:
      scan_outbound_text("Please pay to DE89 3704 0044 0532 0130 00")
        → ["iban_de", "iban_generic"]

      scan_outbound_text("Hi Frank, here's our standard proposal")
        → []

    The function is conservative — false positives are tolerated; false
    negatives (real PII slipping through) are not. Operators can override
    via the approval card if a flag is spurious.
    """
    if not text:
        return []

    matches: list[str] = []
    for name, rx in _PATTERNS:
        if rx.search(text):
            matches.append(name)
    return matches


def has_pii(text: str) -> bool:
    """Convenience boolean for callers that only need a yes/no."""
    return len(scan_outbound_text(text)) > 0
