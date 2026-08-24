"""Contract tests for GET /api/customer-helper/download/{token}.

This is a REFERENCE STUB test suite, mirroring the structure of the
production tests at infra/klara.handlers/tests/test_customer_helper_redeem.py.
The stub here documents the contract the production /download endpoint
must satisfy when it lands (G34 next bounded deliverable):

  - 200 + binary bytes on success, with platform-correct Content-Disposition
  - 404 on unknown token
  - 410 on already-redeemed token
  - 410 on expired token
  - 422 on invalid platform query param (FastAPI Literal enforcement)
  - 503 when the binary is not yet staged for that platform
  - download MUST NOT mark the token redeemed (customer needs token live
    when the helper launches and calls /redeem)
  - raw token never echoes back in the response body

Run from repo root:

    PYTHONPATH=. python3 -m pytest \\
        infra/rustdesk_controller/customer_helper/server-stub/test_download_stub.py
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import sys

import pytest
from fastapi.testclient import TestClient


def _load_stub_module():
    """Load redeem_api.py without going through a package import.

    The directory name contains a dash (`server-stub/`) which is not a
    legal Python identifier, so it cannot be imported as a normal
    package. We load it by file path instead.
    """
    here = pathlib.Path(__file__).parent
    spec = importlib.util.spec_from_file_location(
        "klx_customer_helper_stub", here / "redeem_api.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["klx_customer_helper_stub"] = mod
    spec.loader.exec_module(mod)
    return mod


stub = _load_stub_module()
Session = stub.Session
app = stub.app
client = TestClient(app)


def _seed_token(*, redeemed: bool = False, expired: bool = False) -> str:
    """Insert a known token into the stub's in-memory store and return it."""
    token = "tok-" + "x" * 36
    exp = dt.datetime.utcnow() + (
        dt.timedelta(minutes=-5) if expired else dt.timedelta(minutes=30)
    )
    sess = Session(
        customer_session_id="123456789",
        session_password="pw-20chars-redacted!",
        expires_at=exp.isoformat() + "Z",
        display_topic="printer-trouble",
        operator_label="Klara (AI)",
    )
    stub._TOKENS[token] = {"session": sess, "redeemed": redeemed}
    return token


@pytest.fixture(autouse=True)
def _reset_stub_state():
    """Clear the stub's in-memory tables between tests."""
    stub._TOKENS.clear()
    stub._clear_stub_binaries()
    yield
    stub._TOKENS.clear()
    stub._clear_stub_binaries()


def test_download_success_returns_binary_with_content_disposition():
    token = _seed_token()
    payload = b"FAKE-MACOS-DMG-PAYLOAD"
    stub._register_stub_binary("mac-arm64", payload)

    r = client.get(f"/api/customer-helper/download/{token}?platform=mac-arm64")

    assert r.status_code == 200, r.text
    assert r.content == payload
    assert r.headers["content-type"].startswith("application/x-apple-diskimage")
    assert (
        r.headers["content-disposition"]
        == 'attachment; filename="Klaravex-Helper-arm64.dmg"'
    )
    # Raw token must NOT echo back into response body.
    assert token.encode() not in r.content


def test_download_emits_immutable_cache_control():
    """Signed binaries are immutable per release; downstream caches
    (browser, CDN, corp proxy) MUST be allowed to serve repeats so a
    customer retry click does not re-pull the binary from origin.
    Production contract: Cache-Control: public, max-age=31536000, immutable."""
    token = _seed_token()
    stub._register_stub_binary("mac-arm64", b"PAYLOAD")

    r = client.get(f"/api/customer-helper/download/{token}?platform=mac-arm64")

    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_download_emits_strong_etag_matching_sha256():
    """Strong ETag derived from sha256 of the payload enables cheap
    conditional GET (304 Not Modified) on retry without re-shipping
    the body."""
    import hashlib

    token = _seed_token()
    payload = b"PAYLOAD-FOR-ETAG"
    stub._register_stub_binary("mac-arm64", payload)

    r = client.get(f"/api/customer-helper/download/{token}?platform=mac-arm64")

    assert r.status_code == 200
    expected = f'"{hashlib.sha256(payload).hexdigest()}"'
    assert r.headers["etag"] == expected


def test_download_streams_in_chunks_not_single_buffer():
    """Production must serve via FileResponse/sendfile so 80MB
    binaries don't materialize in process memory per request. The
    stub mirrors that shape with StreamingResponse + chunked iterator.
    Verify via the raw transport, not the convenience .content prop."""
    token = _seed_token()
    # Payload larger than the stub's chunk size (64 KiB) so iter
    # actually yields more than one chunk.
    payload = b"X" * (3 * stub._DOWNLOAD_CHUNK_BYTES + 17)
    stub._register_stub_binary("linux-x64", payload)

    with client.stream(
        "GET", f"/api/customer-helper/download/{token}?platform=linux-x64"
    ) as r:
        assert r.status_code == 200
        chunks = list(r.iter_bytes(chunk_size=stub._DOWNLOAD_CHUNK_BYTES))

    assert b"".join(chunks) == payload
    # The whole payload should not arrive in a single iter step.
    assert len(chunks) >= 2


def test_download_sets_content_length_header():
    """Content-Length must be present so clients can show a progress
    bar and so HEAD requests work without buffering the body."""
    token = _seed_token()
    payload = b"Z" * 4096
    stub._register_stub_binary("win-x64", payload)

    r = client.get(f"/api/customer-helper/download/{token}?platform=win-x64")

    assert r.status_code == 200
    assert r.headers["content-length"] == str(len(payload))


@pytest.mark.parametrize(
    "platform,expected_filename,expected_media",
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
    platform, expected_filename, expected_media
):
    token = _seed_token()
    stub._register_stub_binary(platform, b"X")

    r = client.get(f"/api/customer-helper/download/{token}?platform={platform}")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith(expected_media)
    assert (
        r.headers["content-disposition"]
        == f'attachment; filename="{expected_filename}"'
    )


def test_download_does_not_mark_token_redeemed():
    """Customer can re-download (e.g. browser tab closed) and the helper
    still has a live token to call /redeem with."""
    token = _seed_token()
    stub._register_stub_binary("linux-x64", b"AppImage-bytes")

    r1 = client.get(f"/api/customer-helper/download/{token}?platform=linux-x64")
    r2 = client.get(f"/api/customer-helper/download/{token}?platform=linux-x64")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert stub._TOKENS[token]["redeemed"] is False


def test_download_unknown_token_returns_404():
    stub._register_stub_binary("mac-arm64", b"X")
    bogus = "z" * 40

    r = client.get(f"/api/customer-helper/download/{bogus}?platform=mac-arm64")

    assert r.status_code == 404
    assert r.json() == {"detail": "unknown token"}


def test_download_already_redeemed_token_returns_410():
    token = _seed_token(redeemed=True)
    stub._register_stub_binary("mac-arm64", b"X")

    r = client.get(f"/api/customer-helper/download/{token}?platform=mac-arm64")

    assert r.status_code == 410
    assert "already redeemed" in r.json()["detail"]


def test_download_expired_token_returns_410():
    token = _seed_token(expired=True)
    stub._register_stub_binary("mac-arm64", b"X")

    r = client.get(f"/api/customer-helper/download/{token}?platform=mac-arm64")

    assert r.status_code == 410
    assert r.json()["detail"] == "token expired"


def test_download_binary_missing_returns_503():
    """No binary staged for that platform — production parity for the
    pre-procurement state where signed binaries don't exist yet."""
    token = _seed_token()
    # No _register_stub_binary call — registry is empty.

    r = client.get(f"/api/customer-helper/download/{token}?platform=win-x64")

    assert r.status_code == 503
    assert "win-x64" in r.json()["detail"]


def test_download_invalid_platform_returns_422():
    """FastAPI's Literal type rejects unknown platform values at the
    validation layer."""
    token = _seed_token()

    r = client.get(f"/api/customer-helper/download/{token}?platform=arm-aix")

    assert r.status_code == 422


def test_download_missing_platform_query_returns_422():
    token = _seed_token()
    r = client.get(f"/api/customer-helper/download/{token}")
    assert r.status_code == 422


def test_download_short_token_returns_422():
    """Path-layer min_length=20 enforcement (mirrors /redeem)."""
    r = client.get("/api/customer-helper/download/short?platform=mac-arm64")
    assert r.status_code == 422


def test_download_long_token_returns_422():
    """Path-layer max_length=128 enforcement (mirrors /redeem)."""
    r = client.get(
        f"/api/customer-helper/download/{'q' * 129}?platform=mac-arm64"
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# RFC 7232 conditional GET — 304 Not Modified short-circuit
# ---------------------------------------------------------------------------


def _etag_for(payload: bytes) -> str:
    import hashlib

    return f'"{hashlib.sha256(payload).hexdigest()}"'


def test_download_returns_304_when_if_none_match_equals_etag():
    """Matched If-None-Match must short-circuit before the 80MB body."""
    token = _seed_token()
    payload = b"PAYLOAD-FOR-IF-NONE-MATCH"
    stub._register_stub_binary("mac-arm64", payload)
    etag = _etag_for(payload)

    r = client.get(
        f"/api/customer-helper/download/{token}?platform=mac-arm64",
        headers={"If-None-Match": etag},
    )

    assert r.status_code == 304
    assert r.headers["etag"] == etag
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert r.content == b""


def test_download_returns_304_when_if_none_match_is_wildcard():
    """`If-None-Match: *` matches any existing representation (RFC 7232)."""
    token = _seed_token()
    stub._register_stub_binary("linux-x64", b"PAYLOAD")

    r = client.get(
        f"/api/customer-helper/download/{token}?platform=linux-x64",
        headers={"If-None-Match": "*"},
    )

    assert r.status_code == 304
    assert r.content == b""


def test_download_returns_304_when_if_none_match_lists_match_among_others():
    """Comma-separated list with at least one matching tag → 304."""
    token = _seed_token()
    payload = b"PAYLOAD-MULTI"
    stub._register_stub_binary("mac-arm64", payload)
    etag = _etag_for(payload)

    r = client.get(
        f"/api/customer-helper/download/{token}?platform=mac-arm64",
        headers={"If-None-Match": f'"deadbeef", {etag}, "cafebabe"'},
    )

    assert r.status_code == 304


def test_download_returns_304_when_if_none_match_is_weak_form_of_etag():
    """Weak form W/"..." of the same opaque value matches our strong tag."""
    token = _seed_token()
    payload = b"PAYLOAD-WEAK"
    stub._register_stub_binary("win-x64", payload)
    etag = _etag_for(payload)

    r = client.get(
        f"/api/customer-helper/download/{token}?platform=win-x64",
        headers={"If-None-Match": f"W/{etag}"},
    )

    assert r.status_code == 304


def test_download_returns_200_when_if_none_match_does_not_match():
    """Non-matching If-None-Match falls through to the full body."""
    token = _seed_token()
    payload = b"PAYLOAD-MISS"
    stub._register_stub_binary("mac-arm64", payload)

    r = client.get(
        f"/api/customer-helper/download/{token}?platform=mac-arm64",
        headers={"If-None-Match": '"not-our-etag"'},
    )

    assert r.status_code == 200
    assert r.content == payload


def test_download_returns_200_when_if_none_match_header_absent():
    """No conditional header → full body (regression for plain GET path)."""
    token = _seed_token()
    payload = b"PAYLOAD-NO-COND"
    stub._register_stub_binary("mac-arm64", payload)

    r = client.get(f"/api/customer-helper/download/{token}?platform=mac-arm64")

    assert r.status_code == 200
    assert r.content == payload
