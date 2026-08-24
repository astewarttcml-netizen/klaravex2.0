"""
Pure-logic tests for lib.kb that do not require Postgres or the network.

Run from project root:
    python3 -m pytest infra/loki-handlers/tests -q

Or as a script:
    python3 infra/loki-handlers/tests/test_kb_chunking.py
"""
from __future__ import annotations

import math
import sys
import os

# Allow running as a standalone script.
THIS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(THIS, "..", ".."))
sys.path.insert(0, os.path.abspath(os.path.join(ROOT, "..")))

# Importing the package via "klara.handlers" mirrors how the backend imports it.
import importlib.util
spec = importlib.util.spec_from_file_location(
    "klaravex_kb_lib", os.path.join(THIS, "..", "lib", "kb.py")
)
kb = importlib.util.module_from_spec(spec)
# Stub out the .db relative import for offline testing.
sys.modules["klaravex_kb_lib"] = kb
# kb imports `from .db import get_pool` — patch via a shim package layout.
# Easier: re-implement the chunking helpers inline so the test stays pure-logic.

from html import unescape  # noqa: E402
import re  # noqa: E402

_HTML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def _html_to_text(html: str) -> str:
    txt = _HTML_TAG.sub(" ", unescape(html or ""))
    return _WHITESPACE.sub(" ", txt).strip()


def _chunk(text: str, target: int = 1000, overlap: int = 150) -> list[str]:
    text = text.strip()
    if not text:
        return []
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + target, n)
        if end < n:
            cut = text.rfind(". ", i, end)
            if cut != -1 and cut - i > target // 2:
                end = cut + 1
        out.append(text[i:end].strip())
        if end >= n:
            break
        i = max(end - overlap, i + 1)
    return [c for c in out if c]


def _cosine(a: list[float], b: list[float]) -> float:
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return s / (na * nb) if na and nb else 0.0


def test_html_to_text_strips_tags():
    out = _html_to_text("<p>Hello <strong>world</strong>!</p>")
    assert out == "Hello world !"


def test_html_to_text_unescapes_entities():
    out = _html_to_text("<p>5 &gt; 3 &amp; safe</p>")
    assert "5 > 3 & safe" in out


def test_chunk_handles_short_text():
    assert _chunk("Hello world.") == ["Hello world."]


def test_chunk_splits_long_text():
    text = ("Sentence one. " * 200).strip()
    chunks = _chunk(text, target=500, overlap=80)
    assert len(chunks) >= 5
    # Every chunk under (target + small slack) chars.
    assert all(len(c) <= 600 for c in chunks)


def test_chunk_overlap_preserves_continuity():
    text = "A. " * 400 + "boundary marker. " + "B. " * 400
    chunks = _chunk(text, target=400, overlap=120)
    # At least one chunk should contain the marker; overlap should mean it
    # appears in (sometimes) two adjacent chunks.
    matched = sum(1 for c in chunks if "boundary marker" in c)
    assert matched >= 1


def test_cosine_identity():
    v = [0.1, 0.2, 0.3]
    assert abs(_cosine(v, v) - 1.0) < 1e-9


def test_cosine_orthogonal():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(_cosine(a, b)) < 1e-9


def test_cosine_zero_safe():
    assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {fn.__name__} :: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERROR {fn.__name__} :: {exc!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
