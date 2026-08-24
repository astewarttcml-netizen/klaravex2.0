# Klaravex Customer Helper — Windows build.
#
# Output:
#   target\release\bundle\nsis\Klaravex Support_<ver>_x64-setup.exe
#
# Requirements:
#   - Rust toolchain with x86_64-pc-windows-msvc target
#   - Visual Studio 2022 Build Tools (cl.exe, link.exe)
#   - WebView2 runtime (assumed pre-installed on Win10 21H2+/Win11)
#   - signtool.exe (Windows SDK)
#   - EV code-signing cert (loaded via KLARAVEX_SIGN_THUMBPRINT)
#     OR Azure Trusted Signing endpoint (KLARAVEX_AZURE_SIGN_ENDPOINT)
#
# STUBBED: code-signing is wired but inert without the EV cert
# (formation-checklist item). Without a cert the script produces an
# unsigned installer suitable for internal QA only; on customer machines
# SmartScreen will flag it.

$ErrorActionPreference = "Stop"

$HelperDir = (Resolve-Path "$PSScriptRoot\..").Path
$SharedDir = Join-Path $HelperDir "shared"
$ScriptsDir = (Resolve-Path "$HelperDir\..\..\..\scripts\build_customer_helpers").Path

Push-Location $SharedDir
try {
  & "$ScriptsDir\fetch-rustdesk.ps1" win-x86_64

  cargo tauri build --target x86_64-pc-windows-msvc

  $installer = Get-ChildItem -Path target -Recurse -Filter "Klaravex Support_*_x64-setup.exe" | Select-Object -First 1
  if (-not $installer) {
    throw "no installer produced — check tauri build output"
  }

  if ($env:KLARAVEX_SIGN_THUMBPRINT) {
    & signtool.exe sign `
      /sha1 $env:KLARAVEX_SIGN_THUMBPRINT `
      /fd sha256 `
      /tr "http://timestamp.digicert.com" `
      /td sha256 `
      /d "Klaravex Support" `
      /du "https://klaravex.com" `
      $installer.FullName
  } else {
    Write-Warning "KLARAVEX_SIGN_THUMBPRINT unset — installer is UNSIGNED. Do NOT distribute to customers."
  }

  Write-Host "built: $($installer.FullName)"
} finally {
  Pop-Location
}
