"""Unit + contract tests for the shared customer-helper wire schemas.

Three eng-qa High findings from review-20260622T222553Z-4 motivated this
file when iter-61 promoted `_if_none_match_matches` from two private
copies to a single public `if_none_match_matches` in
`customer_helper_schemas`:

  1. No direct unit test for the relocated function at its new public
     boundary — covered by `TestIfNoneMatchMatches` (a parametrised
     RFC 7232 §3.2 matrix).

  2. No regression test locking the Pattern-38 dedup invariant — covered
     by `test_no_shadow_definitions_in_consumers` (asserts that neither
     consumer module redefines the parser under any of the historical
     names).

  3. No symbol-identity contract across the seam — covered by
     `test_consumers_bind_to_canonical_implementation` (asserts both
     consumers' bound symbol IS the schemas module's function object,
     not a re-import shadow).

Also exercises the `__all__` export contract added alongside the tests
(eng-qa Medium [7]).

Run from repo root:

    PYTHONPATH=. python3 -m pytest \\
        infra/klara.handlers/tests/test_customer_helper_schemas.py
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import pathlib
import sys

import pytest


# Same import-path duality as test_customer_helper_download.py — the
# production app loads handlers under the `klara.handlers.X` module
# identity, so the tests must too.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# --- target module imports -------------------------------------------------

from klara.handlers import customer_helper as _ch_handler  # noqa: E402
from klara.handlers import customer_helper_schemas as _ch_schemas  # noqa: E402


def _load_stub_module():
    """Mirror the loader used by the stub's own test file — the
    `server-stub/` directory contains a dash so it can't be imported as
    a package."""
    stub_path = (
        _REPO_ROOT
        / "infra"
        / "rustdesk_controller"
        / "customer_helper"
        / "server-stub"
        / "redeem_api.py"
    )
    spec = importlib.util.spec_from_file_location(
        "klx_customer_helper_stub_for_schema_tests", stub_path
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_stub = _load_stub_module()


# --- direct unit tests on the public boundary -----------------------------

_ETAG = '"' + ("a" * 64) + '"'  # what the handler emits: strong sha256
_WEAK_ETAG = "W/" + _ETAG
_OTHER = '"deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"'


class TestIfNoneMatchMatches:
    """Parametrised RFC 7232 §3.2 weak-comparison matrix.

    Single source of truth — both /redeem and /download consumers go
    through the same function, so this matrix supplies their full
    expected behaviour by construction (eng-qa review-20260622T222553Z-4
    Low [8]).
    """

    @pytest.mark.parametrize(
        "header,etag,expected,why",
        [
            # --- positive cases (304) --------------------------------------
            (_ETAG, _ETAG, True, "exact strong-form match"),
            (_WEAK_ETAG, _ETAG, True, "weak header against strong tag"),
            ("*", _ETAG, True, "wildcard accepts any tag"),
            (f"{_OTHER}, {_ETAG}", _ETAG, True, "match at tail of list"),
            (f"{_ETAG}, {_OTHER}", _ETAG, True, "match at head of list"),
            (f"{_OTHER},{_ETAG}", _ETAG, True, "list w/o whitespace OWS"),
            (f"  {_ETAG}  ", _ETAG, True, "leading/trailing OWS tolerated"),
            (f"{_OTHER}, {_WEAK_ETAG}", _ETAG, True, "weak form inside list"),
            # --- negative cases (200) --------------------------------------
            (None, _ETAG, False, "missing header"),
            ("", _ETAG, False, "empty header"),
            (_OTHER, _ETAG, False, "different opaque value"),
            (f"{_OTHER}, {_OTHER}", _ETAG, False, "list of misses"),
            ('"a"', _ETAG, False, "prefix-only string is not a match"),
        ],
    )
    def test_matrix(self, header, etag, expected, why):
        assert (
            _ch_schemas.if_none_match_matches(header, etag) is expected
        ), why

    def test_returns_bool_not_truthy(self):
        # Downstream code does `if matches: return 304_response` which
        # would work even with a non-bool truthy return — but the
        # protocol promises bool, and a future caller writing
        # `matches is True` should be supported.
        result = _ch_schemas.if_none_match_matches(_ETAG, _ETAG)
        assert result is True
        result = _ch_schemas.if_none_match_matches(None, _ETAG)
        assert result is False

    def test_weak_against_weak(self):
        # Both sides weak: the function strips the W/ prefix on both
        # sides and compares the opaque tag values. The parametrised
        # matrix only covers header-weak/server-strong; this case locks
        # the symmetry of the strip — a future change that only strips
        # the header side would silently fail to 304 when the server
        # ever emits a weak ETag.
        assert (
            _ch_schemas.if_none_match_matches(_WEAK_ETAG, _WEAK_ETAG) is True
        )

    def test_strong_header_against_weak_server_tag(self):
        # The other half of the symmetry: strong header, weak server
        # tag. Together with `test_weak_against_weak` this locks the
        # bidirectional W/-strip behaviour the public-boundary docstring
        # promises (review-20260622T224005Z-5 eng-qa Medium [1]).
        assert _ch_schemas.if_none_match_matches(_ETAG, _WEAK_ETAG) is True

    def test_weak_inside_list_against_weak_server_tag(self):
        # Combined coverage: list parsing AND bidirectional W/-strip
        # both exercised by a single tail-of-list weak-vs-weak match.
        header = f"{_OTHER}, {_WEAK_ETAG}"
        assert (
            _ch_schemas.if_none_match_matches(header, _WEAK_ETAG) is True
        )


# --- Pattern-38 dedup invariant -------------------------------------------


def _module_names_defined_at_toplevel(module_path: pathlib.Path) -> set[str]:
    """Return the set of names assigned-to or `def`-ined at module
    top-level in `module_path`. Used to prove the consumer modules
    contain NO definition of the parser under any of its historical
    names — they only import it from the shared module."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(
            node.target, ast.Name
        ):
            names.add(node.target.id)
    return names


_HISTORICAL_NAMES = {
    # Pre-iter-61 the parser was duplicated under these names. Any
    # future inline re-definition under any of them would be a
    # pattern-38 regression and must fail this test loudly.
    "_if_none_match_matches",
    "if_none_match_matches",
    "_etag_matches",
    "_parse_if_none_match",
}


def test_no_shadow_definitions_in_production_handler():
    """The production handler MUST NOT define its own parser — only
    import the canonical one from `customer_helper_schemas`."""
    handler_path = pathlib.Path(_ch_handler.__file__)
    defined = _module_names_defined_at_toplevel(handler_path)
    shadows = defined & _HISTORICAL_NAMES
    assert not shadows, (
        f"Pattern-38 regression: customer_helper.py defines {shadows} "
        "at module top-level. The RFC 7232 parser must live exclusively "
        "in customer_helper_schemas.py."
    )


def test_no_shadow_definitions_in_stub():
    """The reference stub MUST NOT define its own parser either —
    same Pattern-38 invariant applies."""
    stub_path = pathlib.Path(_stub.__file__)
    defined = _module_names_defined_at_toplevel(stub_path)
    shadows = defined & _HISTORICAL_NAMES
    assert not shadows, (
        f"Pattern-38 regression: redeem_api.py stub defines {shadows} "
        "at module top-level. The RFC 7232 parser must live exclusively "
        "in customer_helper_schemas.py."
    )


# --- symbol-identity contract across the seam -----------------------------


def test_consumers_bind_to_canonical_implementation():
    """Each consumer's `if_none_match_matches` MUST be the exact
    function object exported by the `customer_helper_schemas` module
    that consumer imports — not a re-defined private shadow, not a
    wrapper, not a hand-copy.

    Subtlety: the production app loads handlers under the package
    identity `klara.handlers.X` (see test_customer_helper_download.py's
    comment on mistake-33), while the stub imports the absolute path
    `infra.klara.handlers.customer_helper_schemas`. Those are two
    `sys.modules` entries pointing at the same source file. The seam
    contract is therefore per-consumer: each consumer's bound function
    IS the function object exported by ITS schemas module — a future
    inlined shadow in either consumer would fail this `is` check
    against its own import.
    """
    # Production handler: relative `from .customer_helper_schemas`
    # resolves to whatever module identity the handler was loaded under,
    # which is `klara.handlers.customer_helper_schemas` here.
    production_canonical = _ch_schemas.if_none_match_matches
    assert _ch_handler.if_none_match_matches is production_canonical, (
        "Production handler bound a non-canonical if_none_match_matches; "
        "a fix to the shared parser will not reach /download."
    )

    # Stub: absolute `from infra.klara.handlers.customer_helper_schemas`
    # resolves to a sibling module entry. The stub must bind to THAT
    # entry's function, not a private redefinition.
    stub_schemas = importlib.import_module(
        "infra.klara.handlers.customer_helper_schemas"
    )
    stub_canonical = stub_schemas.if_none_match_matches
    assert _stub.if_none_match_matches is stub_canonical, (
        "Reference stub bound a non-canonical if_none_match_matches; "
        "stub contract will drift from production."
    )


# --- __all__ export contract ----------------------------------------------


def test_all_exposes_full_seam_surface():
    """`__all__` MUST enumerate every name shared across the
    handler↔stub seam. A new shared identifier added without updating
    `__all__` is implementation detail by definition — and the next
    consumer that imports it has no contract guarantee."""
    expected = {
        "DOWNLOAD_CACHE_CONTROL",
        "PLATFORM_FILENAMES",
        "PLATFORM_MEDIA_TYPES",
        "Platform",
        "Session",
        "if_none_match_matches",
    }
    assert set(_ch_schemas.__all__) == expected


def test_all_entries_resolve():
    """Every name listed in `__all__` MUST actually exist on the
    module — guards against typos at edit time."""
    missing = [
        name for name in _ch_schemas.__all__ if not hasattr(_ch_schemas, name)
    ]
    assert not missing, f"__all__ lists undefined names: {missing}"
