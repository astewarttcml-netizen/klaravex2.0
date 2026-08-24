//! RustDesk relay client — rendezvous protocol (G34.2a checkpoint 1).
//!
//! This module speaks the rustdesk rendezvous protocol against the live
//! Hetzner hbbs server at `87.99.147.244`. The actual rustdesk port layout
//! is:
//!
//!   * **TCP 21115** — hbbs "extra port for NAT test" (listener2).
//!     Accepts `TestNatRequest` (round-trip echo of outbound port) and
//!     `OnlineRequest` (batch online-status query for a list of peer IDs).
//!     These are the cheapest verifiable round-trips against a hbbs
//!     instance — no key exchange, no key registration, instant reply.
//!   * **TCP 21116** — hbbs main rendezvous TCP. Accepts `PunchHoleRequest`
//!     (operator-side "I want to talk to peer X"), `RequestRelay`,
//!     `RelayResponse`, etc. Replies with `PunchHoleResponse`.
//!   * **UDP 21116** — hbbs main rendezvous UDP. The primary path for
//!     `RegisterPeer` peer→server heartbeats. NOT used in this checkpoint
//!     — UDP heartbeats need the full RegisterPk + key-exchange flow to be
//!     useful, which is checkpoint 2.
//!   * **TCP 21117** — hbbr relay (out of scope for this module).
//!
//! Wire framing is the rustdesk varint length prefix from
//! `hbb_common::bytes_codec::BytesCodec`. Bottom 2 bits of the first
//! header byte encode the header size (0–3 → 1–4 bytes total). The
//! remaining bits, little-endian, are the payload length. Payload is the
//! raw `RendezvousMessage` protobuf bytes.
//!
//! Public API (G34.2a checkpoint 1):
//!
//!   * `probe_endpoint` / `probe_relay` — unchanged TCP reachability probe.
//!     Still used by the main loop when `KLX_RDSHIM_PROBE_RELAY=1`.
//!   * `RendezvousClient::register_peer(peer_id)` — handshake the hbbs NAT
//!     test port (21115). Returns `RegisterPeerInfo` containing the
//!     non-zero outbound port the server echoed back. **This is not yet a
//!     real `RegisterPeer` UDP heartbeat** — that arrives in checkpoint 2
//!     once we have the Noise XK pubkey wired through. The unit of work
//!     this checkpoint validates is: "we can send a properly-framed
//!     protobuf message to the live relay and parse its reply".
//!   * `RendezvousClient::punch_hole(target_peer_id)` — send a
//!     `PunchHoleRequest` to the main rendezvous TCP port. Returns
//!     `PunchHoleOutcome`, which is one of:
//!       - `Failure { kind, message }` — server returned a `failure` enum
//!         in `PunchHoleResponse`. Includes `ID_NOT_EXIST` for unknown
//!         peers and `OFFLINE` for registered-but-offline peers.
//!       - `RelayPath { relay_server, .. }` — server told us to fall back
//!         to a hbbr relay. This is what we expect for an unknown peer in
//!         some hbbs configurations (the server may route to relay rather
//!         than rejecting outright).
//!       - `Direct { socket_addr, .. }` — server gave us the peer's
//!         public socket address for direct UDP punch.
//!       - `Timeout` — no reply within the read deadline.
//!
//! All TCP I/O is synchronous (`std::net::TcpStream`). The shim is single-
//! peer per process; we do not need Tokio. Read/write deadlines are
//! explicit.

use std::io::{self, Read, Write};
use std::net::{SocketAddr, TcpStream, ToSocketAddrs};
use std::time::{Duration, Instant};

use protobuf::Message as _;

use crate::rendezvous_proto::{
    punch_hole_response, rendezvous_message, PunchHoleRequest, PunchHoleResponse,
    RendezvousMessage, TestNatRequest,
};

/// Default rustdesk-server port layout. Matches `hbb_common::config`.
pub const HBBS_NAT_PORT: u16 = 21115;
pub const HBBS_MAIN_PORT: u16 = 21116;
pub const HBBR_PORT: u16 = 21117;

// ---------------------------------------------------------------------------
// Probe (unchanged from G34.2 first cut)
// ---------------------------------------------------------------------------

/// Result of probing one (host, port) socket.
#[derive(Debug, Clone)]
pub struct ProbeResult {
    pub host: String,
    pub port: u16,
    pub reachable: bool,
    pub latency_ms: Option<f64>,
    pub error: Option<String>,
}

/// Aggregate probe result for the relay endpoints.
#[derive(Debug, Clone)]
pub struct RelayProbe {
    pub hbbs: ProbeResult,
    pub hbbr: ProbeResult,
}

impl RelayProbe {
    /// Returns true iff BOTH endpoints succeeded.
    pub fn ok(&self) -> bool {
        self.hbbs.reachable && self.hbbr.reachable
    }
}

/// Probe a single TCP endpoint with the given timeout. Never panics.
pub fn probe_endpoint(host: &str, port: u16, timeout: Duration) -> ProbeResult {
    let addr_str = format!("{host}:{port}");
    let socket_addrs: Vec<SocketAddr> = match addr_str.to_socket_addrs() {
        Ok(it) => it.collect(),
        Err(e) => {
            return ProbeResult {
                host: host.into(),
                port,
                reachable: false,
                latency_ms: None,
                error: Some(format!("dns: {e}")),
            };
        }
    };
    if socket_addrs.is_empty() {
        return ProbeResult {
            host: host.into(),
            port,
            reachable: false,
            latency_ms: None,
            error: Some("no addresses resolved".into()),
        };
    }
    let start = Instant::now();
    for sa in &socket_addrs {
        match TcpStream::connect_timeout(sa, timeout) {
            Ok(stream) => {
                let lat_ms = start.elapsed().as_secs_f64() * 1000.0;
                drop(stream);
                return ProbeResult {
                    host: host.into(),
                    port,
                    reachable: true,
                    latency_ms: Some(lat_ms),
                    error: None,
                };
            }
            Err(e) => {
                if e.kind() == io::ErrorKind::TimedOut {
                    continue;
                }
                let _ = e;
            }
        }
    }
    ProbeResult {
        host: host.into(),
        port,
        reachable: false,
        latency_ms: None,
        error: Some("all addresses failed".into()),
    }
}

/// Probe both hbbs (TCP 21115) and hbbr (TCP 21117) on the given host.
pub fn probe_relay(host: &str, hbbs_id_port: u16, hbbr_port: u16) -> RelayProbe {
    let timeout = Duration::from_millis(3000);
    RelayProbe {
        hbbs: probe_endpoint(host, hbbs_id_port, timeout),
        hbbr: probe_endpoint(host, hbbr_port, timeout),
    }
}

// ---------------------------------------------------------------------------
// Wire framing — rustdesk BytesCodec varint length prefix.
// ---------------------------------------------------------------------------

/// Maximum frame payload size we'll accept from the server. Real
/// rendezvous replies are < 2 KB; we cap at 256 KB to match
/// hbb_common::bytes_codec's preallocation guard.
pub const MAX_FRAME_BYTES: usize = 256 * 1024;

/// Encode `data` as a rustdesk BytesCodec frame and append to `out`.
/// Bottom 2 bits of the first byte encode the header size (0–3 → 1–4
/// total header bytes). Remaining bits, little-endian, are the payload
/// length. Mirrors `hbb_common::bytes_codec::BytesCodec::encode`.
pub fn encode_frame(data: &[u8], out: &mut Vec<u8>) -> io::Result<()> {
    let n = data.len();
    if n <= 0x3F {
        out.push((n << 2) as u8);
    } else if n <= 0x3FFF {
        let v = ((n << 2) as u16) | 0x1;
        out.extend_from_slice(&v.to_le_bytes());
    } else if n <= 0x3FFFFF {
        let v = ((n << 2) as u32) | 0x2;
        out.push((v & 0xFF) as u8);
        out.push(((v >> 8) & 0xFF) as u8);
        out.push(((v >> 16) & 0xFF) as u8);
    } else if n <= 0x3FFFFFFF {
        let v = ((n << 2) as u32) | 0x3;
        out.extend_from_slice(&v.to_le_bytes());
    } else {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "frame too large",
        ));
    }
    out.extend_from_slice(data);
    Ok(())
}

/// Read one complete rustdesk BytesCodec frame from `stream`. Returns the
/// payload bytes (no header). Honors the stream's existing read timeout.
pub fn read_frame(stream: &mut TcpStream) -> io::Result<Vec<u8>> {
    // Header: read 1 byte first so we know how many more bytes the length
    // prefix takes.
    let mut head0 = [0u8; 1];
    stream.read_exact(&mut head0)?;
    let head_len = ((head0[0] & 0x3) + 1) as usize;
    let mut rest = vec![0u8; head_len - 1];
    if !rest.is_empty() {
        stream.read_exact(&mut rest)?;
    }
    let mut n: usize = head0[0] as usize;
    if head_len > 1 {
        n |= (rest[0] as usize) << 8;
    }
    if head_len > 2 {
        n |= (rest[1] as usize) << 16;
    }
    if head_len > 3 {
        n |= (rest[2] as usize) << 24;
    }
    n >>= 2;
    if n == 0 {
        return Ok(Vec::new());
    }
    if n > MAX_FRAME_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!("frame too large: {n} > {MAX_FRAME_BYTES}"),
        ));
    }
    let mut payload = vec![0u8; n];
    stream.read_exact(&mut payload)?;
    Ok(payload)
}

// ---------------------------------------------------------------------------
// RendezvousClient — high-level API
// ---------------------------------------------------------------------------

/// Configuration for a `RendezvousClient` session.
#[derive(Debug, Clone)]
pub struct RendezvousConfig {
    /// Hostname or IPv4 of the hbbs server (e.g. `"87.99.147.244"`).
    pub host: String,
    /// TCP port for the NAT-test listener (21115 by default).
    pub nat_port: u16,
    /// TCP port for the main rendezvous listener (21116 by default).
    pub main_port: u16,
    /// Per-operation TCP connect/read timeout.
    pub timeout: Duration,
    /// Optional `licence_key` to pass in `PunchHoleRequest`. The Klaravex
    /// Hetzner hbbs is configured with `--key D7BrbrWQDes...` and rejects
    /// PunchHole requests whose `licence_key` field does not match the
    /// configured value (see
    /// `vendor/rustdesk-server/src/rendezvous_server.rs:690`). On
    /// checkpoint 2 we default this to
    /// [`crate::secure::SERVER_PUBKEY_BASE64`] so live PunchHole tests
    /// pass; callers running against an open relay can `with_licence_key("")`
    /// to opt out.
    pub licence_key: String,
}

impl RendezvousConfig {
    /// Sensible defaults for the Klaravex Hetzner relay. Includes the
    /// known production licence key so PunchHole succeeds out of the
    /// box. Tests and tools that need the empty-key behaviour should
    /// chain `.with_licence_key("")`.
    pub fn for_host(host: impl Into<String>) -> Self {
        Self {
            host: host.into(),
            nat_port: HBBS_NAT_PORT,
            main_port: HBBS_MAIN_PORT,
            timeout: Duration::from_millis(5000),
            licence_key: crate::secure::SERVER_PUBKEY_BASE64.to_string(),
        }
    }

    /// Override the `licence_key` field. Pass `""` to send no key
    /// (matches checkpoint-1 behaviour, useful against an open relay or
    /// to confirm `LICENSE_MISMATCH` is being returned correctly).
    pub fn with_licence_key(mut self, key: impl Into<String>) -> Self {
        self.licence_key = key.into();
        self
    }
}

/// Information returned from a successful "register peer" exchange.
///
/// In checkpoint 1, the registration is implemented as a `TestNatRequest`
/// against TCP 21115, which returns a `TestNatResponse { port: <our
/// outbound port> }`. The non-zero `outbound_port` proves we round-tripped
/// a proto message through the live hbbs. The `peer_id` is the local ID
/// our caller passed in — the actual server-assigned ID only exists once
/// a full `RegisterPk` succeeds on UDP 21116, which is checkpoint 2.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RegisterPeerInfo {
    pub peer_id: String,
    pub outbound_port: u16,
    pub server_serial: i32,
}

/// Result of a `punch_hole` call.
#[derive(Debug, Clone)]
pub enum PunchHoleOutcome {
    /// Server returned a `failure` enum value in PunchHoleResponse.
    Failure { kind: PunchHoleFailure, message: String },
    /// Server told us to fall back to a relay server. The string is the
    /// relay host:port (or empty if the server's default relay applies).
    RelayPath { relay_server: String, has_pk: bool },
    /// Server gave us a direct socket_addr for the peer.
    Direct { socket_addr_len: usize, has_pk: bool, relay_server: String },
    /// No reply within the configured timeout.
    Timeout,
}

/// Subset of `punch_hole_response::Failure` we surface to the caller. The
/// numeric values match the protobuf enum.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PunchHoleFailure {
    IdNotExist,
    Offline,
    LicenseMismatch,
    LicenseOveruse,
    Other(i32),
}

impl PunchHoleFailure {
    fn from_proto(f: punch_hole_response::Failure) -> Self {
        match f {
            punch_hole_response::Failure::ID_NOT_EXIST => Self::IdNotExist,
            punch_hole_response::Failure::OFFLINE => Self::Offline,
            punch_hole_response::Failure::LICENSE_MISMATCH => Self::LicenseMismatch,
            punch_hole_response::Failure::LICENSE_OVERUSE => Self::LicenseOveruse,
        }
    }
}

/// Live client for the hbbs rendezvous protocol.
#[derive(Debug, Clone)]
pub struct RendezvousClient {
    cfg: RendezvousConfig,
}

impl RendezvousClient {
    pub fn new(cfg: RendezvousConfig) -> Self {
        Self { cfg }
    }

    /// Open a TCP stream to `host:port` with the configured timeout, and
    /// set read/write deadlines so a hung server can't stall us forever.
    fn dial(&self, port: u16) -> io::Result<TcpStream> {
        let addr_str = format!("{}:{}", self.cfg.host, port);
        let mut last_err: Option<io::Error> = None;
        for sa in addr_str.to_socket_addrs()? {
            match TcpStream::connect_timeout(&sa, self.cfg.timeout) {
                Ok(s) => {
                    s.set_read_timeout(Some(self.cfg.timeout))?;
                    s.set_write_timeout(Some(self.cfg.timeout))?;
                    s.set_nodelay(true)?;
                    return Ok(s);
                }
                Err(e) => last_err = Some(e),
            }
        }
        Err(last_err.unwrap_or_else(|| {
            io::Error::new(io::ErrorKind::NotFound, "no socket addresses resolved")
        }))
    }

    /// Register the given peer ID against the live hbbs.
    ///
    /// **Checkpoint-1 semantics:** sends `TestNatRequest { serial: 0 }`
    /// over TCP to `nat_port` (21115) and waits for `TestNatResponse`.
    /// A success means the relay is alive AND speaks the rustdesk wire
    /// protocol — the operator-side prerequisite for a real session.
    /// The full `RegisterPeer` UDP heartbeat lands in checkpoint 2.
    pub fn register_peer(&self, peer_id: &str) -> io::Result<RegisterPeerInfo> {
        let mut stream = self.dial(self.cfg.nat_port)?;

        let mut msg_out = RendezvousMessage::new();
        msg_out.set_test_nat_request(TestNatRequest {
            serial: 0,
            ..Default::default()
        });
        let body = msg_out
            .write_to_bytes()
            .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("encode: {e}")))?;
        let mut frame = Vec::with_capacity(body.len() + 4);
        encode_frame(&body, &mut frame)?;
        stream.write_all(&frame)?;
        stream.flush()?;

        let reply = read_frame(&mut stream)?;
        let msg_in = RendezvousMessage::parse_from_bytes(&reply)
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, format!("decode: {e}")))?;
        let (port, serial) = match msg_in.union {
            Some(rendezvous_message::Union::TestNatResponse(r)) => {
                let serial = r.cu.as_ref().map(|cu| cu.serial).unwrap_or(0);
                (r.port, serial)
            }
            other => {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!(
                        "expected TestNatResponse, got: {:?}",
                        other.map(|v| std::mem::discriminant(&v))
                    ),
                ));
            }
        };
        if port <= 0 || port > u16::MAX as i32 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("server returned non-routable port: {port}"),
            ));
        }
        Ok(RegisterPeerInfo {
            peer_id: peer_id.to_string(),
            outbound_port: port as u16,
            server_serial: serial,
        })
    }

    /// Initiate a punch-hole against the target peer ID.
    ///
    /// Sends `PunchHoleRequest { id: target_peer_id, conn_type: DEFAULT_CONN }`
    /// over TCP to `main_port` (21116) and parses `PunchHoleResponse`. For
    /// unknown target IDs the server replies with `failure: ID_NOT_EXIST`.
    /// For known-but-offline peers it returns `failure: OFFLINE`.
    pub fn punch_hole(&self, target_peer_id: &str) -> io::Result<PunchHoleOutcome> {
        let mut stream = self.dial(self.cfg.main_port)?;

        let mut req = PunchHoleRequest::new();
        req.id = target_peer_id.to_string();
        req.version = format!("klx-rdshim/{}", crate::SHIM_VERSION);
        if !self.cfg.licence_key.is_empty() {
            req.licence_key = self.cfg.licence_key.clone();
        }
        let mut msg_out = RendezvousMessage::new();
        msg_out.set_punch_hole_request(req);
        let body = msg_out
            .write_to_bytes()
            .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("encode: {e}")))?;
        let mut frame = Vec::with_capacity(body.len() + 4);
        encode_frame(&body, &mut frame)?;
        stream.write_all(&frame)?;
        stream.flush()?;

        let reply = match read_frame(&mut stream) {
            Ok(b) => b,
            Err(e)
                if e.kind() == io::ErrorKind::WouldBlock
                    || e.kind() == io::ErrorKind::TimedOut =>
            {
                return Ok(PunchHoleOutcome::Timeout)
            }
            Err(e) => return Err(e),
        };
        let msg_in = RendezvousMessage::parse_from_bytes(&reply)
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, format!("decode: {e}")))?;
        let phr: PunchHoleResponse = match msg_in.union {
            Some(rendezvous_message::Union::PunchHoleResponse(r)) => r,
            Some(rendezvous_message::Union::RelayResponse(rr)) => {
                // Some hbbs configurations short-circuit to a relay
                // response (notably when always-use-relay is set or
                // when the requested peer is known via a relay-only
                // entry). Surface this as RelayPath.
                return Ok(PunchHoleOutcome::RelayPath {
                    relay_server: rr.relay_server.clone(),
                    has_pk: matches!(
                        rr.union,
                        Some(crate::rendezvous_proto::relay_response::Union::Pk(_))
                    ),
                });
            }
            other => {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!(
                        "expected PunchHoleResponse, got: {:?}",
                        other.map(|v| std::mem::discriminant(&v))
                    ),
                ));
            }
        };
        // Failure enum is the default ID_NOT_EXIST (0) when no explicit
        // failure was set. We disambiguate by checking other_failure /
        // relay_server / socket_addr.
        let failure = phr.failure.enum_value_or_default();
        let has_relay = !phr.relay_server.is_empty();
        let has_direct = !phr.socket_addr.is_empty();
        let has_pk = !phr.pk.is_empty();
        let other_failure = phr.other_failure.clone();

        if has_direct {
            return Ok(PunchHoleOutcome::Direct {
                socket_addr_len: phr.socket_addr.len(),
                has_pk,
                relay_server: phr.relay_server.clone(),
            });
        }
        if has_relay {
            return Ok(PunchHoleOutcome::RelayPath {
                relay_server: phr.relay_server.clone(),
                has_pk,
            });
        }
        // No direct + no relay → failure case.
        let kind = PunchHoleFailure::from_proto(failure);
        let message = if !other_failure.is_empty() {
            other_failure
        } else {
            format!("failure: {failure:?}")
        };
        Ok(PunchHoleOutcome::Failure { kind, message })
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    // Reachability tests — no network needed beyond DNS.
    #[test]
    fn probe_unreachable_returns_error() {
        // 192.0.2.0/24 is TEST-NET-1 — guaranteed unreachable per RFC5737.
        let res = probe_endpoint("192.0.2.1", 1, Duration::from_millis(500));
        assert!(!res.reachable);
        assert_eq!(res.host, "192.0.2.1");
    }

    #[test]
    fn probe_bad_host_returns_dns_error() {
        let res = probe_endpoint(
            "definitely-not-a-real-host.klaravex.invalid",
            21115,
            Duration::from_millis(500),
        );
        assert!(!res.reachable);
        assert!(res.error.is_some());
    }

    // Frame codec round-trips. These mirror upstream
    // hbb_common::bytes_codec tests so we know we're wire-compatible.
    #[test]
    fn frame_codec_small() {
        let payload = vec![1u8; 0x3F];
        let mut buf = Vec::new();
        encode_frame(&payload, &mut buf).unwrap();
        assert_eq!(buf.len(), 0x3F + 1);
        assert_eq!(buf[0], (0x3F << 2) as u8);
        assert_eq!(&buf[1..], &payload[..]);
    }

    #[test]
    fn frame_codec_medium() {
        let payload = vec![2u8; 0x3F + 1];
        let mut buf = Vec::new();
        encode_frame(&payload, &mut buf).unwrap();
        assert_eq!(buf.len(), 0x3F + 1 + 2);
        assert_eq!(buf[0] & 0x3, 0x1);
    }

    #[test]
    fn frame_codec_large() {
        let payload = vec![3u8; 0x3FFF + 1];
        let mut buf = Vec::new();
        encode_frame(&payload, &mut buf).unwrap();
        // Three-byte header.
        assert_eq!(buf[0] & 0x3, 0x2);
        assert_eq!(buf.len(), payload.len() + 3);
    }

    // Live-relay tests. Gated behind KLX_LIVE_RELAY=1 so CI without
    // internet doesn't break. Run manually:
    //   KLX_LIVE_RELAY=1 cargo test --release register_peer_live -- --nocapture
    fn live_enabled() -> bool {
        std::env::var("KLX_LIVE_RELAY")
            .map(|v| !v.is_empty() && v != "0")
            .unwrap_or(false)
    }

    const LIVE_HOST: &str = "87.99.147.244";

    #[test]
    fn register_peer_live() {
        if !live_enabled() {
            eprintln!("register_peer_live: skipped (set KLX_LIVE_RELAY=1 to enable)");
            return;
        }
        let client = RendezvousClient::new(RendezvousConfig::for_host(LIVE_HOST));
        let info = client
            .register_peer("klx-test-peer-001")
            .expect("register_peer against live hbbs");
        eprintln!(
            "register_peer_live OK: peer_id={} outbound_port={} server_serial={}",
            info.peer_id, info.outbound_port, info.server_serial
        );
        assert_eq!(info.peer_id, "klx-test-peer-001");
        assert!(
            info.outbound_port > 0,
            "expected non-zero outbound port from hbbs, got {}",
            info.outbound_port
        );
    }

    #[test]
    fn punch_hole_unknown_peer_live() {
        if !live_enabled() {
            eprintln!("punch_hole_unknown_peer_live: skipped (set KLX_LIVE_RELAY=1 to enable)");
            return;
        }
        let client = RendezvousClient::new(RendezvousConfig::for_host(LIVE_HOST));
        let outcome = client
            .punch_hole("klx-nonexistent-peer-zzzz")
            .expect("punch_hole against live hbbs");
        eprintln!("punch_hole_unknown_peer_live outcome: {outcome:?}");
        // Unknown target → either explicit ID_NOT_EXIST failure OR a
        // relay path (some hbbs configs route unknowns to relay). Both
        // are acceptable: what we're proving is that the relay PARSED
        // our request and produced a structured reply.
        match outcome {
            PunchHoleOutcome::Failure { kind, .. } => {
                // The Klaravex Hetzner relay is configured with a key, so
                // it will reply LICENSE_MISMATCH to any request whose
                // `licence_key` field is empty — that's the same proof
                // that the server parsed our protobuf and produced a
                // structured rejection. ID_NOT_EXIST + OFFLINE are also
                // valid for relays without a configured key.
                assert!(
                    matches!(
                        kind,
                        PunchHoleFailure::IdNotExist
                            | PunchHoleFailure::Offline
                            | PunchHoleFailure::LicenseMismatch
                            | PunchHoleFailure::LicenseOveruse
                    ),
                    "unexpected failure kind for unknown peer: {kind:?}"
                );
            }
            PunchHoleOutcome::RelayPath { .. } => {
                // Acceptable — server fell back to relay.
            }
            PunchHoleOutcome::Direct { .. } => {
                panic!("hbbs returned Direct path for a peer we never registered");
            }
            PunchHoleOutcome::Timeout => {
                panic!("hbbs timed out on a PunchHoleRequest for unknown peer");
            }
        }
    }

    #[test]
    fn punch_hole_offline_target_live() {
        if !live_enabled() {
            eprintln!("punch_hole_offline_target_live: skipped (set KLX_LIVE_RELAY=1 to enable)");
            return;
        }
        // We don't have a known-but-offline peer to target. The closest
        // proxy is a second unknown-id call from a different syntactic
        // shape (numeric-looking) — both should produce a structured
        // failure or relay-path reply. This guards against the server
        // crashing on the second connect.
        let client = RendezvousClient::new(RendezvousConfig::for_host(LIVE_HOST));
        let outcome = client
            .punch_hole("999999999")
            .expect("punch_hole second call must not error");
        eprintln!("punch_hole_offline_target_live outcome: {outcome:?}");
        // We only assert that it's a structured outcome (not Timeout).
        // Any Failure variant or RelayPath is acceptable — the goal is to
        // prove the server replies cleanly to a second request from the
        // same process (catches connection-pool / framing-state bugs).
        match outcome {
            PunchHoleOutcome::Failure { .. } | PunchHoleOutcome::RelayPath { .. } => {}
            PunchHoleOutcome::Direct { .. } => {
                panic!("unexpected direct path for synthetic offline peer");
            }
            PunchHoleOutcome::Timeout => {
                panic!("hbbs timed out on the second PunchHoleRequest");
            }
        }
    }
}
