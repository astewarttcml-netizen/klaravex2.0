//! Build-time codegen for the rustdesk rendezvous protobuf bindings.
//!
//! Generates `$OUT_DIR/protos/rendezvous.rs` from the vendored
//! `vendor/hbb_common_protos/rendezvous.proto` (copy of
//! `rustdesk/hbb_common/protos/rendezvous.proto`). The generated module
//! is included from `src/rendezvous_proto.rs`.
//!
//! We use the `protobuf-codegen` crate in `pure()` mode — same as upstream
//! hbb_common's own build.rs — so we do NOT need a `protoc` binary on the
//! build host.

fn main() {
    let out_dir = std::env::var("OUT_DIR").expect("OUT_DIR not set");
    let proto_out = format!("{out_dir}/protos");
    std::fs::create_dir_all(&proto_out).expect("create OUT_DIR/protos");

    // Track the source for incremental rebuilds.
    println!("cargo:rerun-if-changed=vendor/hbb_common_protos/rendezvous.proto");
    println!("cargo:rerun-if-changed=vendor/hbb_common_protos/message.proto");
    println!("cargo:rerun-if-changed=build.rs");

    protobuf_codegen::Codegen::new()
        .pure()
        .out_dir(&proto_out)
        .inputs([
            "vendor/hbb_common_protos/rendezvous.proto",
            "vendor/hbb_common_protos/message.proto",
        ])
        .include("vendor/hbb_common_protos")
        // We deliberately do NOT enable `tokio_bytes` here — the upstream
        // hbb_common build uses it to make field types `bytes::Bytes`,
        // but we'd have to pull in the `bytes` crate as a runtime dep.
        // Default (Vec<u8>) is simpler and adequate for the rendezvous
        // protocol — RegisterPeer/PunchHole payloads are small.
        .run()
        .expect("protobuf codegen failed for rendezvous.proto");

    // protobuf-codegen emits inner attributes (`#![allow(...)]`) at the
    // top of the generated file, plus an inner doc comment (`//! ...`)
    // further down. When we pull the file in via `include!()` at module
    // body level, the inner attributes after the first item are rejected
    // by rustc (E0753). Rewrite each `#![...]` → `#[...]` and each `//! `
    // → `// ` so the generated module is a clean self-contained body
    // when included.
    //
    // Apply this fix to both generated files (rendezvous.rs + message.rs).
    for gen_name in ["rendezvous.rs", "message.rs"] {
        let gen_path = format!("{proto_out}/{gen_name}");
        if !std::path::Path::new(&gen_path).exists() {
            continue;
        }
        let raw = std::fs::read_to_string(&gen_path)
            .unwrap_or_else(|e| panic!("read generated {gen_name}: {e}"));
        let mut fixed = String::with_capacity(raw.len());
        for line in raw.lines() {
            let trimmed = line.trim_start();
            if let Some(rest) = trimmed.strip_prefix("#![") {
                let leading = &line[..line.len() - trimmed.len()];
                fixed.push_str(leading);
                fixed.push_str("#[");
                fixed.push_str(rest);
                fixed.push('\n');
            } else if let Some(rest) = trimmed.strip_prefix("//!") {
                let leading = &line[..line.len() - trimmed.len()];
                fixed.push_str(leading);
                fixed.push_str("//");
                fixed.push_str(rest);
                fixed.push('\n');
            } else {
                fixed.push_str(line);
                fixed.push('\n');
            }
        }
        std::fs::write(&gen_path, fixed)
            .unwrap_or_else(|e| panic!("write fixed {gen_name}: {e}"));
    }
}
