#!/usr/bin/env bash
# Klaravex Customer Helper — Linux build.
#
# Output:
#   target/release/bundle/appimage/klaravex-support_<ver>_amd64.AppImage
#   target/release/bundle/deb/klaravex-support_<ver>_amd64.deb
#
# Requirements:
#   - Rust toolchain w/ x86_64-unknown-linux-gnu target
#   - libwebkit2gtk-4.1-dev, libayatana-appindicator3-dev, libssl-dev
#   - linuxdeploy + linuxdeploy-plugin-appimage on PATH
#   - GPG key for AppImage signing (KLARAVEX_GPG_KEY env var)
#
# STUBBED: GPG signing is wired but inert until the Klaravex release
# signing key is generated + published (CSO ticket: see docs/threat-model.md).

set -euo pipefail

HELPER_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SHARED_DIR="$HELPER_DIR/shared"
SCRIPTS_DIR="$(cd "$HELPER_DIR/../../../scripts/build_customer_helpers" && pwd)"

cd "$SHARED_DIR"
"$SCRIPTS_DIR/fetch-rustdesk.sh" linux-x86_64

cargo tauri build --target x86_64-unknown-linux-gnu

APPIMAGE="$(find target -name 'klaravex-support_*_amd64.AppImage' | head -1)"
DEB="$(find target -name 'klaravex-support_*_amd64.deb' | head -1)"

if [[ -n "${KLARAVEX_GPG_KEY:-}" && -n "$APPIMAGE" ]]; then
  gpg --batch --yes --local-user "$KLARAVEX_GPG_KEY" \
    --detach-sign --armor "$APPIMAGE"
  echo "signed: ${APPIMAGE}.asc"
else
  echo "[warn] KLARAVEX_GPG_KEY unset — AppImage is unsigned" >&2
fi

echo "built: $APPIMAGE"
echo "built: $DEB"
