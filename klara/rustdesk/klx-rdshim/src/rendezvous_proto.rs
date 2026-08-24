// Generated rendezvous protobuf bindings.
//
// The actual Rust source is emitted by `build.rs` into
// `$OUT_DIR/protos/rendezvous.rs` from `vendor/hbb_common_protos/rendezvous.proto`.
// `build.rs` post-processes that file to demote inner attributes
// (`#![...]`) and inner doc comments (`//!`) to their outer equivalents,
// so the file can be `include!()`ed at module body level without rustc
// complaining (E0753).
//
// The proto file is an unmodified copy of
// `https://github.com/rustdesk/hbb_common/blob/master/protos/rendezvous.proto`.
// See `THIRD_PARTY_NOTICES.md` for license details.

// Silence all warnings from the auto-generated code — the originals were
// `#![allow(...)]` in the generated file before build.rs converted them
// to outer attrs that no longer apply at file scope.
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
    include!(concat!(env!("OUT_DIR"), "/protos/rendezvous.rs"));
}

pub use gen::*;
