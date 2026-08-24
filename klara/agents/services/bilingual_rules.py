"""
app/services/bilingual_rules.py
─────────────────────────────────
Bilingual content rules for klaravex.de.

Rules:
  - Every EN page must have a corresponding DE page (same slug, /de/ prefix or ?lang=de)
  - German copy must use formal Sie (not Du)
  - hreflang tags must be present and point to correct counterpart
  - Slugs must be consistent across language pairs

Site structure:
  - EN pages: /services/, /about/, /contact/, /pricing/, /blog/, /portal/
  - DE pages: /de/dienstleistungen/, /de/ueber-uns/, /de/kontakt/, /de/preisgestaltung/, /de/blog/
  - DE slugs updated 2026-05-14: renamed to German slugs for better DE SEO
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# EN → DE slug mapping
# ─────────────────────────────────────────────────────────────────────────────

EN_DE_PAGE_MAP: dict[str, str] = {
    "/": "/de/",
    "/services/": "/de/dienstleistungen/",   # WP ID 120 — German slug as of 2026-05-14
    "/about/": "/de/ueber-uns/",              # WP ID 121 — German slug as of 2026-05-14
    "/contact/": "/de/kontakt/",              # WP ID 122 — German slug as of 2026-05-14
    "/pricing/": "/de/preisgestaltung/",      # WP ID 269 — created 2026-05-14
    "/blog/": "/de/blog/",
}

# Reverse map: DE slug → EN slug
_DE_EN_PAGE_MAP: dict[str, str] = {v: k for k, v in EN_DE_PAGE_MAP.items()}

# Structural change types that require page-mapping checks
_STRUCTURAL_CHANGE_TYPES = frozenset({"structure_change", "seo_update"})


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SieCheckResult:
    is_compliant: bool
    violations: list[str] = field(default_factory=list)
    suggestion: str = ""


@dataclass
class HreflangCheckResult:
    is_valid: bool
    expected_de_slug: str
    actual_de_slug: str


@dataclass
class ValidationResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Informal-Du detection
# ─────────────────────────────────────────────────────────────────────────────

# Matches standalone informal pronouns at word boundaries.
# Excludes compound words via negative lookbehind/lookahead on word chars.
_DU_FORMS = re.compile(
    r"(?<!\w)(du|dich|dir|dein|deine|deinen|deinem|deiner|deines)(?!\w)",
    re.IGNORECASE,
)


def check_sie_compliance(german_text: str) -> SieCheckResult:
    """
    Scan german_text for informal Du forms (word-boundary aware).

    Does NOT flag "du" inside compound words — e.g. "Produkt", "Produktion",
    "Studio", "Vorschau" are all safe because the regex requires no adjacent
    word characters (backslash-w) on either side.

    Returns SieCheckResult with is_compliant, list of found violations, and
    a corrective suggestion when violations are present.
    """
    matches = _DU_FORMS.finditer(german_text)
    violations: list[str] = []
    seen: set[str] = set()

    for m in matches:
        token = m.group(0).lower()
        if token not in seen:
            seen.add(token)
            violations.append(m.group(0))

    if not violations:
        return SieCheckResult(is_compliant=True)

    # Build a context-aware suggestion
    _SIE_ALTERNATIVES = {
        "du": "Sie",
        "dich": "Sie",
        "dir": "Ihnen",
        "dein": "Ihr",
        "deine": "Ihre",
        "deinen": "Ihren",
        "deinem": "Ihrem",
        "deiner": "Ihrer",
        "deines": "Ihres",
    }
    replacements = [
        f'"{v}" → "{_SIE_ALTERNATIVES.get(v.lower(), "Sie/Ihr")}"'
        for v in violations
    ]
    suggestion = (
        "Replace informal Du forms with formal Sie: "
        + ", ".join(replacements)
        + ". Klaravex uses formal Sie throughout."
    )
    return SieCheckResult(is_compliant=False, violations=violations, suggestion=suggestion)


# ─────────────────────────────────────────────────────────────────────────────
# Hreflang pair validation
# ─────────────────────────────────────────────────────────────────────────────

def check_hreflang_pair(en_url: str, de_url: str) -> HreflangCheckResult:
    """
    Verify that the EN/DE URL pair exists in EN_DE_PAGE_MAP.

    Strips the origin (scheme + host) from each URL before matching — works
    with both full URLs (https://klaravex.de/about/) and path-only
    strings (/about/).

    Returns HreflangCheckResult(is_valid, expected_de_slug, actual_de_slug).
    """
    en_slug = _extract_slug(en_url)
    de_slug = _extract_slug(de_url)

    expected_de = EN_DE_PAGE_MAP.get(en_slug, "")
    is_valid = bool(expected_de) and (de_slug == expected_de)

    return HreflangCheckResult(
        is_valid=is_valid,
        expected_de_slug=expected_de,
        actual_de_slug=de_slug,
    )


def _extract_slug(url: str) -> str:
    """Strip scheme+host from a URL and return the path component."""
    # Remove scheme and host if present
    url = re.sub(r"^https?://[^/]+", "", url)
    # Normalise: ensure leading slash, strip query/fragment
    url = url.split("?")[0].split("#")[0]
    if not url.startswith("/"):
        url = "/" + url
    # Ensure trailing slash for consistent comparison
    if not url.endswith("/"):
        url += "/"
    return url


# ─────────────────────────────────────────────────────────────────────────────
# Revision validation entry point
# ─────────────────────────────────────────────────────────────────────────────

def validate_content_revision_data(
    page_slug: str,
    page_language: str,
    proposed_content: str,
    change_type: str,
) -> ValidationResult:
    """
    Validate proposed content data against bilingual rules.

    Called from ContentAuditService.propose_change() before creating a revision.

    Rules applied:
      - German copy: run Sie compliance check (errors on violation)
      - Structural/SEO changes on known slugs: check page-mapping is maintained
        (warning only — slug changes are admin-controlled)

    Returns ValidationResult(passed, errors, warnings).
    Errors are blocking; warnings are informational.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ── Sie compliance for German pages ───────────────────────────────────────
    if page_language == "de":
        sie_result = check_sie_compliance(proposed_content)
        if not sie_result.is_compliant:
            errors.append(
                f"German copy contains informal Du forms "
                f"({', '.join(sie_result.violations)}). "
                f"{sie_result.suggestion}"
            )

    # ── Slug / mapping consistency for structural changes ─────────────────────
    if change_type in _STRUCTURAL_CHANGE_TYPES:
        normalised_slug = page_slug if page_slug.endswith("/") else page_slug + "/"
        if normalised_slug not in EN_DE_PAGE_MAP and normalised_slug not in _DE_EN_PAGE_MAP:
            warnings.append(
                f"Slug {page_slug!r} is not in the EN_DE_PAGE_MAP. "
                "Ensure a counterpart page exists in the other language."
            )
        elif page_language == "en":
            expected_de = EN_DE_PAGE_MAP.get(normalised_slug)
            if expected_de:
                warnings.append(
                    f"Structural change on EN slug {page_slug!r}. "
                    f"Verify DE counterpart {expected_de!r} is updated too."
                )
        elif page_language == "de":
            expected_en = _DE_EN_PAGE_MAP.get(normalised_slug)
            if expected_en:
                warnings.append(
                    f"Structural change on DE slug {page_slug!r}. "
                    f"Verify EN counterpart {expected_en!r} is updated too."
                )

    passed = len(errors) == 0
    return ValidationResult(passed=passed, errors=errors, warnings=warnings)


# ─────────────────────────────────────────────────────────────────────────────
# Legacy adapter used by ContentAuditService
# (accepts a partial ContentRevision-like object)
# ─────────────────────────────────────────────────────────────────────────────

def validate_content_revision(
    page_slug: str,
    page_language: str,
    proposed_content: str,
    change_type: str,
) -> ValidationResult:
    """Alias for validate_content_revision_data — kept for external callers."""
    return validate_content_revision_data(
        page_slug=page_slug,
        page_language=page_language,
        proposed_content=proposed_content,
        change_type=change_type,
    )
