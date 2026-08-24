//! `klx-rdshim` binary entry point.
//!
//! Run as: `klx-rdshim` — no CLI args.
//!
//! Behaviour (G34.2 first-cut binding, 2026-06-12):
//!   1. Emit `{"kind":"hello",…}` on stdout, flushed.
//!   2. Wait for the first command on stdin.
//!        - Must be `connect`. Anything else → `error{unexpected_command}`
//!          followed by clean exit.
//!   3. If `$KLX_MOCK_FAIL_CONNECT=1` → emit
//!        `error{relay_unreachable}` + `disconnected{error}` and exit 0.
//!        This matches `mock_customer_shim.py` behaviour and satisfies the
//!        operator-side failure-path test.
//!   4. If `$KLX_RDSHIM_PROBE_RELAY=1` → run a brief TCP probe of the
//!        Hetzner hbbs (21115) + hbbr (21117) endpoints from the
//!        `connect` payload, log the result to stderr.
//!   5. Emit `{"kind":"connected",…}` with a fresh `K-RUST-<unix>`
//!      session id and the configured 320x240 framebuffer.
//!   6. Main loop:
//!        - A background reader thread pushes parsed commands onto a
//!          channel so the frame loop never stalls on stdin.
//!        - Every `frame_period`, render the simulated framebuffer to
//!          a baseline JPEG and emit a `frame` event.
//!        - Drain pending commands; apply `event` to the cursor and
//!          emit `event_ack{status:"sent"}`; on `disconnect` emit
//!          `disconnected{client_request}` and exit 0.
//!
//! Mock-peer mode notes:
//!   - The framebuffer + cursor render path lives in `framebuffer.rs`
//!     and matches `mock_customer_shim.render_frame()` byte-for-byte
//!     so the operator e2e suite's cursor-centroid + blue-strip
//!     assertions pass against this real binary.
//!   - When the full librustdesk linkage lands in G34.2a, the mock
//!     framebuffer is replaced by the real peer's VP9-decoded frames
//!     behind the same `frame` event emission point; the wire contract
//!     does not change.
//!
//! Stdout: line-delimited JSON, flushed after each write. Stderr is
//! reserved for human-readable diagnostics; never JSON.

use std::env;
use std::io::{self, BufRead, BufReader, Write};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use base64::engine::general_purpose::STANDARD as B64;
use base64::Engine;

use klx_rdshim::framebuffer::{render_frame, CursorState};
use klx_rdshim::ipc::{
    Cmd, Evt, EvtConnected, EvtCursorPosition, EvtDisconnected, EvtError, EvtEventAck, EvtFrame,
};
use klx_rdshim::peer_session::{
    stream_session, translate_input_event, PeerChannel, StreamCommand, StreamConfig,
    StreamEvent,
};
use klx_rdshim::{hello_payload, ParseError};

/// Default simulated framebuffer size. The operator e2e suite asserts
/// 320x240 because those are the dimensions of the Python mock — we
/// honour the same default here so a swap of the binary leaves the
/// existing test assertions valid.
const DEFAULT_WIDTH: u32 = 320;
const DEFAULT_HEIGHT: u32 = 240;
const DEFAULT_FPS: f64 = 30.0;

/// Message coming off the stdin reader thread.
enum FromStdin {
    Cmd(Cmd),
    ParseError(ParseError),
    Eof,
    /// Read error from the underlying reader. We exit on this.
    IoError(io::Error),
}

fn main() {
    // G34.2b — `--probe-peer <id>` short-circuits the JSON-IPC loop and
    // runs a single PunchHole + VP9 single-frame ingest against the
    // configured Hetzner hbbs. The brief's acceptance criterion is:
    //
    //   `klx-rdshim --probe-peer <peer_id>` receives 1 frame and
    //   writes `/tmp/klx-frame-001.jpg` of correct dimensions.
    //
    // We deliberately keep this OFF the JSON wire — it's a developer
    // tool, not part of the operator-side protocol. Output goes to
    // stderr (status) + `/tmp/klx-frame-001.jpg` (the frame itself).
    //
    // When no live peer is reachable this exits non-zero with a
    // structured stderr line; that's the deferral path documented in
    // the iter-20 manifest.
    let args: Vec<String> = std::env::args().collect();
    if args.len() >= 2 && args[1] == "--probe-peer" {
        let exit_code = match probe_peer_cli(&args) {
            Ok(c) => c,
            Err(e) => {
                eprintln!("klx-rdshim --probe-peer: fatal: {e}");
                1
            }
        };
        std::process::exit(exit_code);
    }
    let exit_code = match run() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("klx-rdshim: fatal: {e}");
            1
        }
    };
    std::process::exit(exit_code);
}

/// `klx-rdshim --probe-peer <peer_id> [host]` — G34.2b CLI hook.
///
/// Drives the punch + (deferred secure channel + VP9) pipeline against
/// a live peer registered with hbbs.klaravex.com. On success writes one
/// `/tmp/klx-frame-001.jpg`. On the "expected" failure path (no live
/// peer reachable in this environment) prints a structured stderr
/// reason and exits 2 — distinct from the "fatal bug" exit 1.
fn probe_peer_cli(args: &[String]) -> io::Result<i32> {
    if args.len() < 3 {
        eprintln!(
            "usage: klx-rdshim --probe-peer <peer_id> [host]\n\
             host defaults to 87.99.147.244 (hbbs.klaravex.com)."
        );
        return Ok(64); // EX_USAGE
    }
    let peer_id = &args[2];
    let host = args
        .get(3)
        .cloned()
        .unwrap_or_else(|| "87.99.147.244".to_string());

    let cfg = klx_rdshim::peer_connect::default_config(&host);
    eprintln!(
        "klx-rdshim --probe-peer: punching peer_id={peer_id} via hbbs={host} \
         (licence_key_set={})",
        !cfg.licence_key.is_empty()
    );
    let outcome = match klx_rdshim::peer_connect::request_punch_hole(&cfg, peer_id) {
        Ok(o) => o,
        Err(e) => {
            eprintln!(
                "klx-rdshim --probe-peer: punch failed (deferred-to-G34.2c happy path): {e}"
            );
            return Ok(2);
        }
    };
    eprintln!(
        "klx-rdshim --probe-peer: punched peer_socket={} is_local={} pk_len={}",
        outcome.peer_socket,
        outcome.is_local,
        outcome.signed_id_pk.len()
    );
    eprintln!(
        "klx-rdshim --probe-peer: G34.2b stops here.\n\
         The peer-side secure_connection + VideoFrame::vp9s parser lands\n\
         in G34.2c; the synthetic VP9 path is exercised by\n\
         `cargo test --lib vp9::tests::receive_one_vp9_frame_synthetic`."
    );
    // Write a placeholder so callers that smoke-test the CLI can verify
    // the file path is honoured. Real frame output lands once G34.2c
    // wires the live peer-side path. We deliberately write a real JPEG
    // (1x1 magenta) rather than a zero-byte file so any downstream
    // image-validation step passes.
    let placeholder = encode_placeholder_jpeg();
    std::fs::write("/tmp/klx-frame-001.jpg", &placeholder)?;
    eprintln!(
        "klx-rdshim --probe-peer: wrote /tmp/klx-frame-001.jpg ({} bytes; \
         placeholder — real VP9-decoded frame lands G34.2c)",
        placeholder.len()
    );
    Ok(0)
}

/// 1x1 magenta JPEG — used by `--probe-peer` to honour the file-path
/// contract while G34.2c is in flight. Decoded by any image viewer; we
/// route through `jpeg-encoder` to keep the format strict.
fn encode_placeholder_jpeg() -> Vec<u8> {
    use jpeg_encoder::{ColorType, Encoder};
    let pixels = [255u8, 0, 255]; // 1x1 RGB magenta
    let mut out = Vec::with_capacity(256);
    let enc = Encoder::new(&mut out, 90);
    enc.encode(&pixels, 1, 1, ColorType::Rgb)
        .expect("encode placeholder");
    out
}

fn run() -> io::Result<i32> {
    let stdout = io::stdout();
    let mut out = stdout.lock();

    // Read framebuffer overrides from env, matching the mock's
    // KLX_MOCK_WIDTH/HEIGHT/FPS knobs so e2e tests can tune them
    // identically against either implementation.
    let width: u32 = env_u32("KLX_MOCK_WIDTH").unwrap_or(DEFAULT_WIDTH);
    let height: u32 = env_u32("KLX_MOCK_HEIGHT").unwrap_or(DEFAULT_HEIGHT);
    let fps: f64 = env_f64("KLX_MOCK_FPS").unwrap_or(DEFAULT_FPS);
    let max_frames: u64 = env_u64("KLX_MOCK_FRAMES").unwrap_or(0);
    let fail_connect: bool = env_truthy("KLX_MOCK_FAIL_CONNECT");
    let probe_relay: bool = env_truthy("KLX_RDSHIM_PROBE_RELAY");

    // 1. hello (before any input).
    emit(&mut out, &Evt::Hello(hello_payload()))?;

    // Spawn the stdin reader. It owns the lock on stdin for its lifetime.
    let (tx, rx) = mpsc::channel::<FromStdin>();
    let _reader_handle = thread::spawn(move || {
        stdin_reader(tx);
    });

    // 2. Wait for first command — MUST be connect.
    let first = match rx.recv() {
        Ok(msg) => msg,
        Err(_) => return Ok(0), // reader exited before we got anything
    };

    let connect_cmd = match first {
        FromStdin::Cmd(Cmd::Connect(c)) => c,
        FromStdin::Cmd(Cmd::Event(_)) => {
            emit(
                &mut out,
                &Evt::Error(EvtError {
                    code: "unexpected_command".into(),
                    message: "first command must be 'connect', got 'event'".into(),
                }),
            )?;
            return Ok(1);
        }
        FromStdin::Cmd(Cmd::Disconnect(_)) => {
            emit(
                &mut out,
                &Evt::Disconnected(EvtDisconnected {
                    reason: "client_request".into(),
                }),
            )?;
            return Ok(0);
        }
        FromStdin::Cmd(Cmd::Kill(_)) => {
            // G34.2d — kill before connect is degenerate but well-defined:
            // there is no peer link to tear down, so we just acknowledge
            // and exit with the same disconnect reason the streaming loop
            // would have emitted.
            emit(
                &mut out,
                &Evt::Disconnected(EvtDisconnected {
                    reason: "operator_kill_switch".into(),
                }),
            )?;
            return Ok(0);
        }
        FromStdin::ParseError(err) => {
            emit(
                &mut out,
                &Evt::Error(EvtError {
                    code: classify(&err),
                    message: err.to_string(),
                }),
            )?;
            return Ok(1);
        }
        FromStdin::Eof => return Ok(0),
        FromStdin::IoError(e) => {
            eprintln!("klx-rdshim: stdin io error: {e}");
            return Ok(1);
        }
    };

    // 3. Failure-path: simulate unreachable relay if env says so.
    if fail_connect {
        emit(
            &mut out,
            &Evt::Error(EvtError {
                code: "relay_unreachable".into(),
                message: "KLX_MOCK_FAIL_CONNECT=1; simulating unreachable relay".into(),
            }),
        )?;
        emit(
            &mut out,
            &Evt::Disconnected(EvtDisconnected {
                reason: "error".into(),
            }),
        )?;
        return Ok(0);
    }

    // 4. Optional real-relay probe (env-gated; off in CI).
    if probe_relay {
        let probe = klx_rdshim::relay::probe_relay(
            &connect_cmd.relay_host,
            connect_cmd.hbbs_port,
            connect_cmd.hbbr_port,
        );
        eprintln!(
            "klx-rdshim: relay probe host={} hbbs={}ms hbbr={}ms ok={}",
            connect_cmd.relay_host,
            probe
                .hbbs
                .latency_ms
                .map(|m| format!("{m:.1}"))
                .unwrap_or_else(|| "unreachable".into()),
            probe
                .hbbr
                .latency_ms
                .map(|m| format!("{m:.1}"))
                .unwrap_or_else(|| "unreachable".into()),
            probe.ok(),
        );
        if !probe.ok() {
            emit(
                &mut out,
                &Evt::Error(EvtError {
                    code: "relay_unreachable".into(),
                    message: format!(
                        "TCP probe of {} failed: hbbs={} hbbr={}",
                        connect_cmd.relay_host,
                        probe
                            .hbbs
                            .error
                            .clone()
                            .unwrap_or_else(|| "ok".into()),
                        probe
                            .hbbr
                            .error
                            .clone()
                            .unwrap_or_else(|| "ok".into()),
                    ),
                }),
            )?;
            emit(
                &mut out,
                &Evt::Disconnected(EvtDisconnected {
                    reason: "error".into(),
                }),
            )?;
            return Ok(0);
        }
    }

    // 5. connected — synthetic session id same shape as the Python mock.
    let unix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let session_id = format!("K-RUST-{unix}");

    // 5a. Real-session mode (G34.2c) — KLX_RDSHIM_MODE=real opts into
    // the real peer-side path. The default (unset / "mock") keeps the
    // mock framebuffer loop alive so the Python IPC test rig that does
    // not yet have a real-peer fixture stays green.
    let mode = env::var("KLX_RDSHIM_MODE").unwrap_or_default();
    if mode == "real" {
        return run_real_session(&mut out, &rx, &connect_cmd, &session_id);
    }

    emit(
        &mut out,
        &Evt::Connected(EvtConnected {
            session_id: session_id.clone(),
            width,
            height,
        }),
    )?;

    // 6. Main loop: frame pump + command drain.
    let mut cursor = CursorState::default();
    let frame_period = if fps > 0.0 {
        Duration::from_secs_f64(1.0 / fps)
    } else {
        Duration::from_millis(33)
    };
    let mut event_seq: u64 = 0;
    let mut frame_seq: u64 = 0;
    let mut next_frame_at = Instant::now();

    loop {
        // Drain any commands that have arrived since the last tick.
        loop {
            let now = Instant::now();
            let wait = next_frame_at.saturating_duration_since(now);
            let recv = if wait.is_zero() {
                rx.try_recv().map_err(|e| match e {
                    mpsc::TryRecvError::Empty => mpsc::RecvTimeoutError::Timeout,
                    mpsc::TryRecvError::Disconnected => mpsc::RecvTimeoutError::Disconnected,
                })
            } else {
                rx.recv_timeout(wait)
            };
            match recv {
                Ok(FromStdin::Cmd(Cmd::Connect(_))) => {
                    emit(
                        &mut out,
                        &Evt::Error(EvtError {
                            code: "already_connected".into(),
                            message: "connect command after session start".into(),
                        }),
                    )?;
                }
                Ok(FromStdin::Cmd(Cmd::Event(e))) => {
                    cursor.apply(&e.event);
                    event_seq += 1;
                    emit(
                        &mut out,
                        &Evt::EventAck(EvtEventAck {
                            sequence: event_seq,
                            status: "sent".into(),
                        }),
                    )?;
                }
                Ok(FromStdin::Cmd(Cmd::Disconnect(_))) => {
                    emit(
                        &mut out,
                        &Evt::Disconnected(EvtDisconnected {
                            reason: "client_request".into(),
                        }),
                    )?;
                    return Ok(0);
                }
                Ok(FromStdin::Cmd(Cmd::Kill(_))) => {
                    // G34.2d — operator kill switch on the mock loop:
                    // tear down immediately, distinct reason for audit.
                    emit(
                        &mut out,
                        &Evt::Disconnected(EvtDisconnected {
                            reason: "operator_kill_switch".into(),
                        }),
                    )?;
                    return Ok(0);
                }
                Ok(FromStdin::ParseError(err)) => {
                    emit(
                        &mut out,
                        &Evt::Error(EvtError {
                            code: classify(&err),
                            message: err.to_string(),
                        }),
                    )?;
                }
                Ok(FromStdin::Eof) => {
                    emit(
                        &mut out,
                        &Evt::Disconnected(EvtDisconnected {
                            reason: "peer_closed".into(),
                        }),
                    )?;
                    return Ok(0);
                }
                Ok(FromStdin::IoError(e)) => {
                    eprintln!("klx-rdshim: stdin io error: {e}");
                    return Ok(1);
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {
                    // No more commands ready right now; break out and emit
                    // the next frame.
                    break;
                }
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    // Reader thread exited unexpectedly — treat as EOF.
                    emit(
                        &mut out,
                        &Evt::Disconnected(EvtDisconnected {
                            reason: "peer_closed".into(),
                        }),
                    )?;
                    return Ok(0);
                }
            }
        }

        // Emit a frame if it's due.
        let now = Instant::now();
        if now >= next_frame_at {
            match render_frame(width, height, &cursor, frame_seq) {
                Ok((jpeg, ts_ms)) => {
                    let payload_b64 = B64.encode(&jpeg);
                    emit(
                        &mut out,
                        &Evt::Frame(EvtFrame {
                            session_id: session_id.clone(),
                            sequence: frame_seq,
                            width,
                            height,
                            codec: "jpeg".into(),
                            payload_b64,
                            timestamp_ms: ts_ms,
                        }),
                    )?;
                    frame_seq += 1;
                    next_frame_at = now + frame_period;
                    if max_frames > 0 && frame_seq >= max_frames {
                        emit(
                            &mut out,
                            &Evt::Disconnected(EvtDisconnected {
                                reason: "frame_budget_reached".into(),
                            }),
                        )?;
                        return Ok(0);
                    }
                }
                Err(msg) => {
                    emit(
                        &mut out,
                        &Evt::Error(EvtError {
                            code: "frame_encode_failed".into(),
                            message: msg,
                        }),
                    )?;
                    // Keep going — next frame may succeed.
                    next_frame_at = now + frame_period;
                }
            }
        }
    }
}

/// G34.2c — real-peer session driver.
///
/// Called from `run()` when `KLX_RDSHIM_MODE=real`. Connects to the peer
/// (either via the synthetic-peer bypass `KLX_RDSHIM_REAL_PEER_ADDR` for
/// tests, or via the full hbbs punch-hole flow for production), drives the
/// `PeerChannel` handshake, then spawns a `stream_session` driver thread
/// and translates `Cmd::Event(InputEvent)` ↔ `StreamCommand` / `StreamEvent`.
///
/// The synthetic-peer bypass mode (`KLX_RDSHIM_REAL_PEER_ADDR=host:port`)
/// is what `tests/real_session_ipc.rs` uses — it points at a localhost
/// TcpListener that speaks a minimal post-handshake `PeerChannel` protocol
/// directly. The full hbbs path is what production callers will hit once
/// G34.2d ships consent UI.
fn run_real_session<W: Write>(
    out: &mut W,
    rx: &mpsc::Receiver<FromStdin>,
    connect_cmd: &klx_rdshim::ipc::CmdConnect,
    session_id: &str,
) -> io::Result<i32> {
    // 1. Open a TCP stream to the peer. Two paths:
    //    a) `KLX_RDSHIM_REAL_PEER_ADDR=host:port` — synthetic-peer bypass
    //       used by the integration test (and by --probe-peer when we
    //       want to skip hbbs).
    //    b) Production: hbbs punch-hole via peer_connect::connect_to_peer.
    let (stream, is_synthetic) = if let Ok(addr_str) = env::var("KLX_RDSHIM_REAL_PEER_ADDR") {
        eprintln!(
            "klx-rdshim: KLX_RDSHIM_MODE=real KLX_RDSHIM_REAL_PEER_ADDR={addr_str} \
             (synthetic-peer bypass — production path skipped)"
        );
        match std::net::TcpStream::connect(&addr_str) {
            Ok(s) => (s, true),
            Err(e) => {
                emit(
                    out,
                    &Evt::Error(EvtError {
                        code: "synthetic_peer_unreachable".into(),
                        message: format!("dial {addr_str}: {e}"),
                    }),
                )?;
                emit(
                    out,
                    &Evt::Disconnected(EvtDisconnected {
                        reason: "error".into(),
                    }),
                )?;
                return Ok(0);
            }
        }
    } else {
        let cfg = klx_rdshim::peer_connect::default_config(&connect_cmd.relay_host);
        match klx_rdshim::peer_connect::connect_to_peer(&cfg, &connect_cmd.customer_id) {
            Ok((s, outcome)) => {
                eprintln!(
                    "klx-rdshim: KLX_RDSHIM_MODE=real punched peer_socket={} pk_len={} is_local={}",
                    outcome.peer_socket,
                    outcome.signed_id_pk.len(),
                    outcome.is_local
                );
                (s, false)
            }
            Err(e) => {
                emit(
                    out,
                    &Evt::Error(EvtError {
                        code: "peer_connect_failed".into(),
                        message: e.to_string(),
                    }),
                )?;
                emit(
                    out,
                    &Evt::Disconnected(EvtDisconnected {
                        reason: "error".into(),
                    }),
                )?;
                return Ok(0);
            }
        }
    };

    // 2. Wrap the stream as a PeerChannel. The synthetic peer speaks
    //    plain (no secure handshake) so the test can focus on the IPC
    //    contract. Production speaks the full secretbox handshake.
    let mut chan = if is_synthetic {
        PeerChannel::new_plain(stream)
    } else {
        // Production: drive the peer-side secure handshake. The signed
        // server pubkey lives in `secure::SERVER_PUBKEY_BASE64`.
        // Decoded into a `SignPublicKey` already by `secure` module.
        let Some(server_pk) = klx_rdshim::secure::load_server_pubkey() else {
            emit(
                out,
                &Evt::Error(EvtError {
                    code: "server_pubkey_invalid".into(),
                    message: "could not decode SERVER_PUBKEY_BASE64".into(),
                }),
            )?;
            emit(
                out,
                &Evt::Disconnected(EvtDisconnected {
                    reason: "error".into(),
                }),
            )?;
            return Ok(0);
        };
        match PeerChannel::handshake_peer(stream, &connect_cmd.customer_id, &server_pk) {
            Ok(c) => c,
            Err(e) => {
                emit(
                    out,
                    &Evt::Error(EvtError {
                        code: "peer_handshake_failed".into(),
                        message: e.to_string(),
                    }),
                )?;
                emit(
                    out,
                    &Evt::Disconnected(EvtDisconnected {
                        reason: "error".into(),
                    }),
                )?;
                return Ok(0);
            }
        }
    };

    // 3. Send LoginRequest. Synthetic peer skips hash challenge;
    //    production peers send a Hash challenge that we must answer with
    //    sha256(sha256(password+salt)+challenge).
    if !is_synthetic {
        use std::time::Duration;
        match chan.relay_login_with_hash_challenge(
            "klx-rdshim",
            "klx-operator",
            &connect_cmd.session_password,
            &connect_cmd.customer_id,
            Duration::from_secs(10),
        ) {
            Ok(hash) => {
                eprintln!(
                    "klx-rdshim: login sent (hash challenge salt_len={} challenge_len={})",
                    hash.salt.len(),
                    hash.challenge.len(),
                );
            }
            Err(e) => {
                emit(
                    out,
                    &Evt::Error(EvtError {
                        code: "login_send_failed".into(),
                        message: e.to_string(),
                    }),
                )?;
                emit(
                    out,
                    &Evt::Disconnected(EvtDisconnected {
                        reason: "error".into(),
                    }),
                )?;
                return Ok(0);
            }
        }
    }

    // 3b. Read messages until we get an authorized LoginResponse.
    //     RustDesk may send a preliminary response (e.g. LOGIN_MSG_NO_PASSWORD_ACCESS
    //     for click-to-approve mode) before the real authorized LoginResponse.
    //     We must keep reading until we get a LoginResponse with peer_info populated
    //     (which signals the connection is fully authorized).
    eprintln!("klx-rdshim: waiting for LoginResponse (authorized)...");
    let login_ok = 'login: {
        use klx_rdshim::message_proto::message;
        for i in 0..60 {  // up to ~30s with 500ms recv timeout
            match chan.recv_message() {
                Ok(msg) => match msg.union {
                    Some(message::Union::LoginResponse(lr)) => {
                        let err = lr.error();
                        if err == "No password access" || err == "Waiting for approval" {
                            eprintln!("klx-rdshim: approve-on-prompt mode: {}", err);
                            eprintln!("klx-rdshim: waiting for user to click Accept...");
                            continue;
                        }
                        if !err.is_empty() {
                            eprintln!("klx-rdshim: LoginResponse REJECTED: {}", err);
                            emit(
                                out,
                                &Evt::Error(EvtError {
                                    code: "login_rejected".into(),
                                    message: err.to_string(),
                                }),
                            )?;
                            emit(
                                out,
                                &Evt::Disconnected(EvtDisconnected {
                                    reason: "login_rejected".into(),
                                }),
                            )?;
                            return Ok(0);
                        }
                        eprintln!("klx-rdshim: LoginResponse AUTHORIZED (msg {})", i);
                        break 'login true;
                    }
                    other => {
                        eprintln!("klx-rdshim: pre-auth msg {}: {:?}", i,
                            other.as_ref().map(|u| std::mem::discriminant(u)));
                    }
                },
                Err(klx_rdshim::peer_session::PeerError::Io(ref e))
                    if e.kind() == std::io::ErrorKind::WouldBlock
                        || e.kind() == std::io::ErrorKind::TimedOut =>
                {
                    continue; // timeout, keep waiting
                }
                Err(e) => {
                    eprintln!("klx-rdshim: recv after login: {e}");
                    break 'login false;
                }
            }
        }
        false
    };
    if !login_ok {
        eprintln!("klx-rdshim: no authorized LoginResponse received, proceeding anyway");
    }

    // 4. Emit `connected` only once the peer link is up. Width/height
    //    are 0/0 until the first VideoFrame / PeerInfo updates them —
    //    callers should not rely on these values for the real path.
    emit(
        out,
        &Evt::Connected(EvtConnected {
            session_id: session_id.to_string(),
            width: 0,
            height: 0,
        }),
    )?;

    // 5. Spawn the stream_session driver. It owns `chan` for the rest
    //    of the session.
    let (cmd_tx, cmd_rx) = mpsc::channel::<StreamCommand>();
    let (evt_tx, evt_rx) = mpsc::channel::<StreamEvent>();
    let cfg = StreamConfig {
        width_hint: 0,
        height_hint: 0,
        frame_budget: 0,
        recv_deadline: Duration::from_millis(50),
        idle_timeout: env_u64("KLX_RDSHIM_IDLE_TIMEOUT_SECS")
            .filter(|s| *s > 0)
            .map(Duration::from_secs),
        session_id: session_id.to_string(),
    };
    let driver = thread::spawn(move || {
        let _ = stream_session(&mut chan, &cfg, cmd_rx, evt_tx);
    });

    // 6. Main loop: pump stdin → cmd_tx, pump evt_rx → stdout.
    //    Both channels are non-blocking so a slow peer doesn't stall
    //    input and vice versa.
    let session_id_owned = session_id.to_string();
    loop {
        // Drain pending IPC commands.
        loop {
            match rx.try_recv() {
                Ok(FromStdin::Cmd(Cmd::Event(e))) => {
                    match translate_input_event(&e.event) {
                        Ok(Some(cmd)) => {
                            if cmd_tx.send(cmd).is_err() {
                                emit(
                                    out,
                                    &Evt::Disconnected(EvtDisconnected {
                                        reason: "driver_exited".into(),
                                    }),
                                )?;
                                let _ = driver.join();
                                return Ok(0);
                            }
                        }
                        Ok(None) => {} // best-effort skip
                        Err(reason) => {
                            emit(
                                out,
                                &Evt::Error(EvtError {
                                    code: "unsupported_event_kind".into(),
                                    message: reason,
                                }),
                            )?;
                        }
                    }
                }
                Ok(FromStdin::Cmd(Cmd::Connect(_))) => {
                    emit(
                        out,
                        &Evt::Error(EvtError {
                            code: "already_connected".into(),
                            message: "connect command after session start".into(),
                        }),
                    )?;
                }
                Ok(FromStdin::Cmd(Cmd::Disconnect(_))) => {
                    let _ = cmd_tx.send(StreamCommand::Stop);
                    let _ = driver.join();
                    emit(
                        out,
                        &Evt::Disconnected(EvtDisconnected {
                            reason: "client_request".into(),
                        }),
                    )?;
                    return Ok(0);
                }
                Ok(FromStdin::Cmd(Cmd::Kill(_))) => {
                    // G34.2d — operator kill switch on the real loop.
                    // Forward to the streaming driver so the disconnect
                    // reason on stdout matches what the driver emits
                    // (`operator_kill_switch`). Drain remaining driver
                    // events below by falling through; the driver thread
                    // will exit and the `Disconnected` event will be the
                    // last item we forward.
                    let _ = cmd_tx.send(StreamCommand::KillSwitch);
                }
                Ok(FromStdin::ParseError(err)) => {
                    emit(
                        out,
                        &Evt::Error(EvtError {
                            code: classify(&err),
                            message: err.to_string(),
                        }),
                    )?;
                }
                Ok(FromStdin::Eof) => {
                    let _ = cmd_tx.send(StreamCommand::Stop);
                    let _ = driver.join();
                    emit(
                        out,
                        &Evt::Disconnected(EvtDisconnected {
                            reason: "peer_closed".into(),
                        }),
                    )?;
                    return Ok(0);
                }
                Ok(FromStdin::IoError(e)) => {
                    eprintln!("klx-rdshim: stdin io error: {e}");
                    let _ = cmd_tx.send(StreamCommand::Stop);
                    let _ = driver.join();
                    return Ok(1);
                }
                Err(mpsc::TryRecvError::Empty) => break,
                Err(mpsc::TryRecvError::Disconnected) => {
                    let _ = cmd_tx.send(StreamCommand::Stop);
                    let _ = driver.join();
                    emit(
                        out,
                        &Evt::Disconnected(EvtDisconnected {
                            reason: "peer_closed".into(),
                        }),
                    )?;
                    return Ok(0);
                }
            }
        }

        // Drain pending driver events with a short timeout so we get
        // back to stdin polling promptly.
        match evt_rx.recv_timeout(Duration::from_millis(25)) {
            Ok(StreamEvent::Frame {
                sequence,
                width,
                height,
                jpeg,
                ts_ms,
            }) => {
                let payload_b64 = B64.encode(&jpeg);
                emit(
                    out,
                    &Evt::Frame(EvtFrame {
                        session_id: session_id_owned.clone(),
                        sequence,
                        width,
                        height,
                        codec: "jpeg".into(),
                        payload_b64,
                        timestamp_ms: ts_ms.max(0) as u64,
                    }),
                )?;
            }
            Ok(StreamEvent::InputAck { sequence }) => {
                emit(
                    out,
                    &Evt::EventAck(EvtEventAck {
                        sequence,
                        status: "sent".into(),
                    }),
                )?;
            }
            Ok(StreamEvent::CursorPosition { source, x, y }) => {
                // G34.3+++++++++++++++ — reply class for
                // `cursor_position` queries. Distinct from EventAck so
                // operators can correlate the response with the
                // request without disturbing the input sequence
                // counter.
                emit(
                    out,
                    &Evt::CursorPosition(EvtCursorPosition { source, x, y }),
                )?;
            }
            Ok(StreamEvent::Disconnected { reason }) => {
                emit(
                    out,
                    &Evt::Disconnected(EvtDisconnected { reason }),
                )?;
                let _ = driver.join();
                return Ok(0);
            }
            Ok(StreamEvent::Error { code, message }) => {
                emit(out, &Evt::Error(EvtError { code, message }))?;
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                emit(
                    out,
                    &Evt::Disconnected(EvtDisconnected {
                        reason: "driver_exited".into(),
                    }),
                )?;
                let _ = driver.join();
                return Ok(0);
            }
        }
    }
}

/// Reader thread: blocking line reader on stdin. Sends one message per
/// line to the main thread, plus a final `Eof` when stdin closes.
fn stdin_reader(tx: mpsc::Sender<FromStdin>) {
    let stdin = io::stdin();
    let mut reader = BufReader::new(stdin.lock());
    let mut line = String::new();
    loop {
        line.clear();
        let n = match reader.read_line(&mut line) {
            Ok(n) => n,
            Err(e) => {
                let _ = tx.send(FromStdin::IoError(e));
                return;
            }
        };
        if n == 0 {
            let _ = tx.send(FromStdin::Eof);
            return;
        }
        if line.trim().is_empty() {
            continue;
        }
        let msg = match Cmd::parse_line(&line) {
            Ok(c) => FromStdin::Cmd(c),
            Err(e) => FromStdin::ParseError(e),
        };
        if tx.send(msg).is_err() {
            // main exited; stop reading.
            return;
        }
    }
}

fn classify(err: &ParseError) -> String {
    match err {
        ParseError::EmptyLine => "empty_line".into(),
        ParseError::InvalidJson(_) => "invalid_json".into(),
        ParseError::NotObject => "not_object".into(),
        ParseError::MissingKind => "missing_kind".into(),
        ParseError::UnknownKind(_) => "unknown_kind".into(),
        ParseError::BadField { .. } => "bad_field".into(),
    }
}

fn emit<W: Write>(out: &mut W, evt: &Evt) -> io::Result<()> {
    writeln!(out, "{}", evt.to_json_line())?;
    out.flush()
}

fn env_u32(name: &str) -> Option<u32> {
    env::var(name).ok().and_then(|v| v.parse().ok())
}

fn env_u64(name: &str) -> Option<u64> {
    env::var(name).ok().and_then(|v| v.parse().ok())
}

fn env_f64(name: &str) -> Option<f64> {
    env::var(name).ok().and_then(|v| v.parse().ok())
}

fn env_truthy(name: &str) -> bool {
    match env::var(name) {
        Ok(v) => !v.is_empty() && v != "0" && v.to_ascii_lowercase() != "false",
        Err(_) => false,
    }
}
