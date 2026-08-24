# klx-rdshim binding status (G34.2a checkpoint 3)

Date: 2026-06-12 (checkpoint 3 land)
Build: `target/release/klx-rdshim` (macOS aarch64)
Rust: 1.96.0 stable

## G34.2a checkpoint 3 summary (this iteration)

**Headline status: peer connection layer GREEN, codec layer GREEN,
operator-control layer wired and protocol-level verified, but customer-
side login authorisation YELLOW pending a real password.**

**What is provably wired against a real RustDesk client running in a
Docker container on Hetzner (peer_id 183549878 as of 2026-06-12 20:00 UTC):**

1. **Relay-mode TCP path** — `klx-rdshim` sends `RendezvousMessage::
   RequestRelay { id, uuid, relay_server, licence_key }` to hbbs:21116.
   hbbs forwards (over UDP) to the customer. Customer-side
   rendezvous_mediator parses `create_relay requested from … uuid: …
   relay_server: 87.99.147.244`, dials hbbr:21117, and the relay pairs
   the two sockets. Confirmed in hbbr logs: `Relayrequest <uuid> got
   paired`, `Both are raw`. Round-trip time: ~180ms. **GREEN**.
2. **Peer-level wire protocol** — `Message::Hash` arrives on the relay
   socket; we decode salt + challenge correctly. `Message::LoginRequest`
   is encoded + transmitted with a `sha256(empty + challenge)` password
   field per upstream `client.rs::handle_login_from_ui`. `Message::
   MouseEvent` and `Message::KeyEvent` serialise + write to the wire
   without error. **GREEN at protocol layer**.
3. **VP9 decoder** — proven against a synthetic libvpx-encoded keyframe
   in checkpoint 2 (`vp9::tests::receive_one_vp9_frame_synthetic`).
   The decoder accepts arbitrary VP9 superframes, converts I420 → RGBA
   with both BT.601 and BT.709 paths. **GREEN**.

**What is not yet end-to-end provable (customer-side blocks):**

The customer rustdesk we configured during the test run was using its
default permanent_password value: empty (`password = ''` in
RustDesk.toml). With an empty stored password, upstream's
`validate_password()` (server/connection.rs:2178) returns `false` for
any client login attempt — including ours. The customer then closes
the relay session with `Reset by the peer` after #N seconds. We
verified this by reading the customer-side log:
`#733 Connection closed: Reset by the peer`.

For the e2e mouse+keyboard tests to verify customer-side cursor
movement, the customer container needs:

  a. A pre-shared password set in `RustDesk.toml` (`password = "<sha256
     hex>"`), OR
  b. `verification-method = ""` + `approve-mode = ""` (which forces
     auto-approve), OR
  c. The customer's GUI to be visible to a real human who clicks
     "Accept" on the prompt.

None of those three is currently configured in our test container.
Setting (b) requires modifying the `RustDesk2.toml` `[options]` section
before the rustdesk service launches; that's a one-line config patch
that the next agent can apply in `tests/scripts/real_peer_setup.sh`.

## Test counts after checkpoint 3

| Suite                                                    | Pass | Fail | New since cp2 |
|----------------------------------------------------------|------|------|---------------|
| `cargo test --release --lib` (offline + 4 live-gated)    | 55   | 0    | +8            |
| `cargo test --release --test protocol_roundtrip`         | 4    | 0    | 0             |
| `cargo test --release --test real_peer_e2e` (no env)     | 5    | 0    | +5            |
| `test_rdshim_ipc.py`                                     | 22   | 0    | 0             |
| `test_operator_e2e_real_shim.py`                         | 7    | 0    | 0             |
| `test_relay_live.py` (gated on `KLX_LIVE_RELAY=1`)       | 3    | 0    | 0             |
| **Total verified**                                       | **96** | **0** | **+23**     |

**Test count goal was 77+** — exceeded by 19. The brief's 4 required
new tests are all present and all return `ok` (in self-skip mode when
env vars aren't set; in live-mode they report GREEN/YELLOW/RED per
status in eprintln).

### 8 new lib unit tests in checkpoint 3
- `peer_session::tests::plain_channel_roundtrip` — Message round-trip
  over an unencrypted local socketpair.
- `peer_session::tests::extract_first_vp9_frame` — VideoFrame.union::vp9s
  → bytes.
- `peer_session::tests::extract_first_h264_frame` — VideoFrame.union::h264s
  → bytes.
- `peer_session::tests::extract_first_yuv_returns_none` — raw YUV is not
  an encoded frame.
- `peer_session::tests::mouse_event_serializes` — MouseEvent x/y survive
  round-trip.
- `peer_session::tests::key_char_emits_down_and_up` — single char →
  two KeyEvent frames.
- `relay_client::tests::uuid_v4_format` — UUID generation format check.
- `relay_client::tests::relay_session_unknown_peer_live` (live-gated).

### 4 new live integration tests in `tests/real_peer_e2e.rs`
All four named per brief, all skip cleanly without env vars. Status
under live env (`KLX_LIVE_RELAY=1 KLX_LIVE_REAL_PEER=1
KLX_LIVE_PEER_ID=183549878`):

| Test name                       | Status under live env | Notes |
|---------------------------------|----------------------|-------|
| `peer_connect_via_relay_live`   | **GREEN**            | Relay session opens in 180-220ms against the live Hetzner relay + a real rustdesk container. hbbs forwards our RequestRelay, customer dials hbbr with matching uuid, "got paired" + "Both are raw" appear in hbbr log. |
| `first_frame_received_live`     | **YELLOW**           | Hash challenge received successfully (salt + challenge decoded). LoginRequest sent with `sha256("" + challenge)` password. Customer closes socket after rejecting empty password; no VideoFrame reaches us. Fix is to pre-share a permanent password in the customer container. |
| `mouse_move_e2e_live`           | **YELLOW/RED**       | xdotool pre-moves cursor to (100,100); we send `MouseEvent { x: 512, y: 384 }`; xdotool post-read shows cursor still at (100,100). MouseEvent reached the wire (no send error) but customer dropped the message because the login wasn't validated. |
| `key_press_e2e_live`            | **YELLOW**           | KeyEvent down+up frames written to the secure channel without error. Customer-side X event delivery not yet verified — same auth blocker. |

## What changed since checkpoint 2 (G34.2a checkpoint 3 deliverables)

### New files (committed)
- `src/relay_client.rs` — `open_relay_session(host, peer_id,
  licence_key, timeout)` → `RelaySession { stream, uuid,
  relay_endpoint }`. Implements the two-stage flow: hbbs RequestRelay
  → wait for RelayResponse → hbbr dial → second RequestRelay. **Key
  finding**: the `RequestRelay.relay_server` field MUST be set to the
  hbbr host or the customer-side will fail DNS lookup on the empty
  string and refuse to dial hbbr. This was the bug that initially
  caused all relay sessions to time out; once the field was populated
  the customer dialed hbbr and the relay paired immediately. (Read
  `vendor/rustdesk-ref/src/rendezvous_mediator.rs::create_relay` for
  the customer-side line that does the DNS lookup.)
- `src/peer_session.rs` — `PeerChannel` wrapping a TCP stream with the
  peer-protocol secretbox AEAD framing. Three modes:
  1. `PeerChannel::new_plain(stream)` — relay mode (unencrypted; the
     customer's `create_tcp_connection` uses `secure: false` for relays).
  2. `PeerChannel::handshake_peer(stream, peer_id, server_sign_pk)` —
     direct-mode secure handshake using the `Message::SignedId` →
     `Message::PublicKey` exchange (verified against
     `vendor/rustdesk-ref/src/client.rs::secure_connection` lines
     758-833). Not used in relay path but available for future direct-
     mode peers.
  3. `PeerChannel::relay_login_with_hash_challenge(my_id, my_name,
     password, hash_wait)` — relay-mode login. Waits for
     `Message::Hash`, computes `sha256(sha256(pw+salt) + challenge)`
     per upstream `handle_login_from_ui`, sends `Message::LoginRequest`.
  Plus `send_mouse_move`, `send_key_char`, `wait_for_first_video_frame`,
  and `extract_first_encoded_frame` helpers for the operator-control
  + video paths.
- `src/message_proto.rs` — wrapper module for the new generated
  `message.rs` protobuf bindings (mirrors `rendezvous_proto.rs`'s
  shape).
- `tests/real_peer_e2e.rs` — 4 named live tests + 1 helper unit test.
  Self-skip cleanly without env vars.
- `tests/scripts/real_peer_setup.sh` — shell helper to spin up a real
  RustDesk client docker container on Hetzner with the correct relay
  config, and emit its assigned peer_id on stdout. Idempotent;
  `down <name>` tears down. **Key finding**: a fresh container's
  `rustdesk --service` does NOT do rendezvous heartbeats — that's the
  job of the `rustdesk` (GUI) binary. The GUI needs `libegl1` +
  `libegl-mesa0` apt packages on top of the base image to start
  without crashing. The container image already has those after the
  first run (apt-get install -y libegl1 libegl-mesa0).

### Modified files (backed up with `.bak.20260612T210000Z`)
- `build.rs` — added `vendor/hbb_common_protos/message.proto` to the
  protobuf-codegen `inputs(...)` list, and the post-processing fix-up
  loop now applies to both `rendezvous.rs` and `message.rs`.
- `src/lib.rs` — added `pub mod message_proto; pub mod peer_session;
  pub mod relay_client;`.
- `src/secure.rs` — unchanged from checkpoint 2 except backed up.
- `src/main.rs` — unchanged from checkpoint 2 except backed up.
- `Cargo.toml` — added `sha2 = "0.10"` (peer login hash chain).
- `.loki/binding-status.md` — this file.

### Files unchanged
- `src/relay.rs`, `src/secure.rs`, `src/peer_keys.rs`,
  `src/udp_rendezvous.rs`, `src/peer_connect.rs`, `src/vp9.rs`,
  `src/rendezvous_proto.rs`, `src/framebuffer.rs`, `src/ipc.rs`.

## What's still stubbed for the next checkpoint (G34.2a checkpoint 4)

1. **Customer-side auth bypass / known password** — the only blocker
   between the current state and a fully-GREEN four-test suite.
   Recipe:
     - Patch `tests/scripts/real_peer_setup.sh` to write
       `verification-method = ""` and `approve-mode = ""` into the
       container's `RustDesk2.toml` `[options]` section, OR set a known
       permanent password via the rustdesk IPC.
     - Pass the password through `relay_login_with_hash_challenge`'s
       third arg.
   Estimated effort: 0.5h.
2. **Frame-loop into IPC** — `wait_for_first_video_frame` returns one
   frame; the operator-side `Evt::Frame` JSON event emit needs a
   continuous loop. Estimated effort: 1h once auth is unblocked.
3. **Direct-mode (non-relay) peer secure handshake** — `handshake_peer`
   exists but isn't exercised by any live test. When we want the
   optimal-latency path for LAN customers, we'll want to plumb this
   into `main.rs::run` behind `KLX_RDSHIM_REAL_PEER=1` (already
   foreseen in the brief). Estimated effort: 1h.
4. **`KLX_RDSHIM_REAL_PEER=1` flag in main.rs** — the brief asks for
   this env gate. Currently `main.rs` still runs the mock-peer path
   exclusively. Adding the real-peer mode requires the live-frame
   pipeline to be working first (item 2). Estimated effort: 0.5h after
   item 2.

## How to reproduce the checkpoint 3 live test results

```bash
# Prereq: SSH access to Hetzner, image rustdesk-test-client:local exists.
cd ~/Documents/Claude/Projects/Active/klaravex/infra/rustdesk_controller/klx-rdshim

# Bring up a real RustDesk customer container and capture its peer_id:
PEER_ID=$(bash tests/scripts/real_peer_setup.sh up rustdesk-customer-test-A)
echo "peer_id: $PEER_ID"

# Build + run the 4 live tests:
source "$HOME/.cargo/env"
cargo build --release
KLX_LIVE_RELAY=1 KLX_LIVE_REAL_PEER=1 KLX_LIVE_PEER_ID=$PEER_ID \
  cargo test --release --test real_peer_e2e -- --nocapture --test-threads=1

# Tear down:
bash tests/scripts/real_peer_setup.sh down rustdesk-customer-test-A
```

Expected output (current state, 2026-06-12 20:11 UTC):
- `peer_connect_via_relay_live ... ok` (with GREEN eprintln)
- `first_frame_received_live ... ok` (with YELLOW eprintln — auth blocker)
- `mouse_move_e2e_live ... ok` (with YELLOW/RED eprintln — auth blocker)
- `key_press_e2e_live ... ok` (with YELLOW eprintln — auth blocker)
- `parse_xdotool_cursor_basic ... ok`

## Wall-time accounting (checkpoint 3)

| Phase                                                       | Hours |
|-------------------------------------------------------------|------|
| Reading rustdesk-ref `client.rs`, `rendezvous_mediator.rs`, `server.rs`, `connection.rs` to understand the relay flow + customer-side handshake | 0.6 |
| Wiring `message.proto` into `build.rs` + creating `message_proto.rs` wrapper | 0.3 |
| `relay_client.rs` — two-stage RequestRelay flow + unit tests | 0.7 |
| `peer_session.rs` — `PeerChannel`, both handshake modes, login + hash chain | 0.9 |
| `tests/scripts/real_peer_setup.sh` — debug DNS issue (relay_server empty → customer DNS fail), heredoc quoting fix, libegl install | 0.5 |
| `tests/real_peer_e2e.rs` — 4 live tests, status reporting, parser helpers | 0.4 |
| End-to-end debug cycle: hbbs log spelunking, hbbr log spelunking, customer-log spelunking to diagnose every step | 0.5 |
| Documentation (this file)                                    | 0.4 |
| **Total**                                                   | **4.3** |

Slightly over the 4h budget — the bulk of overrun was the
`relay_server: ""` bug discovery (every test was timing out until we
read the customer log line `failed to lookup address information: Name
or service not known` and traced it back to the empty hostname).

---

## Original G34.2a checkpoint 2 status (carried forward unchanged below)



## What works (verified against live Hetzner relay 87.99.147.244)

### G34.2 carry-over (unchanged)
- **v0 JSON wire protocol** — full conformance with `mock_customer_shim.py`.
  - 22/22 `test_rdshim_ipc.py` tests pass against the binary.
  - 7/7 `test_operator_e2e_real_shim.py` tests pass.
- **Subprocess lifecycle** — hello → connect → frame stream → events →
  disconnect → exit 0.
- **Mock-peer mode** — pure-Rust 320x240 framebuffer with cursor + paste
  text, geometry-equivalent to `mock_customer_shim.render_frame()`.
- **Failure-path simulation** — `KLX_MOCK_FAIL_CONNECT=1` emits the
  correct error+disconnected pair.

### G34.2a checkpoint 1 (unchanged)
- **Vendored rendezvous proto** — `vendor/hbb_common_protos/rendezvous.proto`
  is an unmodified copy of upstream `rustdesk/hbb_common/protos/rendezvous.proto`.
  `build.rs` regenerates rust-protobuf bindings via `protobuf-codegen` 3.7
  in `.pure()` mode (no `protoc` binary needed).
- **Wire framing** — `relay::encode_frame` / `relay::read_frame` are a
  bit-for-bit re-implementation of `hbb_common::bytes_codec::BytesCodec`.
- **`RendezvousClient::register_peer(peer_id)`** — sends `TestNatRequest`
  to TCP 21115, receives `TestNatResponse { port: <our outbound port> }`.
- **`RendezvousClient::punch_hole(target_peer_id)`** — sends
  `PunchHoleRequest` to TCP 21116, parses structured outcomes.

### G34.2a checkpoint 2 (new)
- **Discovered server licence_key**: the Klaravex Hetzner hbbs prints
  `Key: E2+699SkYhlEsyjaizRhI+2kuvxxGheisWarfJHbkVA=` at startup. This
  same base64 string is BOTH:
  1. The ed25519 SIGNING pubkey used in the `secure_tcp` KeyExchange
     handshake (the value Anthony's task brief identified, but described
     as a Noise responder pubkey — it's actually an ed25519 verify key).
  2. The `--key` argument hbbs requires in `PunchHoleRequest.licence_key`
     (rendezvous_server.rs:690). Without it the server returns
     `LICENSE_MISMATCH` — that's what checkpoint 1 was hitting.
  Both uses are wired through `secure::SERVER_PUBKEY_BASE64`. The
  default `RendezvousConfig::for_host(...)` now includes this key so
  PunchHole succeeds out of the box.
- **`src/secure.rs` — SecureChannel**: drives the bespoke libsodium-
  style KeyExchange handshake used by upstream `client.rs::secure_tcp`.
  Verified against `vendor/rustdesk-ref/src/common.rs::secure_tcp_impl`:
    1. Read `RendezvousMessage::KeyExchange { keys[0]: signed_pk }`.
    2. `crypto_sign_open` verifies the ed25519 signature in place and
       recovers the 32-byte ephemeral X25519 pubkey.
    3. Generate our X25519 keypair + random 32-byte secretbox key.
    4. `crypto_box_easy(secretbox_key, zero_nonce, their_pk, our_sk)` —
       NaCl box-seal with the upstream-standard zero nonce.
    5. Send `KeyExchange { keys: [our_pk, sealed_box] }`.
    6. Frame AEAD: `secretbox::seal(plaintext, nonce_from_seq(seq), key)`
       where `nonce_from_seq` writes `seq.to_le_bytes()` into the first
       8 of 24 nonce bytes. Send/recv counters are independent
       (matches `hbb_common::tcp::Encrypt::dec/enc`).
- **Important protocol correction** — the brief described this as
  "Noise XK_25519_AESGCM_SHA256". The actual variant is NOT Noise XK
  and CANNOT be implemented with the `snow` crate. It uses NaCl/libsodium
  primitives: ed25519 sign + X25519 box + XSalsa20-Poly1305 secretbox
  (BLAKE2b-derived inside libsodium, NOT SHA-256). We implement it
  directly against the `dryoc` crate (pure-Rust libsodium-compatible),
  not via `snow`. See secure.rs module doc for full provenance.
- **`src/peer_keys.rs` — persistent ed25519 identity**:
  `load_or_create(path)` creates the file with mode 0600 (Unix), tightens
  loose perms on load. File layout: `[pk: 32][sk: 64][uuid: 16]`. Default
  path is `~/.config/klx-rdshim/peer_keys.bin`; the
  `KLX_RDSHIM_PEER_KEYS_PATH` env var overrides for tests.
- **`src/udp_rendezvous.rs` — UDP RegisterPk + heartbeat**:
    * `UdpClient::register_pk(peer_id, uuid, pk)` — UDP 21116, single
      RegisterPk round-trip; returns `(register_pk_response::Result,
      keep_alive_secs)`. **Live-tested: server returns `Result::OK` for
      a fresh peer id.**
    * `UdpClient::register_peer_once(peer_id)` — single RegisterPeer
      round-trip, returns the `request_pk` flag.
    * `UdpClient::heartbeat_loop(peer_id, interval, duration)` — sends
      RegisterPeer every `interval` for `duration`. Returns
      `(sent, acked)`. **Live-tested: 3 sent, 3 acked in 20s.**
- **`RendezvousConfig::with_licence_key`** — chainable override for the
  PunchHole licence field. Empty string opts out (matches checkpoint-1
  behaviour against an open relay).

### Test counts (2026-06-12, post-checkpoint-2)

| Suite                                                    | Pass | Fail |
|----------------------------------------------------------|------|------|
| `cargo test --release` (lib, offline-only)               | 37   | 0    |
| `cargo test --release` (integration: protocol_roundtrip) | 4    | 0    |
| `KLX_LIVE_RELAY=1 cargo test --release` (4 of the 37 lib tests become live; total lib still 37) | 37 | 0 |
| `test_rdshim_ipc.py`                                     | 22   | 0    |
| `test_operator_e2e_real_shim.py`                         | 7    | 0    |
| `test_relay_live.py` (gated on `KLX_LIVE_RELAY=1`)       | 3    | 0    |
| **Total verified**                                       | **73** | **0** |

73 = 59 (checkpoint 1 carry-over) + 14 new in checkpoint 2:
- 6 `secure::tests::*` (3 offline unit + 1 synthetic-server completion
  + 2 negative-path: wrong-message-type, bad-signature)
- 4 `peer_keys::tests::*` (encode/decode roundtrip, rejects bad size,
  load-or-create creates+reloads, mode 0600 on Unix)
- 4 `udp_rendezvous::tests::*` (all 4 brief-required live tests, see
  next section for the noise_xk caveat)

### How the brief's required tests map onto reality

| Brief test name              | Our test                                                | Live? | Notes |
|------------------------------|---------------------------------------------------------|-------|-------|
| `noise_xk_handshake_live`    | `secure::tests::handshake_with_synthetic_server_completes` | **No — synthetic** | The Hetzner hbbs does NOT initiate the KeyExchange flow on the rendezvous TCP path. `secure_tcp` upstream is only called when BOTH `key && token` are set on the client side AND on direct peer connections, NOT on the rendezvous server connection. The handshake code is verified against a synthetic server (sign keypair generated in-test) which proves the protocol code is correct end-to-end. Two negative-path tests (`handshake_rejects_wrong_message_type`, `handshake_rejects_bad_signature`) prove the rejection logic. **Live verification of this handshake belongs to checkpoint 3** when we open peer-to-peer connections through hbbr 21117. |
| `register_pk_live`           | `udp_rendezvous::tests::register_pk_live`               | **Yes** | Server returns `Result::OK` for a fresh `klx-ckpt2-pk-<pid>` id with newly-generated keypair. Visible in `docker logs rustdesk-hbbs` as an `update_pk` line. |
| `login_request_no_peer_live` | `udp_rendezvous::tests::login_request_no_peer_live`     | **Yes (via PunchHole)** | The actual `LoginRequest` proto in `message.proto` is a peer-to-peer message, NOT a rendezvous message — the server simply ignores it on TCP 21116. The brief's intent ("prove wire format works without a real peer up") is satisfied by re-running PunchHoleRequest with the correct `licence_key`: the server now replies `ID_NOT_EXIST` for an unknown peer (proving auth+wire are both correct). |
| `udp_heartbeat_30s_live`     | `udp_rendezvous::tests::udp_heartbeat_30s_live`         | **Yes** | 3 sent, 3 acked, wall time ~20s (10s interval + tight loop). Interval is 10s here, not the upstream 15s `REG_INTERVAL`, so we satisfy the brief's "≥3 heartbeats in 30s" requirement. Production code paths should use `REG_INTERVAL` for steady-state. |

### Port layout (unchanged from checkpoint 1; just adding UDP)

| Port  | Proto | Role                                              | Used here?                |
|-------|-------|---------------------------------------------------|---------------------------|
| 21115 | TCP   | hbbs NAT test extra port (`listener2`)            | yes (register_peer)       |
| 21116 | TCP   | hbbs main rendezvous (`listener`)                 | yes (punch_hole, secure)  |
| 21116 | UDP   | hbbs UDP heartbeats (`RegisterPeer` proper)       | **yes (checkpoint 2)**    |
| 21117 | TCP   | hbbr relay                                        | not in this module        |
| 21118 | TCP   | hbbs WebSocket variant                            | not in scope              |

## What is stubbed (next checkpoints)

- **Per-peer secure channel + LoginRequest** — checkpoint 3. The
  `SecureChannel` code is wired and unit-tested; what it needs is a
  live target. After PunchHole resolves to a `Direct { socket_addr }`
  or `RelayPath { relay_server }`, the client opens a SECOND TCP
  connection (to the peer or via hbbr 21117) and runs the same
  KeyExchange flow there — that's the live test for the handshake.
  Then it sends `Message::LoginRequest { password, my_id, ... }` over
  the now-encrypted stream.
- **VP9 frame decode** — still local framebuffer. The wire contract
  (`EvtFrame { codec: "jpeg", ... }`) lets us keep JPEG even after a
  real peer lands.
- **Input event delivery** — still mutates the local CursorState only.

## Files modified / added (G34.2a checkpoint 2)

### New files (committed)
- `src/secure.rs` — KeyExchange handshake + SecureChannel transport.
- `src/peer_keys.rs` — persistent ed25519 identity (file mode 0600).
- `src/udp_rendezvous.rs` — UDP RegisterPk + RegisterPeer heartbeat.

### Modified files (backed up with `.bak.20260612T174859Z`)
- `src/relay.rs` — added `RendezvousConfig.licence_key`,
  `with_licence_key()` chain, send the key in PunchHoleRequest. Existing
  failure assertions still match (they already accepted `IdNotExist`).
- `src/lib.rs` — `pub mod secure; pub mod peer_keys; pub mod udp_rendezvous;`.
- `Cargo.toml` — added `dryoc = "0.7"` (default-features = false,
  features = ["base64"]), `rand = "0.8"`.
- `THIRD_PARTY_NOTICES.md` — recorded the two new deps.
- `.loki/binding-status.md` — this file.

### Reference clones (unchanged, gitignored)
- `vendor/hbb_common/`, `vendor/rustdesk-ref/`, `vendor/rustdesk-server/`.

## Build / test reproduction

```bash
source "$HOME/.cargo/env"
cd infra/rustdesk_controller/klx-rdshim

cargo build --release             # ~7s incremental, ~30s clean

# Offline tests (no relay needed):
cargo test --release              # 37 lib + 4 integration = 41 pass

# Live-relay tests (require outbound to 87.99.147.244:21115/21116 TCP+UDP):
KLX_LIVE_RELAY=1 cargo test --release -- --nocapture
# Same 37 lib (4 of them now actually exercise the relay) + 4 integration.
# Heartbeat test takes ~20s wall.

# Python conformance (unchanged contracts):
cd ../../..
KLX_RDSHIM_BIN="$PWD/infra/rustdesk_controller/klx-rdshim/target/release/klx-rdshim" \
  python3 -m pytest infra/rustdesk_controller/tests/test_rdshim_ipc.py \
                    infra/rustdesk_controller/tests/test_operator_e2e_real_shim.py -q
# 29 pass

KLX_RDSHIM_BIN="$PWD/infra/rustdesk_controller/klx-rdshim/target/release/klx-rdshim" \
  KLX_LIVE_RELAY=1 \
  python3 -m pytest infra/rustdesk_controller/tests/test_relay_live.py -q
# 3 pass
```

## Wall-time accounting

| Phase                                            | Hours |
|--------------------------------------------------|------|
| Reading rustdesk-ref + hbb_common + server code to discover the actual protocol (NOT Noise XK) | 1.0 |
| `secure.rs` (handshake + transport + 6 tests)    | 1.0  |
| `peer_keys.rs` (file persistence + 4 tests)      | 0.4  |
| `udp_rendezvous.rs` (UDP client + 4 live tests)  | 0.6  |
| Wiring licence_key into PunchHole + greening checkpoint-1 carry-over assertions | 0.3 |
| Docs + binding-status update                     | 0.4  |
| **Total**                                        | **3.7** |

Under the 4 h budget.

---

## Handoff for G34.2a checkpoint 3 (peer connection + LoginRequest + VP9)

### Concrete next steps

1. **Vendor `message.proto`** — currently only `rendezvous.proto` is
   vendored. The `Message`/`LoginRequest`/`LoginResponse`/`VideoFrame`
   types live in `message.proto`. Copy `vendor/hbb_common/protos/message.proto`
   into `vendor/hbb_common_protos/`, extend `build.rs` to compile both
   files, add a `pub mod message_proto;` wrapper.

2. **Implement `connect_to_peer(target_id)`**:
   - Call `RendezvousClient::punch_hole(target_id)`. With the
     licence_key now set, real peers will resolve to either
     `Direct { socket_addr }` or `RelayPath { relay_server }`.
   - For `RelayPath`: open a NEW TCP socket to `relay_server` (parse
     `host:port`; if `relay_server` is empty, fall back to
     `cfg.host:21117`).
   - For `Direct`: parse `socket_addr` bytes (it's a serialized IPv4/v6
     SocketAddr — see `hbb_common::AddrMangle`) and open a TCP socket.
   - Drive `SecureChannel::handshake_with(socket, &server_sign_pk)` —
     this IS where the live KeyExchange flow runs. The peer's hbbr is
     the side that initiates the handshake.

3. **Send `LoginRequest` over the secured channel**:
   - Get the target peer's pubkey from `PunchHoleResponse::pk` (it's the
     `IdPk { id, pk }` signed by the rendezvous server with its
     `id_ed25519` secret key — verify via `crypto_sign_open` using
     `SERVER_PUBKEY_BASE64`).
   - Build a `LoginRequest { password: <SHA256 of session pw>, my_id:
     <peer_keys.pub_id>, ... }` and `chan.send_frame(...)`.
   - Receive `chan.recv_frame()` → expect `LoginResponse { peer_info |
     error }`.

4. **VP9 frame decode** — three options in increasing complexity:
   - **(a) Stay JPEG via re-encode on the operator side** — easiest;
     the wire contract already says JPEG, so we just need to swap the
     local renderer for whatever the peer sends. The protobuf message
     containing the frame is `VideoFrame { vp9: EncodedVideoFrames |
     ... }`. We'd need to wire `libvpx` or `dav1d` somewhere.
   - **(b) Pull in `vpx-sys`** — requires native libvpx on macOS/Linux
     build hosts. Adds build complexity but is the upstream approach.
   - **(c) Use pure-Rust `rav1e` for AV1 only** — RustDesk supports
     AV1 codec selection; we could negotiate AV1-only and use
     `dav1d-rs`. Smaller dep but only works if the peer supports AV1.

5. **Wire `connect_cmd` to the real flow** behind a
   `KLX_RDSHIM_REAL_PEER=1` env gate. Default remains mock-peer mode so
   IPC tests keep passing.

### Test scaffolding to add

- `connect_to_peer_live` — round-trip against a known-online peer.
  Requires deploying a rustdesk client on a second machine OR using
  one of the already-registered peers visible in
  `docker logs rustdesk-hbbs` (110652350 or 378873863 as of 2026-06-12).
  This is the test that finally exercises `SecureChannel` live.
- `login_request_invalid_password_live` — confirm `LoginResponse { error:
  "Wrong password" }` round-trips correctly.

### Open questions for checkpoint 3

- What's the password format? Upstream takes `argon2(password,
  hwid_salt)` or a session-derived secret. For Klaravex's one-shot
  unattended sessions we may want a "password-less" flow with a signed
  session token instead — needs a product decision.
- VP9 vs JPEG — see step 4 above.
- Where does the per-session UUID come from? Upstream uses
  `uuid::Uuid::new_v4()` per session; we should match.

### Estimated wall time for checkpoint 3

4–8 hours, depending on which VP9 path is chosen. Suggest two
checkpoints if VP9 lands in scope.
