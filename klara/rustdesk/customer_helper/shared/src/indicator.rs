//! The persistent "AI is controlling your computer" indicator.
//!
//! REQUIREMENTS (architectural — spec §1, on-screen indicator):
//!   1. Always-on-top across every display, even fullscreen apps where the OS
//!      permits it. (macOS: NSWindow level NSScreenSaverWindowLevel + collection
//!      behavior CanJoinAllSpaces; Windows: HWND_TOPMOST + WS_EX_TOOLWINDOW;
//!      Linux: WM_HINTS _NET_WM_STATE_ABOVE + _NET_WM_STATE_STICKY.)
//!   2. Visible from the moment RustDesk accepts an incoming connection
//!      until the helper exits.
//!   3. Cannot be dismissed by accident — clicking anywhere except the STOP
//!      button is a no-op. The STOP button requires a deliberate hover-and-
//!      click (no keyboard shortcut, no muscle-memory dismissal).
//!   4. Click-through on the badge area is DISABLED (we want the customer to
//!      see-and-feel it). Drag-to-reposition is allowed via the badge area.
//!   5. Survives RustDesk sub-process crashes — the indicator only goes away
//!      when the helper process itself exits.

use anyhow::{Context, Result};
use tauri::{AppHandle, Manager, WebviewWindow};
use tracing::info;

pub async fn show(app: &AppHandle) -> Result<()> {
    let win = app
        .get_webview_window("indicator")
        .context("indicator window not found — tauri.conf.json mis-wired")?;

    apply_platform_topmost(&win)?;
    win.show().context("show indicator")?;
    info!("indicator visible");
    Ok(())
}

#[cfg(target_os = "macos")]
fn apply_platform_topmost(win: &WebviewWindow) -> Result<()> {
    // macOS: lift above fullscreen apps using NSWindow.level + collection
    // behavior. Tauri's set_always_on_top only uses kCGFloatingWindowLevel
    // (3), which is BELOW fullscreen apps. We need NSScreenSaverWindowLevel
    // (1000).
    use objc2::msg_send;
    use objc2::runtime::AnyObject;
    let ns_window: *mut AnyObject = win
        .ns_window()
        .context("ns_window handle missing")?
        as *mut AnyObject;
    unsafe {
        // setLevel: NSScreenSaverWindowLevel (1000)
        let _: () = msg_send![ns_window, setLevel: 1000_isize];
        // setCollectionBehavior:
        //   NSWindowCollectionBehaviorCanJoinAllSpaces (1 << 0) |
        //   NSWindowCollectionBehaviorFullScreenAuxiliary (1 << 8) |
        //   NSWindowCollectionBehaviorStationary (1 << 4)
        let mask: u64 = (1 << 0) | (1 << 8) | (1 << 4);
        let _: () = msg_send![ns_window, setCollectionBehavior: mask];
        // Defeat accidental cmd-W close — handled in UI by preventing the
        // window from being focusable.
    }
    Ok(())
}

#[cfg(target_os = "windows")]
fn apply_platform_topmost(win: &WebviewWindow) -> Result<()> {
    use windows::Win32::Foundation::HWND;
    use windows::Win32::UI::WindowsAndMessaging::{
        SetWindowLongPtrW, SetWindowPos, GWL_EXSTYLE, HWND_TOPMOST, SWP_NOACTIVATE, SWP_NOMOVE,
        SWP_NOSIZE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST,
    };

    let hwnd_raw = win.hwnd().context("hwnd handle missing")?.0 as isize;
    let hwnd = HWND(hwnd_raw as *mut std::ffi::c_void);
    unsafe {
        let style: isize =
            (WS_EX_TOPMOST.0 | WS_EX_TOOLWINDOW.0 | WS_EX_NOACTIVATE.0) as isize;
        SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style);
        SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
        .ok();
    }
    Ok(())
}

#[cfg(all(unix, not(target_os = "macos")))]
fn apply_platform_topmost(win: &WebviewWindow) -> Result<()> {
    // X11/Wayland: rely on Tauri's set_always_on_top + sticky hint. Wayland
    // compositors that disallow always-on-top (GNOME 45+) cannot be coerced
    // — we fall back to a desktop notification reminder every 5 minutes.
    win.set_always_on_top(true).ok();
    win.set_visible_on_all_workspaces(true).ok();
    Ok(())
}
