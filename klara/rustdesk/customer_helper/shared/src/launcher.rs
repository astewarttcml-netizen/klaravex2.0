//! Launches and supervises the bundled RustDesk subprocess.
//!
//! The bundled binary is the official RustDesk client (1.4.7), shipped as a
//! sidecar via Tauri's externalBin mechanism. Per AGPL §13 we ship it as a
//! separate executable — we do NOT statically link it. Source for the
//! RustDesk client is on github.com/rustdesk/rustdesk and the customer can
//! obtain it with `klaravex-helper --print-rustdesk-source`.
//!
//! On launch we pass the per-session ID via `--password` (RustDesk reads it
//! from the config we already wrote) and `--connect <id>` so the customer
//! doesn't have to do anything beyond clicking "Allow" once.
//!
//! Wait — clarification: in **unattended** mode the customer DOES NOT
//! initiate the connection. The customer is the host. The operator dials
//! in. So we launch RustDesk as a service (`--service` on Linux, the
//! installed RustDesk service on Windows/macOS), then watch its stdout/log
//! for the "Online" indicator.

use anyhow::{Context, Result};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Manager};
use tracing::{info, warn};

use crate::token::Session;

pub struct ManagedChild {
    pub child: Child,
}

/// Stored on the AppHandle so the STOP button (and exit cleanup) can kill it.
pub struct ChildHandle(pub Arc<Mutex<Option<ManagedChild>>>);

impl Default for ChildHandle {
    fn default() -> Self {
        Self(Arc::new(Mutex::new(None)))
    }
}

pub fn register_child(app: &AppHandle, child: ManagedChild) {
    if let Some(handle) = app.try_state::<ChildHandle>() {
        let mut guard = handle.0.lock().unwrap();
        *guard = Some(child);
    } else {
        // First registration — install the state slot.
        app.manage(ChildHandle(Arc::new(Mutex::new(Some(child)))));
    }
}

pub fn kill_child(app: &AppHandle) {
    if let Some(handle) = app.try_state::<ChildHandle>() {
        let mut guard = handle.0.lock().unwrap();
        if let Some(mut managed) = guard.take() {
            let _ = managed.child.kill();
            let _ = managed.child.wait();
            info!("RustDesk subprocess killed");
        }
    }
}

pub fn spawn_rustdesk(session: &Session) -> Result<ManagedChild> {
    let bin = locate_bundled_rustdesk()?;
    info!(binary = %bin.display(), "spawning RustDesk");

    let mut cmd = Command::new(&bin);
    // The config we wrote in config.rs already pins everything; we just need
    // to start the host service.
    if cfg!(target_os = "linux") {
        cmd.arg("--service");
    } else if cfg!(target_os = "windows") {
        // RustDesk on Windows uses `--option` to run with custom config dir.
        cmd.arg("--start-service");
    } else if cfg!(target_os = "macos") {
        // On macOS, the bundle's main binary runs as the host when no args.
        // Pre-flight: ensure the Accessibility/Screen-Recording prompt has
        // been shown. We can't grant these — only the user can — but we
        // can pre-warm them by issuing a dummy CGEventCreate (handled by
        // RustDesk's own first-run dance).
    }
    cmd.arg("--password").arg(&session.session_password);

    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

    let child = cmd
        .spawn()
        .with_context(|| format!("spawn {}", bin.display()))?;

    Ok(ManagedChild { child })
}

fn locate_bundled_rustdesk() -> Result<PathBuf> {
    // Tauri places sidecar binaries next to the main executable, suffixed
    // with the target triple. We try the unsuffixed name first (dev builds),
    // then the triple variants.
    let exe = std::env::current_exe().context("current_exe")?;
    let dir = exe.parent().context("current_exe parent")?;

    let candidates = if cfg!(target_os = "windows") {
        vec!["rustdesk.exe", "rustdesk-x86_64-pc-windows-msvc.exe"]
    } else if cfg!(target_os = "macos") {
        vec![
            "rustdesk",
            "rustdesk-aarch64-apple-darwin",
            "rustdesk-x86_64-apple-darwin",
        ]
    } else {
        vec!["rustdesk", "rustdesk-x86_64-unknown-linux-gnu"]
    };

    for name in &candidates {
        let p = dir.join(name);
        if p.exists() {
            return Ok(p);
        }
        // Tauri also drops sidecars in ../Resources/ on macOS bundles.
        let p2 = dir.join("../Resources").join(name);
        if p2.exists() {
            return Ok(p2);
        }
    }

    warn!(
        "no bundled rustdesk binary found in {} — falling back to PATH",
        dir.display()
    );
    Ok(PathBuf::from("rustdesk"))
}
