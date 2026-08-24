"""Server-side contract for the customer helper's token redeem endpoint.

This file is a REFERENCE STUB, not the production wire-in. Production
implementation belongs in `infra/main.py` (FastAPI) and must:

  1. Sit behind support.klaravex.com TLS termination.
  2. Take `:token` from the URL path. Treat the path as PII-adjacent and do
     not log it raw — log only sha256(token)[:16] for correlation.
  3. Look up the token row in `customer_helper_tokens` (see schema.sql).
  4. Verify:
       - row exists
       - row.redeemed_at IS NULL
       - row.expires_at > now()
       - row.payment_confirmed = true  (Stripe webhook flips this)
  5. Atomically (`UPDATE ... RETURNING`) flip `redeemed_at = now()` so a
     race between two redeems still produces exactly one Session.
  6. Emit a `customer_helper.redeemed` event to the Klara AI session manager so
     the operator side knows to dial customer_session_id.
  7. Write a `note_submissions` row per Klaravex Memory Policy with
     topic `api-integration`, action_summary including
     sha256(token)[:16] and customer_session_id.
  8. Return Session JSON.

This stub runs as a standalone FastAPI app for contract testing the
client; do NOT mount it next to production.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import secrets
import string
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Path, Query, Response
from fastapi.responses import StreamingResponse


# Shared wire schemas — single source of truth for the Session payload
# AND the /download wire identifiers (Platform Literal, filenames,
# media types, cache header, RFC 7232 If-None-Match parser). See
# review-20260621T123417Z-1 [4] (Session), review-20260622T215846Z-1 [3]
# (download identifiers), and review-20260622T222000Z-3 High
# (`if_none_match_matches`): producer/consumer drift on wire-protocol
# code is the failure class pattern-38 guards against — collapsed here.
#
# Run from the repo root so that `infra/` is on PYTHONPATH:
#   $ cd <repo-root>
#   $ PYTHONPATH=. python -m klara.rustdesk.customer_helper.server-stub.redeem_api
# OR
#   $ PYTHONPATH=. uvicorn klara.rustdesk.customer_helper.server-stub.redeem_api:app
#
# Pattern-2 (CLAUDE.md): real imports are NOT wrapped in try/ImportError,
# and modules do NOT mutate sys.path at import time. The stub's
# off-tree invocation path is documented above instead.
from infra.klara.handlers.customer_helper_schemas import (
    DOWNLOAD_CACHE_CONTROL as _DOWNLOAD_CACHE_CONTROL,
    PLATFORM_FILENAMES as _PLATFORM_FILENAMES,
    PLATFORM_MEDIA_TYPES as _PLATFORM_MEDIA_TYPES,
    Platform,
    Session,
    if_none_match_matches,
)

app = FastAPI(title="klaravex-customer-helper-stub")


# In-memory token store for the stub. Production uses Postgres
# customer_helper_tokens table.
_TOKENS: dict[str, dict] = {}


def _gen_rustdesk_id() -> str:
    """RustDesk IDs are 9-digit numerics. Production must coordinate with
    the hbbs ID server to ensure non-collision; here we just randomize."""
    return "".join(secrets.choice(string.digits) for _ in range(9))


def _gen_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


@app.post("/api/customer-helper/issue", response_model=Session)
def issue_stub(topic: Optional[str] = None) -> Session:
    """DEV-ONLY: mint a fresh token without going through Stripe. The
    helper smoke test calls this, then immediately redeems it."""
    token = secrets.token_urlsafe(32)
    sess = Session(
        customer_session_id=_gen_rustdesk_id(),
        session_password=_gen_password(),
        expires_at=(dt.datetime.utcnow() + dt.timedelta(minutes=30)).isoformat() + "Z",
        display_topic=topic,
        operator_label="Klara (AI)",
    )
    _TOKENS[token] = {"session": sess, "redeemed": False}
    # In real life we'd return the token via email; here we leak it for the test.
    return {"token": token, **sess.model_dump()}  # type: ignore[return-value]


@app.post("/api/customer-helper/redeem/{token}", response_model=Session)
def redeem(token: str = Path(..., min_length=20, max_length=128)) -> Session:
    tok_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
    print(f"[redeem] token={tok_hash}")  # production: structured logger

    row = _TOKENS.get(token)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown token")
    if row["redeemed"]:
        raise HTTPException(status_code=410, detail="token already redeemed")

    sess: Session = row["session"]
    exp = dt.datetime.fromisoformat(sess.expires_at.rstrip("Z"))
    if exp < dt.datetime.utcnow():
        raise HTTPException(status_code=410, detail="token expired")

    row["redeemed"] = True
    print(f"[redeem] token={tok_hash} session_id={sess.customer_session_id} OK")
    return sess


# ---------------------------------------------------------------------------
# Download endpoint — REFERENCE STUB for the binary distribution contract
# ---------------------------------------------------------------------------
#
# Companion to /redeem. Customer flow:
#
#   1. Klara (AI) sends customer a single URL:
#        https://support.klaravex.com/download/<token>?platform=<plat>
#   2. Customer clicks → THIS endpoint serves the signed helper binary.
#      The token MUST NOT be marked redeemed here; the customer needs the
#      token still valid when the helper launches and calls /redeem.
#   3. Helper runs → calls /api/customer-helper/redeem/<token>
#      to obtain the relay credentials (Session).
#
# The token eligibility checks here are a SUBSET of /redeem's checks:
# the row must exist, NOT already be redeemed, NOT be expired, and
# payment must be confirmed. Same status codes as /redeem for the
# eligibility failures so the client can render one error model.
#
# Production wire-in (FUTURE iteration):
#   - Add `TokenStore.peek(token_sha) -> PeekOutcome` to
#     infra/klara.handlers/customer_helper_store.py (read-only SELECT,
#     no FOR UPDATE).
#   - Add GET /download/{token} to
#     infra/klara.handlers/customer_helper.py mounted under the
#     existing /api/v1/customer-helper prefix.
#   - Serve signed binaries from a path resolved via
#     env KLX_HELPER_BINARIES_DIR (one file per platform, names
#     matching scripts/build_customer_helpers/dist/<platform>/...).
#   - Blocked on procurement: Apple Developer Program (mac-*),
#     Sectigo EV (win-x64), GPG key publication (linux-x64). Until
#     procurement clears, the production endpoint should return 503
#     with detail="binary not yet available for platform=<plat>".
#
# Performance requirements for production wire-in (from review
# 20260621T131000Z performance-oracle findings):
#   [P1] Stream from disk, do NOT load the whole binary into memory.
#        Use starlette.responses.FileResponse(path) — under the hood
#        FastAPI/Starlette uses sendfile(2) on POSIX so the bytes go
#        kernel-to-socket without a Python-side copy. Binaries are
#        60–80MB each; at 100 concurrent downloads, in-memory loading
#        is 6–8GB resident vs near-zero with sendfile. NEVER read
#        the file with open().read() and pass to Response(content=).
#   [P2] Emit Cache-Control: public, max-age=31536000, immutable on
#        all 200 responses. Signed binaries are immutable per release
#        — the URL path is keyed by token but the payload is byte-
#        identical across tokens for a given platform. Browsers,
#        CDNs, and corporate proxies must be allowed to cache so a
#        customer's retry click does not re-pull 80MB from origin.
#        Pair with a strong ETag derived from the file's sha256 so
#        an HTTP/1.1 conditional GET returns 304 cheaply.
#   [P3] Connection pooling / concurrency: front this endpoint with
#        nginx (or Cloudflare) for keepalive + slow-client buffering.
#        FastAPI/uvicorn workers should NOT hold a worker thread per
#        slow downloader — let nginx absorb backpressure. Worker pool
#        sizing: 2 × cpu_count + 1; expect download to be the only
#        slow endpoint in the app, so pin a separate uvicorn instance
#        if concurrent download load exceeds 50.
#   [P4] Eligibility check stays on the redeem hot path; for download
#        the SELECT must use a covering index on (token_sha,
#        redeemed_at, expires_at, payment_confirmed) so the eligibility
#        check is a single index-only scan. Do NOT parse expires_at
#        from a string column at request time — store it as
#        timestamptz and compare server-side.

# Platform Literal, PLATFORM_FILENAMES, PLATFORM_MEDIA_TYPES, and
# DOWNLOAD_CACHE_CONTROL are imported from the shared wire-schema
# module above. The local copies that lived here through iter-56
# were removed in iter-58 per review-20260622T215846Z-1 [3].

# In-memory binary registry for the stub. Production resolves
# bytes off disk under KLX_HELPER_BINARIES_DIR via the
# `BinaryStore` Protocol in infra/klara.handlers/customer_helper_store.py.
_BINARIES: dict[str, bytes] = {}


def _register_stub_binary(platform: str, content: bytes) -> None:
    """Test/dev helper — register a stub payload for `platform`."""
    if platform not in _PLATFORM_FILENAMES:
        raise ValueError(f"unknown platform: {platform}")
    _BINARIES[platform] = content


def _clear_stub_binaries() -> None:
    """Test helper — clear the registry between tests."""
    _BINARIES.clear()


# Chunk size for the stub's StreamingResponse iterator. Mirrors the
# shape production must take (FileResponse → sendfile), so contract
# tests exercise streaming semantics rather than the in-memory
# Response(content=bytes) shape that the performance review flagged.
_DOWNLOAD_CHUNK_BYTES = 64 * 1024


def _iter_in_chunks(buf: bytes, chunk: int = _DOWNLOAD_CHUNK_BYTES):
    for i in range(0, len(buf), chunk):
        yield buf[i : i + chunk]


@app.get("/api/customer-helper/download/{token}")
def download(
    token: str = Path(..., min_length=20, max_length=128),
    platform: Platform = Query(...),
    if_none_match: Optional[str] = Header(default=None, alias="If-None-Match"),
) -> Response:
    tok_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
    print(f"[download] token={tok_hash} platform={platform}")

    row = _TOKENS.get(token)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown token")
    if row["redeemed"]:
        raise HTTPException(status_code=410, detail="token already redeemed")

    sess: Session = row["session"]
    exp = dt.datetime.fromisoformat(sess.expires_at.rstrip("Z"))
    if exp < dt.datetime.utcnow():
        raise HTTPException(status_code=410, detail="token expired")

    content = _BINARIES.get(platform)
    if content is None:
        raise HTTPException(
            status_code=503,
            detail=f"binary not yet available for platform={platform}",
        )

    filename = _PLATFORM_FILENAMES[platform]
    media_type = _PLATFORM_MEDIA_TYPES[platform]
    # Strong ETag = sha256 of the signed binary. Production reads
    # this from the build manifest emitted by scripts/build_customer_helpers.
    etag = f'"{hashlib.sha256(content).hexdigest()}"'

    # RFC 7232 conditional GET — short-circuit before we hand 80MB to
    # the wire. ETag + Cache-Control still ride on the 304 so the
    # client can re-mint its cache entry's freshness window.
    if if_none_match_matches(if_none_match, etag):
        print(f"[download] token={tok_hash} platform={platform} 304")
        return Response(
            status_code=304,
            headers={
                "Cache-Control": _DOWNLOAD_CACHE_CONTROL,
                "ETag": etag,
            },
        )

    print(
        f"[download] token={tok_hash} platform={platform} bytes={len(content)} OK"
    )
    return StreamingResponse(
        _iter_in_chunks(content),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content)),
            "Cache-Control": _DOWNLOAD_CACHE_CONTROL,
            "ETag": etag,
        },
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8765"))
    uvicorn.run(app, host="127.0.0.1", port=port)
