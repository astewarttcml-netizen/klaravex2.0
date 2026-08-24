# Third-party notices — klx-rdshim

This crate links to or vendors the following third-party components.
Every vendored or generated file is enumerated here, with provenance and
license terms as best they can be determined.

## Vendored protobuf source

**File:** `vendor/hbb_common_protos/rendezvous.proto`

**Upstream:** https://github.com/rustdesk/hbb_common/blob/master/protos/rendezvous.proto

**Provenance:** unmodified copy from
`rustdesk/hbb_common@HEAD` as of 2026-06-12.

**License:** the upstream `rustdesk/hbb_common` repository does NOT
contain a top-level `LICENSE` file. The parent project
`rustdesk/rustdesk` declares **AGPL-3.0-or-later** for its source tree.
Out of caution, we treat this `.proto` file as AGPL-3.0-licensed.

The G34.2a checkpoint-1 binding regenerates Rust types from this `.proto`
file at build time. The generated Rust code is also a derivative work and
is treated under the same license, but only the `klx_rdshim::rendezvous_proto`
module — not the whole `klx-rdshim` crate.

This is acceptable for the Klaravex operator-side shim because:

1. The `klx-rdshim` binary is internal tooling for our own MSP operations,
   not redistributed to clients.
2. If `klx-rdshim` ever becomes a distributed artifact, we will either:
   - re-license the crate (AGPL is viral on combined works), or
   - replace the vendored proto with a hand-rolled definition file that
     describes the same wire format. The wire format itself is not
     copyrightable; only the .proto source file is.

## Rust dependencies

| Crate | Version | License | Reason |
|-------|---------|---------|--------|
| `serde` | 1.0 | MIT/Apache-2.0 | JSON IPC serialization |
| `serde_json` | 1.0 | MIT/Apache-2.0 | JSON IPC parsing |
| `base64` | 0.22 | MIT/Apache-2.0 | JPEG payload encoding |
| `jpeg-encoder` | 0.6 | MIT | Framebuffer JPEG output |
| `protobuf` | 3.7 | MIT/Apache-2.0 | Rendezvous protocol runtime |
| `protobuf-codegen` | 3.7 | MIT/Apache-2.0 | Build-time .proto → Rust |
| `dryoc` | 0.7 | MIT/Apache-2.0 | NaCl-compatible crypto (ed25519, X25519, XSalsa20-Poly1305). Pure Rust, no native libsodium link. |
| `rand` | 0.8 | MIT/Apache-2.0 | Random secretbox key / UUID generation |
| `env-libvpx-sys` | 5.1 | MIT | Rust FFI bindings for libvpx (VP9 decoder for G34.2b peer-frame ingest, VP9 encoder for the synthetic-fixture unit test). The `generate` feature runs bindgen at build time against the system libvpx headers, so we automatically track whatever libvpx version is installed (Homebrew 1.16 on the dev macs, libvpx-dev on the Hetzner build host). |

All transitive Rust crate deps inherit the MIT or Apache-2.0 license per
their respective `Cargo.toml` declarations. No GPL or AGPL Rust crates
are pulled in directly or transitively — that boundary stays at the
.proto file only.

## Native dependency — libvpx

**Component:** `libvpx` (built and installed by the host operating
system; **not** vendored or statically linked).

**Upstream:** https://github.com/webmproject/libvpx

**License:** BSD-3-Clause (the WebM project license — see
`https://github.com/webmproject/libvpx/blob/main/LICENSE` and the
`PATENTS` grant in the same repository).

**Linkage:** `env-libvpx-sys` emits `cargo:rustc-link-lib=vpx`, which
dynamic-links against the system `libvpx.dylib` (macOS) /
`libvpx.so.*` (Linux). We deliberately do NOT statically link or
redistribute libvpx. On distribution hosts the operator is responsible
for installing libvpx via `brew install libvpx` (macOS),
`apt install libvpx-dev` (Debian/Ubuntu), or the equivalent.

**License compatibility note:** libvpx is BSD-3-Clause, which is
compatible with both MIT and Apache-2.0. The BSD-3 attribution
requirement is satisfied by this NOTICES file plus the requirement that
operators install libvpx through their OS package manager (which carries
its own copy of the upstream `LICENSE` file).

**Patent grant:** the WebM project's `PATENTS` file grants a royalty-free
patent license for VP8/VP9 use in any "implementation of the WebM
Project". Decoding peer-side screen-share VP9 frames inside the Klaravex
operator console qualifies.

## Reference repositories (read-only, NOT vendored)

`vendor/hbb_common/` and `vendor/rustdesk-ref/` contain sparse clones of
`rustdesk/hbb_common` and `rustdesk/rustdesk` respectively. These are
used at development time as **reference documentation only** (to confirm
port numbers, framing details, and handler logic). They are NOT compiled
into the `klx-rdshim` binary. They are listed in `.gitignore` and should
not be committed.
