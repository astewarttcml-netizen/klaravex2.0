; Inno Setup fallback — used when Tauri's bundled NSIS isn't acceptable
; (e.g. when Anthony wants the older Inno UX, or when WiX/MSI is needed
; later for enterprise deployment).
; This file is OPTIONAL — Tauri's NSIS target is the primary Windows
; deliverable. Inno Setup is documented here so the path exists.

#define MyAppName "Klaravex Support"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Klaravex LLC"
#define MyAppURL "https://klaravex.com"
#define MyAppExeName "klaravex-helper.exe"

[Setup]
AppId={{B7E5A0F4-3C9C-4D31-9F9A-7C8D2E1A4B5C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/support
AppUpdatesURL={#MyAppURL}/download
DefaultDirName={localappdata}\Klaravex Support
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=auto
LicenseFile=..\docs\EULA.txt
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputBaseFilename=Klaravex-Support-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
; SmartScreen reputation requires EV signing — see build.ps1.
SignTool=ktx_sign $f

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Files]
Source: "..\shared\target\x86_64-pc-windows-msvc\release\klaravex-helper.exe"; \
  DestDir: "{app}"; Flags: ignoreversion
Source: "..\shared\target\x86_64-pc-windows-msvc\release\rustdesk.exe"; \
  DestDir: "{app}"; Flags: ignoreversion
Source: "..\shared\ui\assets\*"; DestDir: "{app}\ui\assets"; \
  Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
  Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; \
  GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Registry]
; klaravex-helper:// URL scheme for the post-payment email link.
Root: HKCU; Subkey: "Software\Classes\klaravex-helper"; \
  ValueType: string; ValueData: "URL:Klaravex Helper Token"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\klaravex-helper"; \
  ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\klaravex-helper\shell\open\command"; \
  ValueType: string; ValueData: """{app}\{#MyAppExeName}"" --token ""%1"""

[Run]
Filename: "{app}\{#MyAppExeName}"; \
  Description: "Start Klaravex Support"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
; Best-effort: stop any lingering RustDesk service.
Filename: "{sys}\sc.exe"; Parameters: "stop rustdesk"; Flags: runhidden
