#!/usr/bin/env bash
# Build klx-rdshim for the current host.
#
# Usage:
#   ./build.sh             # build release for host triple
#   ./build.sh --debug     # build debug for host triple
#   TARGET=x86_64-unknown-linux-gnu ./build.sh   # cross-compile to Hetzner
#
# The compiled binary is emitted to:
#   target/$TARGET/release/klx-rdshim   (or debug/)
#
# Point the Python operator at it:
#   export KLX_RDSHIM_BIN="$PWD/target/release/klx-rdshim"
#   python3 -m pytest infra/rustdesk_controller/tests/test_operator_e2e.py
#
# Requires Rust >= 1.74 (per Cargo.toml). Get it via:
#   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

set -euo pipefail

cd "$(dirname "$0")"

PROFILE_FLAG="--release"
PROFILE_DIR="release"
if [ "${1:-}" = "--debug" ]; then
    PROFILE_FLAG=""
    PROFILE_DIR="debug"
fi

if ! command -v cargo >/dev/null 2>&1; then
    echo "error: cargo not found on PATH" >&2
    echo "install Rust: https://rustup.rs" >&2
    exit 127
fi

ARGS=()
if [ -n "${TARGET:-}" ]; then
    ARGS+=("--target" "$TARGET")
fi
if [ -n "$PROFILE_FLAG" ]; then
    ARGS+=("$PROFILE_FLAG")
fi

cargo build "${ARGS[@]}"

if [ -n "${TARGET:-}" ]; then
    BIN_PATH="target/$TARGET/$PROFILE_DIR/klx-rdshim"
else
    BIN_PATH="target/$PROFILE_DIR/klx-rdshim"
fi

if [ ! -x "$BIN_PATH" ]; then
    echo "error: build succeeded but $BIN_PATH not executable" >&2
    exit 1
fi

echo ""
echo "built: $PWD/$BIN_PATH"
echo ""
echo "to use:"
echo "  export KLX_RDSHIM_BIN=$PWD/$BIN_PATH"
echo "  python3 -m pytest infra/rustdesk_controller/tests/test_operator_e2e.py"
