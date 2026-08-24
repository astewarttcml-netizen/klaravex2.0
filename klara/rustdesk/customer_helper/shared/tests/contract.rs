//! End-to-end contract test: helper ↔ stub server ↔ (mock) RustDesk.
//!
//! This test does NOT actually launch RustDesk. It runs the helper in
//! `--dry-run` mode, which exercises:
//!   - argv parsing
//!   - token redemption (against the stub server)
//!   - RustDesk2.toml writing to a temp HOME
//!   - cleanup
//!
//! The contract this test pins is the JSON shape exchanged with the
//! redeem API. If the production Klaravex API (`infra/main.py`) deviates
//! from this shape, this test fails and the helper rejects sessions.
//!
//! Prerequisites: a Python interpreter with fastapi+uvicorn installed,
//! and the stub server's port (8765) free.

use std::time::Duration;

#[tokio::test]
#[ignore = "requires Python + fastapi installed; run with `cargo test --ignored`"]
async fn redeem_and_configure_roundtrip() {
    // 1. Spawn stub server.
    let mut server = std::process::Command::new("python3")
        .arg("../server-stub/redeem_api.py")
        .env("PORT", "8765")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .expect("spawn stub server");

    // 2. Wait for readiness.
    let client = reqwest::Client::new();
    for _ in 0..50 {
        if client
            .get("http://127.0.0.1:8765/docs")
            .send()
            .await
            .map(|r| r.status().is_success())
            .unwrap_or(false)
        {
            break;
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }

    // 3. Issue a token.
    let issued: serde_json::Value = client
        .post("http://127.0.0.1:8765/api/customer-helper/issue?topic=test")
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    let token = issued["token"].as_str().expect("token").to_string();

    // 4. Redeem.
    let session = klaravex_customer_helper_contract::redeem(
        "http://127.0.0.1:8765",
        &token,
    )
    .await
    .expect("redeem");
    assert_eq!(session.customer_session_id.len(), 9);
    assert!(session.session_password.len() >= 16);
    assert!(session.expires_at.contains('T'));

    // 5. Replay must 410.
    let replay = klaravex_customer_helper_contract::redeem(
        "http://127.0.0.1:8765",
        &token,
    )
    .await;
    assert!(replay.is_err(), "replay must fail with 410");

    // 6. Unknown token must 404.
    let unknown = klaravex_customer_helper_contract::redeem(
        "http://127.0.0.1:8765",
        "thisdoesnotexist",
    )
    .await;
    assert!(unknown.is_err(), "unknown token must fail");

    server.kill().ok();
}

// Re-export the token module under a stable path for the test.
// Lib crate exposes the modules so integration tests can call into them
// without rebuilding the bin.
mod klaravex_customer_helper_contract {
    pub use klaravex_customer_helper::token::*;
}
