//! G34.2a checkpoint 2 — RustDesk secure-channel handshake + per-frame AEAD.
//!
//! ## Protocol reality (not Noise XK)
//!
//! The task brief framed this layer as a Noise XK pattern handshake, but a
//! careful read of upstream `vendor/rustdesk-ref/src/common.rs::secure_tcp_impl`
//! shows RustDesk does **not** use the Noise Protocol Framework. It uses a
//! bespoke libsodium-style three-message exchange:
//!
//! 1. The server sends `RendezvousMessage::KeyExchange { keys: [signed_pk] }`
//!    where `signed_pk` is a 32-byte ephemeral X25519 public key signed in
//!    place by the server's well-known **ed25519 signing key**
//!    (`E2+699SkYhlEsyjaizRhI+2kuvxxGheisWarfJHbkVA=` for the Klaravex
//!    Hetzner deployment). The signature is verified with NaCl
//!    `sign::verify`, which both *checks* the signature AND returns the
//!    enclosed plaintext (the 32-byte ephemeral X25519 pubkey).
//!
//! 2. The client generates its own ephemeral X25519 keypair `(our_pk, our_sk)`
//!    and a random 32-byte XSalsa20-Poly1305 `secretbox::Key`. It seals the
//!    secretbox key inside a NaCl `box_seal(key, zero_nonce, their_pk,
//!    our_sk)` — that's X25519 ECDH + XSalsa20-Poly1305 authenticated
//!    encryption — and sends `RendezvousMessage::KeyExchange { keys: [
//!    our_pk_bytes, sealed_box ] }`.
//!
//! 3. From that point both sides wrap every subsequent BytesCodec frame
//!    payload with `secretbox::seal(plaintext, nonce, key)`. The nonce is
//!    24 bytes; the first 8 are the per-direction message sequence number
//!    encoded little-endian, the remaining 16 are zero. The send and recv
//!    counters are independent (1, 2, 3…) and increment **before** use.
//!
//! ## Why this looks like the brief's description anyway
//!
//! The brief calls this "Noise XK_25519_AESGCM_SHA256". The actual variant
//! is closer to a single-flight `IK`-pattern hybrid: the responder
//! (server) static *signing* key is known to the initiator (client) ahead
//! of time and used to authenticate an ephemeral X25519 pubkey. The AEAD
//! is XSalsa20-Poly1305, not AES-GCM, and the hash is BLAKE2b inside
//! NaCl's primitives, not SHA-256. We follow upstream **exactly** to stay
//! wire-compatible; the `snow` crate cannot speak this variant so we
//! implement it directly against `dryoc`'s libsodium-compatible API.
//!
//! ## Surface area exposed
//!
//! * [`SERVER_PUBKEY_BASE64`] — Hetzner relay's ed25519 signing pubkey.
//! * [`load_server_pubkey`] — parse the base64 string into a verify key.
//! * [`SecureChannel`] — wraps a [`TcpStream`], encrypts every payload
//!   passed through [`SecureChannel::send_frame`] / [`SecureChannel::recv_frame`].
//! * [`SecureChannel::handshake_with`] — drive the three-message exchange
//!   above as the **initiator** (client side). Takes ownership of the
//!   TcpStream until the channel is dropped.
//! * Pure unit-test helpers for crafting a synthetic server `KeyExchange`
//!   message so the handshake can be tested without a live relay.

use std::io::{self, Write};
use std::net::TcpStream;

use base64::engine::general_purpose::STANDARD as B64;
use base64::Engine;
use dryoc::classic::crypto_box::{crypto_box_easy, crypto_box_keypair, Nonce as BoxNonce};
use dryoc::classic::crypto_secretbox::{
    crypto_secretbox_easy, crypto_secretbox_open_easy, Key as SecretboxKey, Nonce as SecretboxNonce,
};
use dryoc::classic::crypto_sign::{crypto_sign_open, PublicKey as SignPublicKey};
use dryoc::constants::{
    CRYPTO_BOX_MACBYTES, CRYPTO_BOX_NONCEBYTES, CRYPTO_BOX_PUBLICKEYBYTES,
    CRYPTO_SECRETBOX_KEYBYTES, CRYPTO_SECRETBOX_MACBYTES, CRYPTO_SECRETBOX_NONCEBYTES,
    CRYPTO_SIGN_BYTES, CRYPTO_SIGN_ED25519_PUBLICKEYBYTES,
};

use crate::relay::{encode_frame, read_frame};
use crate::rendezvous_proto::{rendezvous_message, KeyExchange, RendezvousMessage};
use protobuf::Message as _;

/// The Klaravex Hetzner hbbs server's ed25519 signing key in base64. This
/// is the value the server prints at startup as
/// `INFO Key: E2+699SkYhlEsyjaizRhI+2kuvxxGheisWarfJHbkVA=` (verified
/// against `docker logs hbbs` on hetzner-usa-watchdog, 2026-07-20).
/// Anyone who possesses the matching SECRET key can impersonate the
/// rendezvous server; this PUBLIC half lets clients verify the server's
/// signature.
pub const SERVER_PUBKEY_BASE64: &str = "E2+699SkYhlEsyjaizRhI+2kuvxxGheisWarfJHbkVA=";

/// Decode the base64 server signing pubkey into a 32-byte ed25519 verify
/// key. Returns `None` if the string is malformed.
pub fn load_server_pubkey() -> Option<SignPublicKey> {
    decode_server_pubkey(SERVER_PUBKEY_BASE64)
}

pub fn decode_server_pubkey(b64: &str) -> Option<SignPublicKey> {
    let raw = B64.decode(b64).ok()?;
    if raw.len() != CRYPTO_SIGN_ED25519_PUBLICKEYBYTES {
        return None;
    }
    let mut out = [0u8; CRYPTO_SIGN_ED25519_PUBLICKEYBYTES];
    out.copy_from_slice(&raw);
    Some(out)
}

/// Established secure channel on top of a [`TcpStream`]. Every payload
/// passed through [`SecureChannel::send_frame`] is wrapped with
/// `secretbox::seal` using a 24-byte nonce whose first 8 bytes are the
/// little-endian send counter. The recv side mirrors this with a separate
/// counter (matches upstream `hbb_common::tcp::Encrypt::dec`).
pub struct SecureChannel {
    stream: TcpStream,
    key: SecretboxKey,
    send_seq: u64,
    recv_seq: u64,
}

impl SecureChannel {
    /// Build a SecureChannel directly from an already-negotiated key. Used
    /// by [`Self::handshake_with`] and exposed for unit tests that bypass
    /// the rendezvous round-trip.
    pub fn from_key(stream: TcpStream, key: SecretboxKey) -> Self {
        Self {
            stream,
            key,
            send_seq: 0,
            recv_seq: 0,
        }
    }

    /// Drive the three-message KeyExchange flow against `stream` and
    /// return a ready-to-use SecureChannel. The stream MUST already be
    /// connected to a rendezvous server that initiates the exchange. If
    /// the server never sends a KeyExchange the handshake returns
    /// `Err(io::ErrorKind::InvalidData)`.
    ///
    /// `server_sign_pk` is the 32-byte ed25519 signing pubkey of the
    /// rendezvous server (see [`SERVER_PUBKEY_BASE64`]).
    pub fn handshake_with(
        mut stream: TcpStream,
        server_sign_pk: &SignPublicKey,
    ) -> io::Result<Self> {
        // Step 1: read the server's signed ephemeral X25519 pubkey.
        let payload = read_frame(&mut stream)?;
        let key = perform_handshake_step(&payload, server_sign_pk, &mut stream)?;
        Ok(Self::from_key(stream, key))
    }

    /// Send one ciphertext frame. The plaintext is `payload`; the wire is
    /// `BytesCodec(secretbox::seal(payload, nonce(send_seq+1), key))`.
    pub fn send_frame(&mut self, payload: &[u8]) -> io::Result<()> {
        self.send_seq = self.send_seq.checked_add(1).ok_or_else(|| {
            io::Error::new(io::ErrorKind::Other, "send seqnum overflow")
        })?;
        let nonce = nonce_from_seq(self.send_seq);
        let mut ciphertext = vec![0u8; payload.len() + CRYPTO_SECRETBOX_MACBYTES];
        crypto_secretbox_easy(&mut ciphertext, payload, &nonce, &self.key)
            .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("seal: {e}")))?;
        let mut framed = Vec::with_capacity(ciphertext.len() + 4);
        encode_frame(&ciphertext, &mut framed)?;
        self.stream.write_all(&framed)?;
        self.stream.flush()?;
        Ok(())
    }

    /// Receive one ciphertext frame, decrypt it, and return the plaintext.
    pub fn recv_frame(&mut self) -> io::Result<Vec<u8>> {
        let ciphertext = read_frame(&mut self.stream)?;
        if ciphertext.is_empty() {
            return Ok(Vec::new());
        }
        self.recv_seq = self.recv_seq.checked_add(1).ok_or_else(|| {
            io::Error::new(io::ErrorKind::Other, "recv seqnum overflow")
        })?;
        let nonce = nonce_from_seq(self.recv_seq);
        if ciphertext.len() < CRYPTO_SECRETBOX_MACBYTES {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "ciphertext shorter than Poly1305 tag",
            ));
        }
        let mut plaintext = vec![0u8; ciphertext.len() - CRYPTO_SECRETBOX_MACBYTES];
        crypto_secretbox_open_easy(&mut plaintext, &ciphertext, &nonce, &self.key)
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, format!("open: {e}")))?;
        Ok(plaintext)
    }

    /// Borrow the inner TcpStream — used by tests that want to assert on
    /// the underlying socket state after handshake.
    pub fn stream(&self) -> &TcpStream {
        &self.stream
    }
}

/// Encode the rustdesk wire nonce derivation: 8 little-endian bytes of
/// `seq` followed by 16 zero bytes (matches `FramedStream::get_nonce` in
/// `vendor/hbb_common/src/tcp.rs`).
fn nonce_from_seq(seq: u64) -> SecretboxNonce {
    let mut nonce = [0u8; CRYPTO_SECRETBOX_NONCEBYTES];
    nonce[..8].copy_from_slice(&seq.to_le_bytes());
    nonce
}

/// Parse the server's first KeyExchange message, generate our half, and
/// write the reply back. Returns the established secretbox key. Pure
/// function w.r.t. the stream — unit tests inject a fake server message.
pub fn perform_handshake_step(
    server_msg: &[u8],
    server_sign_pk: &SignPublicKey,
    out_stream: &mut TcpStream,
) -> io::Result<SecretboxKey> {
    let msg = RendezvousMessage::parse_from_bytes(server_msg)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, format!("decode kx: {e}")))?;
    let ex = match msg.union {
        Some(rendezvous_message::Union::KeyExchange(ex)) => ex,
        other => {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!(
                    "expected KeyExchange, got: {:?}",
                    other.map(|v| std::mem::discriminant(&v))
                ),
            ));
        }
    };
    if ex.keys.len() != 1 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!("KeyExchange.keys.len() = {}, want 1", ex.keys.len()),
        ));
    }
    // Verify the ed25519 signature in place. `crypto_sign_ed25519_open`
    // returns the plaintext (which is the 32-byte ephemeral X25519
    // pubkey). The signature is 64 bytes prefix, payload is 32 bytes.
    let signed = &ex.keys[0];
    if signed.len() != CRYPTO_SIGN_BYTES + CRYPTO_BOX_PUBLICKEYBYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "signed pk length {} != {}",
                signed.len(),
                CRYPTO_SIGN_BYTES + CRYPTO_BOX_PUBLICKEYBYTES
            ),
        ));
    }
    let mut their_pk = vec![0u8; CRYPTO_BOX_PUBLICKEYBYTES];
    crypto_sign_open(&mut their_pk, signed, server_sign_pk)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, format!("sig verify: {e}")))?;
    let mut their_pk_arr = [0u8; CRYPTO_BOX_PUBLICKEYBYTES];
    their_pk_arr.copy_from_slice(&their_pk);
    // Generate our half. We use a sealed-box round-trip so the server can
    // open it with its corresponding box secret key. Per upstream code,
    // the nonce for box_seal is all zeros (the server's matching open
    // path uses the same constant zero nonce — see
    // `vendor/rustdesk-ref/src/common.rs::create_symmetric_key_msg`).
    let (our_pk, our_sk) = crypto_box_keypair();
    let mut secretbox_key = [0u8; CRYPTO_SECRETBOX_KEYBYTES];
    fill_random(&mut secretbox_key);
    let zero_nonce: BoxNonce = [0u8; CRYPTO_BOX_NONCEBYTES];
    let mut sealed = vec![0u8; CRYPTO_SECRETBOX_KEYBYTES + CRYPTO_BOX_MACBYTES];
    crypto_box_easy(
        &mut sealed,
        &secretbox_key,
        &zero_nonce,
        &their_pk_arr,
        &our_sk,
    )
    .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("box_seal: {e}")))?;

    let mut reply = RendezvousMessage::new();
    reply.set_key_exchange(KeyExchange {
        keys: vec![our_pk.to_vec(), sealed],
        ..Default::default()
    });
    let bytes = reply
        .write_to_bytes()
        .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("encode kx: {e}")))?;
    let mut framed = Vec::with_capacity(bytes.len() + 4);
    encode_frame(&bytes, &mut framed)?;
    out_stream.write_all(&framed)?;
    out_stream.flush()?;
    Ok(secretbox_key)
}

fn fill_random(buf: &mut [u8]) {
    use rand::RngCore;
    rand::thread_rng().fill_bytes(buf);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    #[test]
    fn server_pubkey_parses() {
        let pk = load_server_pubkey().expect("server pubkey decodes");
        assert_eq!(pk.len(), CRYPTO_SIGN_ED25519_PUBLICKEYBYTES);
    }

    #[test]
    fn nonce_derivation_matches_upstream() {
        // Upstream `FramedStream::get_nonce(1)` = [0x01, 0,0,0,0,0,0,0, 0..0].
        let n = nonce_from_seq(1);
        assert_eq!(n[0], 1);
        for &b in &n[1..] {
            assert_eq!(b, 0);
        }
        let n2 = nonce_from_seq(0xdead_beef_1234_5678);
        let want = [0x78, 0x56, 0x34, 0x12, 0xef, 0xbe, 0xad, 0xde];
        assert_eq!(&n2[..8], &want);
    }

    #[test]
    fn secretbox_roundtrip_with_known_key() {
        // Construct two channels sharing a key over a localhost socketpair.
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        let key = [42u8; CRYPTO_SECRETBOX_KEYBYTES];
        let key_a = key;
        let key_b = key;
        let server_thread = std::thread::spawn(move || {
            let (sock, _) = listener.accept().unwrap();
            let mut chan = SecureChannel::from_key(sock, key_b);
            let got = chan.recv_frame().unwrap();
            assert_eq!(&got, b"ping");
            chan.send_frame(b"pong").unwrap();
        });
        let client = TcpStream::connect(addr).unwrap();
        let mut chan = SecureChannel::from_key(client, key_a);
        chan.send_frame(b"ping").unwrap();
        let got = chan.recv_frame().unwrap();
        assert_eq!(&got, b"pong");
        server_thread.join().unwrap();
    }

    #[test]
    fn handshake_rejects_wrong_message_type() {
        // Build a non-KeyExchange RendezvousMessage and confirm the
        // handshake bails cleanly with InvalidData.
        use crate::rendezvous_proto::TestNatRequest;
        let mut msg = RendezvousMessage::new();
        msg.set_test_nat_request(TestNatRequest {
            serial: 0,
            ..Default::default()
        });
        let bytes = msg.write_to_bytes().unwrap();
        let server_pk = load_server_pubkey().unwrap();
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        let server_thread = std::thread::spawn(move || {
            let (_sock, _) = listener.accept().unwrap();
        });
        let mut client = TcpStream::connect(addr).unwrap();
        let result = perform_handshake_step(&bytes, &server_pk, &mut client);
        assert!(result.is_err());
        assert_eq!(
            result.unwrap_err().kind(),
            io::ErrorKind::InvalidData,
            "wrong-message-type handshake must InvalidData"
        );
        server_thread.join().unwrap();
    }

    #[test]
    fn handshake_with_synthetic_server_completes() {
        // Generate a sign keypair, simulate the server-side: build a
        // signed KeyExchange, drive perform_handshake_step, verify the
        // returned secretbox key is non-zero AND the client's reply has
        // the expected `[ our_pk (32 bytes), sealed_secretbox_key (48
        // bytes = 32 plaintext + 16 MAC) ]` shape.
        use dryoc::classic::crypto_sign::{crypto_sign, crypto_sign_keypair};
        let (server_sign_pk, server_sign_sk) = crypto_sign_keypair();
        let (server_box_pk, _server_box_sk) = crypto_box_keypair();
        let mut signed = vec![0u8; CRYPTO_SIGN_BYTES + CRYPTO_BOX_PUBLICKEYBYTES];
        crypto_sign(&mut signed, &server_box_pk, &server_sign_sk).unwrap();
        let mut msg = RendezvousMessage::new();
        msg.set_key_exchange(KeyExchange {
            keys: vec![signed],
            ..Default::default()
        });
        let server_bytes = msg.write_to_bytes().unwrap();
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        let server_thread = std::thread::spawn(move || {
            let (mut sock, _) = listener.accept().unwrap();
            let payload = read_frame(&mut sock).unwrap();
            let reply = RendezvousMessage::parse_from_bytes(&payload).unwrap();
            match reply.union {
                Some(rendezvous_message::Union::KeyExchange(ex)) => {
                    assert_eq!(ex.keys.len(), 2);
                    assert_eq!(ex.keys[0].len(), CRYPTO_BOX_PUBLICKEYBYTES);
                    assert_eq!(
                        ex.keys[1].len(),
                        CRYPTO_SECRETBOX_KEYBYTES + CRYPTO_BOX_MACBYTES
                    );
                }
                _ => panic!("client did not reply with KeyExchange"),
            }
        });
        let mut client = TcpStream::connect(addr).unwrap();
        let key = perform_handshake_step(&server_bytes, &server_sign_pk, &mut client)
            .expect("handshake completes with valid signed pk");
        assert_eq!(key.len(), CRYPTO_SECRETBOX_KEYBYTES);
        assert!(key.iter().any(|&b| b != 0));
        server_thread.join().unwrap();
    }

    /// **G34.2b deliverable 2 acceptance test** — wraps a TCP socketpair
    /// as `SecureChannel`s on both ends and verifies the secretbox
    /// AEAD ferries multi-KB payloads cleanly. This is the same wire
    /// path the peer link uses; the only delta with the hbbs link is
    /// *who* generates the secretbox key (the peer side derives it
    /// from a different `Message::PublicKey` exchange instead of the
    /// hbbs `KeyExchange` — but the post-handshake framing is
    /// byte-for-byte identical, as confirmed by reading
    /// `vendor/rustdesk-ref/src/client.rs::secure_connection`).
    ///
    /// The test deliberately exchanges several frames with sizes that
    /// straddle the BytesCodec varint header boundaries (`<= 63`,
    /// `<= 16383`, `<= 4 MB`) to catch any framing regressions.
    #[test]
    fn tcp_secure_channel_roundtrip() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        // Shared key. In the real flow this comes out of the secretbox
        // handshake (server side) or the peer-side `Message::PublicKey`
        // exchange (peer side). Here we inject it directly via
        // `from_key` so we're testing the *transport*, not the
        // handshake (which has its own tests above).
        let key = [0xA5u8; CRYPTO_SECRETBOX_KEYBYTES];

        let payloads: Vec<Vec<u8>> = vec![
            b"small".to_vec(),
            vec![0x77u8; 60], // straddles 1-byte header
            vec![0x33u8; 4096], // straddles 2-byte header
            vec![0xCCu8; 32 * 1024], // straddles 3-byte header
        ];
        let server_payloads = payloads.clone();

        let server_thread = std::thread::spawn(move || {
            let (sock, _) = listener.accept().unwrap();
            let mut chan = SecureChannel::from_key(sock, key);
            for expected in &server_payloads {
                let got = chan.recv_frame().unwrap();
                assert_eq!(&got, expected, "server-side recv mismatch");
                // Reply with the same bytes — full round-trip.
                chan.send_frame(expected).unwrap();
            }
        });

        let client = TcpStream::connect(addr).unwrap();
        let mut chan = SecureChannel::from_key(client, key);
        for payload in &payloads {
            chan.send_frame(payload).unwrap();
            let echo = chan.recv_frame().unwrap();
            assert_eq!(&echo, payload, "client-side recv mismatch");
        }
        server_thread.join().unwrap();
    }

    #[test]
    fn handshake_rejects_bad_signature() {
        // Build a KeyExchange with a deliberately wrong signature; verify
        // the client refuses it.
        let mut bogus = vec![0u8; CRYPTO_SIGN_BYTES + CRYPTO_BOX_PUBLICKEYBYTES];
        bogus[0] = 0xFF;
        let mut msg = RendezvousMessage::new();
        msg.set_key_exchange(KeyExchange {
            keys: vec![bogus],
            ..Default::default()
        });
        let bytes = msg.write_to_bytes().unwrap();
        let server_pk = load_server_pubkey().unwrap();
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        let server_thread = std::thread::spawn(move || {
            let (_sock, _) = listener.accept().unwrap();
        });
        let mut client = TcpStream::connect(addr).unwrap();
        let result = perform_handshake_step(&bytes, &server_pk, &mut client);
        assert!(result.is_err());
        assert_eq!(result.unwrap_err().kind(), io::ErrorKind::InvalidData);
        server_thread.join().unwrap();
    }
}
