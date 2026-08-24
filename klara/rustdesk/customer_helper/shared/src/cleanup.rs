//! Cleanup: kill RustDesk subprocess + wipe all on-disk state.
//!
//! Called from:
//!   - cmd_stop_session (STOP button)
//!   - RunEvent::Exit (window closed, ctrl-c, OS shutdown)
//!   - top-level error paths (defensive: if redeem or write fails, wipe
//!     anything we might have partially written so the customer is never
//!     left with a config that could be replayed)
//!
//! This function MUST be idempotent — it can run twice if the user clicks
//! STOP and the app then exits.

use anyhow::Result;
use std::fs;
use tauri::AppHandle;
use tracing::{info, warn};

use crate::config;
use crate::launcher;

pub fn wipe_all(app: &AppHandle) -> Result<()> {
    // 1. Kill the RustDesk subprocess (if running).
    launcher::kill_child(app);

    // 2. Delete the config + sibling files we wrote.
    match config::managed_paths() {
        Ok(paths) => {
            for p in paths {
                match fs::remove_file(&p) {
                    Ok(()) => info!(path = %p.display(), "wiped"),
                    Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                    Err(e) => warn!(path = %p.display(), error = ?e, "wipe failed"),
                }
            }
        }
        Err(e) => warn!(error = ?e, "could not enumerate managed paths"),
    }

    // 3. Best-effort: nuke any RustDesk-installed service.
    //    On Linux: `systemctl --user stop rustdesk` (no-op if not installed).
    //    On Windows: `sc stop rustdesk` (no-op if not installed).
    //    On macOS: `launchctl unload ~/Library/LaunchAgents/com.carriez.rustdesk.plist`.
    //    Each is fire-and-forget; we don't surface errors because the user
    //    may never have installed the service in the first place.
    stop_rustdesk_service();

    Ok(())
}

#[cfg(target_os = "linux")]
fn stop_rustdesk_service() {
    let _ = std::process::Command::new("systemctl")
        .args(["--user", "stop", "rustdesk"])
        .output();
}

#[cfg(target_os = "macos")]
fn stop_rustdesk_service() {
    if let Some(home) = dirs::home_dir() {
        let plist = home.join("Library/LaunchAgents/com.carriez.rustdesk.plist");
        if plist.exists() {
            let _ = std::process::Command::new("launchctl")
                .args(["unload", "-w"])
                .arg(&plist)
                .output();
        }
    }
}

#[cfg(target_os = "windows")]
fn stop_rustdesk_service() {
    let _ = std::process::Command::new("sc")
        .args(["stop", "rustdesk"])
        .output();
}
