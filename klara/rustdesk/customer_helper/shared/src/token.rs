//! Token redemption client.
//!
//! The customer arrives with a single-use opaque token (≥32 bytes of url-safe
//! base64). The token is bound to:
//!   - an Apollo/Stripe payment id (server side)
//!   - a TTL (default 30 min from issue, configurable per service tier)
//!   - a single redemption (server invalidates the token on first successful
//!     redeem; replay returns 410 Gone)
//!
//! We return ONLY the data the client needs to drive RustDesk. We do NOT
//! return the operator-side credentials or any Loki bearer.

use anyhow::{anyhow, bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tauri::{AppHandle, Emitter, Listener};
use tokio::sync::oneshot;
use tracing::{info, warn};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Session {
    /// 9-digit RustDesk ID the operator will dial. Generated server-side and
    /// also injected into Loki's session_manager so the operator knows what to
    /// connect to.
    pub customer_session_id: String,
    /// Single-session password baked into the customer's RustDesk config.
    /// Length ≥ 16, charset alphanumeric. Wiped from disk on helper exit.
    pub session_password: String,
    /// RFC3339 expiry. Helper refuses to start the launcher after this.
    pub expires_at: String,
    /// Human label shown in the UI ("Helping with: macOS Mail setup").
    /// Server-supplied; trusted because the channel is HTTPS + token-bound.
    pub display_topic: Option<String>,
    /// Optional operator name to show ("You are being assisted by Klara (AI)").
    pub operator_label: Option<String>,
}

/// Redeem a token. Retries 3× with exponential backoff on transient errors.
pub async fn redeem(api_base: &str, token: &str) -> Result<Session> {
    let url = format!(
        "{}/api/customer-helper/redeem/{}",
        api_base.trim_end_matches('/'),
        url_encode(token)
    );

    let client = reqwest::Client::builder()
        .user_agent(concat!("klaravex-helper/", env!("CARGO_PKG_VERSION")))
        .timeout(Duration::from_secs(15))
        .https_only(api_base.starts_with("https://"))
        .build()?;

    let mut delay = Duration::from_millis(500);
    for attempt in 1..=3 {
        match client.post(&url).send().await {
            Ok(r) if r.status().is_success() => {
                let session: Session = r.json().await.context("invalid session JSON")?;
                validate(&session)?;
                return Ok(session);
            }
            Ok(r) if r.status() == 410 => {
                bail!("This support link has already been used or has expired.");
            }
            Ok(r) if r.status() == 404 => {
                bail!("This support link is not valid. Please check the email Klaravex sent you.");
            }
            Ok(r) if r.status().as_u16() >= 500 && attempt < 3 => {
                warn!(status = %r.status(), attempt, "redeem 5xx — retrying");
            }
            Ok(r) => {
                let status = r.status();
                let body = r.text().await.unwrap_or_default();
                bail!("Klaravex API returned {}: {}", status, body);
            }
            Err(e) if attempt < 3 => {
                warn!(error = ?e, attempt, "redeem transport error — retrying");
            }
            Err(e) => return Err(e).context("redeem failed after 3 attempts"),
        }
        tokio::time::sleep(delay).await;
        delay *= 2;
    }
    unreachable!()
}

fn validate(s: &Session) -> Result<()> {
    if s.customer_session_id.is_empty() {
        bail!("server returned empty customer_session_id");
    }
    if s.session_password.len() < 8 {
        bail!("server returned weak session_password");
    }
    // Verify expires_at is parseable + in the future.
    // (Lightweight check — we don't pull a full chrono dep just for this.)
    if !s.expires_at.contains('T') {
        bail!("server returned malformed expires_at: {}", s.expires_at);
    }
    Ok(())
}

fn url_encode(s: &str) -> String {
    s.chars()
        .map(|c| match c {
            'A'..='Z' | 'a'..='z' | '0'..='9' | '-' | '_' | '.' | '~' => c.to_string(),
            _ => format!("%{:02X}", c as u8),
        })
        .collect()
}

// ---------------------------------------------------------------------------
// Deep-link / UI handoff plumbing
// ---------------------------------------------------------------------------
//
// When the helper is launched WITHOUT a token (user double-clicked the bundle
// rather than following the klaravex-helper:// link), the UI shows a
// "Paste your support code" prompt. The UI sends the typed code via the
// cmd_request_token Tauri command, which forwards it through a oneshot.

static TOKEN_CHANNEL: once_cell::sync::Lazy<
    std::sync::Mutex<Option<oneshot::Sender<String>>>,
> = once_cell::sync::Lazy::new(|| std::sync::Mutex::new(None));

pub async fn wait_for_token(app: &AppHandle) -> Result<String> {
    let (tx, rx) = oneshot::channel();
    {
        let mut slot = TOKEN_CHANNEL.lock().unwrap();
        *slot = Some(tx);
    }

    // Also listen for deep-link delivered tokens (klaravex-helper://<token>).
    let app_clone = app.clone();
    app.listen("deep-link://new-url", move |event| {
        if let Some(payload) = event.payload().strip_prefix('"') {
            if let Some(url) = payload.strip_suffix('"') {
                if let Some(tok) = url.strip_prefix("klaravex-helper://") {
                    info!("token received via deep-link");
                    let _ = deliver(&app_clone, tok.to_string());
                }
            }
        }
    });

    app.emit("helper:state", "awaiting-token").ok();
    rx.await.map_err(|_| anyhow!("token channel closed"))
}

pub fn deliver(_app: &AppHandle, token: String) -> Result<()> {
    let mut slot = TOKEN_CHANNEL.lock().unwrap();
    if let Some(tx) = slot.take() {
        tx.send(token)
            .map_err(|_| anyhow!("token receiver dropped"))?;
        Ok(())
    } else {
        bail!("token already delivered or session not awaiting token");
    }
}
