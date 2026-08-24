//! In-shim simulated framebuffer.
//!
//! The first iteration of `klx-rdshim` ships a Rust implementation of the
//! same render path the Python `mock_customer_shim.py` uses, so the
//! operator-side e2e suite can target the real binary and exercise the
//! full subprocess + JSON wire transport without librustdesk linkage on
//! the host.
//!
//! Output format: baseline JPEG, RGB, 320x240 default, drawn from a
//! `CursorState` that the input-event loop mutates.
//!
//! Visual contract (matches mock_customer_shim.py::render_frame):
//!   - Black background
//!   - Red cursor dot (radius 4 px) at (cursor.x * w, cursor.y * h)
//!     clamped so the dot stays on-canvas
//!   - White horizontal bar on row 0, length = (seq % w), so tests can
//!     verify frame ordering
//!   - Blue horizontal bar on row 2, length = min(w-1, typed_text.len()),
//!     so paste_text propagation is visible
//!
//! The dot/bar geometry is identical to the Python mock so the existing
//! e2e cursor-centroid assertions pass byte-for-byte.

use std::io;
use std::time::{SystemTime, UNIX_EPOCH};

use jpeg_encoder::{ColorType, Encoder};

/// Tracks the simulated customer-side cursor + input state.
#[derive(Debug, Clone)]
pub struct CursorState {
    /// Normalized 0–1 of framebuffer width.
    pub x: f64,
    /// Normalized 0–1 of framebuffer height.
    pub y: f64,
    pub last_button: Option<String>,
    pub last_key: Option<String>,
    pub typed_text: String,
    pub modifiers: Vec<String>,
}

impl Default for CursorState {
    fn default() -> Self {
        Self {
            x: 0.5,
            y: 0.5,
            last_button: None,
            last_key: None,
            typed_text: String::new(),
            modifiers: Vec::new(),
        }
    }
}

impl CursorState {
    /// Mutate this cursor state per an incoming v0 InputEvent.
    pub fn apply(&mut self, event: &crate::ipc::InputEvent) {
        match event.event_kind.as_str() {
            "mouse_move" => {
                if let Some(x) = event.x {
                    self.x = x;
                }
                if let Some(y) = event.y {
                    self.y = y;
                }
            }
            "mouse_click" => {
                self.last_button = Some(
                    event
                        .button
                        .clone()
                        .unwrap_or_else(|| "left".to_string()),
                );
            }
            "mouse_scroll" => {
                self.last_button = Some("scroll".to_string());
            }
            "key_down" | "key_up" | "key_press" => {
                self.last_key = Some(event.key.clone().unwrap_or_default());
                self.modifiers = event.modifiers.clone();
            }
            "paste_text" => {
                if let Some(t) = &event.text {
                    self.typed_text.push_str(t);
                }
            }
            _ => {}
        }
    }
}

/// Encode a single RGB framebuffer as a JPEG byte buffer.
///
/// `width` * `height` * 3 RGB bytes in `pixels`.
fn encode_jpeg(pixels: &[u8], width: u16, height: u16) -> Result<Vec<u8>, String> {
    let mut out = Vec::with_capacity((width as usize) * (height as usize) / 4);
    let encoder = Encoder::new(&mut out, 70);
    encoder
        .encode(pixels, width, height, ColorType::Rgb)
        .map_err(|e| format!("jpeg encode failed: {e}"))?;
    Ok(out)
}

/// Encode a decoded RGBA framebuffer as a baseline JPEG byte buffer.
///
/// `rgba` must hold `w*h*4` bytes (row-major, R/G/B/A per pixel). Quality
/// is fixed at 75 — a deliberate notch above the mock framebuffer's 70 to
/// avoid visible chroma blocks on real screen content, but still small
/// enough to comfortably ride the JSON-line IPC channel.
///
/// G34.2c — used by `peer_session::stream_session` to re-encode the
/// VP9-decoded customer screen as JPEG before emitting `EvtFrame`. The
/// caller hands us a freshly-decoded `RgbaFrame.pixels` slice; we own no
/// allocations beyond the encoder's output buffer.
pub fn encode_rgba_as_jpeg(rgba: &[u8], w: u32, h: u32) -> io::Result<Vec<u8>> {
    if w == 0 || h == 0 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "encode_rgba_as_jpeg: zero dimensions",
        ));
    }
    if w > u16::MAX as u32 || h > u16::MAX as u32 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "encode_rgba_as_jpeg: dimensions exceed u16",
        ));
    }
    let expected = (w as usize)
        .checked_mul(h as usize)
        .and_then(|n| n.checked_mul(4))
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                "encode_rgba_as_jpeg: dimensions overflow usize",
            )
        })?;
    if rgba.len() < expected {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!(
                "encode_rgba_as_jpeg: buffer too small: {} < {expected}",
                rgba.len()
            ),
        ));
    }
    let mut out = Vec::with_capacity((w as usize) * (h as usize) / 4);
    let encoder = Encoder::new(&mut out, 75);
    encoder
        .encode(&rgba[..expected], w as u16, h as u16, ColorType::Rgba)
        .map_err(|e| {
            io::Error::new(
                io::ErrorKind::Other,
                format!("encode_rgba_as_jpeg: {e}"),
            )
        })?;
    Ok(out)
}

/// Render one frame of the simulated customer framebuffer and return
/// (jpeg_bytes, timestamp_ms).
///
/// Mirrors `mock_customer_shim.render_frame()` byte-for-byte in terms of
/// geometry so the operator e2e cursor-detection assertions pass.
pub fn render_frame(
    width: u32,
    height: u32,
    cursor: &CursorState,
    seq: u64,
) -> Result<(Vec<u8>, u64), String> {
    if width == 0 || height == 0 {
        return Err("framebuffer dimensions must be > 0".into());
    }
    if width > u16::MAX as u32 || height > u16::MAX as u32 {
        return Err("framebuffer dimensions exceed u16".into());
    }

    let w = width as usize;
    let h = height as usize;
    let mut pixels = vec![0u8; w * h * 3]; // black background

    // Red cursor dot — filled circle, radius 4, matching the Python mock's
    // `draw.ellipse([cx-4, cy-4, cx+4, cy+4], fill=(255,0,0))`.
    let cx = (cursor.x * width as f64) as i32;
    let cy = (cursor.y * height as f64) as i32;
    let cx = cx.max(4).min(width as i32 - 5);
    let cy = cy.max(4).min(height as i32 - 5);
    let r: i32 = 4;
    for dy in -r..=r {
        for dx in -r..=r {
            // PIL ellipse uses the bounding-box pixel test; a 9x9
            // square is what (cx-4..cx+4, cy-4..cy+4) inclusive
            // produces. We do the same rectangle-bounded circle to
            // match the centroid the Python mock produces under JPEG
            // quantization.
            if dx * dx + dy * dy <= r * r + r {
                let px = cx + dx;
                let py = cy + dy;
                if px >= 0 && py >= 0 && (px as u32) < width && (py as u32) < height {
                    let idx = ((py as usize) * w + (px as usize)) * 3;
                    pixels[idx] = 255;
                    pixels[idx + 1] = 0;
                    pixels[idx + 2] = 0;
                }
            }
        }
    }

    // White sequence bar on row 0, length = max(1, seq % width).
    let bar_len = (seq % width as u64).max(1) as usize;
    for px in 0..bar_len.min(w) {
        let idx = px * 3;
        pixels[idx] = 255;
        pixels[idx + 1] = 255;
        pixels[idx + 2] = 255;
    }

    // Blue strip on row 2 (offset by 2*w pixels) when typed_text present.
    if !cursor.typed_text.is_empty() {
        let n = cursor.typed_text.len().min(w - 1);
        let row_offset = 2 * w * 3;
        for px in 0..=n {
            let idx = row_offset + px * 3;
            if idx + 2 < pixels.len() {
                pixels[idx] = 0;
                pixels[idx + 1] = 0;
                pixels[idx + 2] = 200;
            }
        }
        // Row 3 too — PIL's `rectangle([0,2,n,3])` fills inclusive both rows.
        let row_offset = 3 * w * 3;
        for px in 0..=n {
            let idx = row_offset + px * 3;
            if idx + 2 < pixels.len() {
                pixels[idx] = 0;
                pixels[idx + 1] = 0;
                pixels[idx + 2] = 200;
            }
        }
    }

    let jpeg = encode_jpeg(&pixels, width as u16, height as u16)?;
    let ts = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0);
    Ok((jpeg, ts))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ipc::InputEvent;

    #[test]
    fn render_default_frame_is_valid_jpeg() {
        let cursor = CursorState::default();
        let (jpeg, _ts) = render_frame(320, 240, &cursor, 0).expect("encode ok");
        // JPEG SOI marker
        assert!(jpeg.len() > 4);
        assert_eq!(&jpeg[..2], &[0xff, 0xd8]);
        // EOI marker
        let last2 = &jpeg[jpeg.len() - 2..];
        assert_eq!(last2, &[0xff, 0xd9]);
    }

    #[test]
    fn apply_mouse_move_updates_position() {
        let mut c = CursorState::default();
        let ev = InputEvent {
            event_kind: "mouse_move".into(),
            x: Some(0.25),
            y: Some(0.75),
            ..Default::default()
        };
        c.apply(&ev);
        assert!((c.x - 0.25).abs() < 1e-9);
        assert!((c.y - 0.75).abs() < 1e-9);
    }

    #[test]
    fn encode_rgba_as_jpeg_magenta_roundtrip() {
        // 320x240 magenta RGBA frame — full opacity. Encoder must emit a
        // baseline JPEG starting with the SOI marker 0xFFD8.
        const W: u32 = 320;
        const H: u32 = 240;
        let mut rgba = vec![0u8; (W as usize) * (H as usize) * 4];
        for px in rgba.chunks_exact_mut(4) {
            px[0] = 255; // R
            px[1] = 0; // G
            px[2] = 255; // B
            px[3] = 255; // A
        }
        let jpeg = encode_rgba_as_jpeg(&rgba, W, H).expect("encode ok");
        assert!(jpeg.len() > 4, "JPEG output too short: {}", jpeg.len());
        assert_eq!(
            &jpeg[..2],
            &[0xFF, 0xD8],
            "JPEG SOI magic missing"
        );
        assert_eq!(
            &jpeg[jpeg.len() - 2..],
            &[0xFF, 0xD9],
            "JPEG EOI magic missing"
        );
    }

    #[test]
    fn encode_rgba_as_jpeg_rejects_short_buffer() {
        // 4 bytes for a 2x2 frame — caller would need 16. Reject loudly.
        let rgba = vec![0u8; 4];
        let result = encode_rgba_as_jpeg(&rgba, 2, 2);
        assert!(result.is_err(), "expected error for too-short buffer");
    }

    #[test]
    fn apply_paste_text_accumulates() {
        let mut c = CursorState::default();
        let ev1 = InputEvent {
            event_kind: "paste_text".into(),
            text: Some("hello".into()),
            ..Default::default()
        };
        let ev2 = InputEvent {
            event_kind: "paste_text".into(),
            text: Some(" world".into()),
            ..Default::default()
        };
        c.apply(&ev1);
        c.apply(&ev2);
        assert_eq!(c.typed_text, "hello world");
    }
}
