//! v0 JSON line protocol — Rust types mirroring `rdshim_ipc.py`.
//!
//! Wire format (every line is one JSON object, `kind` discriminator):
//!
//!   Python → shim (commands)
//!     {"kind":"connect", relay_host, relay_key, hbbs_port, hbbr_port,
//!      customer_id, session_password}
//!     {"kind":"event", event_kind, x?, y?, button?, key?, text?, modifiers?}
//!     {"kind":"disconnect"}
//!     {"kind":"kill"}                                      (G34.2d)
//!
//!   shim → Python (events)
//!     {"kind":"hello", shim_version, librustdesk_commit}
//!     {"kind":"connected", session_id, width, height}
//!     {"kind":"frame", session_id, sequence, width, height, codec,
//!      payload_b64, timestamp_ms}
//!     {"kind":"event_ack", sequence, status}
//!     {"kind":"cursor_position", source, x, y}            (G34.3+++++++++++++++)
//!     {"kind":"error", code, message}
//!     {"kind":"disconnected", reason}
//!
//! The Python `parse_shim_event()` function is the reference parser; this
//! module's `Cmd::parse_line()` is its dual on the shim side.

use serde::{Deserialize, Serialize};

// ─────────────────────────────────────────────────────────────────────────────
// Errors
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub enum ParseError {
    EmptyLine,
    InvalidJson(serde_json::Error),
    NotObject,
    MissingKind,
    UnknownKind(String),
    BadField {
        field: &'static str,
        reason: String,
    },
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::EmptyLine => write!(f, "empty line"),
            Self::InvalidJson(e) => write!(f, "not valid JSON: {e}"),
            Self::NotObject => write!(f, "top-level JSON value must be object"),
            Self::MissingKind => write!(f, "missing or non-string 'kind'"),
            Self::UnknownKind(k) => write!(f, "unknown command kind: {k:?}"),
            Self::BadField { field, reason } => {
                write!(f, "bad field {field:?}: {reason}")
            }
        }
    }
}

impl std::error::Error for ParseError {}

// ─────────────────────────────────────────────────────────────────────────────
// Python → shim (commands)
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CmdConnect {
    pub relay_host: String,
    pub relay_key: String,
    pub hbbs_port: u16,
    pub hbbr_port: u16,
    pub customer_id: String,
    pub session_password: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct InputEvent {
    /// One of: mouse_move, mouse_click, mouse_scroll, key_press, key_release,
    /// paste_text. We accept anything to keep the protocol forward-compatible.
    pub event_kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub x: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub y: Option<f64>,
    /// G34.3+++++++ — start coordinate for composite drag gestures
    /// (`left_mouse_drag`). For single-point events (`mouse_move`,
    /// `mouse_click`, etc.) leave `None`; `x`/`y` always carry the
    /// "primary" coordinate (end point for drags).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub x_start: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub y_start: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub button: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub key: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub text: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub modifiers: Vec<String>,
    /// G34.3++++++++ — duration in milliseconds for `event_kind = "wait"`
    /// (and the alias `"pause"`). Ignored for all other event kinds.
    /// `None` defaults to 0 ms — a degenerate Wait that emits an
    /// immediate InputAck (useful as a no-op synchronisation point).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration_ms: Option<u64>,
    /// G34.3+++++++++ — wheel delta for `event_kind = "mouse_scroll_at"`
    /// (and the alias `"scroll_at"`). Horizontal component; positive
    /// values scroll right (matches upstream rustdesk wheel semantics).
    /// Ignored for all other event kinds. `None` defaults to 0.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub dx: Option<f64>,
    /// G34.3+++++++++ — wheel delta for `event_kind = "mouse_scroll_at"`
    /// (and the alias `"scroll_at"`). Vertical component; positive
    /// values scroll up (matches upstream rustdesk wheel semantics).
    /// Ignored for all other event kinds. `None` defaults to 0.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub dy: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CmdEvent {
    #[serde(flatten)]
    pub event: InputEvent,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct CmdDisconnect {}

/// G34.2d — operator-side kill switch. Distinct from `Disconnect` so the
/// operator UI and audit log can tell "user closed the session normally"
/// apart from "user pulled the emergency stop". The shim translates this
/// into `StreamCommand::KillSwitch` which emits a `Disconnected` event
/// with `reason: "operator_kill_switch"`.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct CmdKill {}

#[derive(Debug, Clone)]
pub enum Cmd {
    Connect(CmdConnect),
    Event(CmdEvent),
    Disconnect(CmdDisconnect),
    Kill(CmdKill),
}

impl Cmd {
    /// Parse one newline-delimited JSON command line. Whitespace-only lines
    /// are rejected by the caller — this function refuses them so the shim
    /// loop can distinguish "blank input" (idle) from "bad input" (error).
    pub fn parse_line(line: &str) -> Result<Self, ParseError> {
        let line = line.trim();
        if line.is_empty() {
            return Err(ParseError::EmptyLine);
        }
        let raw: serde_json::Value =
            serde_json::from_str(line).map_err(ParseError::InvalidJson)?;
        let obj = raw.as_object().ok_or(ParseError::NotObject)?;
        let kind = obj
            .get("kind")
            .and_then(|v| v.as_str())
            .ok_or(ParseError::MissingKind)?;

        match kind {
            "connect" => {
                let c: CmdConnect = serde_json::from_value(raw)
                    .map_err(|e| ParseError::BadField {
                        field: "connect",
                        reason: e.to_string(),
                    })?;
                Ok(Cmd::Connect(c))
            }
            "event" => {
                // event is the flattened InputEvent fields plus kind.
                let ev: InputEvent =
                    serde_json::from_value(raw).map_err(|e| ParseError::BadField {
                        field: "event",
                        reason: e.to_string(),
                    })?;
                Ok(Cmd::Event(CmdEvent { event: ev }))
            }
            "disconnect" => Ok(Cmd::Disconnect(CmdDisconnect::default())),
            "kill" => Ok(Cmd::Kill(CmdKill::default())),
            other => Err(ParseError::UnknownKind(other.to_string())),
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Shim → Python (events)
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvtHello {
    pub shim_version: String,
    pub librustdesk_commit: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvtConnected {
    pub session_id: String,
    pub width: u32,
    pub height: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvtFrame {
    pub session_id: String,
    pub sequence: u64,
    pub width: u32,
    pub height: u32,
    pub codec: String,
    pub payload_b64: String,
    pub timestamp_ms: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvtEventAck {
    pub sequence: u64,
    /// One of: "sent" | "dropped" | "rejected"
    pub status: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvtError {
    pub code: String,
    pub message: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvtDisconnected {
    pub reason: String,
}

/// G34.3+++++++++++++++ — response to an operator-side `cursor_position`
/// event (Anthropic computer-use `cursor_position` action). Carries the
/// last-known cursor screen coordinates plus a `source` discriminator so
/// the operator can tell where the coordinates came from:
///
///   - `"shim_last_send"` — the shim's record of the most recent
///     coordinate it forwarded to the peer. Not a true read-back: if the
///     customer or another controller moved the cursor between then and
///     now, the value is stale. Available immediately after any mouse
///     command is issued in the session.
///   - `"peer_report"` — the peer's own cursor position, returned by a
///     future rustdesk protocol query. NOT YET IMPLEMENTED at the
///     driver level; reserved here so the wire format is forward-compatible.
///
/// Coordinates are absolute screen pixels (same convention as inbound
/// mouse commands). `x` and `y` are signed because the upstream rustdesk
/// CursorPosition message uses i32 — keeps the wire types aligned.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvtCursorPosition {
    pub source: String,
    pub x: i32,
    pub y: i32,
}

/// All shim-emitted event types. We tag with `kind` to match the Python
/// `parse_shim_event` discriminator.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Evt {
    Hello(EvtHello),
    Connected(EvtConnected),
    Frame(EvtFrame),
    EventAck(EvtEventAck),
    CursorPosition(EvtCursorPosition),
    Error(EvtError),
    Disconnected(EvtDisconnected),
}

impl Evt {
    /// Serialize to a single line (no trailing newline). The runner appends
    /// `\n` so we can re-use this in tests without splitting lines.
    pub fn to_json_line(&self) -> String {
        serde_json::to_string(self).expect("Evt serialization is total")
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_connect_command() {
        let line = r#"{"kind":"connect","relay_host":"87.99.147.244","relay_key":"AAAA","hbbs_port":21116,"hbbr_port":21117,"customer_id":"4242-1111-9090","session_password":"pwd"}"#;
        let cmd = Cmd::parse_line(line).unwrap();
        match cmd {
            Cmd::Connect(c) => {
                assert_eq!(c.relay_host, "87.99.147.244");
                assert_eq!(c.hbbs_port, 21116);
                assert_eq!(c.hbbr_port, 21117);
                assert_eq!(c.customer_id, "4242-1111-9090");
            }
            _ => panic!("expected Connect"),
        }
    }

    #[test]
    fn parse_event_command_mouse_move() {
        let line = r#"{"kind":"event","event_kind":"mouse_move","x":0.4218,"y":0.6614}"#;
        let cmd = Cmd::parse_line(line).unwrap();
        match cmd {
            Cmd::Event(e) => {
                assert_eq!(e.event.event_kind, "mouse_move");
                assert_eq!(e.event.x, Some(0.4218));
                assert_eq!(e.event.y, Some(0.6614));
                assert!(e.event.button.is_none());
            }
            _ => panic!("expected Event"),
        }
    }

    #[test]
    fn parse_event_command_paste_text() {
        let line = r#"{"kind":"event","event_kind":"paste_text","text":"hello"}"#;
        let cmd = Cmd::parse_line(line).unwrap();
        match cmd {
            Cmd::Event(e) => {
                assert_eq!(e.event.event_kind, "paste_text");
                assert_eq!(e.event.text.as_deref(), Some("hello"));
            }
            _ => panic!("expected Event"),
        }
    }

    #[test]
    fn parse_disconnect_command() {
        let cmd = Cmd::parse_line(r#"{"kind":"disconnect"}"#).unwrap();
        assert!(matches!(cmd, Cmd::Disconnect(_)));
    }

    #[test]
    fn parse_kill_command() {
        // G34.2d — `{"kind":"kill"}` is the operator-side panic button.
        let cmd = Cmd::parse_line(r#"{"kind":"kill"}"#).unwrap();
        assert!(matches!(cmd, Cmd::Kill(_)));
    }

    #[test]
    fn parse_kill_command_ignores_extra_fields() {
        // Future protocol fields (reason string, operator id, etc.) must
        // not break legacy parsers. Today the shim doesn't model them
        // but accepting the basic shape is the forward-compat contract.
        let cmd = Cmd::parse_line(r#"{"kind":"kill","reason":"client_consent_revoked"}"#).unwrap();
        assert!(matches!(cmd, Cmd::Kill(_)));
    }

    #[test]
    fn parse_rejects_empty_line() {
        assert!(matches!(Cmd::parse_line("   "), Err(ParseError::EmptyLine)));
    }

    #[test]
    fn parse_rejects_invalid_json() {
        assert!(matches!(
            Cmd::parse_line("{not json"),
            Err(ParseError::InvalidJson(_))
        ));
    }

    #[test]
    fn parse_rejects_unknown_kind() {
        let result = Cmd::parse_line(r#"{"kind":"frobnicate"}"#);
        match result {
            Err(ParseError::UnknownKind(k)) => assert_eq!(k, "frobnicate"),
            _ => panic!("expected UnknownKind"),
        }
    }

    #[test]
    fn parse_rejects_top_level_array() {
        assert!(matches!(Cmd::parse_line("[]"), Err(ParseError::NotObject)));
    }

    #[test]
    fn evt_hello_serializes_with_kind_tag() {
        let evt = Evt::Hello(EvtHello {
            shim_version: "klx-rdshim 0.1.0".into(),
            librustdesk_commit: "abcd1234".into(),
        });
        let line = evt.to_json_line();
        let parsed: serde_json::Value = serde_json::from_str(&line).unwrap();
        assert_eq!(parsed["kind"], "hello");
        assert_eq!(parsed["shim_version"], "klx-rdshim 0.1.0");
        assert_eq!(parsed["librustdesk_commit"], "abcd1234");
    }

    #[test]
    fn evt_error_serializes_correctly() {
        let evt = Evt::Error(EvtError {
            code: "not_implemented".into(),
            message: "librustdesk not linked in this build".into(),
        });
        let line = evt.to_json_line();
        let parsed: serde_json::Value = serde_json::from_str(&line).unwrap();
        assert_eq!(parsed["kind"], "error");
        assert_eq!(parsed["code"], "not_implemented");
    }

    #[test]
    fn evt_event_ack_uses_snake_case_kind() {
        let evt = Evt::EventAck(EvtEventAck {
            sequence: 42,
            status: "sent".into(),
        });
        let line = evt.to_json_line();
        let parsed: serde_json::Value = serde_json::from_str(&line).unwrap();
        assert_eq!(parsed["kind"], "event_ack");
        assert_eq!(parsed["sequence"], 42);
    }

    #[test]
    fn evt_disconnected_serializes_correctly() {
        let evt = Evt::Disconnected(EvtDisconnected {
            reason: "peer_closed".into(),
        });
        let line = evt.to_json_line();
        let parsed: serde_json::Value = serde_json::from_str(&line).unwrap();
        assert_eq!(parsed["kind"], "disconnected");
        assert_eq!(parsed["reason"], "peer_closed");
    }

    #[test]
    fn evt_cursor_position_serializes_with_kind_tag() {
        // G34.3+++++++++++++++ — wire format pin: the operator-side
        // consumer reads `kind == "cursor_position"` and `source`,
        // `x`, `y` at the top level (snake_case). Lock both the
        // discriminator and the field set so accidental renames break
        // here rather than at the Python parser.
        let evt = Evt::CursorPosition(EvtCursorPosition {
            source: "shim_last_send".into(),
            x: 640,
            y: 360,
        });
        let line = evt.to_json_line();
        let parsed: serde_json::Value = serde_json::from_str(&line).unwrap();
        assert_eq!(parsed["kind"], "cursor_position");
        assert_eq!(parsed["source"], "shim_last_send");
        assert_eq!(parsed["x"], 640);
        assert_eq!(parsed["y"], 360);
    }

    #[test]
    fn evt_cursor_position_round_trips() {
        // Confirm Deserialize is wired symmetrically with Serialize so
        // tests / fixtures can build Evt values from raw JSON.
        let line = r#"{"kind":"cursor_position","source":"peer_report","x":-12,"y":2048}"#;
        let evt: Evt = serde_json::from_str(line).unwrap();
        match evt {
            Evt::CursorPosition(c) => {
                assert_eq!(c.source, "peer_report");
                assert_eq!(c.x, -12);
                assert_eq!(c.y, 2048);
            }
            other => panic!("expected CursorPosition, got {other:?}"),
        }
    }
}
