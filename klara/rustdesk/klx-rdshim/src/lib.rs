//! `klx-rdshim` — Klaravex RustDesk operator-side shim library.
//!
//! This crate is the Rust half of the G34.1 binding decision (subprocess +
//! thin Rust shim). The Python side lives in
//! `infra/rustdesk_controller/rdshim_ipc.py` and defines the v0 JSON line
//! protocol; this crate is the conformance implementation.
//!
//! ## Current cursor (G34.2d — 2026-06-12, iter-22)
//!
//! G34.2a + G34.2b + G34.2c are **done**. G34.2d **operator-side half**
//! lands this iteration; the customer-side helper UI work is tracked
//! separately under `infra/rustdesk-helper-*` (out of this crate's
//! scope). The shim can now:
//!   - run a UDP RegisterPk + RegisterPeer heartbeat against the live
//!     hbbs at `87.99.147.244:21116/udp` (see [`udp_rendezvous`]).
//!   - drive the hbbs secretbox handshake over TCP-21116 against the
//!     server's signed ed25519 pubkey (see [`secure`]).
//!   - issue PunchHoleRequest over TCP-21116 and parse the structured
//!     PunchHoleResponse / RelayResponse reply (see [`relay`]).
//!   - decode `PunchHoleResponse.socket_addr` via AddrMangle, dial the
//!     peer over TCP, return the TcpStream + signed-peer-pk envelope
//!     (see [`peer_connect`]).
//!   - decode VP9 keyframes to RGBA via libvpx (see [`vp9`]).
//!   - drive a `PeerChannel` end-to-end through `stream_session` —
//!     `StreamCommand::{Mouse, KeyChar, Stop, KillSwitch}` in,
//!     `StreamEvent::{Frame, InputAck, Disconnected, Error}` out.
//!
//! **G34.2d operator-side deliverables landed this iteration:**
//!
//!   1. [`peer_session::StreamCommand::KillSwitch`] — operator panic
//!      button. Emits `Disconnected { reason: "operator_kill_switch" }`,
//!      distinct from `Stop`'s `"stop_requested"` so audit pipelines
//!      can tell a clean close from an emergency tear-down.
//!   2. [`peer_session::StreamConfig::idle_timeout`] — optional
//!      `Some(Duration)` watchdog. If no peer message AND no operator
//!      command for the configured window, the driver self-terminates
//!      with `Disconnected { reason: "idle_timeout" }`. Default
//!      `None` preserves G34.2c semantics for callers that haven't
//!      opted in.
//!   3. [`ipc::CmdKill`] (`{"kind":"kill"}`) IPC command — operator-
//!      facing wire shape that `main.rs` translates into
//!      `StreamCommand::KillSwitch` on the real path and into a
//!      direct `Disconnected{operator_kill_switch}` emission on the
//!      mock path. Parseable both pre-connect and mid-session.
//!   4. `main.rs` — `KLX_RDSHIM_IDLE_TIMEOUT_SECS=<n>` env knob wires
//!      the idle watchdog into the production real-session driver
//!      without touching the in-process API.
//!
//! **G34.3 landed iter-3 (2026-06-13):**
//!
//!   1. [`peer_session::MouseButton`] — `Left | Right | Middle` enum
//!      with `from_ipc_str` parser covering the
//!      `"left"|"primary"|"right"|"secondary"|"middle"|"wheel"`
//!      IPC synonyms. The empty string defaults to `Left`.
//!   2. New `PeerChannel` send helpers — `send_mouse_button`,
//!      `send_mouse_click`, `send_mouse_scroll`, `send_key_char_down`,
//!      `send_key_char_up`. All masks computed from the upstream
//!      `(button << 3) | type` rustdesk encoding.
//!   3. [`peer_session::StreamCommand`] gained `MouseClick`,
//!      `MouseScroll`, `KeyDown`, `KeyUp` variants. The streaming
//!      driver forwards each to its matching `PeerChannel` helper and
//!      bumps `input_seq` once per logical event (clicks count as one
//!      `InputAck` even though they emit two wire messages).
//!   4. [`peer_session::translate_input_event`] — moved out of
//!      `main.rs` so it lives in the lib and is unit-testable. v0 IPC
//!      `mouse_click` / `mouse_scroll` / `key_down` / `key_up` /
//!      `key_release` all now translate to real-path `StreamCommand`s
//!      instead of being no-op'd. Coordinate scaling is shared with
//!      `mouse_move`; wheel deltas are intentionally not scaled.
//!
//! **G34.3+ landed iter-5 (2026-06-13):**
//!
//!   1. [`peer_session::PeerChannel::send_clipboard_text`] — encodes
//!      a `Message::Clipboard` with `format = ClipboardFormat::Text`,
//!      `compress = false`, `content = text.as_bytes()`. Mirrors
//!      upstream `rustdesk/src/client.rs::clipboard_msg` for the
//!      uncompressed-text path.
//!   2. [`peer_session::StreamCommand::PasteText`] — opt-in
//!      string-paste variant for the streaming driver. Counts as a
//!      single `InputAck` regardless of string length.
//!   3. [`peer_session::translate_input_event`] — v0 IPC `paste_text`
//!      now translates to a full-string `StreamCommand::PasteText`
//!      (was: first-char-only `KeyChar` workaround). Empty `text`
//!      still returns `Ok(None)` so the no-op path is unchanged.
//!
//! **G34.3++ landed iter-6 (2026-06-13):**
//!
//!   1. [`peer_session::Modifier`] — operator-side Ctrl/Alt/Shift/Meta
//!      abstraction with `from_ipc_str` synonym-tolerant parser
//!      (accepts `ctrl|control`, `alt|option|opt`, `shift`,
//!      `meta|cmd|command|win|super`) and `to_control_key()` mapper
//!      to the upstream `crate::message_proto::ControlKey` wire enum.
//!   2. [`peer_session::PeerChannel::send_key_char_with_modifiers`] —
//!      encodes a chorded press as two `KeyEvent` messages
//!      (down + up) with `KeyEvent.modifiers` populated on both edges
//!      from the supplied `&[ControlKey]` slice. Empty slice is valid
//!      and produces empty modifier lists on both edges.
//!   3. [`peer_session::StreamCommand::KeyChord`] — streaming-driver
//!      variant for chorded press+release. Counts as a single
//!      `InputAck` regardless of modifier count.
//!   4. [`peer_session::translate_input_event`] — v0 IPC `key_press`
//!      with a non-empty `modifiers` list now translates to a
//!      `StreamCommand::KeyChord`; empty `modifiers` preserves the
//!      no-modifier `StreamCommand::KeyChar` path bit-for-bit so all
//!      iter-3 tests stay green. Unknown modifier strings surface as
//!      `Err("unsupported modifier: ...")` so the IPC layer can emit
//!      a structured `EvtError`.
//!
//! **G34.3+++ landed iter-7 (2026-06-13):**
//!
//!   1. [`peer_session::PeerChannel::send_key_char_down_with_modifiers`] +
//!      [`peer_session::PeerChannel::send_key_char_up_with_modifiers`] —
//!      single-edge encoders that populate `KeyEvent.modifiers` on the
//!      wire so the IPC layer can drive a held-modifier sequence
//!      (e.g. Shift held while emitting Shift+Arrow chords). Empty
//!      slice preserves the existing no-modifier `send_key_char_down` /
//!      `send_key_char_up` wire output bit-for-bit.
//!   2. [`peer_session::StreamCommand::KeyDownChord`] +
//!      [`peer_session::StreamCommand::KeyUpChord`] — streaming-driver
//!      variants that pair with the new encoders. One `InputAck` per
//!      edge (mirrors the existing `KeyDown` / `KeyUp` semantics; the
//!      chord adds modifier state, not extra events).
//!   3. [`peer_session::translate_input_event`] — v0 IPC `key_down`
//!      and `key_up` / `key_release` with a non-empty `modifiers`
//!      list now translate to `KeyDownChord` / `KeyUpChord`; empty
//!      `modifiers` preserves the `KeyDown` / `KeyUp` path
//!      bit-for-bit so all iter-3 and iter-6 tests stay green.
//!      Unknown modifier strings still surface as
//!      `Err("unsupported modifier: ...")`.
//!
//! With the down/up chord variants now landed, the IPC layer owns the
//! contract for held-modifier sequences (Shift+Arrow, Cmd+Tab, modal
//! command-palette flows). There is no operator-side state that
//! auto-attaches a held modifier — every wire `KeyEvent` carries
//! exactly what the IPC layer specified. The held-modifier flow that
//! was deferred in iter-6 is therefore covered: a held-Shift sequence
//! is expressed as `KeyDown` (Shift) → `KeyChord` (Arrow, [Shift]) →
//! `KeyUp` (Shift), and every per-event wire message reflects that.
//!
//! **G34.3++++ landed iter-8 (2026-06-13):**
//!
//!   1. [`peer_session::StreamCommand::MouseDown`] +
//!      [`peer_session::StreamCommand::MouseUp`] — button-edge variants
//!      that emit a single `MOUSE_TYPE_DOWN` / `MOUSE_TYPE_UP` wire
//!      message at the supplied coordinates. The wire mask is bit-for-bit
//!      identical to the down half / up half of the existing
//!      [`peer_session::StreamCommand::MouseClick`] flow, so a
//!      `MouseDown → Mouse → MouseUp` triple replays as a single
//!      drag-and-drop gesture from the customer-OS perspective.
//!   2. [`peer_session::translate_input_event`] now recognises
//!      `"mouse_down"` and `"mouse_up"` (plus the v0 alias
//!      `"mouse_release"`, mirroring the `key_release` alias for
//!      `key_up`). Unknown `button` strings surface as
//!      `Err("unsupported mouse button: …")` so the IPC layer can
//!      emit a structured `EvtError`. Coordinates use the same
//!      fractional-vs-pixel scaling as `mouse_move` / `mouse_click`.
//!   3. Each `MouseDown` and `MouseUp` counts as one `InputAck`, so a
//!      drag triple acks three times. This matches the IPC layer's
//!      "one ack per logical event" contract and lets the caller
//!      sequence drag start / move / drag end independently for
//!      pacing or retry purposes.
//!
//! **G34.3+++++ landed iter-9 (2026-06-13):**
//!
//!   1. [`peer_session::StreamCommand::MouseDoubleClick`] — first-class
//!      double-click variant matching Anthropic computer-use's
//!      `double_click` action. Emits four wire messages —
//!      `MOUSE_TYPE_DOWN` → `MOUSE_TYPE_UP` → `MOUSE_TYPE_DOWN` →
//!      `MOUSE_TYPE_UP`, all at the supplied coordinates and button —
//!      so the customer-side OS double-click detector (Windows DCM,
//!      macOS NSEvent `clickCount`, X11 XInput2) fires reliably
//!      regardless of operator-side scheduling jitter. Counts as a
//!      single `InputAck` because callers treat a double-click as one
//!      logical event.
//!   2. [`peer_session::translate_input_event`] now recognises
//!      `"double_click"` and the alias `"mouse_double_click"` (mirrors
//!      the `mouse_release` / `mouse_up` alias precedent). Coordinates
//!      use the same fractional-vs-pixel scaling as `mouse_click`.
//!      Unknown `button` strings surface as
//!      `Err("unsupported mouse button: …")` so the IPC layer can emit
//!      a structured `EvtError`. Default button is `Left` when the
//!      field is absent.
//!
//! **G34.3++++++ landed iter-11 (2026-06-13):**
//!
//!   1. [`peer_session::StreamCommand::MouseTripleClick`] — first-class
//!      triple-click variant matching Anthropic computer-use's
//!      `triple_click` action. Emits six wire messages —
//!      `MOUSE_TYPE_DOWN` → `MOUSE_TYPE_UP` repeated three times, all
//!      at the supplied coordinates and button — so the customer-side
//!      platform triple-click selection (macOS NSEvent `clickCount` = 3
//!      for word/line select, Windows triple-click chains, X11
//!      multi-click sequences) fires reliably regardless of
//!      operator-side scheduling jitter. Counts as a single
//!      `InputAck` because callers treat a triple-click as one logical
//!      event. Encoded via three chained `send_mouse_click` calls
//!      using `Result::and_then` — a partial failure surfaces as one
//!      `mouse_send_failed` `Error` event (same semantics as
//!      `MouseClick` / `MouseDoubleClick`).
//!   2. [`peer_session::translate_input_event`] now recognises
//!      `"triple_click"` and the alias `"mouse_triple_click"`. Same
//!      fractional-vs-pixel scaling, same `from_ipc_str` button
//!      validation, same `Left` default as `double_click`.
//!
//! **G34.3+++++++ landed iter-12 (2026-06-13):**
//!
//!   1. [`peer_session::StreamCommand::LeftMouseDrag`] — first-class
//!      drag-and-drop variant matching Anthropic computer-use's
//!      `left_mouse_drag` action. Encodes the canonical three-event
//!      drag wire burst: `MOUSE_TYPE_DOWN` at the start coord,
//!      `MOUSE_TYPE_MOVE` at the end coord, `MOUSE_TYPE_UP` at the end
//!      coord — the customer-OS treats the button as held throughout
//!      so standard drag-and-drop handlers (file-manager DnD, text
//!      selection drag-extend, web `dragstart`/`dragend`, native
//!      window-move and resize) fire correctly. Counts as a single
//!      `InputAck` because callers treat a drag as one logical event.
//!      Encoded via `send_mouse_button(down) → send_mouse_move →
//!      send_mouse_button(up)` chained through `Result::and_then` so a
//!      partial failure (e.g. the release wire-send fails after the
//!      move succeeds) surfaces as one `mouse_send_failed` `Error`
//!      event — matches `MouseClick` / `MouseDoubleClick` /
//!      `MouseTripleClick` error semantics. The UP edge carries the
//!      same button bits as the DOWN edge so the customer-OS sees a
//!      consistent button-hold bracket.
//!   2. [`peer_session::translate_input_event`] now recognises
//!      `"left_mouse_drag"` and the alias `"mouse_drag"`. IPC schema:
//!      `x`/`y` carry the END coordinate (matching the rest of the
//!      mouse event surface), and the new
//!      [`ipc::InputEvent::x_start`] / [`ipc::InputEvent::y_start`]
//!      fields carry the START coordinate. Both pairs use the same
//!      fractional-vs-pixel scaling rule. If `x_start`/`y_start` are
//!      absent, the start defaults to the end — a degenerate
//!      zero-motion drag that still emits a valid DOWN→MOVE→UP burst.
//!      Default button is `Left` (matches the action name); explicit
//!      `button:"right"` is honored so a right-button drag uses the
//!      same event_kind.
//!
//! **G34.3++++++++ landed iter-13 (2026-06-13):**
//!
//!   1. [`peer_session::StreamCommand::Wait`] — explicit driver-side
//!      pause matching Anthropic computer-use's `wait` action. Lets the
//!      controller insert a deterministic delay between input commands
//!      (e.g. after a click that triggers a slow page render, before
//!      asking for a fresh screenshot). Hard-capped at
//!      [`peer_session::WAIT_MAX_MS`] (60 s) so a buggy controller
//!      cannot pin the driver indefinitely — values above the cap are
//!      silently clamped, the InputAck still fires, and the controller
//!      can re-issue Wait if it needs more time. Counts as exactly one
//!      `InputAck` regardless of the requested duration. Not
//!      interruptible mid-sleep; an operator `KillSwitch` issued
//!      during a Wait fires as soon as the clamped sleep returns.
//!   2. [`peer_session::translate_input_event`] now recognises
//!      `"wait"` and the alias `"pause"`. The new
//!      [`ipc::InputEvent::duration_ms`] field carries the requested
//!      pause duration; missing field defaults to 0 (a no-op
//!      synchronisation point that still emits one InputAck). The
//!      translator is a pure mapping function and does NOT clamp —
//!      clamping is the driver's responsibility so the policy lives in
//!      one place.
//!
//! **G34.3+++++++++ landed iter-25 (2026-06-14):**
//!
//!   1. [`peer_session::StreamCommand::MouseScrollAt`] — scroll at a
//!      specific anchor coordinate. Translates to two wire messages at
//!      the driver level: `MOUSE_TYPE_MOVE` at `(x, y)` then a wheel
//!      event carrying the deltas (`dx`, `dy`). Matches Anthropic
//!      computer-use's `scroll` action where `coordinate` is the
//!      required argument naming where the scroll should land — a
//!      specific panel, list, embedded widget. Without the explicit
//!      move, [`peer_session::StreamCommand::MouseScroll`] would
//!      scroll whichever element the customer's existing cursor
//!      happens to be over — usually wrong. Counts as a single
//!      `InputAck` because callers treat scroll-at-coordinate as one
//!      logical event (same composite-burst contract as
//!      [`peer_session::StreamCommand::LeftMouseDrag`]).
//!   2. [`peer_session::translate_input_event`] now recognises
//!      `"mouse_scroll_at"` and the alias `"scroll_at"`. The new
//!      [`ipc::InputEvent::dx`] and [`ipc::InputEvent::dy`] fields
//!      carry the wheel deltas. Anchor coordinates (`x`, `y`) follow
//!      the same fractional-vs-pixel scaling rules as `mouse_move`;
//!      deltas are never scaled (wheel ticks are operator-side intent,
//!      not screen-space). Missing deltas default to `0` — a degenerate
//!      MOVE-then-zero-wheel burst that still emits one InputAck,
//!      useful as a synchronisation anchor before a series of
//!      `mouse_scroll` commands.
//!
//! **G34.3++++++++++ landed iter-26 (2026-06-14):**
//!
//!   1. [`peer_session::StreamCommand::TypeText`] — type a literal
//!      string by emitting one `KeyEvent` press (down + up) per
//!      character. Matches Anthropic computer-use's `type` action.
//!      Distinct from [`peer_session::StreamCommand::PasteText`]:
//!      `PasteText` uses `Message::Clipboard` (one wire message,
//!      fast, but doesn't work in fields that block paste — password
//!      prompts, sandboxed UIs, native controls intercepting
//!      `WM_PASTE`); `TypeText` simulates real keystrokes
//!      (N wire messages for an N-char string, universal). Counts as
//!      a single `InputAck` regardless of length — one `type` action
//!      is one logical event, same contract as `PasteText`. On the
//!      first per-char send failure, the driver surfaces a single
//!      `key_send_failed` Error event and stops typing the remainder.
//!   2. [`peer_session::translate_input_event`] now recognises
//!      `"type"` and the alias `"type_text"`. Reuses
//!      [`ipc::InputEvent::text`] (same field as `paste_text`).
//!      Empty text returns `Ok(None)` so the driver never sees a
//!      zero-keystroke command (matches the paste_text empty-string
//!      semantics).
//!
//! **G34.3+++++++++++ landed iter-27 (2026-06-14):**
//!
//!   1. [`peer_session::StreamCommand::NamedKeyPress`] — press a
//!      named key (Return, Tab, Escape, Arrow keys, F1..F12, Home,
//!      End, PageUp/PageDown, CapsLock, NumLock, ScrollLock, etc.)
//!      with an optional modifier chord. Matches Anthropic
//!      computer-use's `key` action. Distinct from
//!      [`peer_session::StreamCommand::KeyChar`] (Unicode codepoint
//!      via `KeyEvent.chr`) and
//!      [`peer_session::StreamCommand::KeyChord`] (Unicode codepoint
//!      with a held chord): `NamedKeyPress` targets the
//!      `KeyEvent.control_key` oneof variant so the operator can
//!      drive keys that have no useful Unicode codepoint. Also
//!      exposes the rustdesk-special CtrlAltDel / LockScreen
//!      affordances. Emits two wire messages (down + up); counts as
//!      a single `InputAck`.
//!   2. [`peer_session::translate_input_event`] now recognises
//!      `"named_key"`, `"key"`, and `"press_key"`. The XKB-style
//!      name lives in [`ipc::InputEvent::key`] (reusing the field
//!      `key_press` already uses for single chars). Empty key fields
//!      and unknown names both return `Err` so the IPC layer can
//!      surface a structured `unsupported_event_kind` error. The
//!      optional modifier chord reuses the same `event.modifiers`
//!      list that `key_press` and `key_down`/`key_up` consume, so
//!      chorded named-key shortcuts (Ctrl+Tab, Shift+F10, Alt+F4)
//!      use the same wire encoding as char chords.
//!   3. New helper [`peer_session::parse_named_key`] maps the named
//!      string into the upstream `ControlKey` enum. Accepts case-
//!      insensitive matches and tolerates `_` / `-` / space
//!      separators (so "Page_Down", "page-down", "PAGEDOWN", and
//!      "Page Down" all collide on the same variant). Aliases like
//!      `enter`↔`return`, `esc`↔`escape`, `pgdn`↔`pagedown`,
//!      `arrow_up`↔`up` are recognised so callers don't need to
//!      normalise.
//!
//! **Deferred — explicitly out of scope for this crate:**
//!
//!   - **Consent UI dialog** — runs on the customer's machine inside
//!     the support.klaravex.com helper. Tracked under
//!     `infra/rustdesk-helper-windows/` and `infra/rustdesk-helper-macos/`.
//!     The operator side already supports the kill switch the helper
//!     will fire when consent is revoked.
//!   - **On-screen "Klaravex is connected" indicator** — same scope
//!     boundary as the consent dialog; lives in the helper, not here.
//!   - **Live-peer integration** — Anthony will spin up a rustdesk VM
//!     and re-run the `#[ignore]` tests against a real peer ID for
//!     the end-to-end mouse-move proof.
//!   - Compressed-clipboard payloads (`Clipboard.compress = true`,
//!     zstd-encoded content) — uncompressed text covers the v0
//!     paste_text contract; the compressed path can land alongside
//!     the file-transfer flow when that scope reopens.
//!   - **Held-modifier flow** — landed iter-7 as G34.3+++. See the
//!     `send_key_char_down_with_modifiers` / `send_key_char_up_with_modifiers`
//!     encoders and the `KeyDownChord` / `KeyUpChord` streaming
//!     variants. The IPC layer can now drive Shift+Arrow / Cmd+Tab
//!     style flows where the modifier is held across multiple
//!     subsequent key events.
//!   - **Drag-and-drop / mouse-edge events** — landed iter-8 as
//!     G34.3++++. See the `MouseDown` / `MouseUp` `StreamCommand`
//!     variants and the matching `"mouse_down"` / `"mouse_up"` IPC
//!     event_kinds. The IPC layer can now drive drag gestures by
//!     interleaving `Mouse { x, y }` moves between the button-edge
//!     events. The wire mask matches the existing `MouseClick` halves
//!     bit-for-bit so customer-OS behaviour is identical.
//!
//! Anti-pattern audit (Mistakes 13–15):
//!   - All `env-libvpx-sys` symbol callsites in `vp9.rs` were authored
//!     against the actual generated FFI in
//!     `target/debug/build/env-libvpx-sys-*/out/ffi.rs` — no symbol
//!     guessing (Mistake #13 avoided).
//!   - The generated `rendezvous.rs` is still wrapped per the
//!     `build.rs` rewriter (Mistake #14 avoided).
//!   - The TCP path uses synchronous `std::net::TcpStream` matching
//!     `udp_rendezvous.rs` (no tokio).

pub mod framebuffer;
pub mod ipc;
pub mod message_proto;
pub mod peer_connect;
pub mod peer_keys;
pub mod peer_session;
pub mod relay;
pub mod relay_client;
pub mod rendezvous_proto;
pub mod secure;
pub mod udp_rendezvous;
pub mod vp9;

pub use ipc::{
    Cmd, CmdConnect, CmdDisconnect, CmdEvent, CmdKill, Evt, EvtConnected, EvtDisconnected,
    EvtError, EvtEventAck, EvtFrame, EvtHello, InputEvent, ParseError,
};

/// Library version emitted in the `hello` message. The MAJOR component is
/// what `rdshim_ipc.py::SUPPORTED_MAJOR_VERSIONS` compares against.
pub const SHIM_VERSION: &str = "0.1.0";

/// Placeholder commit hash. Real builds replace this via `build.rs` reading
/// `git rev-parse HEAD` of the upstream librustdesk submodule.
pub const LIBRUSTDESK_COMMIT: &str = "g34.2-mock-peer";

/// Convenience formatter for the `hello` event payload.
pub fn hello_payload() -> EvtHello {
    EvtHello {
        shim_version: format!("klx-rdshim {SHIM_VERSION}"),
        librustdesk_commit: LIBRUSTDESK_COMMIT.to_string(),
    }
}
