//! Writes the pre-baked RustDesk2.toml that pins the RustDesk client to
//! Klaravex's relay + the per-session ID and password.
//!
//! Path resolution by platform:
//!   macOS   ~/Library/Preferences/com.carriez.RustDesk/RustDesk2.toml
//!   Linux   ~/.config/rustdesk/RustDesk2.toml
//!   Windows %AppData%\RustDesk\config\RustDesk2.toml
//!
//! We never write to a system-wide location — this helper is single-user,
//! single-session by design. The customer should NOT be left with a config
//! that survives a reboot.
//!
//! On exit (see cleanup.rs) we delete every file we wrote AND the parent
//! directory IF it is empty AND we created it.

use anyhow::{Context, Result};
use serde::Serialize;
use std::fs;
use std::path::{Path, PathBuf};
use tracing::info;

use crate::token::Session;

/// Resolve the per-OS RustDesk config file path.
pub fn config_path() -> Result<PathBuf> {
    let base = if cfg!(target_os = "macos") {
        dirs::home_dir()
            .context("no home dir")?
            .join("Library/Preferences/com.carriez.RustDesk")
    } else if cfg!(target_os = "windows") {
        dirs::config_dir()
            .context("no AppData dir")?
            .join("RustDesk/config")
    } else {
        dirs::config_dir()
            .context("no XDG_CONFIG_HOME / .config dir")?
            .join("rustdesk")
    };
    Ok(base.join("RustDesk2.toml"))
}

/// All paths the helper writes — used by cleanup::wipe_all.
pub fn managed_paths() -> Result<Vec<PathBuf>> {
    let cfg = config_path()?;
    let parent = cfg
        .parent()
        .context("config path has no parent")?
        .to_path_buf();
    // Sibling files RustDesk creates next to RustDesk2.toml.
    Ok(vec![
        cfg.clone(),
        parent.join("RustDesk.toml"),
        parent.join("RustDesk_local.toml"),
        parent.join("fingerprint"),
    ])
}

#[derive(Serialize)]
struct RustDeskConfig<'a> {
    #[serde(rename = "rendezvous_server")]
    rendezvous_server: &'a str,
    #[serde(rename = "nat_type")]
    nat_type: i32,
    serial: i32,
    options: Options<'a>,
}

#[derive(Serialize)]
struct Options<'a> {
    #[serde(rename = "custom-rendezvous-server")]
    custom_rendezvous_server: &'a str,
    key: &'a str,
    /// Force relay if direct hole-punch fails (CGNAT scenarios).
    #[serde(rename = "relay-server")]
    relay_server: &'a str,
    /// Disables RustDesk's public ID server entirely — the helper is locked
    /// to Klaravex's relay.
    #[serde(rename = "stop-service")]
    stop_service: &'static str,
    /// Permanent password the operator dials with. Single-session.
    #[serde(rename = "verification-method")]
    verification_method: &'static str,
    #[serde(rename = "permanent-password")]
    permanent_password: &'a str,
    #[serde(rename = "approve-mode")]
    approve_mode: &'static str,
    /// Bind the helper to ONLY this 9-digit ID. RustDesk normally generates
    /// one based on hardware fingerprint; we override so the operator can
    /// dial the server-assigned ID without round-tripping.
    #[serde(rename = "force-always-relay")]
    force_always_relay: &'static str,
}

pub fn write_rustdesk_config(session: &Session, relay_host: &str, relay_key: &str) -> Result<()> {
    let path = config_path()?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).with_context(|| format!("create_dir_all {:?}", parent))?;
    }

    let relay_addr = format!("{}:21116", relay_host);
    let cfg = RustDeskConfig {
        rendezvous_server: &relay_addr,
        nat_type: 1, // assume symmetric — forces relay first attempt
        serial: 0,
        options: Options {
            custom_rendezvous_server: &relay_addr,
            key: relay_key,
            relay_server: relay_host,
            stop_service: "N",
            verification_method: "use-permanent-password",
            permanent_password: &session.session_password,
            approve_mode: "password", // skip per-connection click-through
            force_always_relay: "Y",
        },
    };

    let toml = toml::to_string_pretty(&cfg).context("serialize RustDesk2.toml")?;
    write_secure(&path, &toml)?;
    info!(path = %path.display(), "wrote RustDesk config");

    // Also write the customer ID hint to a sibling file so the launcher
    // can pass it on the command line where supported (Windows + Linux).
    let hint = path
        .parent()
        .unwrap()
        .join("klaravex-session-id");
    write_secure(&hint, &session.customer_session_id)?;

    Ok(())
}

/// 0600 on Unix; default ACL on Windows (only current user can read AppData).
fn write_secure(path: &Path, contents: &str) -> Result<()> {
    fs::write(path, contents).with_context(|| format!("write {:?}", path))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perm = fs::metadata(path)?.permissions();
        perm.set_mode(0o600);
        fs::set_permissions(path, perm)?;
    }
    Ok(())
}

// `toml` crate is brought in transitively via toml_edit. If not, replace
// with `toml_edit::ser::to_string_pretty`. We keep this module
// self-contained — see Cargo.toml.
mod toml {
    use serde::Serialize;

    pub fn to_string_pretty<T: Serialize>(value: &T) -> anyhow::Result<String> {
        // Lazy fallback using toml_edit if `toml` is not available.
        let doc = toml_edit::ser::to_string_pretty(value)?;
        Ok(doc)
    }
}
