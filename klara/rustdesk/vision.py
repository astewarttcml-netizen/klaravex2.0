"""Screen-action predictor (Claude or local vision model).

Spec §3 (docs/architecture/ai-remote-session.md):
    Frame + goal → {action_type, target_description, target_coords, rationale}

2026-08-16: the Anthropic `computer_20250124` tool is rejected by
claude-opus-4-7 on this account (400), so we prompt the vision model for
action JSON (image + JSON schema) instead. Claude is the default provider
(RUSTDESK_VISION_MODEL=claude-opus-4-7, no base_url); set
RUSTDESK_VISION_BASE_URL to a local gateway/Ollama to use a local vision
model. The model returns absolute pixel coords; we convert to the 0.0–1.0
normalized form `protocol.InputEvent` uses so the higher-level session
loop stays resolution-agnostic.

The confidence-abort policy (§3 OPEN): start at "abort after 2 consecutive
customer rejections OR self-reported confidence <0.6" and tune from logs.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from .protocol import EventKind, Frame, InputEvent

log = logging.getLogger("klaravex.rustdesk.vision")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# RUSTDESK_VISION_MODEL: model id. Default claude-sonnet-5 (benchmarked 2026-08-16:
# 0px target error on a 256px test frame, 1.9s — beats opus-4-7 and sonnet-4-6).
# Set RUSTDESK_VISION_BASE_URL to the local fcc-server gateway (e.g.
# http://host.docker.internal:8090) and RUSTDESK_VISION_MODEL to a vision NIM
# (e.g. anthropic/nvidia_nim/meta/llama-3.2-11b-vision-instruct) to use your own
# local vision model instead of Claude. base_url empty = api.anthropic.com.
VISION_MODEL = os.environ.get("RUSTDESK_VISION_MODEL", "claude-sonnet-5")
VISION_BASE_URL = os.environ.get("RUSTDESK_VISION_BASE_URL", "").strip()
LOW_CONFIDENCE_THRESHOLD = float(os.environ.get("RUSTDESK_LOW_CONF", "0.6"))


class ComputerUseParseError(ValueError):
    """Raised when an Anthropic computer-use response cannot be turned into a
    PredictedAction.

    The error message must echo the caller's original input verbatim (action
    string, coordinate, etc.) — never a normalised form. See pattern-21 /
    mistake-21 in CONTINUITY.md.
    """


# Map of Anthropic computer-use `action` strings → (EventKind, click button|None).
# Anthropic actions we do NOT yet handle: double_click, triple_click,
# left_click_drag (controller-side drag is mouse_down + mouse_move + mouse_up,
# but mouse_down / mouse_up are not in EventKind v0 — defer to a future
# iteration that extends EventKind), screenshot / cursor_position / wait
# (these have no controller-side effect — frame capture is loop-driven), and
# hold_key (no duration field in InputEvent v0).
_CLICK_ACTIONS: dict[str, tuple[EventKind, str | None]] = {
    "mouse_move": (EventKind.MOUSE_MOVE, None),
    "left_click": (EventKind.MOUSE_CLICK, "left"),
    "right_click": (EventKind.MOUSE_CLICK, "right"),
    "middle_click": (EventKind.MOUSE_CLICK, "middle"),
}

# Scroll: button encodes the direction ("up" | "down" | "left" | "right"); the
# controller's send_event arm maps it to wire MouseEvent.wheel + direction.
_SCROLL_DIRECTIONS: frozenset[str] = frozenset({"up", "down", "left", "right"})


def _iter_content_blocks(response: Any) -> list[dict[str, Any]]:
    """Return the response's content blocks as a list of plain dicts.

    Accepts both the raw JSON shape (`{"content": [...]}`) and the SDK Message
    object shape (`response.content` is a list of block objects with `.type`,
    `.text`, `.name`, `.input` attributes). Normalising here means the parser
    proper only ever reads dicts.
    """
    if isinstance(response, dict):
        blocks = response.get("content")
    else:
        blocks = getattr(response, "content", None)
    if not isinstance(blocks, list):
        raise ComputerUseParseError(
            f"response has no list `content` field; got {type(response).__name__}"
        )
    out: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, dict):
            out.append(block)
            continue
        # SDK object — pull the fields we care about.
        kind = getattr(block, "type", None)
        if kind == "text":
            out.append({"type": "text", "text": getattr(block, "text", "")})
        elif kind == "tool_use":
            out.append(
                {
                    "type": "tool_use",
                    "name": getattr(block, "name", ""),
                    "input": getattr(block, "input", {}) or {},
                }
            )
        else:
            # Ignore unknown block types (e.g. thinking blocks) — they don't
            # contribute to the action and shouldn't crash the parser.
            continue
    return out


def _coerce_coordinate(
    raw: Any,
    *,
    frame_width: int,
    frame_height: int,
    action_name: str,
) -> tuple[float, float]:
    """Convert an Anthropic `[x_px, y_px]` coordinate into normalised
    0.0–1.0 floats clamped to the frame box.

    Anthropic returns absolute pixel coordinates in the framebuffer the model
    saw (i.e. the resized frame the controller sent to it). The session loop
    keeps things resolution-agnostic by normalising on this side.
    """
    if frame_width <= 0 or frame_height <= 0:
        raise ComputerUseParseError(
            f"action {action_name!r} cannot normalise coordinate: "
            f"frame size is {frame_width}x{frame_height}"
        )
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ComputerUseParseError(
            f"action {action_name!r} missing or malformed coordinate: {raw!r}"
        )
    try:
        px_x = float(raw[0])
        px_y = float(raw[1])
    except (TypeError, ValueError) as exc:
        raise ComputerUseParseError(
            f"action {action_name!r} coordinate not numeric: {raw!r}"
        ) from exc
    # Clamp before dividing so a model that returns out-of-bounds pixels
    # (which happens — sub-pixel rounding, model confusion at the edge)
    # still produces a normalised value the wire encoder accepts.
    px_x = max(0.0, min(px_x, float(frame_width)))
    px_y = max(0.0, min(px_y, float(frame_height)))
    return px_x / float(frame_width), px_y / float(frame_height)


def _extract_rationale(blocks: list[dict[str, Any]]) -> str:
    """Collect any text blocks that precede the tool_use as the rationale.

    Anthropic's computer-use models routinely emit `"I'm going to click the
    WiFi icon in the bottom-right corner"` before the tool call. Klara reads
    this verbatim to the customer during the confirm-gate.
    """
    parts: list[str] = []
    for block in blocks:
        if block.get("type") == "text":
            text = (block.get("text") or "").strip()
            if text:
                parts.append(text)
        elif block.get("type") == "tool_use":
            break
    return " ".join(parts)


def _parse_computer_use_action(
    response: Any,
    *,
    frame_width: int,
    frame_height: int,
    confidence_override: float | None = None,
) -> PredictedAction:
    """Turn an Anthropic `messages.create` response that used the `computer`
    tool into a PredictedAction.

    Args:
        response: The raw Anthropic response (dict or SDK Message). MUST
            contain a tool_use block named `"computer"`.
        frame_width / frame_height: Pixel size of the frame that was sent to
            the model. Used to normalise the returned coordinate to 0.0–1.0.
        confidence_override: If given, used as the PredictedAction.confidence.
            If None, defaults to 1.0 for a clean tool_use (the model
            committed to an action) — the abort policy in session.py treats
            a present tool_use as confident; rejection-streak handles the
            "model is wrong" case empirically.

    Raises:
        ComputerUseParseError: If no `computer` tool_use block is present,
        the action string is not in the supported set, or the action's
        required fields (coordinate / text / direction) are missing or
        malformed.
    """
    blocks = _iter_content_blocks(response)
    rationale = _extract_rationale(blocks)
    tool_use: dict[str, Any] | None = next(
        (
            b
            for b in blocks
            if b.get("type") == "tool_use" and b.get("name") == "computer"
        ),
        None,
    )
    if tool_use is None:
        raise ComputerUseParseError(
            "response has no `computer` tool_use block — "
            "model returned text only (likely refused or hit max_tokens)"
        )
    tool_input = tool_use.get("input")
    if not isinstance(tool_input, dict):
        raise ComputerUseParseError(
            f"computer tool_use.input is not an object: {tool_input!r}"
        )
    action = tool_input.get("action")
    if not isinstance(action, str) or not action:
        raise ComputerUseParseError(
            f"computer tool_use.input.action is missing or not a string: {action!r}"
        )

    confidence = (
        confidence_override
        if confidence_override is not None
        else (tool_input.get("confidence") or 1.0)
    )
    target_description = rationale or f"({action})"

    if action in _CLICK_ACTIONS:
        kind, button = _CLICK_ACTIONS[action]
        x, y = _coerce_coordinate(
            tool_input.get("coordinate"),
            frame_width=frame_width,
            frame_height=frame_height,
            action_name=action,
        )
        event = InputEvent(kind=kind, x=x, y=y, button=button)
    elif action == "key":
        text = tool_input.get("text")
        if not isinstance(text, str) or not text:
            raise ComputerUseParseError(
                f"action {action!r} missing required `text` field "
                f"(keysym like 'Return' or 'ctrl+c'); got {text!r}"
            )
        event = InputEvent(kind=EventKind.KEY_PRESS, key=text)
    elif action == "type":
        text = tool_input.get("text")
        if not isinstance(text, str):
            raise ComputerUseParseError(
                f"action {action!r} missing required `text` field; got {text!r}"
            )
        # An empty `type` string is technically a no-op — refuse it so the
        # session loop doesn't burn a confirm-gate cycle on nothing.
        if text == "":
            raise ComputerUseParseError(
                f"action {action!r} has empty `text` — refusing no-op type"
            )
        event = InputEvent(kind=EventKind.PASTE_TEXT, text=text)
    elif action == "scroll":
        direction = tool_input.get("scroll_direction")
        if direction not in _SCROLL_DIRECTIONS:
            raise ComputerUseParseError(
                f"action {action!r} has invalid `scroll_direction`: {direction!r} "
                f"(expected one of: {sorted(_SCROLL_DIRECTIONS)})"
            )
        x, y = _coerce_coordinate(
            tool_input.get("coordinate"),
            frame_width=frame_width,
            frame_height=frame_height,
            action_name=action,
        )
        event = InputEvent(kind=EventKind.MOUSE_SCROLL, x=x, y=y, button=direction)
    else:
        raise ComputerUseParseError(
            f"unsupported computer-use action: {action!r} "
            "(supported: mouse_move, left_click, right_click, middle_click, "
            "key, type, scroll)"
        )

    return PredictedAction(
        event=event,
        target_description=target_description,
        rationale=rationale or f"Model requested {action}.",
        confidence=confidence,
        raw_model_response=tool_use,
    )


@dataclass(frozen=True)
class PredictedAction:
    event: InputEvent
    target_description: str  # "the WiFi icon in the bottom-right corner"
    rationale: str  # readable by Klara for voice confirmation
    confidence: float  # 0.0–1.0, model self-report
    raw_model_response: dict[str, Any] | None = None

    @property
    def low_confidence(self) -> bool:
        return self.confidence < LOW_CONFIDENCE_THRESHOLD


class VisionPredictor:
    """Wraps the Anthropic computer-use API.

    The actual messages.create call is stubbed in G34 scaffold; G34.2 wires
    the real call. The shape returned to callers (PredictedAction) is final.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or ANTHROPIC_API_KEY
        self.model = model or VISION_MODEL

    async def predict(self, frame: Frame, goal: str) -> PredictedAction:
        if not self.api_key:
            log.warning("vision predict: ANTHROPIC_API_KEY unset; returning safe no-op")
            return PredictedAction(
                event=InputEvent(kind=EventKind.MOUSE_MOVE, x=0.5, y=0.5),
                target_description="(no api key — vision disabled)",
                rationale="Vision predictor not configured; controller is in safe no-op mode.",
                confidence=0.0,
            )
        # G34.2: real Anthropic computer-use call. The response shape is
        # parsed by _parse_computer_use_action (pure data, unit-tested) —
        # this method is the only place that performs network I/O.
        log.info("vision predict goal=%r seq=%d", goal, frame.sequence)
        response = await self._call_anthropic(frame, goal)
        return _parse_computer_use_action(
            response,
            frame_width=frame.width,
            frame_height=frame.height,
        )

    async def _call_anthropic(self, frame: Frame, goal: str) -> Any:
        """Make the actual messages.create call. Split out so tests can patch
        a single seam (`_call_anthropic`) and feed canned responses into the
        parser without touching the network.
        """
        import base64

        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover — install path
            raise RuntimeError(
                "anthropic SDK not installed; `pip install anthropic` "
                "or run the controller in stub mode by unsetting "
                "ANTHROPIC_API_KEY."
            ) from exc

        # 2026-08-16: the `computer_20250124` tool is REJECTED by claude-opus-4-7
        # on this account (400 — only bash_*/code_execution_* tools accepted), so
        # we use the image + JSON-prompt approach for BOTH Claude and any local
        # vision provider. Claude returns clean action JSON with good coordinates
        # (tested: 28px from target center on a 256px frame). VISION_BASE_URL
        # empty = api.anthropic.com (Claude default); set to the :8090 gateway /
        # Ollama to use a local vision model.
        base_url = VISION_BASE_URL or None
        client = anthropic.AsyncAnthropic(api_key=self.api_key, base_url=base_url)

        image_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": f"image/{frame.codec if frame.codec in ('jpeg', 'png') else 'jpeg'}",
                "data": base64.b64encode(frame.payload).decode("ascii"),
            },
        }
        resp = await client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        image_block,
                        {"type": "text", "text": _vision_json_prompt(goal)},
                    ],
                }
            ],
        )
        return _json_to_computer_response(resp)


def _prompt_for_goal(goal: str) -> str:
    """Build the user prompt that frames the goal for the computer-use loop.

    Kept as a free function so test code can assert on the rendered prompt
    without instantiating VisionPredictor.
    """
    return (
        "You are Klara, a remote IT support agent. The screenshot above is "
        "what the customer currently sees on their screen. The goal is:\n\n"
        f"    {goal}\n\n"
        "Pick exactly ONE next action that moves toward the goal, using "
        "the `computer` tool. Before the tool call, write one short "
        "sentence describing in plain language what you are about to do — "
        "this sentence will be read aloud to the customer for confirmation "
        "before the action fires. If you cannot decide on a safe next "
        "action, do not call the tool — output only the sentence "
        "explaining why."
    )


_VISION_JSON_SCHEMA = """\
Return ONLY valid JSON matching this exact schema (no markdown, no prose):
{
  "action": "mouse_move" | "left_click" | "right_click" | "middle_click" | "key" | "type" | "scroll",
  "coordinate": [<int px x>, <int px y>],
  "text": "<keysym or text>",
  "scroll_direction": "up" | "down" | "left" | "right",
  "target_description": "<human-readable target>",
  "rationale": "<one sentence why>",
  "confidence": <0.0 to 1.0>
}

Rules:
- coordinate is REQUIRED for mouse_move / clicks / scroll — a JSON list of two pixel ints [x, y] in the screenshot.
- text is REQUIRED for key (keysym like \"Return\" or \"ctrl+c\") and type (string to type).
- scroll_direction is REQUIRED for scroll.
- Never include fields not requested."""


def _vision_json_prompt(goal: str) -> str:
    """Prompt a local vision model (no `computer` tool) to emit the same action
    JSON the parser expects. Kept free so tests can assert on the rendered prompt."""
    return (
        "You are the computer-use predictor for a remote IT support session.\n"
        f"Goal: {goal}\n"
        "Look at the screenshot and decide the single next input action.\n"
        + _VISION_JSON_SCHEMA
    )


# Vision models often emit "click" for a left-click, "hover"/"move" for a
# mouse_move. Normalise to the parser's action vocabulary (kept small — only
# unambiguous aliases; anything genuinely ambiguous stays and errors).
_ACTION_ALIASES = {
    "click": "left_click",
    "single_click": "left_click",
    "move": "mouse_move",
    "move_mouse": "mouse_move",
    "hover": "mouse_move",
}


def _json_to_computer_response(response: Any) -> dict[str, Any]:
    """Wrap a local vision model's JSON text reply into the `computer` tool_use
    shape so `_parse_computer_use_action` is reused verbatim (same coordinate /
    action validation). Raises ComputerUseParseError if the reply is not JSON."""
    text = ""
    blocks = getattr(response, "content", None)
    if blocks:
        for b in blocks:
            if getattr(b, "type", None) == "text":
                text = getattr(b, "text", "") or ""
                break

    # Vision models routinely wrap the JSON in prose and/or markdown fences.
    # Extract the object substring (first '{' .. last '}') before parsing.
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ComputerUseParseError(
            f"vision JSON parse failed — no JSON object in reply: {text[:300]!r}"
        )
    cleaned = text[start : end + 1]
    try:
        tool_input = json.loads(cleaned)
    except json.JSONDecodeError:
        raise ComputerUseParseError(
            f"vision JSON parse failed — invalid JSON: {text[:300]!r}"
        )
    if not isinstance(tool_input, dict):
        raise ComputerUseParseError(f"vision JSON is not an object: {tool_input!r}")
    action = tool_input.get("action")
    if isinstance(action, str) and action in _ACTION_ALIASES:
        tool_input["action"] = _ACTION_ALIASES[action]
    return {
        "content": [
            {"type": "text", "text": tool_input.get("rationale", "")},
            {"type": "tool_use", "name": "computer", "input": tool_input},
        ]
    }
