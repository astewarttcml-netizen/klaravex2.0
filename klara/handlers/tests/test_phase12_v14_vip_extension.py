"""Phase 12 V14 — VIP extension code validator tests.

Coverage:
  - _is_valid_code: 6-8 digits pass; <6, >8, alpha, empty fail
  - _attempt_count: placeholder call_sids return 0 without DB hit
  - vip_extension_check endpoint:
      • _test flag → {authorized: False, test: True}
      • VIP_EXTENSION_CODE unset → fail-closed {authorized: False}, get_pool never called
      • correct code → {authorized: True}
      • wrong code → {authorized: False} — no oracle, indistinguishable from invalid
      • invalid format → {authorized: False}
      • 2-strike lockout → {authorized: False} after prior >= MAX_ATTEMPTS_PER_CALL
      • attempt_count > MAX (3, 5, 99) → still locked (guards strict-== bug)
      • attempt_count == MAX-1 + correct code → {authorized: True} (not locked)
      • missing code field (default '') → {authorized: False}
      • empty string code='' → {authorized: False}
      • whitespace-padded code ' 654321 ' → stripped → matches
      • actual code and transfer number NEVER appear in any response body
      • all placeholder call_sids ({call.id}/{call_sid}/{CALL_SID}/None/null) skip fetchval+execute
      • execute actually called on miss and locked paths (audit row written)
      • record uses <match>/<miss>/<locked>/<invalid_format> — real code never persisted
      • DB execute failure during _record → swallowed (non-fatal), endpoint returns normally
      • fetchval failure in _attempt_count → propagates as hard fail (not fail-open)

Note on concurrency: _attempt_count is count-then-compare (read, then act at caller).
Two parallel requests can both read prior=1 and both proceed past the MAX check, giving
one extra attempt beyond MAX. Atomic SQL-level enforcement (FOR UPDATE / counter CTE)
is not yet implemented; this is a documented gap accepted at current call volume.
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infra.klara.handlers.vapi.vip_extension_check import (
    MAX_ATTEMPTS_PER_CALL,
    VipExtensionCheckRequest,
    _attempt_count,
    _is_valid_code,
    vip_extension_check,
)


# ── _is_valid_code ────────────────────────────────────────────────────────────

class TestIsValidCode(unittest.TestCase):
    def test_6_digits_valid(self):
        assert _is_valid_code("123456") is True

    def test_7_digits_valid(self):
        assert _is_valid_code("1234567") is True

    def test_8_digits_valid(self):
        assert _is_valid_code("12345678") is True

    def test_5_digits_invalid(self):
        assert _is_valid_code("12345") is False

    def test_9_digits_invalid(self):
        assert _is_valid_code("123456789") is False

    def test_empty_invalid(self):
        assert _is_valid_code("") is False

    def test_alpha_invalid(self):
        assert _is_valid_code("abcdef") is False

    def test_mixed_invalid(self):
        assert _is_valid_code("123abc") is False

    def test_spaces_invalid(self):
        assert _is_valid_code("123 456") is False


# ── _attempt_count ────────────────────────────────────────────────────────────

class TestAttemptCount(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_empty_call_sid_returns_zero_no_db_hit(self):
        conn = AsyncMock()
        result = self._run(_attempt_count(conn, ""))
        assert result == 0
        conn.fetchval.assert_not_called()

    def test_placeholder_call_sid_returns_zero_no_db_hit(self):
        conn = AsyncMock()
        for sid in ("{{call.id}}", "{{call_sid}}", "{{CALL_SID}}", "None", "null"):
            result = self._run(_attempt_count(conn, sid))
            assert result == 0
        conn.fetchval.assert_not_called()

    def test_real_call_sid_queries_db(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=1)
        result = self._run(_attempt_count(conn, "real-call-sid-001"))
        assert result == 1
        conn.fetchval.assert_awaited_once()


# ── helpers ───────────────────────────────────────────────────────────────────

def _mock_pool(attempt_count: int = 0):
    """Return an AsyncMock for get_pool() yielding a connection with given prior count."""
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=attempt_count)
    conn.execute = AsyncMock(return_value=None)

    acm = MagicMock()
    acm.__aenter__ = AsyncMock(return_value=conn)
    acm.__aexit__ = AsyncMock(return_value=None)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acm)

    return AsyncMock(return_value=pool), conn


# ── vip_extension_check endpoint ─────────────────────────────────────────────

class TestVipExtensionCheck(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    # — test flag ——————————————————————————————————————————————————————————————

    def test_flag_returns_false_without_db(self):
        req = VipExtensionCheckRequest(**{"_test": True, "code": "123456", "call_sid": "sid"})
        result = self._run(vip_extension_check(req))
        assert result == {"authorized": False, "test": True}

    # — no env set ————————————————————————————————————————————————————————————

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "")
    def test_no_env_code_fail_closed(self):
        req = VipExtensionCheckRequest(code="123456", call_sid="sid-001")
        result = self._run(vip_extension_check(req))
        assert result == {"authorized": False}

    # — correct code ——————————————————————————————————————————————————————————

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_correct_code_returns_authorized_true(self):
        get_pool_mock, conn = _mock_pool(attempt_count=0)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            req = VipExtensionCheckRequest(code="654321", call_sid="sid-match-001")
            result = self._run(vip_extension_check(req))
        assert result == {"authorized": True}

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_correct_code_records_match_not_actual_code(self):
        """Recorded submitted_code must be '<match>', never the real code."""
        get_pool_mock, conn = _mock_pool(attempt_count=0)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            req = VipExtensionCheckRequest(code="654321", call_sid="sid-match-002")
            self._run(vip_extension_check(req))
        # The execute call inserts the audit row — check submitted_code arg
        call_args = conn.execute.call_args
        assert call_args is not None
        args = call_args.args
        # args[0] is SQL, args[1]=call_sid, args[2]=submitted_code, ...
        submitted_code_arg = args[2] if len(args) > 2 else str(call_args)
        assert submitted_code_arg == "<match>"
        assert "654321" not in str(call_args)

    # — wrong code ————————————————————————————————————————————————————————————

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_wrong_code_returns_authorized_false(self):
        get_pool_mock, conn = _mock_pool(attempt_count=0)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            req = VipExtensionCheckRequest(code="999999", call_sid="sid-miss-001")
            result = self._run(vip_extension_check(req))
        assert result == {"authorized": False}

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_wrong_code_response_same_as_invalid_format(self):
        """Miss and invalid-format both return {authorized: False} — no oracle."""
        get_pool_mock_miss, _ = _mock_pool(attempt_count=0)
        get_pool_mock_invalid, _ = _mock_pool(attempt_count=0)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock_miss):
            miss_result = self._run(
                vip_extension_check(VipExtensionCheckRequest(code="000000", call_sid="sid-a"))
            )
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock_invalid):
            invalid_result = self._run(
                vip_extension_check(VipExtensionCheckRequest(code="abc", call_sid="sid-b"))
            )
        assert miss_result == invalid_result == {"authorized": False}

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_wrong_code_records_miss_not_actual_code(self):
        """Recorded submitted_code must be '<miss>', never the actual attempt."""
        get_pool_mock, conn = _mock_pool(attempt_count=0)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            req = VipExtensionCheckRequest(code="999999", call_sid="sid-miss-002")
            self._run(vip_extension_check(req))
        call_args = conn.execute.call_args
        args = call_args.args
        submitted_code_arg = args[2] if len(args) > 2 else str(call_args)
        assert submitted_code_arg == "<miss>"
        assert "999999" not in str(call_args)

    # — invalid format ————————————————————————————————————————————————————————

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_invalid_format_returns_false(self):
        get_pool_mock, _ = _mock_pool(attempt_count=0)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            result = self._run(
                vip_extension_check(VipExtensionCheckRequest(code="abc", call_sid="sid-fmt-1"))
            )
        assert result == {"authorized": False}

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_too_short_code_returns_false(self):
        get_pool_mock, _ = _mock_pool(attempt_count=0)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            result = self._run(
                vip_extension_check(VipExtensionCheckRequest(code="12345", call_sid="sid-fmt-2"))
            )
        assert result == {"authorized": False}

    # — 2-strike lockout ——————————————————————————————————————————————————————

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_locked_after_max_attempts(self):
        """Prior attempts = MAX_ATTEMPTS_PER_CALL → locked immediately."""
        get_pool_mock, conn = _mock_pool(attempt_count=MAX_ATTEMPTS_PER_CALL)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            req = VipExtensionCheckRequest(code="654321", call_sid="sid-locked-001")
            result = self._run(vip_extension_check(req))
        assert result == {"authorized": False}

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_locked_records_locked_sentinel_not_code(self):
        """Lock audit row uses '<locked>', not the real code."""
        get_pool_mock, conn = _mock_pool(attempt_count=MAX_ATTEMPTS_PER_CALL)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            req = VipExtensionCheckRequest(code="654321", call_sid="sid-locked-002")
            self._run(vip_extension_check(req))
        call_args = conn.execute.call_args
        args = call_args.args
        submitted_code_arg = args[2] if len(args) > 2 else str(call_args)
        assert submitted_code_arg == "<locked>"
        assert "654321" not in str(call_args)

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_first_miss_not_locked(self):
        """One prior attempt (< MAX) — still processes normally."""
        get_pool_mock, _ = _mock_pool(attempt_count=1)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            req = VipExtensionCheckRequest(code="000000", call_sid="sid-one-prior")
            result = self._run(vip_extension_check(req))
        # Should process the miss (not locked), still authorized=False
        assert result == {"authorized": False}

    # — code/number never in response body ————————────————────————————————————

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "777888")
    def test_vip_code_never_in_response_on_match(self):
        get_pool_mock, _ = _mock_pool(attempt_count=0)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            req = VipExtensionCheckRequest(code="777888", call_sid="sid-sec-1")
            result = self._run(vip_extension_check(req))
        assert "777888" not in str(result)

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "777888")
    def test_vip_code_never_in_response_on_miss(self):
        get_pool_mock, _ = _mock_pool(attempt_count=0)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            req = VipExtensionCheckRequest(code="111111", call_sid="sid-sec-2")
            result = self._run(vip_extension_check(req))
        assert "777888" not in str(result)
        assert "111111" not in str(result)

    # — placeholder call_sid ——————————————————————————————————————————————————

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_placeholder_call_sid_handled_silently(self):
        """Placeholder sids are normalised to '' — no DB crash, result still valid."""
        get_pool_mock, conn = _mock_pool(attempt_count=0)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            req = VipExtensionCheckRequest(code="654321", call_sid="{{call.id}}")
            result = self._run(vip_extension_check(req))
        # Auth should succeed (code correct), and no attempt logging for placeholder
        assert result == {"authorized": True}
        # fetchval should NOT have been called (placeholder → skip DB count)
        conn.fetchval.assert_not_called()

    # — all placeholder call_sid variants (not just one) ─────────────────────────

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_all_placeholder_sids_skip_db_and_authorize(self):
        """Every placeholder variant in _PLACEHOLDER_SIDS skips fetchval+execute."""
        for placeholder in ("{{call.id}}", "{{call_sid}}", "{{CALL_SID}}", "None", "null"):
            get_pool_mock, conn = _mock_pool(attempt_count=0)
            with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
                req = VipExtensionCheckRequest(code="654321", call_sid=placeholder)
                result = self._run(vip_extension_check(req))
            assert result == {"authorized": True}, f"placeholder={placeholder!r}"
            conn.fetchval.assert_not_called()
            conn.execute.assert_not_called()

    # — DB execute failure during _record (non-fatal: wrapped in try/except) ──────

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_audit_insert_failure_non_fatal_on_match(self):
        """execute raises during _record on match path → swallowed, still authorized True."""
        get_pool_mock, conn = _mock_pool(attempt_count=0)
        conn.execute = AsyncMock(side_effect=Exception("insert error"))
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            result = self._run(
                vip_extension_check(VipExtensionCheckRequest(code="654321", call_sid="sid-ex-fail-match"))
            )
        assert result == {"authorized": True}

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_audit_insert_failure_non_fatal_on_miss(self):
        """execute raises during _record on miss path → swallowed, still authorized False."""
        get_pool_mock, conn = _mock_pool(attempt_count=0)
        conn.execute = AsyncMock(side_effect=Exception("insert error"))
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            result = self._run(
                vip_extension_check(VipExtensionCheckRequest(code="999999", call_sid="sid-ex-fail-miss"))
            )
        assert result == {"authorized": False}

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_audit_insert_failure_non_fatal_on_locked(self):
        """execute raises on locked path → swallowed, still authorized False (no fail-open)."""
        get_pool_mock, conn = _mock_pool(attempt_count=MAX_ATTEMPTS_PER_CALL)
        conn.execute = AsyncMock(side_effect=Exception("insert error"))
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            result = self._run(
                vip_extension_check(VipExtensionCheckRequest(code="654321", call_sid="sid-ex-fail-locked"))
            )
        assert result == {"authorized": False}

    # — DB unavailable during _attempt_count (fetchval raises → hard fail) ────────

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_db_unavailable_fetchval_raises_propagates(self):
        """fetchval raises in _attempt_count → exception propagates, not silently fail-open."""
        conn = AsyncMock()
        conn.fetchval = AsyncMock(side_effect=Exception("connection lost"))
        conn.execute = AsyncMock(return_value=None)
        acm = MagicMock()
        acm.__aenter__ = AsyncMock(return_value=conn)
        acm.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=acm)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", AsyncMock(return_value=pool)):
            with pytest.raises(Exception, match="connection lost"):
                self._run(vip_extension_check(VipExtensionCheckRequest(code="654321", call_sid="real-sid-db-down")))

    # — lockout boundary: attempt_count strictly above MAX (not just ==) ──────────

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_locked_when_strictly_above_max_attempts(self):
        """attempt_count > MAX also locks — guards regression to strict == comparison."""
        for count in (MAX_ATTEMPTS_PER_CALL + 1, MAX_ATTEMPTS_PER_CALL + 3, 99):
            get_pool_mock, _ = _mock_pool(attempt_count=count)
            with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
                result = self._run(
                    vip_extension_check(VipExtensionCheckRequest(code="654321", call_sid=f"sid-above-{count}"))
                )
            assert result == {"authorized": False}, f"expected locked at attempt_count={count}"

    # — boundary: MAX-1 prior attempts still processes (correct code matches) ─────

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_max_minus_one_prior_correct_code_matches(self):
        """Prior = MAX-1 (last allowed attempt): not locked, correct code → authorized True."""
        get_pool_mock, _ = _mock_pool(attempt_count=MAX_ATTEMPTS_PER_CALL - 1)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            result = self._run(
                vip_extension_check(VipExtensionCheckRequest(code="654321", call_sid="sid-final-ok"))
            )
        assert result == {"authorized": True}

    # — missing / empty code field ────────────────────────────────────────────────

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_missing_code_field_defaults_to_empty_returns_false(self):
        """code omitted → Pydantic default '' → _is_valid_code('') False → {authorized: False}."""
        get_pool_mock, _ = _mock_pool(attempt_count=0)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            result = self._run(vip_extension_check(VipExtensionCheckRequest(call_sid="sid-no-code")))
        assert result == {"authorized": False}

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_empty_string_code_returns_false(self):
        """Explicit code='' → strip → '' → invalid format → {authorized: False}."""
        get_pool_mock, _ = _mock_pool(attempt_count=0)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            result = self._run(vip_extension_check(VipExtensionCheckRequest(code="", call_sid="sid-empty")))
        assert result == {"authorized": False}

    # — fail-closed path must not touch DB ───────────────────────────────────────

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "")
    def test_fail_closed_no_env_does_not_call_get_pool(self):
        """VIP_EXTENSION_CODE unset → returns False before get_pool is ever invoked."""
        get_pool_mock, _ = _mock_pool()
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            result = self._run(vip_extension_check(VipExtensionCheckRequest(code="123456", call_sid="sid-fc")))
        assert result == {"authorized": False}
        get_pool_mock.assert_not_called()

    # — whitespace-padded code (strip normalisation) ──────────────────────────────

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_whitespace_padded_code_matches_after_strip(self):
        """' 654321 ' stripped → '654321' → hmac match → {authorized: True}."""
        get_pool_mock, _ = _mock_pool(attempt_count=0)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            result = self._run(
                vip_extension_check(VipExtensionCheckRequest(code=" 654321 ", call_sid="sid-padded"))
            )
        assert result == {"authorized": True}

    # — audit row actually written on miss and locked paths ───────────────────────

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_execute_called_once_on_miss_path(self):
        """Audit row INSERT is actually executed on the miss path (not silently skipped)."""
        get_pool_mock, conn = _mock_pool(attempt_count=0)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            self._run(vip_extension_check(VipExtensionCheckRequest(code="000000", call_sid="sid-audit-miss")))
        conn.execute.assert_awaited_once()

    @patch("infra.klara.handlers.vapi.vip_extension_check.VIP_EXTENSION_CODE", "654321")
    def test_execute_called_once_on_locked_path(self):
        """Audit row INSERT is actually executed on the locked path (not silently skipped)."""
        get_pool_mock, conn = _mock_pool(attempt_count=MAX_ATTEMPTS_PER_CALL)
        with patch("infra.klara.handlers.vapi.vip_extension_check.get_pool", get_pool_mock):
            self._run(vip_extension_check(VipExtensionCheckRequest(code="654321", call_sid="sid-audit-locked")))
        conn.execute.assert_awaited_once()
