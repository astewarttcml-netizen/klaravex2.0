// Tauri build hook — generates platform-specific resource bundles, embeds
// the webview assets, and prepares the externalBin sidecar references.
fn main() {
    tauri_build::build()
}
