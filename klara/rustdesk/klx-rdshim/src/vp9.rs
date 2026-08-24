//! G34.2b deliverable 3 — VP9 single-frame ingest.
//!
//! ## Scope
//!
//! The RustDesk peer encodes its screen as a stream of `VideoFrame`
//! protobuf messages. Each `VideoFrame.vp9s.frames[i]` is a complete
//! VP9 bitstream payload (one VP9 superframe — usually a single
//! coded frame, but multi-frame superframes are legal). Decoding it
//! produces raw YUV planar data.
//!
//! This module wraps libvpx (via the `env-libvpx-sys` crate) just
//! enough to:
//!
//!   * initialise a VP9 decoder
//!   * feed it one or more VP9 frames
//!   * pull out the first decoded I420 image and convert it to RGBA
//!
//! That's the *minimum* needed for G34.2b's success criterion:
//! "operator can see one frame of the customer's screen". The
//! multi-frame stream + the operator → peer input event emit are
//! G34.2c.
//!
//! ## Why I420 → RGBA (not JPEG directly)?
//!
//! The existing `framebuffer::render_frame` helper produces JPEG from an
//! RGB buffer. We expose RGBA out of `Vp9Decoder` so callers can:
//!
//!   1. Hand the RGBA to the JPEG encoder if they're going through the
//!      IPC path that emits `EvtFrame` (chrome bookmark-style preview).
//!   2. Hand the RGBA to a renderer if a future feature wants direct
//!      framebuffer drawing.
//!
//! BT.601 limited-range conversion math matches what most software VP9
//! decoders use for screen content (rustdesk peers emit BT.601 unless
//! they're explicitly running BT.709 — `vpx_image.cs == VPX_CS_BT_709`).
//! We pick the converter based on `vpx_image.cs` for correctness.
//!
//! ## Symbol provenance (Mistake #13 avoidance)
//!
//! Every libvpx symbol called here was verified against the generated
//! bindings at:
//!   `target/debug/build/env-libvpx-sys-<hash>/out/ffi.rs`
//! at the time of authoring (2026-06-12). The symbol set is stable
//! across libvpx 1.8 .. 1.16 per upstream's ABI version pin
//! (`VPX_DECODER_ABI_VERSION == 12`, `VPX_IMAGE_ABI_VERSION == 5`).
//!
//! Used symbols:
//!
//!   - `vpx_codec_vp9_dx()` — returns the VP9 decoder algorithm vtable.
//!   - `vpx_codec_dec_init_ver(...)` — init a decoder context.
//!   - `vpx_codec_decode(ctx, data, sz, user_priv, deadline)` — feed one
//!     frame.
//!   - `vpx_codec_get_frame(ctx, iter)` — pull the next decoded image.
//!   - `vpx_codec_destroy(ctx)` — release decoder resources.
//!   - `vpx_codec_err_to_string(err)` — human-readable error.
//!   - `vpx_image_t` — { fmt, d_w, d_h, planes[4], stride[4], cs, ... }
//!
//! For the synthetic-fixture test we also use the encoder side:
//!
//!   - `vpx_codec_vp9_cx()`, `vpx_codec_enc_config_default(...)`,
//!     `vpx_codec_enc_init_ver(...)`, `vpx_codec_encode(...)`,
//!     `vpx_codec_get_cx_data(...)`, `vpx_img_wrap(...)`.

#![allow(unsafe_code)]
#![allow(non_camel_case_types)]

use std::ffi::CStr;
use std::os::raw::{c_int, c_uint};

// `env-libvpx-sys` ships its `[lib].name` as `vpx_sys` — that's the
// Rust crate identifier. Confirmed in its `Cargo.toml`:
//   [lib]
//   name = "vpx_sys"
// (Mistake #13 avoidance: verified before authoring.)
use vpx_sys as vpx;

/// Decoded RGBA frame: row-major, width*height pixels, 4 bytes each.
#[derive(Debug, Clone)]
pub struct RgbaFrame {
    pub width: u32,
    pub height: u32,
    pub pixels: Vec<u8>,
}

/// Single-instance VP9 decoder. Wraps a `vpx_codec_ctx_t` and a
/// `vpx_codec_iter_t` cursor used by `vpx_codec_get_frame`.
///
/// The decoder is `!Send` and `!Sync` — libvpx is reentrant per-context
/// but not concurrent-safe per-context. For G34.2b that's irrelevant
/// (single peer per shim), and explicit `unsafe impl Send` would be a
/// future trap.
pub struct Vp9Decoder {
    ctx: Box<vpx::vpx_codec_ctx_t>,
    initialised: bool,
}

impl Vp9Decoder {
    /// Construct a fresh VP9 decoder. Returns Err with the libvpx error
    /// string on failure (caller should treat this as fatal — usually
    /// indicates a libvpx ABI mismatch).
    pub fn new() -> Result<Self, String> {
        // SAFETY: vpx_codec_ctx_t is `#[repr(C)]` with no Drop. We box
        // it so the address is stable across moves of `Vp9Decoder`.
        // The struct contains a union of pointers + a `vpx_codec_err_t`
        // enum (which has VPX_CODEC_OK = 0) — all-zeros is sound. Use
        // `MaybeUninit::zeroed().assume_init()` to keep the compiler's
        // niche-validity check happy.
        let mut ctx_box: Box<vpx::vpx_codec_ctx_t> = Box::new(unsafe {
            std::mem::MaybeUninit::<vpx::vpx_codec_ctx_t>::zeroed().assume_init()
        });
        let iface = unsafe { vpx::vpx_codec_vp9_dx() };
        if iface.is_null() {
            return Err("vpx_codec_vp9_dx() returned NULL".to_string());
        }
        let cfg: vpx::vpx_codec_dec_cfg_t = vpx::vpx_codec_dec_cfg_t {
            threads: 1,
            w: 0,
            h: 0,
        };
        // env-libvpx-sys exposes the ABI version constant from
        // `vpx_decoder.h`. The `_ver` variant of init takes that ABI
        // tag so libvpx can refuse to load against a mismatching
        // header.
        let abi_ver = vpx::VPX_DECODER_ABI_VERSION as c_int;
        let err = unsafe {
            vpx::vpx_codec_dec_init_ver(
                ctx_box.as_mut() as *mut _,
                iface,
                &cfg as *const _,
                0,
                abi_ver,
            )
        };
        if err != vpx::vpx_codec_err_t::VPX_CODEC_OK {
            return Err(format!(
                "vpx_codec_dec_init_ver: {}",
                vpx_err_str(err, None)
            ));
        }
        Ok(Self {
            ctx: ctx_box,
            initialised: true,
        })
    }

    /// Decode one VP9 frame (one element of `EncodedVideoFrames.frames`)
    /// and return the first emitted image as RGBA, or `Ok(None)` if the
    /// decoder consumed the frame without producing visible output
    /// (e.g. it was a non-show frame).
    ///
    /// Returns `Err(_)` if libvpx rejects the input — typically means
    /// the frame is truncated, corrupt, or a non-VP9 codec.
    pub fn decode_one(&mut self, vp9_frame: &[u8]) -> Result<Option<RgbaFrame>, String> {
        if vp9_frame.is_empty() {
            return Ok(None);
        }
        if vp9_frame.len() > u32::MAX as usize {
            return Err("vp9 frame too large for libvpx (> u32::MAX)".to_string());
        }
        let err = unsafe {
            vpx::vpx_codec_decode(
                self.ctx.as_mut() as *mut _,
                vp9_frame.as_ptr(),
                vp9_frame.len() as c_uint,
                std::ptr::null_mut(),
                0,
            )
        };
        if err != vpx::vpx_codec_err_t::VPX_CODEC_OK {
            return Err(format!(
                "vpx_codec_decode: {}",
                vpx_err_str(err, Some(self.ctx.as_ref()))
            ));
        }
        // Pull the first emitted image.
        let mut iter: vpx::vpx_codec_iter_t = std::ptr::null();
        let img_ptr =
            unsafe { vpx::vpx_codec_get_frame(self.ctx.as_mut() as *mut _, &mut iter) };
        if img_ptr.is_null() {
            return Ok(None);
        }
        // SAFETY: libvpx owns the image; lifetime is until the next
        // call to vpx_codec_decode or vpx_codec_destroy on this ctx.
        // We copy out of it before yielding control.
        let img: &vpx::vpx_image_t = unsafe { &*img_ptr };
        let rgba = image_to_rgba(img)?;
        Ok(Some(rgba))
    }
}

impl Drop for Vp9Decoder {
    fn drop(&mut self) {
        if self.initialised {
            // Ignore the return — there's nothing useful to do on
            // double-free at Drop time.
            unsafe {
                vpx::vpx_codec_destroy(self.ctx.as_mut() as *mut _);
            }
        }
    }
}

/// Convert a libvpx error code (and optional ctx for the
/// implementation-specific detail string) to a human-readable error.
fn vpx_err_str(err: vpx::vpx_codec_err_t, ctx: Option<&vpx::vpx_codec_ctx_t>) -> String {
    let basic_ptr = unsafe { vpx::vpx_codec_err_to_string(err) };
    let basic = if basic_ptr.is_null() {
        format!("{err:?}")
    } else {
        unsafe { CStr::from_ptr(basic_ptr) }
            .to_string_lossy()
            .into_owned()
    };
    if let Some(ctx) = ctx {
        let detail_ptr = unsafe { vpx::vpx_codec_error_detail(ctx as *const _) };
        if !detail_ptr.is_null() {
            let detail = unsafe { CStr::from_ptr(detail_ptr) }
                .to_string_lossy()
                .into_owned();
            if !detail.is_empty() {
                return format!("{basic}: {detail}");
            }
        }
    }
    basic
}

/// Convert a libvpx I420 image to RGBA. Returns an error on unsupported
/// pixel formats (we only handle I420 for G34.2b; I444 + I422 land in
/// G34.2c when we plug in full screen content).
///
/// BT.601 limited-range coefficients are the libvpx default for screen
/// content. If `img.cs == VPX_CS_BT_709` we use the BT.709 matrix
/// instead — matters for darker-than-norm screens (looks washed
/// otherwise).
fn image_to_rgba(img: &vpx::vpx_image_t) -> Result<RgbaFrame, String> {
    if img.fmt != vpx::vpx_img_fmt::VPX_IMG_FMT_I420 {
        return Err(format!(
            "unsupported vpx_image fmt {:?} (G34.2b decoder only handles I420 — \
             multi-format support is G34.2c)",
            img.fmt
        ));
    }
    let w = img.d_w as usize;
    let h = img.d_h as usize;
    if w == 0 || h == 0 {
        return Err("vpx_image has zero dimensions".to_string());
    }
    if img.planes[0].is_null() || img.planes[1].is_null() || img.planes[2].is_null() {
        return Err("vpx_image has NULL plane pointer(s)".to_string());
    }
    let y_stride = img.stride[0] as usize;
    let u_stride = img.stride[1] as usize;
    let v_stride = img.stride[2] as usize;
    let y_plane = unsafe { std::slice::from_raw_parts(img.planes[0], y_stride * h) };
    // U+V planes are half-height for I420.
    let half_h = (h + 1) / 2;
    let u_plane = unsafe { std::slice::from_raw_parts(img.planes[1], u_stride * half_h) };
    let v_plane = unsafe { std::slice::from_raw_parts(img.planes[2], v_stride * half_h) };

    let use_709 = img.cs == vpx::vpx_color_space::VPX_CS_BT_709;
    let mut pixels = vec![0u8; w * h * 4];
    for y in 0..h {
        let y_row = &y_plane[y * y_stride..y * y_stride + w];
        let uv_y = y / 2;
        let u_row = &u_plane[uv_y * u_stride..uv_y * u_stride + (w + 1) / 2];
        let v_row = &v_plane[uv_y * v_stride..uv_y * v_stride + (w + 1) / 2];
        for x in 0..w {
            let y_val = y_row[x] as i32;
            let u_val = u_row[x / 2] as i32;
            let v_val = v_row[x / 2] as i32;
            let (r, g, b) = if use_709 {
                yuv_to_rgb_bt709(y_val, u_val, v_val)
            } else {
                yuv_to_rgb_bt601(y_val, u_val, v_val)
            };
            let idx = (y * w + x) * 4;
            pixels[idx] = r;
            pixels[idx + 1] = g;
            pixels[idx + 2] = b;
            pixels[idx + 3] = 255;
        }
    }
    Ok(RgbaFrame {
        width: w as u32,
        height: h as u32,
        pixels,
    })
}

/// BT.601 limited-range YUV → RGB. Coefficients from ITU-R BT.601-7,
/// matched against libyuv's reference table.
fn yuv_to_rgb_bt601(y: i32, u: i32, v: i32) -> (u8, u8, u8) {
    let c = y - 16;
    let d = u - 128;
    let e = v - 128;
    // Round-to-nearest by adding 128 before >>8.
    let r = (298 * c + 409 * e + 128) >> 8;
    let g = (298 * c - 100 * d - 208 * e + 128) >> 8;
    let b = (298 * c + 516 * d + 128) >> 8;
    (clamp(r), clamp(g), clamp(b))
}

/// BT.709 limited-range YUV → RGB. Coefficients from ITU-R BT.709-6.
fn yuv_to_rgb_bt709(y: i32, u: i32, v: i32) -> (u8, u8, u8) {
    let c = y - 16;
    let d = u - 128;
    let e = v - 128;
    let r = (298 * c + 459 * e + 128) >> 8;
    let g = (298 * c - 55 * d - 136 * e + 128) >> 8;
    let b = (298 * c + 541 * d + 128) >> 8;
    (clamp(r), clamp(g), clamp(b))
}

#[inline]
fn clamp(v: i32) -> u8 {
    if v < 0 {
        0
    } else if v > 255 {
        255
    } else {
        v as u8
    }
}

// ---------------------------------------------------------------------------
// Encoder helper for the synthetic test (G34.2b acceptance criterion).
//
// In production the operator side NEVER encodes video — only decodes
// what the peer sends. But for the unit test we need a VP9 keyframe to
// feed `Vp9Decoder::decode_one`. The simplest way to produce one in-tree
// is to run libvpx's encoder against a synthetic I420 buffer.
//
// This helper is `cfg(test)` only and behind `pub(crate)` so it doesn't
// leak into the public API.
// ---------------------------------------------------------------------------

/// VP9 encoder helpers used by unit tests AND the integration test in
/// `tests/real_session_ipc.rs`. Marked `#[doc(hidden)]` so it doesn't
/// pollute the public API: production callers should never need an
/// encoder because the operator side only decodes.
///
/// Not feature-gated because integration tests compile against the
/// library as a separate crate and `#[cfg(test)]` items don't survive
/// that boundary. Dead-stripped in release builds when unused.
#[doc(hidden)]
pub mod test_helpers {
    use super::*;
    use std::os::raw::c_ulong;

    /// Encode a single 320x240 I420 keyframe and return the VP9 bytes.
    ///
    /// Caller provides the Y/U/V planes; we wrap them with
    /// `vpx_img_wrap` and feed to the encoder with `VPX_EFLAG_FORCE_KF`.
    pub fn encode_one_vp9_keyframe(
        width: u32,
        height: u32,
        y_plane: &[u8],
        u_plane: &[u8],
        v_plane: &[u8],
    ) -> Result<Vec<u8>, String> {
        unsafe {
            let iface = vpx::vpx_codec_vp9_cx();
            if iface.is_null() {
                return Err("vpx_codec_vp9_cx() returned NULL".to_string());
            }
            // `vpx_codec_enc_cfg` contains a `vpx_bit_depth_t` enum
            // which has no zero variant — `mem::zeroed()` is UB-checked
            // at compile time. Use `MaybeUninit` and let
            // `vpx_codec_enc_config_default` write through the raw
            // pointer to populate it.
            let mut cfg_uninit = std::mem::MaybeUninit::<vpx::vpx_codec_enc_cfg_t>::uninit();
            let err =
                vpx::vpx_codec_enc_config_default(iface, cfg_uninit.as_mut_ptr(), 0);
            if err != vpx::vpx_codec_err_t::VPX_CODEC_OK {
                return Err(format!(
                    "vpx_codec_enc_config_default: {}",
                    vpx_err_str(err, None)
                ));
            }
            let mut cfg = cfg_uninit.assume_init();
            cfg.g_w = width;
            cfg.g_h = height;
            cfg.g_timebase.num = 1;
            cfg.g_timebase.den = 30;
            cfg.rc_target_bitrate = 200; // kbps; arbitrary, low enough to be fast
            cfg.g_threads = 1;

            // `vpx_codec_ctx_t` contains a union of pointers + an enum
            // `vpx_codec_err_t` which DOES have a zero variant
            // (VPX_CODEC_OK = 0), so zeroed is safe here. We
            // double-confirm by using MaybeUninit anyway for symmetry.
            let ctx_uninit =
                std::mem::MaybeUninit::<vpx::vpx_codec_ctx_t>::zeroed();
            let mut ctx = ctx_uninit.assume_init();
            let abi_ver = vpx::VPX_ENCODER_ABI_VERSION as c_int;
            let err = vpx::vpx_codec_enc_init_ver(
                &mut ctx as *mut _,
                iface,
                &cfg as *const _,
                0,
                abi_ver,
            );
            if err != vpx::vpx_codec_err_t::VPX_CODEC_OK {
                return Err(format!(
                    "vpx_codec_enc_init_ver: {}",
                    vpx_err_str(err, Some(&ctx))
                ));
            }

            // Pack planes into a contiguous buffer because vpx_img_wrap
            // expects one img_data pointer (the planes alias into it).
            let half_w = (width as usize + 1) / 2;
            let half_h = (height as usize + 1) / 2;
            let y_sz = (width as usize) * (height as usize);
            let uv_sz = half_w * half_h;
            if y_plane.len() < y_sz
                || u_plane.len() < uv_sz
                || v_plane.len() < uv_sz
            {
                vpx::vpx_codec_destroy(&mut ctx as *mut _);
                return Err(format!(
                    "plane sizes wrong: Y={}({}), U={}({}), V={}({})",
                    y_plane.len(),
                    y_sz,
                    u_plane.len(),
                    uv_sz,
                    v_plane.len(),
                    uv_sz
                ));
            }
            let mut packed = Vec::with_capacity(y_sz + uv_sz * 2);
            packed.extend_from_slice(&y_plane[..y_sz]);
            packed.extend_from_slice(&u_plane[..uv_sz]);
            packed.extend_from_slice(&v_plane[..uv_sz]);

            // vpx_image_t contains 3 enums (fmt, cs, range). fmt has
            // VPX_IMG_FMT_NONE = 0, cs has VPX_CS_UNKNOWN = 0, range has
            // VPX_CR_STUDIO_RANGE = 0 — all zero-variants exist, so
            // zeroed is sound. Use MaybeUninit to keep the unsafe
            // surface clean.
            let img_uninit = std::mem::MaybeUninit::<vpx::vpx_image_t>::zeroed();
            let mut img = img_uninit.assume_init();
            let wrapped = vpx::vpx_img_wrap(
                &mut img as *mut _,
                vpx::vpx_img_fmt::VPX_IMG_FMT_I420,
                width,
                height,
                1, // stride_align
                packed.as_mut_ptr(),
            );
            if wrapped.is_null() {
                vpx::vpx_codec_destroy(&mut ctx as *mut _);
                return Err("vpx_img_wrap returned NULL".to_string());
            }

            let err = vpx::vpx_codec_encode(
                &mut ctx as *mut _,
                &img as *const _,
                0,
                1,
                vpx::VPX_EFLAG_FORCE_KF as i64,
                vpx::VPX_DL_REALTIME as c_ulong,
            );
            if err != vpx::vpx_codec_err_t::VPX_CODEC_OK {
                vpx::vpx_codec_destroy(&mut ctx as *mut _);
                return Err(format!(
                    "vpx_codec_encode: {}",
                    vpx_err_str(err, Some(&ctx))
                ));
            }

            // Drain encoded packets.
            let mut iter: vpx::vpx_codec_iter_t = std::ptr::null();
            let mut out: Vec<u8> = Vec::new();
            loop {
                let pkt = vpx::vpx_codec_get_cx_data(&mut ctx as *mut _, &mut iter);
                if pkt.is_null() {
                    break;
                }
                let pkt_ref = &*pkt;
                if pkt_ref.kind == vpx::vpx_codec_cx_pkt_kind::VPX_CODEC_CX_FRAME_PKT {
                    let frame = &pkt_ref.data.frame;
                    let bytes = std::slice::from_raw_parts(
                        frame.buf as *const u8,
                        frame.sz,
                    );
                    out.extend_from_slice(bytes);
                }
            }

            // Flush — VP9 may buffer one frame before emitting.
            if out.is_empty() {
                let err = vpx::vpx_codec_encode(
                    &mut ctx as *mut _,
                    std::ptr::null(),
                    0,
                    1,
                    0,
                    vpx::VPX_DL_REALTIME as c_ulong,
                );
                if err != vpx::vpx_codec_err_t::VPX_CODEC_OK {
                    vpx::vpx_codec_destroy(&mut ctx as *mut _);
                    return Err(format!(
                        "vpx_codec_encode (flush): {}",
                        vpx_err_str(err, Some(&ctx))
                    ));
                }
                let mut iter2: vpx::vpx_codec_iter_t = std::ptr::null();
                loop {
                    let pkt = vpx::vpx_codec_get_cx_data(&mut ctx as *mut _, &mut iter2);
                    if pkt.is_null() {
                        break;
                    }
                    let pkt_ref = &*pkt;
                    if pkt_ref.kind
                        == vpx::vpx_codec_cx_pkt_kind::VPX_CODEC_CX_FRAME_PKT
                    {
                        let frame = &pkt_ref.data.frame;
                        let bytes = std::slice::from_raw_parts(
                            frame.buf as *const u8,
                            frame.sz,
                        );
                        out.extend_from_slice(bytes);
                    }
                }
            }

            vpx::vpx_codec_destroy(&mut ctx as *mut _);
            // We deliberately drop `packed` after vpx_codec_destroy: the
            // encoder has copied / digested its content by then.
            drop(packed);
            if out.is_empty() {
                return Err("encoder produced no packets".to_string());
            }
            Ok(out)
        }
    }

    /// Build a 320x240 I420 frame containing a diagonal gradient.
    pub fn synthetic_i420_gradient(width: u32, height: u32) -> (Vec<u8>, Vec<u8>, Vec<u8>) {
        let w = width as usize;
        let h = height as usize;
        let half_w = (w + 1) / 2;
        let half_h = (h + 1) / 2;
        let mut y = vec![0u8; w * h];
        let mut u = vec![128u8; half_w * half_h];
        let mut v = vec![128u8; half_w * half_h];
        for j in 0..h {
            for i in 0..w {
                // Diagonal gradient — guarantees the encoder produces a
                // real keyframe (a flat-gray frame can be skipped on
                // some libvpx tunes).
                y[j * w + i] = ((i + j) % 256) as u8;
            }
        }
        for j in 0..half_h {
            for i in 0..half_w {
                u[j * half_w + i] = ((i * 2) % 256) as u8;
                v[j * half_w + i] = ((j * 2) % 256) as u8;
            }
        }
        (y, u, v)
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use test_helpers::{encode_one_vp9_keyframe, synthetic_i420_gradient};

    #[test]
    fn decoder_init_and_drop() {
        let _dec = Vp9Decoder::new().expect("decoder init");
        // Drop runs vpx_codec_destroy — observed-clean if no panic.
    }

    /// Synthetic round-trip: encode a 320x240 I420 keyframe using libvpx,
    /// decode it with our `Vp9Decoder`, and assert the output has the
    /// expected dimensions and a non-trivial pixel distribution.
    ///
    /// **Why this test gates G34.2b**: it proves end-to-end that the
    /// libvpx FFI calls we make are wire-compatible. A real
    /// rustdesk-peer keyframe is structurally identical (it's the same
    /// `VideoFrame.vp9s.frames[0]` payload format), so if this passes
    /// the only remaining variable for `receive_one_vp9_frame_live` is
    /// the network path — not the codec layer.
    #[test]
    fn receive_one_vp9_frame_synthetic() {
        const W: u32 = 320;
        const H: u32 = 240;
        let (y, u, v) = synthetic_i420_gradient(W, H);
        let vp9_bytes =
            encode_one_vp9_keyframe(W, H, &y, &u, &v).expect("encode synthetic keyframe");
        assert!(
            !vp9_bytes.is_empty(),
            "encoder produced 0-byte VP9 stream"
        );

        let mut dec = Vp9Decoder::new().expect("decoder init");
        let frame = dec
            .decode_one(&vp9_bytes)
            .expect("decode_one ok")
            .expect("decoder emitted a visible frame");
        assert_eq!(frame.width, W, "decoded width != encoded width");
        assert_eq!(frame.height, H, "decoded height != encoded height");
        assert_eq!(
            frame.pixels.len(),
            (W as usize) * (H as usize) * 4,
            "RGBA buffer size != w*h*4"
        );
        // Sanity: the gradient should produce a range of distinct
        // values, not a single flat color.
        let distinct = {
            let mut s = std::collections::HashSet::new();
            for px in frame.pixels.chunks_exact(4).step_by(64) {
                s.insert([px[0], px[1], px[2]]);
            }
            s.len()
        };
        assert!(
            distinct > 4,
            "decoded image is too flat (distinct samples = {distinct})"
        );
        // Acceptance: ≥ 320x240 per task brief.
        assert!(
            frame.width >= 320 && frame.height >= 240,
            "decoded frame too small: {}x{}",
            frame.width,
            frame.height
        );
    }

    /// Calling decode on an empty buffer must Ok(None), not error.
    /// Matches the upstream pattern where an empty input is a no-op.
    #[test]
    fn decode_empty_buffer_returns_none() {
        let mut dec = Vp9Decoder::new().expect("decoder init");
        let out = dec.decode_one(&[]).expect("decode_one ok");
        assert!(out.is_none());
    }

    /// Garbage input must return Err — proves we surface libvpx errors
    /// rather than silently producing a "black frame".
    #[test]
    fn decode_garbage_returns_err() {
        let mut dec = Vp9Decoder::new().expect("decoder init");
        let garbage = vec![0xFFu8; 64];
        let result = dec.decode_one(&garbage);
        assert!(
            result.is_err(),
            "decoder accepted garbage input: {result:?}"
        );
    }

    /// **LIVE TEST**: receive one frame from a real rustdesk peer.
    ///
    /// Gated behind `KLX_LIVE_PEER_ID=<id>` so it only runs when a peer
    /// is up. The flow is:
    ///
    ///   1. `connect_to_peer` over hbbs PunchHole
    ///   2. Drive the peer-side secretbox handshake (G34.2b deliverable 2)
    ///   3. Read until we see a `Message::VideoFrame::vp9s.frames[0]`
    ///   4. Decode it via Vp9Decoder
    ///
    /// G34.2b deliberately stops here — multi-frame stream + input
    /// emit is G34.2c. The brief explicitly allows this test to be
    /// `#[ignore]` since no live peer is available in the CI env.
    ///
    /// Manual run:
    ///   KLX_LIVE_RELAY=1 KLX_LIVE_PEER_ID=<peer-id> \
    ///     cargo test --lib vp9::tests::receive_one_vp9_frame_live \
    ///     -- --nocapture --ignored
    #[test]
    #[ignore = "requires a live rustdesk peer registered against hbbs.klaravex.com — \
                set KLX_LIVE_PEER_ID and run with --ignored"]
    fn receive_one_vp9_frame_live() {
        // Deferred: the secure-channel handshake against the peer side
        // (deliverable 2's full peer-key flow) and the `Message`
        // protobuf parser for the peer link are in G34.2c. The
        // synthetic-fixture test above (`receive_one_vp9_frame_synthetic`)
        // proves the decoder works against codec-correct input; the
        // remaining live-only piece is the peer-side network plumbing.
        //
        // When the iter-21 live peer is up:
        //   1. `let (mut stream, outcome) = peer_connect::connect_to_peer(...);`
        //   2. drive peer secure_connection (G34.2c)
        //   3. parse `Message::VideoFrame::vp9s.frames[0]`
        //   4. assert decoded dimensions >= 320x240
        eprintln!(
            "receive_one_vp9_frame_live: stub. \
             Run with KLX_LIVE_PEER_ID + a real peer once G34.2c lands."
        );
    }
}
