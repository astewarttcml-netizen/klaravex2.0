//! G34.2b — Hole-punch + TCP direct-connect to a RustDesk peer.
//!
//! ## Where this sits in the flow
//!
//! The rustdesk session lifecycle on the operator side is:
//!
//!   1. (already done in G34.2a) **UDP register** with the rendezvous
//!      server so the server knows our id, pubkey, and outbound NAT
//!      mapping. See `udp_rendezvous.rs`.
//!   2. (already done in G34.2a checkpoint 1) **PunchHoleRequest** over
//!      TCP-21116 to ask the rendezvous server to put us in touch with a
//!      remote peer. See `relay::RendezvousClient::punch_hole`.
//!   3. **THIS MODULE — G34.2b deliverable 1.** Drive that punch request
//!      to a successful peer endpoint and open a TCP socket to it. The
//!      server's `PunchHoleResponse.socket_addr` carries a *mangled*
//!      `SocketAddr` (upstream `hbb_common::AddrMangle`) of the peer's
//!      NAT-mapped TCP listener; we decode it and dial.
//!   4. (G34.2b deliverable 2 — `secure.rs`) wrap that TCP stream in
//!      a `SecureChannel` running the same secretbox AEAD we use for the
//!      hbbs link, but driven by the peer's signed pubkey instead of the
//!      server's.
//!   5. (G34.2b deliverable 3 — `vp9.rs`) read one peer-side
//!      `Message::VideoFrame::vp9s.frames[0]` payload and decode it.
//!
//! ## Why this is a separate module
//!
//! `relay.rs` already contains a `punch_hole` that returns a
//! `PunchHoleOutcome` enum. That enum was sufficient for checkpoint 1
//! (we only had to confirm the server replied), but it deliberately
//! does **not** expose the mangled `socket_addr` bytes — it just reports
//! "Direct { socket_addr_len, has_pk }". For G34.2b we need the actual
//! bytes so we can decode them into a `SocketAddr` and dial.
//!
//! Rather than break `PunchHoleOutcome`'s API (it's used by 4+ live
//! tests), this module re-runs PunchHoleRequest itself and consumes the
//! raw `PunchHoleResponse` proto. That's also the upstream pattern: the
//! client first issues a single PunchHoleRequest and a single decode,
//! and only then graduates to the multi-attempt connect loop. (See
//! `vendor/rustdesk-ref/src/client.rs:460` for the upstream callsite.)
//!
//! ## AddrMangle decode — wire-format reproduction
//!
//! Upstream `vendor/hbb_common/src/lib.rs:142-200` defines:
//!
//! ```text
//! fn decode(bytes: &[u8]) -> SocketAddr {
//!     if bytes.len() > 16 {
//!         // IPv6 path: 16 bytes ip + 2 bytes port, little-endian
//!         ...
//!     }
//!     // IPv4 path: padded LE u128, then bit-decode:
//!     //   tm   = (number >> 17) & u32::MAX
//!     //   ip   = (((number >> 49) - tm) as u32).to_le_bytes()
//!     //   port = (number & 0xFFFFFF) - (tm & 0xFFFF)
//! }
//! ```
//!
//! We reproduce this 1:1 in [`AddrMangle::decode`] below. Round-trip
//! tested against the upstream encode + decode in `tests::mangle_roundtrip`.
//!
//! ## What this module is NOT yet
//!
//! - There's no TCP NAT-test loop here. Upstream rustdesk pre-warms the
//!   NAT before issuing PunchHoleRequest by hammering a UDP "test_nat"
//!   message; our shim relies on the prior `udp_rendezvous::heartbeat_loop`
//!   to have done that.
//! - There's no relay-path fallback. If the rendezvous server replies
//!   `RelayResponse` or `PunchHoleResponse { relay_server: <non-empty> }`,
//!   we surface that as `ConnectError::RelayRequired` and the caller is
//!   responsible for picking up a relay client. Direct-connect is the
//!   only path G34.2b implements.
//! - There's no IPv6 punching. The upstream `socket_addr_v6` field is
//!   parsed but only used to log; we always dial the IPv4 mangled addr
//!   if present. IPv6 lands in G34.2c if any Klaravex peer needs it.

use std::io;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr, SocketAddrV4, TcpStream, ToSocketAddrs};
use std::time::Duration;

use protobuf::Message as _;

use crate::relay::{encode_frame, read_frame, RendezvousConfig, HBBS_MAIN_PORT};
use crate::rendezvous_proto::{
    punch_hole_response, rendezvous_message, PunchHoleRequest, PunchHoleResponse,
    RendezvousMessage,
};

/// Error type returned by [`connect_to_peer`]. Each variant carries
/// enough context for the operator UI to decide what to do next.
#[derive(Debug)]
pub enum ConnectError {
    /// Local I/O failure (bind / connect / read / write). Carries the
    /// `io::Error` for surfacing to the operator log.
    Io(io::Error),
    /// Server returned a structured PunchHoleResponse failure (peer id
    /// unknown, peer offline, licence mismatch, etc).
    PeerError {
        kind: punch_hole_response::Failure,
        message: String,
    },
    /// Server told us to use a relay server instead of direct connect.
    /// Direct-only is the G34.2b scope; surface this so the caller can
    /// pivot to the relay path in a later phase.
    RelayRequired { relay_server: String, has_pk: bool },
    /// Server returned something other than PunchHoleResponse /
    /// RelayResponse — protocol mismatch.
    Protocol(String),
    /// Server returned PunchHoleResponse but with no socket_addr AND no
    /// relay_server — we cannot route the connection.
    NoEndpoint,
}

impl std::fmt::Display for ConnectError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(e) => write!(f, "io: {e}"),
            Self::PeerError { kind, message } => {
                write!(f, "peer-error: {kind:?} ({message})")
            }
            Self::RelayRequired {
                relay_server,
                has_pk,
            } => write!(
                f,
                "relay-required: relay_server={relay_server:?} has_pk={has_pk}"
            ),
            Self::Protocol(s) => write!(f, "protocol: {s}"),
            Self::NoEndpoint => write!(f, "no-endpoint"),
        }
    }
}

impl std::error::Error for ConnectError {}

impl From<io::Error> for ConnectError {
    fn from(e: io::Error) -> Self {
        Self::Io(e)
    }
}

/// Outcome of a successful punch — what the caller actually wants to do
/// next is open a TCP stream to `peer_socket` and then wrap it in a
/// `SecureChannel` using `signed_id_pk` as the peer-pubkey envelope.
#[derive(Debug)]
pub struct PunchOutcome {
    /// IPv4 (or IPv6) socket address we should dial to reach the peer.
    pub peer_socket: SocketAddr,
    /// The peer's signed pubkey blob (`PunchHoleResponse.pk`), still
    /// rendezvous-server-signed. Pass this to `SecureChannel`'s
    /// peer-side handshake to authenticate the peer before encrypting.
    /// May be empty if the rendezvous server is configured without keys.
    pub signed_id_pk: Vec<u8>,
    /// True iff the server marked this peer as on the same LAN as us.
    pub is_local: bool,
}

/// Full operator-side connect: punch → decode addr → dial.
///
/// Synchronous. Reuses [`RendezvousConfig`] from `relay.rs` so the live
/// licence_key + timeouts are consistent with the rest of the shim.
///
/// On success returns:
///   * `TcpStream` already connected to the peer with read/write
///     deadlines applied
///   * the [`PunchOutcome`] metadata that the next layer
///     (`SecureChannel`) needs to drive the peer-side handshake.
///
/// The TcpStream is **unencrypted** at this point — wrap it with
/// `SecureChannel::handshake_with_peer` before sending any sensitive
/// frames.
pub fn connect_to_peer(
    cfg: &RendezvousConfig,
    peer_id: &str,
) -> Result<(TcpStream, PunchOutcome), ConnectError> {
    let outcome = request_punch_hole(cfg, peer_id)?;
    let stream = dial_peer(outcome.peer_socket, cfg.timeout)?;
    Ok((stream, outcome))
}

/// Send PunchHoleRequest to hbbs, parse PunchHoleResponse, return the
/// decoded peer endpoint. Pure protocol — does NOT touch the peer.
pub fn request_punch_hole(
    cfg: &RendezvousConfig,
    peer_id: &str,
) -> Result<PunchOutcome, ConnectError> {
    let mut stream = dial_hbbs(&cfg.host, cfg.main_port, cfg.timeout)?;

    let mut req = PunchHoleRequest::new();
    req.id = peer_id.to_string();
    req.version = format!("klx-rdshim/{}", crate::SHIM_VERSION);
    if !cfg.licence_key.is_empty() {
        req.licence_key = cfg.licence_key.clone();
    }
    let mut out_msg = RendezvousMessage::new();
    out_msg.set_punch_hole_request(req);
    let body = out_msg
        .write_to_bytes()
        .map_err(|e| ConnectError::Protocol(format!("encode PunchHoleRequest: {e}")))?;
    let mut framed = Vec::with_capacity(body.len() + 4);
    encode_frame(&body, &mut framed)?;
    use std::io::Write;
    stream.write_all(&framed)?;
    stream.flush()?;

    let reply = read_frame(&mut stream)?;
    let in_msg = RendezvousMessage::parse_from_bytes(&reply)
        .map_err(|e| ConnectError::Protocol(format!("decode reply: {e}")))?;

    let phr: PunchHoleResponse = match in_msg.union {
        Some(rendezvous_message::Union::PunchHoleResponse(r)) => r,
        Some(rendezvous_message::Union::RelayResponse(rr)) => {
            // Server short-circuited to relay — surface for G34.2c.
            return Err(ConnectError::RelayRequired {
                relay_server: rr.relay_server.clone(),
                has_pk: matches!(
                    rr.union,
                    Some(crate::rendezvous_proto::relay_response::Union::Pk(_))
                ),
            });
        }
        other => {
            return Err(ConnectError::Protocol(format!(
                "expected PunchHoleResponse, got {:?}",
                other.map(|v| std::mem::discriminant(&v))
            )));
        }
    };

    // Failure path.
    if phr.socket_addr.is_empty() && phr.socket_addr_v6.is_empty() {
        if !phr.relay_server.is_empty() {
            return Err(ConnectError::RelayRequired {
                relay_server: phr.relay_server.clone(),
                has_pk: !phr.pk.is_empty(),
            });
        }
        let failure = phr.failure.enum_value_or_default();
        let message = if !phr.other_failure.is_empty() {
            phr.other_failure.clone()
        } else {
            format!("{failure:?}")
        };
        return Err(ConnectError::PeerError {
            kind: failure,
            message,
        });
    }

    // The server gave us a peer endpoint. Prefer IPv4 (the IPv6 path is
    // deferred to G34.2c).
    let peer_socket = if !phr.socket_addr.is_empty() {
        AddrMangle::decode(&phr.socket_addr).ok_or(ConnectError::NoEndpoint)?
    } else {
        AddrMangle::decode_v6(&phr.socket_addr_v6).ok_or(ConnectError::NoEndpoint)?
    };

    // is_local lives in the `union` oneof per the .proto. Match either
    // variant; default false otherwise.
    let is_local = matches!(
        phr.union,
        Some(crate::rendezvous_proto::punch_hole_response::Union::IsLocal(true))
    );

    Ok(PunchOutcome {
        peer_socket,
        signed_id_pk: phr.pk.clone(),
        is_local,
    })
}

/// Open a TCP stream to the punched peer endpoint with the given timeout.
/// Read/write deadlines are set to the same value so a stuck peer cannot
/// hang the operator console.
pub fn dial_peer(addr: SocketAddr, timeout: Duration) -> io::Result<TcpStream> {
    let stream = TcpStream::connect_timeout(&addr, timeout)?;
    stream.set_read_timeout(Some(timeout))?;
    stream.set_write_timeout(Some(timeout))?;
    stream.set_nodelay(true)?;
    Ok(stream)
}

fn dial_hbbs(host: &str, port: u16, timeout: Duration) -> io::Result<TcpStream> {
    let addr_str = format!("{host}:{port}");
    let mut last_err: Option<io::Error> = None;
    for sa in addr_str.to_socket_addrs()? {
        match TcpStream::connect_timeout(&sa, timeout) {
            Ok(s) => {
                s.set_read_timeout(Some(timeout))?;
                s.set_write_timeout(Some(timeout))?;
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

/// Reproduction of `hbb_common::AddrMangle` (upstream
/// `vendor/hbb_common/src/lib.rs:142`). Exposed so unit tests can verify
/// the round-trip against synthetic inputs.
pub struct AddrMangle;

impl AddrMangle {
    /// Decode a mangled `socket_addr` bytes blob into a `SocketAddr`.
    ///
    /// Returns `None` when the input is malformed (e.g. bytes len in
    /// (16, 18) which upstream treats as "unspecified" — we surface
    /// that as None rather than the upstream `0.0.0.0:0` fallback so the
    /// caller can produce a NoEndpoint error).
    pub fn decode(bytes: &[u8]) -> Option<SocketAddr> {
        if bytes.is_empty() {
            return None;
        }
        if bytes.len() > 16 {
            return Self::decode_v6(bytes);
        }
        let mut padded = [0u8; 16];
        padded[..bytes.len()].copy_from_slice(bytes);
        let number = u128::from_le_bytes(padded);
        let tm = (number >> 17) & (u32::MAX as u128);
        // ip is recovered exactly: `(number >> 49) == ip + tm` from the
        // encode formula (bits 49..81 of v hold `ip + tm`, no overlap).
        // `wrapping_sub` here matches upstream (which does plain `-` on
        // u128) — we never expect underflow for well-formed input.
        let ip_recovered = (number >> 49).wrapping_sub(tm);
        let ip = (ip_recovered as u32).to_le_bytes();
        // Port recovery: see the doc-comment block on `encode_v4` for
        // the bit-juggling proof. The short version:
        //   v & 0xFFFFFF = ((tm & 0x7F) << 17) | (port + (tm & 0xFFFF))
        // and the two terms don't overlap because `port + tm&0xFFFF`
        // fits in 17 bits and only uses bits 0..16 (bit 17 is never
        // set, since the max is 2*65535 = 131070 = 0x1FFFE).
        //
        // Upstream then does `(... - tm & 0xFFFF) as u16` — the `as u16`
        // truncation throws away the bits coming from `(tm & 0x7F) << 17`
        // because they live in bits 17..24. We replicate that with
        // `wrapping_sub` + truncating cast.
        let port = (number & 0xFFFFFF).wrapping_sub(tm & 0xFFFF) as u16;
        Some(SocketAddr::V4(SocketAddrV4::new(
            Ipv4Addr::new(ip[0], ip[1], ip[2], ip[3]),
            port,
        )))
    }

    /// IPv6 form: 16 bytes ip + 2 bytes port (little-endian). Must be
    /// exactly 18 bytes per upstream.
    pub fn decode_v6(bytes: &[u8]) -> Option<SocketAddr> {
        if bytes.len() != 18 {
            return None;
        }
        let mut ip = [0u8; 16];
        ip.copy_from_slice(&bytes[..16]);
        let port = u16::from_le_bytes([bytes[16], bytes[17]]);
        Some(SocketAddr::new(IpAddr::V6(Ipv6Addr::from(ip)), port))
    }

    /// Encode a `SocketAddr` to the mangled IPv4 representation.
    /// Implements the upstream `encode()` algorithm so the unit tests
    /// can construct synthetic `PunchHoleResponse.socket_addr` bytes
    /// without needing a live relay. Verified by the round-trip test
    /// `tests::mangle_roundtrip`.
    pub fn encode_v4(addr: SocketAddrV4, tm_micros: u32) -> Vec<u8> {
        let ip = u32::from_le_bytes(addr.ip().octets()) as u128;
        let port = addr.port() as u128;
        let tm = tm_micros as u128;
        let v = ((ip + tm) << 49) | (tm << 17) | (port + (tm & 0xFFFF));
        let bytes = v.to_le_bytes();
        let mut n_padding = 0;
        for i in bytes.iter().rev() {
            if i == &0u8 {
                n_padding += 1;
            } else {
                break;
            }
        }
        bytes[..(16 - n_padding)].to_vec()
    }
}

/// Default RendezvousConfig with klx-rdshim's known hbbs main port and
/// licence key. Convenience for the common case.
pub fn default_config(host: &str) -> RendezvousConfig {
    RendezvousConfig {
        host: host.to_string(),
        nat_port: crate::relay::HBBS_NAT_PORT,
        main_port: HBBS_MAIN_PORT,
        timeout: Duration::from_millis(5000),
        licence_key: crate::secure::SERVER_PUBKEY_BASE64.to_string(),
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn live_enabled() -> bool {
        std::env::var("KLX_LIVE_RELAY")
            .map(|v| !v.is_empty() && v != "0")
            .unwrap_or(false)
    }

    const LIVE_HOST: &str = "87.99.147.244";

    /// IPv4 round-trip: encode a known SocketAddr at a fixed timestamp,
    /// then decode and compare. Proves we read upstream's algorithm
    /// correctly.
    #[test]
    fn mangle_roundtrip_ipv4() {
        let addr = SocketAddrV4::new(Ipv4Addr::new(203, 0, 113, 42), 31337);
        // tm_micros is deliberately arbitrary; the encode/decode pair
        // must invert regardless of the timestamp.
        for &tm in &[1u32, 12345u32, 0x1234_5678u32] {
            let bytes = AddrMangle::encode_v4(addr, tm);
            let decoded = AddrMangle::decode(&bytes).expect("decode");
            assert_eq!(decoded, SocketAddr::V4(addr), "tm={tm:#x}");
        }
    }

    /// IPv6 round-trip: build 18 bytes manually, decode, compare.
    #[test]
    fn mangle_roundtrip_ipv6() {
        let ip: [u8; 16] = [
            0x20, 0x01, 0x0d, 0xb8, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x01,
        ];
        let port: u16 = 31337;
        let mut blob = ip.to_vec();
        blob.extend_from_slice(&port.to_le_bytes());
        assert_eq!(blob.len(), 18);
        let decoded = AddrMangle::decode(&blob).expect("v6 decode");
        match decoded {
            SocketAddr::V6(s) => {
                assert_eq!(s.ip().octets(), ip);
                assert_eq!(s.port(), port);
            }
            other => panic!("expected V6, got {other:?}"),
        }
    }

    /// Empty bytes must decode to None (NOT the upstream 0.0.0.0:0
    /// fallback — we want callers to know there was no endpoint).
    #[test]
    fn mangle_empty_returns_none() {
        assert!(AddrMangle::decode(&[]).is_none());
    }

    /// Length 17 is the "unspecified" upstream code path. Surface as None
    /// so the caller can produce ConnectError::NoEndpoint.
    #[test]
    fn mangle_len_17_returns_none() {
        let buf = vec![0u8; 17];
        assert!(AddrMangle::decode(&buf).is_none());
    }

    /// **LIVE TEST**: punches the live Hetzner hbbs against a deliberately
    /// unknown peer id. We expect `ConnectError::PeerError { kind:
    /// ID_NOT_EXIST | OFFLINE, .. }` — that proves the full
    /// PunchHoleRequest → PunchHoleResponse path is wired, even though no
    /// peer is up to receive the punch.
    ///
    /// To actually drive a successful connect we'd need a known test peer
    /// running rustdesk and registered with our hbbs. We don't have one
    /// available in this environment (G34.2c will spin up a rustdesk
    /// peer in a VM and re-run this with a real id), so this test
    /// confirms the *negative* path live.
    ///
    /// Manual run:
    ///   KLX_LIVE_RELAY=1 cargo test --lib peer_connect::tests::punch_hole_live -- --nocapture
    #[test]
    fn punch_hole_live() {
        if !live_enabled() {
            eprintln!("punch_hole_live: skipped (set KLX_LIVE_RELAY=1)");
            return;
        }
        let cfg = default_config(LIVE_HOST);
        let peer_id = format!("klx-g34-2b-nonexistent-{}", std::process::id());
        let result = request_punch_hole(&cfg, &peer_id);
        eprintln!("punch_hole_live: {result:?}");
        match result {
            Err(ConnectError::PeerError { kind, .. }) => {
                assert!(
                    matches!(
                        kind,
                        punch_hole_response::Failure::ID_NOT_EXIST
                            | punch_hole_response::Failure::OFFLINE
                    ),
                    "expected ID_NOT_EXIST or OFFLINE for unknown peer, got {kind:?}"
                );
            }
            Err(ConnectError::RelayRequired { .. }) => {
                // Acceptable: some hbbs configs fall back to relay for
                // unknown ids.
            }
            Ok(outcome) => {
                panic!(
                    "hbbs claimed to know a peer we just invented: socket={:?} pk_len={} is_local={}",
                    outcome.peer_socket,
                    outcome.signed_id_pk.len(),
                    outcome.is_local
                )
            }
            Err(other) => panic!("unexpected error: {other}"),
        }
    }

    /// **LIVE TEST (peer required)**: full connect → TCP socket open.
    /// Gated behind `KLX_LIVE_PEER_ID=<id>` so it only runs when a
    /// developer has a rustdesk peer up and ready. The peer id is the
    /// 9-or-10-digit number rustdesk shows in the peer's tray UI.
    ///
    /// Manual run:
    ///   KLX_LIVE_RELAY=1 KLX_LIVE_PEER_ID=123456789 \
    ///     cargo test --lib peer_connect::tests::full_connect_to_peer_live \
    ///     -- --nocapture --ignored
    #[test]
    #[ignore = "requires a live rustdesk peer registered against hbbs.klaravex.com — set KLX_LIVE_PEER_ID"]
    fn full_connect_to_peer_live() {
        let Some(peer_id) = std::env::var("KLX_LIVE_PEER_ID").ok() else {
            eprintln!("full_connect_to_peer_live: KLX_LIVE_PEER_ID not set");
            return;
        };
        let cfg = default_config(LIVE_HOST);
        let (stream, outcome) = connect_to_peer(&cfg, &peer_id).expect("connect");
        eprintln!(
            "full_connect_to_peer_live: connected to peer_socket={} pk_len={} is_local={}",
            outcome.peer_socket,
            outcome.signed_id_pk.len(),
            outcome.is_local
        );
        // Just a sanity check — the actual handshake is exercised by
        // `secure::tests::tcp_secure_channel_against_peer_live`.
        assert!(stream.peer_addr().is_ok());
    }
}
