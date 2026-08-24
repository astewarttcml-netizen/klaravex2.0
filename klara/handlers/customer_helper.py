"""Customer-helper token redeem endpoint (G34 — RustDesk session bootstrap).

Production wire-in for the contract documented at:
    infra/rustdesk_controller/customer_helper/server-stub/redeem_api.py

Mount under prefix `/api/v1/customer-helper` so the public path is:
    POST /api/v1/customer-helper/redeem/{token}

Handler responsibilities (intentionally minimal):

  1. Hash the URL token with sha256. NEVER log or store the raw token —
     log only the first 16 hex chars of the digest as `token_h16`.
  2. Delegate the atomic redeem to a `TokenStore` (injected via
     FastAPI `Depends(get_token_store)`). The store returns a
     `RedeemOutcome` ADT; the handler's only job is to translate that
     ADT into an HTTP status. No SQL lives in this file.
  3. Delegate the `note_submissions` row to an `AuditLog` (injected via
     `Depends(get_audit_log)`). Symmetric DI seam: both persistence
     boundaries cross the same protocol shape, no module-level
     `get_pool()` calls in this file. (review-20260621T124700Z-2 High [1])

The store + audit seams were introduced after architecture reviews
review-20260621T123417Z-1 and review-20260621T124700Z-2 flagged the
DIP / repository / TOCTOU / asymmetric-DI debts.
"""

import hashlib
import logging
from typing import assert_never

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from fastapi.responses import FileResponse, Response

from .customer_helper_schemas import (
    DOWNLOAD_CACHE_CONTROL,
    PLATFORM_FILENAMES,
    PLATFORM_MEDIA_TYPES,
    Platform,
    Session,
    if_none_match_matches,
)
from .customer_helper_store import (
    AlreadyRedeemed,
    AuditLog,
    Available,
    BinaryStore,
    Expired,
    PaymentMissing,
    PeekOutcome,
    RedeemOutcome,
    Redeemed,
    TokenStore,
    Unknown,
    get_audit_log,
    get_binary_store,
    get_token_store,
)

log = logging.getLogger("klaravex.customer_helper")

router = APIRouter()

# Tokens are minted via secrets.token_urlsafe → base64url alphabet
# (A–Z, a–z, 0–9, '_', '-'). Pinning the pattern at the FastAPI layer
# rejects malformed paths at 422 before the SQL parameter binding,
# closes security-sentinel S2988 Low (token regex validation), and
# keeps the failure surface uniform across /redeem + /download.
_TOKEN_PATTERN = r"^[A-Za-z0-9_-]{20,128}$"


def _hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _h16(digest: bytes) -> str:
    return digest.hex()[:16]


def _failure_to_http(outcome: RedeemOutcome) -> tuple[int, str]:
    """Translate a non-success `RedeemOutcome` to (status, detail).

    Uses `match`/`case` with `assert_never` so the type checker fails
    at edit time when a new `RedeemOutcome` variant is added without
    a corresponding HTTP mapping, instead of raising `KeyError` in
    production (review-20260621T124700Z-2 Medium [3]).
    """
    match outcome:
        case Unknown():
            return 404, "unknown token"
        case AlreadyRedeemed():
            return 410, "token already redeemed"
        case Expired():
            return 410, "token expired"
        case PaymentMissing():
            return 402, "payment not confirmed"
        case Redeemed():  # pragma: no cover — caller filters this branch
            raise AssertionError("Redeemed must be handled before _failure_to_http")
        case _ as unreachable:
            assert_never(unreachable)


@router.post("/redeem/{token}", response_model=Session)
async def redeem(
    token: str = Path(..., min_length=20, max_length=128, pattern=_TOKEN_PATTERN),
    store: TokenStore = Depends(get_token_store),
    audit: AuditLog = Depends(get_audit_log),
) -> Session:
    token_sha = _hash(token)
    token_h16 = _h16(token_sha)
    log.info("redeem attempt token_h16=%s", token_h16)

    outcome = await store.try_redeem(token_sha)

    if isinstance(outcome, Redeemed):
        session = outcome.session
        log.info(
            "redeem ok token_h16=%s session_id=%s",
            token_h16,
            session.customer_session_id,
        )
        await audit.record_redeem(token_h16, session.customer_session_id)
        return session

    status, detail = _failure_to_http(outcome)
    log.info(
        "redeem rejected token_h16=%s status=%s detail=%s",
        token_h16,
        status,
        detail,
    )
    raise HTTPException(status_code=status, detail=detail)


# ---------------------------------------------------------------------------
# /download — signed customer-helper binary distribution
# ---------------------------------------------------------------------------
#
# Companion to /redeem. Customer flow:
#   1. Klara sends a single URL: https://support.klaravex.com/download/<token>?platform=<plat>
#   2. The browser hits THIS endpoint → 200 + signed binary streamed via sendfile.
#      Token MUST NOT be flipped to redeemed here — the helper still needs
#      to call /redeem after it launches.
#   3. Helper runs → calls /api/v1/customer-helper/redeem/<token>.
#
# Eligibility checks mirror /redeem but are read-only (TokenStore.peek).
# Binaries are resolved from KLX_HELPER_BINARIES_DIR; one file per
# platform with deterministic filenames. Strong ETag + Cache-Control
# come from a build manifest written by scripts/build_customer_helpers
# at sign time (NOT computed per request — sha256 of 80MB on the hot
# path would re-introduce the [P1] memory regression).
#
# Pre-procurement state: when the manifest or the file for a platform
# is missing, return 503 (matches stub parity). Production must NOT
# 404 in that case — 404 means "unknown token", and conflating the two
# would make the customer think their token is invalid when actually
# we just don't have a notarized Mac binary yet.

# Wire identifiers (Platform, PLATFORM_FILENAMES, PLATFORM_MEDIA_TYPES,
# DOWNLOAD_CACHE_CONTROL) live in customer_helper_schemas so the
# reference stub and this handler import the same source — see
# review-20260622T215846Z-1 [3] pattern-38 (no producer/consumer
# duplication of wire schemas).


def _peek_failure_to_http(outcome: PeekOutcome) -> tuple[int, str]:
    """Translate a non-`Available` PeekOutcome to (status, detail).

    `match`/`case` + `assert_never` so the type checker fails when a
    new variant is added without an HTTP mapping (Pattern-39 +
    next_iteration_intent point g).
    """
    match outcome:
        case Unknown():
            return 404, "unknown token"
        case AlreadyRedeemed():
            return 410, "token already redeemed"
        case Expired():
            return 410, "token expired"
        case PaymentMissing():
            return 402, "payment not confirmed"
        case Available():  # pragma: no cover — caller filters this branch
            raise AssertionError("Available must be handled before _peek_failure_to_http")
        case _ as unreachable:
            assert_never(unreachable)


@router.get("/download/{token}")
async def download(
    token: str = Path(..., min_length=20, max_length=128, pattern=_TOKEN_PATTERN),
    platform: Platform = Query(...),
    store: TokenStore = Depends(get_token_store),
    binaries: BinaryStore = Depends(get_binary_store),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
) -> Response:
    token_sha = _hash(token)
    token_h16 = _h16(token_sha)
    log.info("download attempt token_h16=%s platform=%s", token_h16, platform)

    outcome = await store.peek(token_sha)

    if not isinstance(outcome, Available):
        status, detail = _peek_failure_to_http(outcome)
        log.info(
            "download rejected token_h16=%s platform=%s status=%s detail=%s",
            token_h16,
            platform,
            status,
            detail,
        )
        raise HTTPException(status_code=status, detail=detail)

    artifact = binaries.resolve(platform)
    if artifact is None:
        log.info(
            "download unavailable token_h16=%s platform=%s reason=binary_missing",
            token_h16,
            platform,
        )
        raise HTTPException(
            status_code=503,
            detail=f"binary not yet available for platform={platform}",
        )

    filename = PLATFORM_FILENAMES[platform]
    media_type = PLATFORM_MEDIA_TYPES[platform]
    etag = f'"{artifact.sha256}"'

    # RFC 7232 conditional GET — short-circuit before sendfile so a
    # cached client's retry click skips the 80MB body. ETag +
    # Cache-Control still ride on the 304 so the cache entry's
    # freshness window can be re-minted. Addresses
    # review-20260622T215846Z-1 Medium [P2].
    if if_none_match_matches(if_none_match, etag):
        log.info(
            "download 304 token_h16=%s platform=%s sha=%s",
            token_h16,
            platform,
            artifact.sha256[:16],
        )
        return Response(
            status_code=304,
            headers={"Cache-Control": DOWNLOAD_CACHE_CONTROL, "ETag": etag},
        )

    log.info(
        "download ok token_h16=%s platform=%s sha=%s",
        token_h16,
        platform,
        artifact.sha256[:16],
    )
    # FileResponse uses sendfile(2) on POSIX so 80MB binaries go
    # kernel→socket without a Python-side copy — addresses iter-55/56
    # finding [P1]. Cache-Control + strong ETag from finding [P2].
    return FileResponse(
        path=str(artifact.path),
        media_type=media_type,
        filename=filename,
        headers={"Cache-Control": DOWNLOAD_CACHE_CONTROL, "ETag": etag},
    )


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "handler": "customer_helper"}
