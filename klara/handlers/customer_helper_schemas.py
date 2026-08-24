"""Wire-protocol schemas for the customer helper token redeem flow.

Single source of truth for every wire identifier on the customer-helper
surface. Both ends of the wire import from here:

  - Production handler:    infra/klara.handlers/customer_helper.py
  - Reference stub:        infra/rustdesk_controller/customer_helper/
                             server-stub/redeem_api.py

Pre-refactor (iter-1) the `Session` model was duplicated; per
architecture-review finding (review-20260621T123417Z-1 High [4]) it was
collapsed here. Iter-57's /download wire shipped a fresh duplication of
`Platform` + filenames + media types + cache header across the two
modules — review-20260622T215846Z-1 High flagged it as a regression of
pattern-38 (wire schemas live in a shared module imported by both
ends). Iter-58 moves those identifiers here.
"""

from typing import Literal, Optional

from pydantic import BaseModel

# Stable export contract for the customer-helper wire surface. Anything
# imported across the handler↔stub seam MUST appear here; anything not
# listed is implementation detail and may be renamed without notice.
# Codifies eng-qa review-20260622T222553Z-4 Medium finding (public API
# surface change without explicit export contract).
__all__ = [
    "DOWNLOAD_CACHE_CONTROL",
    "PLATFORM_FILENAMES",
    "PLATFORM_MEDIA_TYPES",
    "Platform",
    "Session",
    "if_none_match_matches",
]


class Session(BaseModel):
    """Successful redeem payload returned to the customer helper binary."""

    customer_session_id: str
    session_password: str
    expires_at: str
    display_topic: Optional[str] = None
    operator_label: Optional[str] = None


# ---------------------------------------------------------------------------
# /download wire schema — shared between production handler and stub.
# ---------------------------------------------------------------------------
#
# Adding a platform (e.g. linux-arm64) requires updating BOTH dicts here.
# Because the production handler and the stub both import from this
# module, the type checker + the stub contract tests catch any drift at
# edit time rather than at customer-download time.

Platform = Literal["mac-arm64", "mac-x64", "win-x64", "linux-x64"]

PLATFORM_FILENAMES: dict[str, str] = {
    "mac-arm64": "Klaravex-Helper-arm64.dmg",
    "mac-x64": "Klaravex-Helper-x64.dmg",
    "win-x64": "Klaravex-Helper-Setup.exe",
    "linux-x64": "Klaravex-Helper-x86_64.AppImage",
}

PLATFORM_MEDIA_TYPES: dict[str, str] = {
    "mac-arm64": "application/x-apple-diskimage",
    "mac-x64": "application/x-apple-diskimage",
    "win-x64": "application/vnd.microsoft.portable-executable",
    "linux-x64": "application/x-executable",
}

# Cache-Control for signed binaries. Safe ONLY because (a) the URL is
# gated by a one-time token whose eligibility we check before serving,
# (b) the payload bytes are identical across tokens for a given
# release. Re-signing a release mints a new sha256 → new ETag → cache
# is invalidated automatically.
DOWNLOAD_CACHE_CONTROL = "public, max-age=31536000, immutable"


def if_none_match_matches(header: Optional[str], etag: str) -> bool:
    """RFC 7232 §3.2 weak-comparison match for `If-None-Match`.

    `etag` is our strong, quoted tag (e.g. `"<64-hex>"`). Returns True
    when the client already has this representation cached and the
    response should be 304 (no body). Accepts the wildcard `*`,
    exact strong tags, and `W/"..."` weak forms of the same opaque
    value.

    Lives here (not in the handler or stub) so the production
    `/api/v1/customer-helper/download` and the reference stub share
    one parser — pattern-38: edge-case-prone wire-protocol code
    crossing the handler↔stub seam must be defined once. Codified
    in iter-60 architecture review (review-20260622T222000Z-3 High).
    """
    if not header:
        return False
    bare = (etag[2:] if etag.startswith("W/") else etag).strip('"')
    for raw in header.split(","):
        candidate = raw.strip()
        if candidate == "*":
            return True
        cand_bare = (
            candidate[2:] if candidate.startswith("W/") else candidate
        ).strip('"')
        if cand_bare == bare:
            return True
    return False
