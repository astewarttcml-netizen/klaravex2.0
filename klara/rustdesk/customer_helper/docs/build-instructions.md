# Build Instructions — Klaravex Customer Helper

The helper is a Tauri 2.0 app written in Rust with a small webview UI. One
codebase produces a macOS `.dmg`, Windows `.exe` installer, and Linux
AppImage + `.deb`. The bundled RustDesk client is shipped as a Tauri
sidecar binary (per AGPL §13 — separate executable, not statically
linked).

## Prerequisites — all platforms

1. Rust 1.77+
   ```sh
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   ```
2. Tauri CLI
   ```sh
   cargo install tauri-cli --version "^2.0" --locked
   ```
3. A working network path to https://github.com/rustdesk/rustdesk/releases —
   the `fetch-rustdesk` scripts download the official RustDesk binary at
   build time.

## macOS

```sh
# Toolchain (one-time)
rustup target add aarch64-apple-darwin x86_64-apple-darwin
brew install create-dmg

# Build
cd infra/rustdesk_controller/customer_helper
./macos/build.sh
```

Output: `shared/target/universal-apple-darwin/release/bundle/dmg/Klaravex Support_0.1.0_universal.dmg`

### Signing (production)

Set `KLARAVEX_SIGN_IDENTITY="Developer ID Application: Klaravex LLC (TEAMID)"`
and have `xcrun notarytool store-credentials KlaravexNotary` configured.
The build script auto-signs and notarizes.

Without these set, the script produces an unsigned `.dmg`. To run it for
QA: `xattr -rd com.apple.quarantine "/Applications/Klaravex Support.app"`.

### macOS first-run permissions

macOS will prompt for Screen Recording + Accessibility on first connect.
The strings are pre-baked in `macos/Info.plist.template`. The user must
grant both, then click "Reconnect" in the helper UI — this is a known
RustDesk constraint and applies to every macOS remote-support tool.

## Windows

```pwsh
# Toolchain (one-time)
rustup target add x86_64-pc-windows-msvc
# Install Visual Studio 2022 Build Tools + WebView2 Runtime (system-wide)

# Build
cd infra\rustdesk_controller\customer_helper
.\windows\build.ps1
```

Output: `shared\target\x86_64-pc-windows-msvc\release\bundle\nsis\Klaravex Support_0.1.0_x64-setup.exe`

### Signing (production)

Set `KLARAVEX_SIGN_THUMBPRINT` to the EV cert thumbprint and ensure
`signtool.exe` is on PATH. The build script signs both the helper EXE
and the NSIS installer with a SHA-256 timestamped signature.

Without signing, SmartScreen will flag the installer until enough
customers click through. Buy the EV cert before shipping (see formation
checklist in `/CLAUDE.md`).

## Linux

```sh
# Toolchain (one-time)
sudo apt install -y \
  libwebkit2gtk-4.1-dev libayatana-appindicator3-dev \
  libssl-dev pkg-config build-essential curl wget file libsoup-3.0-dev

# Build
cd infra/rustdesk_controller/customer_helper
./linux/build.sh
```

Output:
- `shared/target/release/bundle/appimage/klaravex-support_0.1.0_amd64.AppImage`
- `shared/target/release/bundle/deb/klaravex-support_0.1.0_amd64.deb`

### Distribution

- AppImage is the primary Linux artifact (zero install, runs anywhere).
- `.deb` is provided for customers who prefer system integration; the
  postinst registers the `klaravex-helper://` URL scheme via
  `xdg-mime`.

## Smoke testing without a real session

```sh
# 1. Spin up the contract server
cd infra/rustdesk_controller/customer_helper/server-stub
python3 -m venv .venv && . .venv/bin/activate
pip install fastapi uvicorn pydantic
python redeem_api.py &

# 2. Mint a token
TOKEN=$(curl -s -X POST 'http://127.0.0.1:8765/api/customer-helper/issue?topic=smoke-test' \
  | python -c 'import sys,json; print(json.load(sys.stdin)["token"])')

# 3. Run the helper in dry-run (no RustDesk launch)
cd ../shared
KLARAVEX_API_BASE=http://127.0.0.1:8765 \
KLARAVEX_HELPER_TOKEN="$TOKEN" \
cargo run -- --dry-run
```

The Rust integration test in `shared/tests/` performs all three steps
inline; see `shared/tests/contract.rs`.

## Cross-build matrix (CI)

| Platform | Builder | Artifacts | Signed? |
|---|---|---|---|
| macOS (universal) | GitHub Actions `macos-14` runner | `.dmg` | Yes (when secrets set) |
| Windows (x64) | GitHub Actions `windows-2022` runner | `.exe` NSIS installer | Yes (when secrets set) |
| Linux (x64) | GitHub Actions `ubuntu-24.04` runner | `.AppImage`, `.deb` | GPG-signed `.asc` |

CI workflow lives at `.github/workflows/customer-helper.yml` — NOT YET
COMMITTED, this is G34.2b scope (next iteration).

## Release checklist (per version)

- [ ] Bump version in `shared/Cargo.toml` and `shared/tauri.conf.json`
- [ ] Update `branding/strings.en.toml` if copy changed
- [ ] Re-verify checksums in `scripts/build_customer_helpers/rustdesk-checksums.txt`
- [ ] Build all three platforms
- [ ] Run smoke test against staging API
- [ ] QA on a fresh macOS VM + Windows VM + Linux VM (no cached state)
- [ ] Upload signed artifacts to `support.klaravex.com/dl/helper/v<ver>/`
- [ ] Update support.klaravex.com download page links
- [ ] Tag `customer-helper-v<ver>` in git
- [ ] Log release via `note_submissions` (topic: `deployment`)
