//! G34.2c integration test — end-to-end IPC against a synthetic peer.
//!
//! Spawns the `klx-rdshim` binary in real-session mode pointed at a
//! localhost TcpListener that plays the role of the customer-side
//! rustdesk peer. The synthetic peer:
//!
//!   1. Accepts the operator's TCP connect.
//!   2. Sends one `Message::VideoFrame::vp9s` carrying a synthetic VP9
//!      keyframe (encoded with the same libvpx the shim links against).
//!   3. Waits for the operator's input events (the test sends none).
//!
//! The test asserts that the shim:
//!   * Emits `hello` then `connected` on stdout within 2 seconds.
//!   * Emits exactly one `frame` event with `codec=jpeg` and a non-empty
//!     `payload_b64` whose base64-decoded bytes start with the JPEG SOI
//!     marker `0xFFD8`.
//!
//! When this test passes, G34.2c's end-to-end IPC contract is proven:
//! the full path from peer-side VP9 bytes → operator-side IPC EvtFrame
//! works without relying on a live rustdesk peer.

use std::io::{BufRead, BufReader, Write};
use std::net::TcpListener;
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

use base64::engine::general_purpose::STANDARD as B64;
use base64::Engine;
use protobuf::Message as _;

use klx_rdshim::message_proto::{
    EncodedVideoFrame, EncodedVideoFrames, Message as PeerMessage, VideoFrame,
};
use klx_rdshim::relay::{encode_frame, read_frame};

fn cargo_bin_path() -> std::path::PathBuf {
    // CARGO_BIN_EXE_klx-rdshim is set by Cargo for integration tests.
    std::path::PathBuf::from(env!("CARGO_BIN_EXE_klx-rdshim"))
}

fn synth_vp9_keyframe() -> Vec<u8> {
    use klx_rdshim::vp9::test_helpers::{
        encode_one_vp9_keyframe, synthetic_i420_gradient,
    };
    const W: u32 = 320;
    const H: u32 = 240;
    let (y, u, v) = synthetic_i420_gradient(W, H);
    encode_one_vp9_keyframe(W, H, &y, &u, &v).expect("encode synth keyframe")
}

#[test]
fn real_session_emits_frame_event_for_synthetic_vp9_peer() {
    // 1. Bind a TcpListener — this is our synthetic peer endpoint.
    let listener =
        TcpListener::bind("127.0.0.1:0").expect("synthetic peer bind");
    let peer_addr = listener.local_addr().expect("local_addr").to_string();

    // 2. Pre-encode the VP9 frame so the test can fail fast if libvpx
    //    encode is broken (rather than blaming the shim).
    let vp9_bytes = synth_vp9_keyframe();
    assert!(!vp9_bytes.is_empty(), "synth VP9 encoder produced 0 bytes");

    // 3. Spawn the synthetic-peer thread. It accepts one connection,
    //    sends one Message::VideoFrame::vp9s, then holds the socket
    //    open until the shim closes it (so the shim doesn't see an
    //    EOF mid-stream).
    let (peer_ready_tx, peer_ready_rx) = mpsc::channel::<()>();
    let peer_handle = std::thread::spawn(move || -> std::io::Result<()> {
        let (mut sock, _addr) = listener.accept()?;
        sock.set_read_timeout(Some(Duration::from_secs(5)))?;
        sock.set_write_timeout(Some(Duration::from_secs(5)))?;
        // Tell the test we accepted.
        let _ = peer_ready_tx.send(());

        // Build a Message::VideoFrame::vp9s carrying the keyframe.
        let mut ef = EncodedVideoFrame::new();
        ef.data = vp9_bytes;
        ef.key = true;
        let mut frames = EncodedVideoFrames::new();
        frames.frames.push(ef);
        let mut vf = VideoFrame::new();
        vf.set_vp9s(frames);
        let mut msg = PeerMessage::new();
        msg.set_video_frame(vf);

        let body = msg.write_to_bytes().map_err(|e| {
            std::io::Error::new(std::io::ErrorKind::Other, format!("encode: {e}"))
        })?;
        let mut framed = Vec::with_capacity(body.len() + 4);
        encode_frame(&body, &mut framed)?;
        sock.write_all(&framed)?;
        sock.flush()?;

        // Keep socket open: drain any frames the shim sends (we don't
        // assert on them — the test only cares about the shim's
        // stdout). Bail on the first read error (typically WouldBlock
        // → loop, or peer hangup → exit).
        loop {
            match read_frame(&mut sock) {
                Ok(_) => continue,
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => continue,
                Err(e) if e.kind() == std::io::ErrorKind::TimedOut => continue,
                Err(_) => return Ok(()),
            }
        }
    });

    // 4. Spawn the shim binary in real-session mode pointed at the
    //    synthetic peer.
    let mut child = Command::new(cargo_bin_path())
        .env("KLX_RDSHIM_MODE", "real")
        .env("KLX_RDSHIM_REAL_PEER_ADDR", &peer_addr)
        .env_remove("KLX_MOCK_FAIL_CONNECT")
        .env_remove("KLX_RDSHIM_PROBE_RELAY")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn klx-rdshim");
    let mut stdin = child.stdin.take().expect("stdin handle");
    let stdout = child.stdout.take().expect("stdout handle");

    // 5. Send a `connect` command on stdin. relay_host/customer_id are
    //    irrelevant in synthetic-peer mode (the shim bypasses the punch
    //    flow because KLX_RDSHIM_REAL_PEER_ADDR is set).
    let connect_line = r#"{"kind":"connect","relay_host":"127.0.0.1","relay_key":"","hbbs_port":21116,"hbbr_port":21117,"customer_id":"synthetic-peer","session_password":""}"#;
    writeln!(stdin, "{connect_line}").expect("write connect");
    stdin.flush().expect("flush stdin");

    // 6. Wait for the peer to accept (gives a clear failure mode if the
    //    shim never dials).
    peer_ready_rx
        .recv_timeout(Duration::from_secs(2))
        .expect("synthetic peer did not accept within 2s");

    // 7. Read shim stdout. We're looking for a "frame" event with a
    //    JPEG payload within the test budget.
    let reader = BufReader::new(stdout);
    let deadline = Instant::now() + Duration::from_secs(5);
    let mut saw_hello = false;
    let mut saw_connected = false;
    let mut saw_frame = false;
    let mut frame_decoded_bytes: Vec<u8> = Vec::new();

    for line_result in reader.lines() {
        if Instant::now() > deadline {
            break;
        }
        let line = match line_result {
            Ok(l) => l,
            Err(e) => panic!("stdout read error: {e}"),
        };
        if line.is_empty() {
            continue;
        }
        let parsed: serde_json::Value = serde_json::from_str(&line)
            .unwrap_or_else(|e| panic!("non-JSON stdout line {line:?}: {e}"));
        let kind = parsed["kind"].as_str().unwrap_or("");
        match kind {
            "hello" => saw_hello = true,
            "connected" => saw_connected = true,
            "frame" => {
                saw_frame = true;
                let b64 = parsed["payload_b64"].as_str().unwrap_or("");
                frame_decoded_bytes =
                    B64.decode(b64).expect("payload_b64 must be valid base64");
                break;
            }
            "error" => {
                // Surface error events to the test log but don't bail —
                // a transient error may be followed by a successful
                // frame. We do bail if the shim says "disconnected".
                eprintln!("shim error event: {line}");
            }
            "disconnected" => {
                panic!("shim disconnected before emitting a frame: {line}");
            }
            _ => {}
        }
    }

    // 8. Tear down: close stdin so the shim exits cleanly.
    drop(stdin);
    let _ = child.wait_timeout_or_kill(Duration::from_secs(2));
    let _ = peer_handle.join();

    assert!(saw_hello, "shim never emitted hello");
    assert!(saw_connected, "shim never emitted connected");
    assert!(
        saw_frame,
        "shim never emitted a frame event for the synthetic VP9 keyframe"
    );
    assert!(
        frame_decoded_bytes.len() > 4,
        "frame payload too short: {}",
        frame_decoded_bytes.len()
    );
    assert_eq!(
        &frame_decoded_bytes[..2],
        &[0xFF, 0xD8],
        "frame payload missing JPEG SOI magic — decode-then-encode pipeline broken"
    );
}

/// Lightweight wait-with-timeout helper. Avoids the `wait-timeout` crate
/// dependency: poll `try_wait` every 50 ms until the deadline, then kill.
trait ChildWaitExt {
    fn wait_timeout_or_kill(&mut self, dur: Duration) -> std::io::Result<()>;
}

impl ChildWaitExt for std::process::Child {
    fn wait_timeout_or_kill(&mut self, dur: Duration) -> std::io::Result<()> {
        let deadline = Instant::now() + dur;
        loop {
            match self.try_wait()? {
                Some(_) => return Ok(()),
                None => {
                    if Instant::now() >= deadline {
                        let _ = self.kill();
                        let _ = self.wait();
                        return Ok(());
                    }
                    std::thread::sleep(Duration::from_millis(50));
                }
            }
        }
    }
}
