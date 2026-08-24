"""
Unit tests for the Twitter/X Playwright compose+submit path in
infra/klara.handlers/social_publisher.py.

Context (iteration-8): the prior implementation declared a tweet "posted"
the instant it clicked whatever submit-button selector was merely
`is_visible()` -- but X's Post button stays `aria-disabled="true"` until its
input handler registers the typed text, so a click that lands during that
window is a silent no-op, not a post. There was zero direct test coverage
of this path (Pattern 47: a function nothing tests directly gives false
confidence), so these tests exercise the real compose/submit/confirm logic
against a fake Playwright page -- no real browser or network involved.

Run with:
    pytest infra/klara.handlers/tests/test_social_publisher_twitter.py -v
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INFRA_DIR = PROJECT_ROOT / "infra"
sys.path.insert(0, str(INFRA_DIR))

import klara.handlers.social_publisher as sp  # noqa: E402


# ---------------------------------------------------------------------------
# Fake Playwright page/locator -- implements only the subset of the API
# social_publisher.py's Twitter path actually calls.
# ---------------------------------------------------------------------------

class _FakeLocator:
    def __init__(self, state: dict):
        self._state = state

    @property
    def first(self):
        return self

    async def is_visible(self, timeout=0):
        visible = self._state.get("visible", False)
        return visible() if callable(visible) else visible

    async def click(self):
        self._state["clicks"] = self._state.get("clicks", 0) + 1
        on_click = self._state.get("on_click")
        if on_click:
            on_click()

    async def type(self, text, delay=0):
        self._state["typed"] = text

    async def get_attribute(self, name):
        return self._state.get("attrs", {}).get(name)

    async def inner_text(self):
        text = self._state.get("text", "")
        return text() if callable(text) else text


class _FakePage:
    def __init__(self, selector_states: dict[str, dict]):
        self._selector_states = selector_states
        self.url = "https://x.com/home"
        self.goto_calls: list[str] = []
        self.screenshots: list[str] = []

    async def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls.append(url)

    def locator(self, selector):
        # Unmatched selectors behave as never-visible, matching real
        # Playwright's locator-for-anything-that-resolves-to-zero-nodes.
        return _FakeLocator(self._selector_states.setdefault(selector, {"visible": False}))

    async def screenshot(self, path):
        self.screenshots.append(path)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """None of _pw_tw_post's sleeps are used as correctness-critical
    deadlines (that's _pw_wait_enabled_and_click's job, tested separately
    with real short waits) -- they're UI-settle pacing. Make them instant."""
    async def _instant(_seconds):
        return None
    monkeypatch.setattr(asyncio, "sleep", _instant)


# ---------------------------------------------------------------------------
# _pw_wait_enabled_and_click -- direct tests (Pattern 47)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wait_enabled_and_click_succeeds_when_already_enabled():
    page = _FakePage({
        "button.a": {"visible": True, "attrs": {"aria-disabled": "false"}},
    })
    clicked = await sp._pw_wait_enabled_and_click(page, ["button.a"], timeout_ms=500)
    assert clicked is True
    assert page._selector_states["button.a"]["clicks"] == 1


@pytest.mark.asyncio
async def test_wait_enabled_and_click_never_clicks_while_aria_disabled_true():
    """The regression this whole fix exists for: is_visible()=True alone
    must NOT be treated as clickable while aria-disabled="true"."""
    page = _FakePage({
        "button.a": {"visible": True, "attrs": {"aria-disabled": "true"}},
    })
    clicked = await sp._pw_wait_enabled_and_click(page, ["button.a"], timeout_ms=300)
    assert clicked is False
    assert page._selector_states["button.a"].get("clicks", 0) == 0


@pytest.mark.asyncio
async def test_wait_enabled_and_click_waits_for_button_to_become_enabled():
    """Simulates X flipping aria-disabled to false a couple of polls in --
    the helper must keep polling rather than give up on the first check."""
    calls = {"n": 0}
    state = {"visible": True, "attrs": {"aria-disabled": "true"}}

    class _CountingLocator(_FakeLocator):
        async def get_attribute(self, name):
            calls["n"] += 1
            if calls["n"] >= 2:
                self._state["attrs"] = {"aria-disabled": "false"}
            return await super().get_attribute(name)

    class _CountingPage(_FakePage):
        def locator(self, selector):
            return _CountingLocator(self._selector_states[selector])

    page = _CountingPage({"button.a": state})
    clicked = await sp._pw_wait_enabled_and_click(page, ["button.a"], timeout_ms=3_000)
    assert clicked is True
    assert state["clicks"] == 1
    assert calls["n"] >= 2


@pytest.mark.asyncio
async def test_wait_enabled_and_click_falls_back_to_second_selector():
    page = _FakePage({
        "button.primary": {"visible": False},
        "button.fallback": {"visible": True, "attrs": {"aria-disabled": "false"}},
    })
    clicked = await sp._pw_wait_enabled_and_click(
        page, ["button.primary", "button.fallback"], timeout_ms=500
    )
    assert clicked is True
    assert page._selector_states["button.fallback"]["clicks"] == 1
    assert "clicks" not in page._selector_states["button.primary"]


# ---------------------------------------------------------------------------
# _pw_tw_post -- end-to-end against the fake page
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pw_tw_post_success_primary_selectors():
    page = _FakePage({
        'div[data-testid="tweetTextarea_0"]': {"visible": True, "text": ""},
        'button[data-testid="tweetButtonInline"]': {"visible": True, "attrs": {"aria-disabled": "false"}},
    })
    result = await sp._pw_tw_post(page, "hello world", confirm_attempts=2, confirm_interval=0)
    assert result == ""
    assert page._selector_states['div[data-testid="tweetTextarea_0"]']["typed"] == "hello world"
    assert page._selector_states['button[data-testid="tweetButtonInline"]']["clicks"] == 1
    assert page.screenshots == []


@pytest.mark.asyncio
async def test_pw_tw_post_falls_back_to_secondary_composer_selector():
    """If X renames the primary testid, the broader aria-label fallback
    must still find the composer -- this is the actual fragility class
    'compose/submit button not found' names."""
    page = _FakePage({
        'div[data-testid="tweetTextarea_0"]': {"visible": False},
        'div[data-testid^="tweetTextarea_"][contenteditable="true"]': {"visible": False},
        'div[role="textbox"][aria-label*="Post text"]': {"visible": True, "text": ""},
        'button[data-testid="tweetButtonInline"]': {"visible": True, "attrs": {"aria-disabled": "false"}},
    })
    result = await sp._pw_tw_post(page, "hello world", confirm_attempts=2, confirm_interval=0)
    assert result == ""
    assert page._selector_states['div[role="textbox"][aria-label*="Post text"]']["typed"] == "hello world"


@pytest.mark.asyncio
async def test_pw_tw_post_composer_not_found_raises_and_captures_debug(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCIAL_SESSIONS_DIR", str(tmp_path))
    page = _FakePage({})  # nothing visible anywhere
    with pytest.raises(RuntimeError, match="Could not find tweet composer"):
        await sp._pw_tw_post(page, "hello world")
    assert len(page.screenshots) == 1
    assert "composer_not_found" in page.screenshots[0]


@pytest.mark.asyncio
async def test_pw_tw_post_submit_button_never_enabled_raises_and_captures_debug(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCIAL_SESSIONS_DIR", str(tmp_path))
    page = _FakePage({
        'div[data-testid="tweetTextarea_0"]': {"visible": True, "text": "hello world"},
        'button[data-testid="tweetButtonInline"]': {"visible": True, "attrs": {"aria-disabled": "true"}},
    })
    with pytest.raises(RuntimeError, match="Could not find tweet submit button"):
        await sp._pw_tw_post(page, "hello world", submit_timeout_ms=100)
    assert len(page.screenshots) == 1
    assert "submit_button_not_clickable" in page.screenshots[0]


@pytest.mark.asyncio
async def test_pw_tw_post_click_that_does_not_clear_composer_raises(tmp_path, monkeypatch):
    """A click on a button that turns out to be a no-op (overlay intercepted
    it, rate-limited toast appeared, etc.) must NOT be reported as success
    just because the click call itself didn't raise."""
    monkeypatch.setenv("SOCIAL_SESSIONS_DIR", str(tmp_path))
    page = _FakePage({
        'div[data-testid="tweetTextarea_0"]': {"visible": True, "text": "hello world"},
        'button[data-testid="tweetButtonInline"]': {"visible": True, "attrs": {"aria-disabled": "false"}},
    })
    with pytest.raises(RuntimeError, match="post not confirmed"):
        await sp._pw_tw_post(page, "hello world", confirm_attempts=2, confirm_interval=0)
    assert page._selector_states['button[data-testid="tweetButtonInline"]']["clicks"] == 1
    assert len(page.screenshots) == 1
    assert "post_not_confirmed" in page.screenshots[0]
