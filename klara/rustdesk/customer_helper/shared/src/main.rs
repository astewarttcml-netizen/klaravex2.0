//! Klaravex Customer Helper (G34.2) entry point.
//!
//! Flow:
//!   1. Parse one-time token from argv / klaravex-helper:// URL / env.
//!   2. Redeem token against Klaravex API → receive session_id + password.
//!   3. Write pre-baked RustDesk2.toml with relay 87.99.147.244, key
//!      E2+699SkYhlEsyjaizRhI+2kuvxxGheisWarfJHbkVA=, and the redeemed
//!      session ID + password.
//!   4. Launch the bundled RustDesk binary in unattended mode.
//!   5. Show indicator overlay (always-on-top, persistent "AI is controlling
//!      your computer" badge + STOP button).
//!   6. On exit OR STOP click → kill RustDesk, wipe config, exit cleanly.

use anyhow::{Context, Result};
use clap::Parser;
use std::sync::Arc;
use tauri::{Emitter, RunEvent};
use tracing::{error, info, warn};

use klaravex_customer_helper::{cleanup, config, indicator, launcher, token};

/// Default API base; overridable for staging via --api-base or env.
const DEFAULT_API_BASE: &str = "https://support.klaravex.com";

/// Pinned relay parameters — public on purpose (RustDesk pubkey is not secret).
const RELAY_HOST: &str = "87.99.147.244";
const RELAY_PUBKEY: &str = "E2+699SkYhlEsyjaizRhI+2kuvxxGheisWarfJHbkVA=";

#[derive(Parser, Debug, Clone)]
#[command(name = "klaravex-helper", version)]
struct Args {
    /// One-time customer-helper token from the post-payment email link.
    /// May also be supplied via klaravex-helper://<token> URL scheme on
    /// macOS/Windows, or via KLARAVEX_HELPER_TOKEN env var.
    #[arg(long, env = "KLARAVEX_HELPER_TOKEN")]
    token: Option<String>,

    /// Override API base. Production: https://support.klaravex.com
    #[arg(long, env = "KLARAVEX_API_BASE", default_value = DEFAULT_API_BASE)]
    api_base: String,

    /// UI locale (en only). Accepted but unused — English is the sole locale.
    #[arg(long, env = "KLARAVEX_LOCALE")]
    locale: Option<String>,

    /// Skip actually launching RustDesk — used by smoke tests.
    #[arg(long, hide = true)]
    dry_run: bool,
}

fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .json()
        .init();

    let args = Args::parse();
    info!(api_base = %args.api_base, "klaravex-helper starting");

    // Token may arrive later via the URL scheme handler (deep link); we don't
    // require it at startup. If we have it now, we'll redeem on app-ready.
    let initial_token = args.token.clone();
    let args_arc = Arc::new(args);

    tauri::Builder::default()
        .plugin(tauri_plugin_deep_link::init())
        .setup({
            let args = args_arc.clone();
            move |app| {
                let app_handle = app.handle().clone();
                let args = args.clone();
                tauri::async_runtime::spawn(async move {
                    if let Err(e) = run_session(app_handle, args, initial_token).await {
                        error!(error = ?e, "session failed");
                    }
                });
                Ok(())
            }
        })
        .invoke_handler(tauri::generate_handler![
            cmd_stop_session,
            cmd_request_token,
        ])
        .build(tauri::generate_context!())
        .context("failed to build tauri app")?
        .run(|app_handle, event| match event {
            RunEvent::Exit => {
                info!("exit event received — running cleanup");
                if let Err(e) = cleanup::wipe_all(app_handle) {
                    warn!(error = ?e, "cleanup error on exit");
                }
            }
            _ => {}
        });

    Ok(())
}

async fn run_session(
    app: tauri::AppHandle,
    args: Arc<Args>,
    token: Option<String>,
) -> Result<()> {
    // Wait for a token (from CLI or deep-link).
    let token = match token {
        Some(t) => t,
        None => {
            info!("no token at startup — waiting for deep-link / UI input");
            token::wait_for_token(&app).await?
        }
    };

    app.emit("helper:state", "redeeming")?;
    let session = token::redeem(&args.api_base, &token)
        .await
        .context("token redeem failed")?;

    info!(
        session_id = %session.customer_session_id,
        expires_at = %session.expires_at,
        "token redeemed"
    );

    app.emit("helper:state", "configuring")?;
    config::write_rustdesk_config(&session, RELAY_HOST, RELAY_PUBKEY)
        .context("failed to write RustDesk config")?;

    if args.dry_run {
        info!("dry-run: skipping launcher + indicator");
        return Ok(());
    }

    app.emit("helper:state", "launching")?;
    let child = launcher::spawn_rustdesk(&session).context("failed to launch RustDesk")?;
    launcher::register_child(&app, child);

    app.emit("helper:state", "active")?;
    indicator::show(&app).await?;

    Ok(())
}

#[tauri::command]
async fn cmd_stop_session(app: tauri::AppHandle) -> Result<(), String> {
    info!("STOP requested by user");
    cleanup::wipe_all(&app).map_err(|e| e.to_string())?;
    app.exit(0);
    Ok(())
}

#[tauri::command]
async fn cmd_request_token(app: tauri::AppHandle, token: String) -> Result<(), String> {
    token::deliver(&app, token).map_err(|e| e.to_string())
}
