#!/usr/bin/env bash
# macOS helper build.
# Output: target/release/bundle/dmg/Klaravex\ Support_<ver>_<arch>.dmg
#
# Requirements:
#   - Rust toolchain w/ aarch64-apple-darwin + x86_64-apple-darwin targets
#   - Xcode CLT (codesign, hdiutil)
#   - Apple Developer ID Application cert (loaded as KLARAVEX_SIGN_IDENTITY)
#   - notarytool credentials profile "KlaravexNotary" (xcrun notarytool store-credentials)
#
# STUBBED: signing + notarization are wired but inert until the Apple
# Developer Program account is purchased (formation checklist).
# Without a cert the script still produces an unsigned .dmg suitable for
# internal QA on Anthony's laptop with `xattr -rd com.apple.quarantine`.

set -euo pipefail

HELPER_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SHARED_DIR="$HELPER_DIR/shared"
SCRIPTS_DIR="$(cd "$HELPER_DIR/../../../scripts/build_customer_helpers" && pwd)"

cd "$SHARED_DIR"

# 1. Fetch + verify the bundled RustDesk binary (sidecar) for both arches.
"$SCRIPTS_DIR/fetch-rustdesk.sh" macos-aarch64
"$SCRIPTS_DIR/fetch-rustdesk.sh" macos-x86_64

# 2. Build universal binary.
cargo tauri build --target universal-apple-darwin

# 3. Code-sign (optional — requires KLARAVEX_SIGN_IDENTITY).
DMG_PATH="$(find target -name 'Klaravex Support_*.dmg' | head -1)"
if [[ -n "${KLARAVEX_SIGN_IDENTITY:-}" ]]; then
  codesign --force --options runtime --timestamp \
    --sign "$KLARAVEX_SIGN_IDENTITY" \
    --entitlements "$HELPER_DIR/macos/entitlements.plist" \
    "target/universal-apple-darwin/release/bundle/macos/Klaravex Support.app"

  xcrun notarytool submit "$DMG_PATH" \
    --keychain-profile KlaravexNotary --wait

  xcrun stapler staple "$DMG_PATH"
else
  echo "[warn] KLARAVEX_SIGN_IDENTITY unset — producing unsigned .dmg for QA only" >&2
fi

echo "built: $DMG_PATH"
