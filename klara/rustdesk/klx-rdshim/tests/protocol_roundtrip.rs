//! Integration-style tests that exercise the v0 protocol from the outside
//! of the crate. These mirror the conformance tests in
//! `infra/rustdesk_controller/tests/test_rdshim_ipc.py` so divergence
//! between Python and Rust shows up as a test failure on either side.

use klx_rdshim::ipc::{Cmd, Evt, EvtConnected, EvtFrame};
use klx_rdshim::{hello_payload, SHIM_VERSION};

#[test]
fn hello_payload_advertises_major_version_zero() {
    let h = hello_payload();
    assert!(h.shim_version.contains(SHIM_VERSION));
    // Python's SUPPORTED_MAJOR_VERSIONS is {"0"}; major must be the first
    // dot-separated component of the trailing whitespace-separated token.
    let token = h.shim_version.split_whitespace().last().unwrap();
    let major = token.split('.').next().unwrap();
    assert_eq!(major, "0");
}

#[test]
fn connect_command_round_trips_through_json() {
    let original = r#"{"kind":"connect","relay_host":"x","relay_key":"y","hbbs_port":21116,"hbbr_port":21117,"customer_id":"c","session_password":"p"}"#;
    let cmd = Cmd::parse_line(original).expect("parse");
    let re_encoded = match cmd {
        Cmd::Connect(c) => serde_json::to_string(&c).unwrap(),
        _ => panic!("wrong variant"),
    };
    // Re-encode and confirm all original fields survive.
    let parsed: serde_json::Value = serde_json::from_str(&re_encoded).unwrap();
    assert_eq!(parsed["relay_host"], "x");
    assert_eq!(parsed["hbbs_port"], 21116);
    assert_eq!(parsed["customer_id"], "c");
}

#[test]
fn evt_connected_kind_is_lowercase() {
    let line = Evt::Connected(EvtConnected {
        session_id: "K-1".into(),
        width: 1920,
        height: 1080,
    })
    .to_json_line();
    let parsed: serde_json::Value = serde_json::from_str(&line).unwrap();
    assert_eq!(parsed["kind"], "connected");
    assert_eq!(parsed["width"], 1920);
}

#[test]
fn evt_frame_uses_payload_b64_field_name() {
    // The Python parser expects `payload_b64` exactly — guard against
    // someone renaming the field on the Rust side.
    let line = Evt::Frame(EvtFrame {
        session_id: "K-1".into(),
        sequence: 17,
        width: 1920,
        height: 1080,
        codec: "jpeg".into(),
        payload_b64: "AAAA".into(),
        timestamp_ms: 1_718_178_501_023,
    })
    .to_json_line();
    let parsed: serde_json::Value = serde_json::from_str(&line).unwrap();
    assert!(parsed.get("payload_b64").is_some());
    assert!(parsed.get("payload").is_none(), "do not rename payload_b64");
}
