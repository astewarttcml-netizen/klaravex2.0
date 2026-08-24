"""
Tests for infra/klara.handlers/lib/higgsfield_client.py

Covers the three findings from iter-20 code review:
  finding-1: _BASE_URL must be read at call time (verified via _base_url())
  finding-2: _StructLogShim.bind override semantic (kwargs win over prior ctx)
  finding-3: _StructLogShim.bind chained-bind last-write-wins
"""
import importlib
import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Module import helper
# ---------------------------------------------------------------------------

def _load_module():
    """Re-import the module fresh so env changes are visible."""
    mod_name = "klara.handlers.lib.higgsfield_client"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    import klara.handlers.lib.higgsfield_client as m
    return m


# ---------------------------------------------------------------------------
# Finding-1: _base_url() reads from env at call time
# ---------------------------------------------------------------------------

class TestBaseUrlLazyRead:
    def test_default_url(self, monkeypatch):
        monkeypatch.delenv("HIGGSFIELD_BASE_URL", raising=False)
        m = _load_module()
        assert m._base_url() == "https://api.higgsfield.ai"

    def test_env_override_respected_without_reimport(self, monkeypatch):
        """monkeypatch.setenv after import must take effect — lazy read guarantees this."""
        m = _load_module()
        monkeypatch.setenv("HIGGSFIELD_BASE_URL", "https://mock.higgsfield.test")
        assert m._base_url() == "https://mock.higgsfield.test"


# ---------------------------------------------------------------------------
# Finding-2 & 3: _StructLogShim.bind semantics
# ---------------------------------------------------------------------------

class TestStructLogShimBind:
    def _shim(self):
        import logging
        m = _load_module()
        return m._StructLogShim(logging.getLogger("test"))

    def test_bind_override_semantic_kwargs_win_over_prior_ctx(self):
        """Finding-2: kwargs passed to bind() must win over already-bound ctx."""
        shim = self._shim()
        bound1 = shim.bind(x=1, y="original")
        bound2 = bound1.bind(x=999)  # override x; y untouched
        assert bound2._ctx["x"] == 999, "kwarg must override prior ctx value"
        assert bound2._ctx["y"] == "original", "unrelated key must be preserved"

    def test_bind_new_key_added(self):
        """New key introduced in second bind is present in resulting ctx."""
        shim = self._shim()
        result = shim.bind(a=1).bind(b=2)
        assert result._ctx == {"a": 1, "b": 2}

    def test_chained_bind_last_write_wins(self):
        """Finding-3: a.bind(x=1).bind(x=2) → x==2."""
        shim = self._shim()
        result = shim.bind(x=1).bind(x=2)
        assert result._ctx["x"] == 2, "last bind call must win for repeated keys"

    def test_bind_returns_new_instance(self):
        """bind() must not mutate self — returns a fresh _StructLogShim."""
        m = _load_module()
        import logging
        shim = m._StructLogShim(logging.getLogger("test"), {"k": "original"})
        _ = shim.bind(k="modified")
        assert shim._ctx["k"] == "original", "original shim must not be mutated"

    def test_bind_empty_kwargs_is_identity(self):
        shim = self._shim().bind(z=42)
        result = shim.bind()
        assert result._ctx == {"z": 42}
