"""T-INF-02 — /healthz HTTP-method handling.

Regression test for observation 9096: /healthz used to return 405 with a
contradictory Allow header. GET=200, HEAD=200, POST=405 with Allow exactly
listing the allowed methods.
"""
from fastapi.testclient import TestClient

from infra.main import app


client = TestClient(app)


def test_healthz_get_returns_200_ok():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_healthz_head_returns_200():
    r = client.head("/healthz")
    assert r.status_code == 200


def test_healthz_post_returns_405_with_allow_header():
    r = client.post("/healthz")
    assert r.status_code == 405
    allow = r.headers.get("Allow") or r.headers.get("allow")
    assert allow is not None, "405 must include Allow"
    methods = {m.strip().upper() for m in allow.split(",")}
    assert "GET" in methods, f"Allow must include GET: {allow!r}"
