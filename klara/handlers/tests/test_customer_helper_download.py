"""Regression tests for GET /api/v1/customer-helper/download/{token}.

Production wire-in tests for the contract locked in the reference stub:
    infra/rustdesk_controller/customer_helper/server-stub/test_download_stub.py

Architecture mirrors test_customer_helper_redeem.py:
  - TokenStore Protocol injected via FastAPI dependency_overrides
  - _FakePeekStore returns the exact PeekOutcome the test wants
  - filesystem layout faked by pointing KLX_HELPER_BINARIES_DIR at a
    tmp_path + writing a manifest.json + a fake binary

Contract:
  - 200 + Cache-Control: public, max-age=31536000, immutable
  - ETag = sha256 from build manifest (NOT computed per request)
  - Content-Disposition with platform filename
  - FileResponse path (sendfile-backed) — body matches file bytes
  - 402/404/410 mirror the redeem semantics for the eligibility branch
  - 503 when env unset, manifest missing, manifest entry missing,
    or the file the manifest names is absent
  - download MUST NOT call try_redeem (peek-only contract)
  - 422 on missing/invalid platform query param and out-of-range token
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

# Path A re-enabled with Sectigo + Apple signing (16.9 reopened)

from infra import main as main_module

# Same import-path duality workaround as test_customer_helper_redeem.py
# (mistake-33 in CONTINUITY) — go through `klara.handlers.X` because
# main.py loads the handlers under that module identity.
from klara.handlers.customer_helper_store import (  # noqa: E402
    AlreadyRedeemed,
    Available,
    BinaryArtifact,
    BinaryStore,
    Expired,
    PaymentMissing,
    PeekOutcome,
    Unknown,
    get_binary_store,
    get_token_store,
)

client = TestClient(main_module.app)


class _FakePeekStore:
    """In-memory TokenStore for /download tests.

    Asserts the redeem path is never invoked from a download request —
    peek-only contract is load-bearing because /download mid-request
    must not race with /redeem.
    """

    def __init__(self, outcome: PeekOutcome):
        self.outcome = outcome
        self.peek_calls: list[bytes] = []
        self.redeem_calls: list[bytes] = []

    async def try_redeem(self, token_sha: bytes):
        self.redeem_calls.append(token_sha)
        raise AssertionError("download path must not call try_redeem")

    async def peek(self, token_sha: bytes) -> PeekOutcome:
        self.peek_calls.append(token_sha)
        return self.outcome


@pytest.fixture
def with_peek() -> Iterator[callable]:
    """Install a fake TokenStore with a fixed PeekOutcome."""

    def _install(outcome: PeekOutcome) -> _FakePeekStore:
        store = _FakePeekStore(outcome)
        main_module.app.dependency_overrides[get_token_store] = lambda: store
        return store

    yield _install
    main_module.app.dependency_overrides.pop(get_token_store, None)


@pytest.fixture
def binaries_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point KLX_HELPER_BINARIES_DIR at an empty tmp dir."""
    monkeypatch.setenv("KLX_HELPER_BINARIES_DIR", str(tmp_path))
    return tmp_path


def _stage(
    binaries_dir: Path,
    platform: str,
    filename: str,
    content: bytes,
    sha: str,
) -> None:
    """Write the binary + a manifest entry for `platform`."""
    (binaries_dir / filename).write_bytes(content)
    manifest_path = binaries_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text("utf-8"))
    else:
        manifest = {}
    manifest[platform] = {"file": filename, "sha256": sha}
    manifest_path.write_text(json.dumps(manifest), "utf-8")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_download_success_streams_file_with_platform_headers(
    with_peek, binaries_dir
):
    with_peek(Available())
    sha = "f" * 64
    _stage(
        binaries_dir,
        "mac-arm64",
        "Klaravex-Helper-arm64.dmg",
        b"FAKE-DMG-PAYLOAD",
        sha,
    )

    token = "a" * 40
    r = client.get(f"/api/v1/customer-helper/download/{token}?platform=mac-arm64")

    assert r.status_code == 200, r.text
    assert r.content == b"FAKE-DMG-PAYLOAD"
    assert r.headers["content-type"].startswith("application/x-apple-diskimage")
    assert "Klaravex-Helper-arm64.dmg" in r.headers["content-disposition"]
    # Raw token MUST NOT echo back into the response body.
    assert token.encode() not in r.content


def test_download_emits_immutable_cache_control(with_peek, binaries_dir):
    with_peek(Available())
    _stage(binaries_dir, "mac-arm64", "Klaravex-Helper-arm64.dmg", b"X", "0" * 64)

    r = client.get(
        f"/api/v1/customer-helper/download/{'a' * 32}?platform=mac-arm64"
    )

    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_download_etag_is_strong_quoted_sha_from_manifest(
    with_peek, binaries_dir
):
    """ETag MUST come from build manifest, not be hashed at request time —
    request-time hashing of 80MB re-introduces the [P1] memory regression
    that iter-55/56 fixed in the stub."""
    with_peek(Available())
    sha = "deadbeef" * 8  # 64 hex chars
    _stage(binaries_dir, "linux-x64", "Klaravex-Helper-x86_64.AppImage", b"Z", sha)

    r = client.get(
        f"/api/v1/customer-helper/download/{'b' * 32}?platform=linux-x64"
    )

    assert r.status_code == 200
    assert r.headers["etag"] == f'"{sha}"'


@pytest.mark.parametrize(
    "platform,filename,media_type",
    [
        ("mac-arm64", "Klaravex-Helper-arm64.dmg", "application/x-apple-diskimage"),
        ("mac-x64", "Klaravex-Helper-x64.dmg", "application/x-apple-diskimage"),
        (
            "win-x64",
            "Klaravex-Helper-Setup.exe",
            "application/vnd.microsoft.portable-executable",
        ),
        (
            "linux-x64",
            "Klaravex-Helper-x86_64.AppImage",
            "application/x-executable",
        ),
    ],
)
def test_download_per_platform_filename_and_media_type(
    with_peek, binaries_dir, platform, filename, media_type
):
    with_peek(Available())
    _stage(binaries_dir, platform, filename, b"BYTES", "1" * 64)

    r = client.get(
        f"/api/v1/customer-helper/download/{'c' * 32}?platform={platform}"
    )

    assert r.status_code == 200
    assert r.headers["content-type"].startswith(media_type)
    assert filename in r.headers["content-disposition"]


def test_download_does_not_invoke_try_redeem(with_peek, binaries_dir):
    """Peek-only contract: /download MUST NOT mutate the row.

    Customer must be able to re-download (e.g. browser closed)
    and the helper must still find a live token when it calls /redeem.
    """
    store = with_peek(Available())
    _stage(binaries_dir, "mac-arm64", "Klaravex-Helper-arm64.dmg", b"X", "1" * 64)

    r = client.get(
        f"/api/v1/customer-helper/download/{'d' * 32}?platform=mac-arm64"
    )

    assert r.status_code == 200
    assert store.redeem_calls == []
    assert len(store.peek_calls) == 1


# ---------------------------------------------------------------------------
# Eligibility branches
# ---------------------------------------------------------------------------


def test_download_unknown_token_returns_404(with_peek, binaries_dir):
    with_peek(Unknown())
    _stage(binaries_dir, "mac-arm64", "Klaravex-Helper-arm64.dmg", b"X", "1" * 64)

    r = client.get(
        f"/api/v1/customer-helper/download/{'e' * 32}?platform=mac-arm64"
    )

    assert r.status_code == 404
    assert r.json() == {"detail": "unknown token"}


def test_download_already_redeemed_returns_410(with_peek, binaries_dir):
    with_peek(AlreadyRedeemed())
    _stage(binaries_dir, "mac-arm64", "Klaravex-Helper-arm64.dmg", b"X", "1" * 64)

    r = client.get(
        f"/api/v1/customer-helper/download/{'f' * 32}?platform=mac-arm64"
    )

    assert r.status_code == 410
    assert "already redeemed" in r.json()["detail"]


def test_download_expired_returns_410(with_peek, binaries_dir):
    with_peek(Expired())
    _stage(binaries_dir, "mac-arm64", "Klaravex-Helper-arm64.dmg", b"X", "1" * 64)

    r = client.get(
        f"/api/v1/customer-helper/download/{'g' * 32}?platform=mac-arm64"
    )

    assert r.status_code == 410
    assert r.json()["detail"] == "token expired"


def test_download_payment_missing_returns_402(with_peek, binaries_dir):
    with_peek(PaymentMissing())
    _stage(binaries_dir, "mac-arm64", "Klaravex-Helper-arm64.dmg", b"X", "1" * 64)

    r = client.get(
        f"/api/v1/customer-helper/download/{'h' * 32}?platform=mac-arm64"
    )

    assert r.status_code == 402
    assert r.json()["detail"] == "payment not confirmed"


# ---------------------------------------------------------------------------
# Pre-procurement / unavailability branches — MUST be 503, never 404
# ---------------------------------------------------------------------------


def test_download_returns_503_when_env_unset(
    with_peek, monkeypatch: pytest.MonkeyPatch
):
    """KLX_HELPER_BINARIES_DIR unset — operator deployed handler before
    binary distribution path exists. Customer sees 503, not 404."""
    monkeypatch.delenv("KLX_HELPER_BINARIES_DIR", raising=False)
    with_peek(Available())

    r = client.get(
        f"/api/v1/customer-helper/download/{'i' * 32}?platform=mac-arm64"
    )

    assert r.status_code == 503
    assert "mac-arm64" in r.json()["detail"]


def test_download_returns_503_when_manifest_missing(with_peek, binaries_dir):
    """Env set, dir exists, but no manifest.json — pre-staging state."""
    with_peek(Available())

    r = client.get(
        f"/api/v1/customer-helper/download/{'j' * 32}?platform=mac-arm64"
    )

    assert r.status_code == 503


def test_download_returns_503_when_manifest_lacks_platform(
    with_peek, binaries_dir
):
    """Manifest present but missing this platform — e.g. win-x64 signed
    but mac notarization not yet through Apple."""
    with_peek(Available())
    _stage(binaries_dir, "win-x64", "Klaravex-Helper-Setup.exe", b"X", "1" * 64)

    r = client.get(
        f"/api/v1/customer-helper/download/{'k' * 32}?platform=mac-arm64"
    )

    assert r.status_code == 503
    assert "mac-arm64" in r.json()["detail"]


def test_download_returns_503_when_file_missing_despite_manifest(
    with_peek, binaries_dir
):
    """Manifest references a file that does not exist — partial deploy."""
    with_peek(Available())
    manifest = {
        "mac-arm64": {"file": "missing.dmg", "sha256": "0" * 64}
    }
    (binaries_dir / "manifest.json").write_text(json.dumps(manifest), "utf-8")

    r = client.get(
        f"/api/v1/customer-helper/download/{'l' * 32}?platform=mac-arm64"
    )

    assert r.status_code == 503


def test_download_handles_unreadable_manifest(
    with_peek, binaries_dir
):
    """Corrupt JSON manifest is logged + falls through to 503, never
    crashes the handler."""
    with_peek(Available())
    (binaries_dir / "manifest.json").write_text("not-json{", "utf-8")

    r = client.get(
        f"/api/v1/customer-helper/download/{'m' * 32}?platform=mac-arm64"
    )

    assert r.status_code == 503


# ---------------------------------------------------------------------------
# Path / query validation
# ---------------------------------------------------------------------------


def test_download_rejects_invalid_platform_with_422(binaries_dir):
    r = client.get(
        f"/api/v1/customer-helper/download/{'n' * 32}?platform=arm-aix"
    )
    assert r.status_code == 422


def test_download_rejects_missing_platform_with_422(binaries_dir):
    r = client.get(f"/api/v1/customer-helper/download/{'o' * 32}")
    assert r.status_code == 422


def test_download_rejects_too_short_token():
    r = client.get("/api/v1/customer-helper/download/short?platform=mac-arm64")
    assert r.status_code == 422


def test_download_rejects_too_long_token():
    r = client.get(
        f"/api/v1/customer-helper/download/{'p' * 129}?platform=mac-arm64"
    )
    assert r.status_code == 422


def test_download_rejects_non_base64url_token_with_422():
    """Token pattern is base64url (A-Za-z0-9_-); other chars must 422
    at the FastAPI layer, never reach the SQL parameter binding.
    Closes security-sentinel S2988 Low (token regex validation)."""
    # 32 chars including a '!' — meets length, fails pattern.
    bad = "a" * 31 + "!"
    r = client.get(
        f"/api/v1/customer-helper/download/{bad}?platform=mac-arm64"
    )
    assert r.status_code == 422


def test_download_logs_only_token_hash_prefix(
    with_peek, binaries_dir, caplog
):
    """Raw token MUST NOT appear in any log line (mirrors /redeem
    contract — review-20260621T123417Z-1)."""
    import logging

    with_peek(Available())
    _stage(binaries_dir, "mac-arm64", "Klaravex-Helper-arm64.dmg", b"X", "1" * 64)

    token = "leaky-token-do-not-print" + "x" * 16
    with caplog.at_level(logging.INFO, logger="klaravex.customer_helper"):
        r = client.get(
            f"/api/v1/customer-helper/download/{token}?platform=mac-arm64"
        )

    assert r.status_code == 200
    for rec in caplog.records:
        assert token not in rec.getMessage(), (
            f"raw token leaked into log: {rec.getMessage()!r}"
        )


def test_download_returns_503_when_manifest_escapes_binaries_dir(
    with_peek, binaries_dir, tmp_path: Path
):
    """Path-traversal guard: a manifest whose `file` field escapes the
    binaries dir MUST resolve to 503, never to streaming the escaped
    file. Closes the security-sentinel S2988 medium finding from
    iter-57.
    """
    with_peek(Available())
    # Stage a real file *outside* the binaries dir.
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    leak_target = sibling / "secret.bin"
    leak_target.write_bytes(b"SHOULD-NEVER-STREAM")
    # Manifest names a relative path that escapes the dir.
    manifest = {
        "mac-arm64": {
            "file": "../sibling/secret.bin",
            "sha256": "0" * 64,
        }
    }
    (binaries_dir / "manifest.json").write_text(json.dumps(manifest), "utf-8")

    r = client.get(
        f"/api/v1/customer-helper/download/{'r' * 32}?platform=mac-arm64"
    )

    assert r.status_code == 503
    assert b"SHOULD-NEVER-STREAM" not in r.content


def test_download_uses_injected_binary_store(with_peek, tmp_path: Path):
    """BinaryStore DI seam: when a fake BinaryStore is injected via
    `app.dependency_overrides[get_binary_store]`, the handler does
    NOT consult the filesystem or KLX_HELPER_BINARIES_DIR — it asks
    the injected store. Closes review-20260622T215846Z-1 [2]
    (asymmetric DI / pattern-40 regression).
    """
    with_peek(Available())
    payload = tmp_path / "fake.dmg"
    payload.write_bytes(b"INJECTED-VIA-STORE")

    calls: list[str] = []

    class _FakeBinaryStore:
        def resolve(self, platform: str):
            calls.append(platform)
            return BinaryArtifact(path=payload, sha256="c" * 64)

    main_module.app.dependency_overrides[get_binary_store] = lambda: _FakeBinaryStore()
    try:
        r = client.get(
            f"/api/v1/customer-helper/download/{'s' * 32}?platform=win-x64"
        )
    finally:
        main_module.app.dependency_overrides.pop(get_binary_store, None)

    assert r.status_code == 200, r.text
    assert r.content == b"INJECTED-VIA-STORE"
    assert r.headers["etag"] == f'"{"c" * 64}"'
    assert calls == ["win-x64"]


def test_download_503_when_injected_store_returns_none(with_peek):
    """Pre-procurement parity through the DI seam — None → 503."""
    with_peek(Available())

    class _NullBinaryStore:
        def resolve(self, platform: str):
            return None

    main_module.app.dependency_overrides[get_binary_store] = lambda: _NullBinaryStore()
    try:
        r = client.get(
            f"/api/v1/customer-helper/download/{'t' * 32}?platform=mac-x64"
        )
    finally:
        main_module.app.dependency_overrides.pop(get_binary_store, None)

    assert r.status_code == 503
    assert "mac-x64" in r.json()["detail"]


def test_binary_store_protocol_is_satisfied_by_fake():
    """Compile-time sanity: a minimal class satisfies the Protocol."""

    class _Min:
        def resolve(self, platform: str):
            return None

    store: BinaryStore = _Min()
    assert store.resolve("mac-arm64") is None


def test_download_passes_sha256_to_store(with_peek, binaries_dir):
    """Lock the contract that store.peek receives sha256(token), NOT raw."""
    import hashlib

    store = with_peek(Available())
    _stage(binaries_dir, "mac-arm64", "Klaravex-Helper-arm64.dmg", b"X", "1" * 64)

    token = "q" * 40
    expected = hashlib.sha256(token.encode("utf-8")).digest()
    r = client.get(
        f"/api/v1/customer-helper/download/{token}?platform=mac-arm64"
    )

    assert r.status_code == 200
    assert store.peek_calls == [expected]


# ---------------------------------------------------------------------------
# RFC 7232 conditional GET — 304 short-circuits the 80MB body
# review-20260622T215846Z-1 Medium [P2]
# ---------------------------------------------------------------------------


def _setup_available_dmg(with_peek, binaries_dir: Path, sha: str = "a" * 64) -> str:
    """Common arrangement: Available peek + staged DMG. Returns the ETag."""
    with_peek(Available())
    _stage(
        binaries_dir,
        "mac-arm64",
        "Klaravex-Helper-arm64.dmg",
        b"FAKE-DMG-PAYLOAD",
        sha,
    )
    return f'"{sha}"'


def test_download_returns_304_when_if_none_match_equals_etag(
    with_peek, binaries_dir
):
    etag = _setup_available_dmg(with_peek, binaries_dir)

    token = "a" * 40
    r = client.get(
        f"/api/v1/customer-helper/download/{token}?platform=mac-arm64",
        headers={"If-None-Match": etag},
    )

    assert r.status_code == 304
    assert r.headers["etag"] == etag
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert r.content == b""


def test_download_returns_304_on_wildcard_if_none_match(with_peek, binaries_dir):
    _setup_available_dmg(with_peek, binaries_dir)

    token = "b" * 40
    r = client.get(
        f"/api/v1/customer-helper/download/{token}?platform=mac-arm64",
        headers={"If-None-Match": "*"},
    )

    assert r.status_code == 304
    assert r.content == b""


def test_download_returns_304_on_weak_form_of_etag(with_peek, binaries_dir):
    etag = _setup_available_dmg(with_peek, binaries_dir, sha="c" * 64)

    token = "c" * 40
    r = client.get(
        f"/api/v1/customer-helper/download/{token}?platform=mac-arm64",
        headers={"If-None-Match": f"W/{etag}"},
    )

    assert r.status_code == 304


def test_download_returns_304_when_etag_appears_in_list(with_peek, binaries_dir):
    etag = _setup_available_dmg(with_peek, binaries_dir, sha="d" * 64)

    token = "d" * 40
    r = client.get(
        f"/api/v1/customer-helper/download/{token}?platform=mac-arm64",
        headers={"If-None-Match": f'"deadbeef", {etag}, "cafebabe"'},
    )

    assert r.status_code == 304


def test_download_returns_200_when_if_none_match_does_not_match(
    with_peek, binaries_dir
):
    _setup_available_dmg(with_peek, binaries_dir, sha="e" * 64)

    token = "e" * 40
    r = client.get(
        f"/api/v1/customer-helper/download/{token}?platform=mac-arm64",
        headers={"If-None-Match": '"not-the-etag"'},
    )

    assert r.status_code == 200
    assert r.content == b"FAKE-DMG-PAYLOAD"


def test_download_304_skips_filesystem_read_for_body(
    with_peek, binaries_dir, monkeypatch
):
    """304 path must NOT invoke the FileResponse body — verify by deleting
    the staged file AFTER setup but before request, then matching ETag
    short-circuits the response."""
    etag = _setup_available_dmg(with_peek, binaries_dir, sha="f" * 64)
    # File still on disk at this point — ETag handshake doesn't depend
    # on the body, but we DO need the manifest+file to pass the
    # BinaryStore.resolve eligibility check. Leaving the file in place
    # is correct; this test just locks that the body is empty.

    token = "f" * 40
    r = client.get(
        f"/api/v1/customer-helper/download/{token}?platform=mac-arm64",
        headers={"If-None-Match": etag},
    )

    assert r.status_code == 304
    assert r.content == b""
    # Content-Length on 304 is either absent or 0 (RFC 9110 §15.4.5)
    cl = r.headers.get("content-length")
    assert cl in (None, "0")


# Pattern-44 regression — conditional-GET handler MUST reject body before
# sendfile. Locks the call-order invariant by spying on the handler's
# FileResponse symbol: matching If-None-Match short-circuits via Response
# (status 304) and FileResponse is NEVER instantiated. Without this spy a
# future reorder that constructs FileResponse before the early-return
# would still emit 304 (FastAPI discards the body on 304) but would have
# touched the filesystem to stat the file, defeating the whole purpose of
# the conditional-GET fast path. (review-20260622T224005Z-5 eng-qa
# Medium [2]; previously flagged in review-20260622T222000Z-3 Low [P10]
# and review-20260622T222553Z-4 Low [9].)


def test_download_304_does_not_construct_fileresponse(
    with_peek, binaries_dir, monkeypatch
):
    from klara.handlers import customer_helper as _ch

    calls: list[tuple[tuple, dict]] = []
    real_fileresponse = _ch.FileResponse

    def _spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real_fileresponse(*args, **kwargs)

    monkeypatch.setattr(_ch, "FileResponse", _spy)

    etag = _setup_available_dmg(with_peek, binaries_dir, sha="9" * 64)
    token = "9" * 40

    r = client.get(
        f"/api/v1/customer-helper/download/{token}?platform=mac-arm64",
        headers={"If-None-Match": etag},
    )

    assert r.status_code == 304
    assert calls == [], (
        "Pattern-44 regression: FileResponse was constructed on the 304 "
        "path. The conditional-GET early-return must precede every "
        "FileResponse call site so cached clients never trigger a stat "
        "or sendfile on the 80MB body."
    )


def test_download_200_does_construct_fileresponse(
    with_peek, binaries_dir, monkeypatch
):
    """Positive control for the Pattern-44 spy — the 200 path MUST still
    instantiate FileResponse, otherwise the spy would pass when the
    handler regresses to never serving the body at all."""
    from klara.handlers import customer_helper as _ch

    calls: list[tuple[tuple, dict]] = []
    real_fileresponse = _ch.FileResponse

    def _spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real_fileresponse(*args, **kwargs)

    monkeypatch.setattr(_ch, "FileResponse", _spy)

    _setup_available_dmg(with_peek, binaries_dir, sha="8" * 64)
    token = "8" * 40

    r = client.get(
        f"/api/v1/customer-helper/download/{token}?platform=mac-arm64",
    )

    assert r.status_code == 200
    assert len(calls) == 1, (
        f"expected exactly one FileResponse construction, got {len(calls)}"
    )
