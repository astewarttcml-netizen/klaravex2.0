// Generated peer-protocol protobuf bindings.
//
// The actual Rust source is emitted by `build.rs` into
// `$OUT_DIR/protos/message.rs` from `vendor/hbb_common_protos/message.proto`.
// `build.rs` post-processes that file the same way it does for
// `rendezvous.rs` so the file can be `include!()`ed at module body level
// without rustc complaining (E0753).
//
// This proto file is an unmodified copy of
// `https://github.com/rustdesk/hbb_common/blob/master/protos/message.proto`.
// See `THIRD_PARTY_NOTICES.md` for license details.
//
// G34.2a checkpoint 3: introduced so the peer-side `Message::SignedId`
// handshake, `Message::PublicKey` reply, `Message::LoginRequest`, and
// `Message::VideoFrame` parsing can be implemented in pure Rust without
// linking the upstream hbb_common crate.

#[allow(clippy::all)]
#[allow(unknown_lints)]
#[allow(unused_imports)]
#[allow(unused_mut)]
#[allow(unused_results)]
#[allow(unused_attributes)]
#[allow(unused_qualifications)]
#[allow(unused_parens)]
#[allow(unused_variables)]
#[allow(dead_code)]
#[allow(non_snake_case)]
#[allow(non_camel_case_types)]
#[allow(non_upper_case_globals)]
#[allow(trivial_casts)]
#[allow(missing_docs)]
#[allow(renamed_and_removed_lints)]
#[allow(bare_trait_objects)]
#[rustfmt::skip]
mod gen {
    include!(concat!(env!("OUT_DIR"), "/protos/message.rs"));
}

pub use gen::*;
