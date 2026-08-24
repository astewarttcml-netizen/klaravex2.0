"""Tests for the Anthropic computer-use response parser (G34.2 enabler).

The parser converts an Anthropic `messages.create` response that exercised
the `computer` tool into a PredictedAction. Pure data transformation — no
network. Lets the session loop's contract be exercised end-to-end against
canned responses, and pins the supported action surface so a future SDK
shape change is caught at test time.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make `rustdesk_controller` importable when tests run from the repo root.
_INFRA = Path(__file__).resolve().parents[2]
if str(_INFRA) not in sys.path:
    sys.path.insert(0, str(_INFRA))

# Force-stub the api key so the predictor path does not silently disable.
os.environ.setdefault("ANTHROPIC_API_KEY", "stub-for-tests")

from rustdesk_controller.protocol import EventKind  # noqa: E402
from rustdesk_controller.vision import (  # noqa: E402
    ComputerUseParseError,
    _parse_computer_use_action,
    _prompt_for_goal,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


FRAME_W = 1920
FRAME_H = 1080


def _resp(
    *,
    action: str | None = "left_click",
    coordinate: list[int] | None = None,
    text: str | None = None,
    scroll_direction: str | None = None,
    rationale: str | None = "Clicking the WiFi icon",
    include_tool_use: bool = True,
    tool_name: str = "computer",
) -> dict:
    """Build an Anthropic messages.create response shape."""
    content: list[dict] = []
    if rationale:
        content.append({"type": "text", "text": rationale})
    if include_tool_use:
        tool_input: dict = {}
        if action is not None:
            tool_input["action"] = action
        if coordinate is not None:
            tool_input["coordinate"] = coordinate
        if text is not None:
            tool_input["text"] = text
        if scroll_direction is not None:
            tool_input["scroll_direction"] = scroll_direction
        content.append(
            {"type": "tool_use", "name": tool_name, "input": tool_input}
        )
    return {"role": "assistant", "content": content}


# ── Happy-path action parsing ─────────────────────────────────────────────


def test_parses_left_click_with_normalised_coordinate():
    resp = _resp(action="left_click", coordinate=[960, 540])
    action = _parse_computer_use_action(
        resp, frame_width=FRAME_W, frame_height=FRAME_H
    )
    assert action.event.kind == EventKind.MOUSE_CLICK
    assert action.event.button == "left"
    assert action.event.x == pytest.approx(0.5, abs=1e-6)
    assert action.event.y == pytest.approx(0.5, abs=1e-6)
    assert action.confidence == 1.0
    assert action.target_description == "Clicking the WiFi icon"


def test_parses_right_click_routes_button():
    resp = _resp(action="right_click", coordinate=[1920, 1080])
    action = _parse_computer_use_action(
        resp, frame_width=FRAME_W, frame_height=FRAME_H
    )
    assert action.event.kind == EventKind.MOUSE_CLICK
    assert action.event.button == "right"
    assert action.event.x == pytest.approx(1.0)
    assert action.event.y == pytest.approx(1.0)


def test_parses_middle_click_routes_button():
    resp = _resp(action="middle_click", coordinate=[0, 0])
    action = _parse_computer_use_action(
        resp, frame_width=FRAME_W, frame_height=FRAME_H
    )
    assert action.event.kind == EventKind.MOUSE_CLICK
    assert action.event.button == "middle"
    assert action.event.x == pytest.approx(0.0)
    assert action.event.y == pytest.approx(0.0)


def test_parses_mouse_move_without_button():
    resp = _resp(action="mouse_move", coordinate=[480, 270])
    action = _parse_computer_use_action(
        resp, frame_width=FRAME_W, frame_height=FRAME_H
    )
    assert action.event.kind == EventKind.MOUSE_MOVE
    assert action.event.button is None
    assert action.event.x == pytest.approx(0.25)
    assert action.event.y == pytest.approx(0.25)


def test_parses_key_press():
    resp = _resp(action="key", coordinate=None, text="Return")
    action = _parse_computer_use_action(
        resp, frame_width=FRAME_W, frame_height=FRAME_H
    )
    assert action.event.kind == EventKind.KEY_PRESS
    assert action.event.key == "Return"
    assert action.event.x is None
    assert action.event.y is None


def test_parses_paste_text():
    resp = _resp(action="type", coordinate=None, text="hello world")
    action = _parse_computer_use_action(
        resp, frame_width=FRAME_W, frame_height=FRAME_H
    )
    assert action.event.kind == EventKind.PASTE_TEXT
    assert action.event.text == "hello world"


def test_parses_scroll_with_direction():
    resp = _resp(
        action="scroll",
        coordinate=[100, 200],
        scroll_direction="down",
    )
    action = _parse_computer_use_action(
        resp, frame_width=FRAME_W, frame_height=FRAME_H
    )
    assert action.event.kind == EventKind.MOUSE_SCROLL
    assert action.event.button == "down"
    assert action.event.x == pytest.approx(100 / FRAME_W)
    assert action.event.y == pytest.approx(200 / FRAME_H)


# ── Rationale + confidence ────────────────────────────────────────────────


def test_collects_multiple_text_blocks_as_rationale():
    resp = {
        "content": [
            {"type": "text", "text": "First, I see the WiFi icon."},
            {"type": "text", "text": "I will click it."},
            {
                "type": "tool_use",
                "name": "computer",
                "input": {"action": "left_click", "coordinate": [10, 20]},
            },
        ]
    }
    action = _parse_computer_use_action(
        resp, frame_width=FRAME_W, frame_height=FRAME_H
    )
    assert action.target_description == (
        "First, I see the WiFi icon. I will click it."
    )
    assert action.rationale == (
        "First, I see the WiFi icon. I will click it."
    )


def test_no_text_blocks_falls_back_to_action_name():
    resp = _resp(action="left_click", coordinate=[10, 20], rationale=None)
    action = _parse_computer_use_action(
        resp, frame_width=FRAME_W, frame_height=FRAME_H
    )
    assert action.target_description == "(left_click)"
    assert action.rationale == "Model requested left_click."


def test_confidence_override_propagates():
    resp = _resp(action="left_click", coordinate=[10, 20])
    action = _parse_computer_use_action(
        resp,
        frame_width=FRAME_W,
        frame_height=FRAME_H,
        confidence_override=0.42,
    )
    assert action.confidence == 0.42
    assert action.low_confidence is True


def test_text_blocks_after_tool_use_do_not_pollute_rationale():
    """Anthropic sometimes appends a post-tool_use text block. The rationale
    must be everything that PRECEDES the tool_use — Klara reads it before
    asking for confirmation, so trailing chatter would arrive after the
    customer has already heard the question.
    """
    resp = {
        "content": [
            {"type": "text", "text": "Pre-action."},
            {
                "type": "tool_use",
                "name": "computer",
                "input": {"action": "left_click", "coordinate": [10, 20]},
            },
            {"type": "text", "text": "Post-action chatter."},
        ]
    }
    action = _parse_computer_use_action(
        resp, frame_width=FRAME_W, frame_height=FRAME_H
    )
    assert action.rationale == "Pre-action."


# ── Coordinate handling ──────────────────────────────────────────────────


def test_out_of_bounds_coordinate_is_clamped():
    """The model occasionally returns pixels slightly outside the frame
    box — sub-pixel rounding at the edge, or model confusion. The parser
    clamps instead of erroring because the wire encoder requires 0.0–1.0.
    """
    resp = _resp(action="left_click", coordinate=[3000, -50])
    action = _parse_computer_use_action(
        resp, frame_width=FRAME_W, frame_height=FRAME_H
    )
    assert action.event.x == pytest.approx(1.0)
    assert action.event.y == pytest.approx(0.0)


def test_zero_frame_size_is_rejected():
    resp = _resp(action="left_click", coordinate=[10, 20])
    with pytest.raises(ComputerUseParseError, match="frame size is 0x0"):
        _parse_computer_use_action(resp, frame_width=0, frame_height=0)


def test_missing_coordinate_for_click_is_rejected():
    resp = _resp(action="left_click", coordinate=None)
    with pytest.raises(ComputerUseParseError, match="missing or malformed"):
        _parse_computer_use_action(
            resp, frame_width=FRAME_W, frame_height=FRAME_H
        )


def test_non_numeric_coordinate_is_rejected():
    resp = _resp(action="left_click", coordinate=["a", "b"])  # type: ignore[list-item]
    with pytest.raises(ComputerUseParseError, match="not numeric"):
        _parse_computer_use_action(
            resp, frame_width=FRAME_W, frame_height=FRAME_H
        )


# ── Error paths echo the caller's original input ─────────────────────────


def test_unsupported_action_error_quotes_offending_string_verbatim():
    """Per pattern-21: error messages from normalising parsers must echo
    the caller's original input, not a normalised form.
    """
    resp = _resp(action="LEFT_DOUBLE_CLICK", coordinate=[10, 20])
    with pytest.raises(ComputerUseParseError) as exc_info:
        _parse_computer_use_action(
            resp, frame_width=FRAME_W, frame_height=FRAME_H
        )
    assert "LEFT_DOUBLE_CLICK" in str(exc_info.value)


def test_invalid_scroll_direction_is_rejected_with_visible_value():
    resp = _resp(
        action="scroll",
        coordinate=[10, 20],
        scroll_direction="diagonal",
    )
    with pytest.raises(ComputerUseParseError) as exc_info:
        _parse_computer_use_action(
            resp, frame_width=FRAME_W, frame_height=FRAME_H
        )
    assert "diagonal" in str(exc_info.value)


def test_missing_text_for_key_action_is_rejected():
    resp = _resp(action="key", coordinate=None, text=None)
    with pytest.raises(ComputerUseParseError, match="missing required `text`"):
        _parse_computer_use_action(
            resp, frame_width=FRAME_W, frame_height=FRAME_H
        )


def test_empty_type_string_is_refused_as_noop():
    resp = _resp(action="type", coordinate=None, text="")
    with pytest.raises(ComputerUseParseError, match="empty `text`"):
        _parse_computer_use_action(
            resp, frame_width=FRAME_W, frame_height=FRAME_H
        )


def test_response_without_tool_use_is_rejected():
    resp = _resp(
        action=None,
        rationale="I refuse to proceed without clearer context.",
        include_tool_use=False,
    )
    with pytest.raises(ComputerUseParseError, match="no `computer` tool_use"):
        _parse_computer_use_action(
            resp, frame_width=FRAME_W, frame_height=FRAME_H
        )


def test_tool_use_with_wrong_name_is_treated_as_missing():
    """If the model called a tool other than `computer` (which shouldn't be
    in the toolbox at all in this controller, but be defensive), we treat
    it as no computer action having been emitted.
    """
    resp = _resp(action="left_click", coordinate=[10, 20], tool_name="bash")
    with pytest.raises(ComputerUseParseError, match="no `computer` tool_use"):
        _parse_computer_use_action(
            resp, frame_width=FRAME_W, frame_height=FRAME_H
        )


def test_response_missing_content_field_is_rejected():
    with pytest.raises(ComputerUseParseError, match="no list `content` field"):
        _parse_computer_use_action(
            {"role": "assistant"}, frame_width=FRAME_W, frame_height=FRAME_H
        )


def test_tool_input_not_an_object_is_rejected():
    resp = {
        "content": [
            {"type": "tool_use", "name": "computer", "input": "not-a-dict"}
        ]
    }
    with pytest.raises(ComputerUseParseError, match="not an object"):
        _parse_computer_use_action(
            resp, frame_width=FRAME_W, frame_height=FRAME_H
        )


def test_missing_action_string_is_rejected():
    resp = {
        "content": [
            {"type": "tool_use", "name": "computer", "input": {"coordinate": [1, 2]}}
        ]
    }
    with pytest.raises(ComputerUseParseError, match="action is missing"):
        _parse_computer_use_action(
            resp, frame_width=FRAME_W, frame_height=FRAME_H
        )


# ── SDK object shape (attribute access) ──────────────────────────────────


class _SdkBlock:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class _SdkMessage:
    def __init__(self, content):
        self.content = content


def test_parses_sdk_message_object_with_attribute_access():
    """The anthropic SDK returns Message objects with attribute access, not
    dicts. The parser must accept both shapes — that's the only seam
    between `_call_anthropic` (real SDK) and the unit tests (dicts).
    """
    msg = _SdkMessage(
        content=[
            _SdkBlock(type="text", text="Clicking start menu."),
            _SdkBlock(
                type="tool_use",
                name="computer",
                input={"action": "left_click", "coordinate": [50, 1000]},
            ),
        ]
    )
    action = _parse_computer_use_action(
        msg, frame_width=FRAME_W, frame_height=FRAME_H
    )
    assert action.event.kind == EventKind.MOUSE_CLICK
    assert action.event.button == "left"
    assert action.target_description == "Clicking start menu."


def test_sdk_unknown_block_types_are_skipped_not_crashed():
    """Future block types (e.g. extended thinking, reasoning) must not crash
    the parser — they're just ignored when collecting content blocks.
    """
    msg = _SdkMessage(
        content=[
            _SdkBlock(type="thinking", thinking="..."),
            _SdkBlock(type="text", text="Click."),
            _SdkBlock(
                type="tool_use",
                name="computer",
                input={"action": "left_click", "coordinate": [10, 20]},
            ),
        ]
    )
    action = _parse_computer_use_action(
        msg, frame_width=FRAME_W, frame_height=FRAME_H
    )
    assert action.event.kind == EventKind.MOUSE_CLICK
    assert action.rationale == "Click."


# ── Prompt rendering ──────────────────────────────────────────────────────


def test_prompt_for_goal_includes_goal_verbatim():
    prompt = _prompt_for_goal("fix the customer's WiFi")
    assert "fix the customer's WiFi" in prompt
    assert "computer" in prompt  # references the tool name
    assert "read aloud" in prompt  # the confirm-gate hint


def test_prompt_handles_multiline_goal_without_crashing():
    prompt = _prompt_for_goal("line 1\nline 2")
    assert "line 1" in prompt and "line 2" in prompt
