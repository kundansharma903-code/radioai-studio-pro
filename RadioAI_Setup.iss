; ═══════════════════════════════════════════════════════════════════
; RadioAI Studio Pro — Inno Setup script (Phase N)
; ───────────────────────────────────────────────────────────────────
; Produces a single ``RadioAI_Studio_Pro_Setup_v2.0.exe`` installer
; that wraps the PyInstaller bundle at ``dist\RadioAI Studio Pro\``
; and presents a professional Next-Next-Install wizard:
;
;   1. Welcome screen   — banner + version
;   2. License           — LICENSE.txt accept/decline
;   3. Install Location  — default C:\Program Files\RadioAI Studio Pro\
;   4. Start Menu Folder — default "RadioAI Studio Pro"
;   5. Additional Tasks  — Desktop shortcut checkbox
;   6. Ready to Install  — summary of choices
;   7. Installing        — progress bar + extracting files
;   8. Finish            — Launch checkbox + Finish button
;
; Installer also:
;   • Registers uninstaller in Windows "Add/Remove Programs"
;   • Embeds RadioAI's RA logo .ico (visible on the setup file
;     itself + on the uninstaller entry in Control Panel)
;   • Requires admin privileges (writing to Program Files needs UAC)
;
; Build:
;     ISCC RadioAI_Setup.iss
;
; Output:
;     installer\RadioAI_Studio_Pro_Setup_v2.0.exe
; ═══════════════════════════════════════════════════════════════════

#define MyAppName        "RadioAI Studio Pro"
#define MyAppVersion     "2.0.0"
#define MyAppPublisher   "MonoLoop Productions"
#define MyAppURL         "https://github.com/kundansharma903-code/radioai-studio-pro"
#define MyAppExeName     "RadioAI Studio Pro.exe"
#define MyAppCopyright   "Copyright (C) 2026 MonoLoop Productions"

[Setup]
; Unique AppId — Inno Setup uses this to detect upgrades vs fresh
; installs of the SAME app. Never change this for the lifetime of
; the v2.x line; generate a NEW GUID only when launching a v3.0.
AppId={{CB5B13C7-E662-4D04-9450-09F0975DCF84}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
AppCopyright={#MyAppCopyright}

; Install location
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=auto
DisableDirPage=no

; License — operator can edit LICENSE.txt for the actual EULA text
LicenseFile=LICENSE.txt

; Privileges — Program Files needs admin / UAC elevation
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=

; Output
OutputDir=installer
OutputBaseFilename=RadioAI_Studio_Pro_Setup_v{#MyAppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

; Compression — LZMA2/ultra64 squeezes the 98MB bundle to ~35MB
Compression=lzma2/ultra64
SolidCompression=yes

; Visuals — modern wizard with banner image
WizardStyle=modern
ShowLanguageDialog=no

; Architecture — 64-bit only (PyQt6 + Python 3.14 are 64-bit on Windows)
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Min Windows version — Windows 10 1809 (build 17763) and later.
; Earlier Win10 + Win7/8 are EOL and may not run modern PyQt6.
MinVersion=10.0.17763

; Welcome screen — show the standard "Welcome to the Setup Wizard"
; page (DisableWelcomePage=no is the default but be explicit)
DisableWelcomePage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Desktop shortcut — optional, unchecked by default (operator-friendly)
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; Quick Launch — skip (legacy Win7 / Vista feature)

[Files]
; The PyInstaller bundle — entire dist/RadioAI Studio Pro/ folder
; recurses into the install destination. Skips intermediate
; build/ artefacts. ignoreversion + recursesubdirs + createall
; ensures the install matches the source tree exactly.
Source: "dist\{#MyAppName}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
; License + readme alongside the exe (operator can read locally)
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu shortcut — always created. We deliberately do NOT set
; IconFilename so Windows extracts the icon directly from the .exe
; (PyInstaller embedded the multi-res .ico into the binary). This
; is more reliable than IconFilename: the explicit path approach
; sometimes shows a generic blank-page icon if Windows' shell
; icon cache hasn't refreshed or the assets folder isn't readable
; under UAC.
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
; Optional desktop shortcut (controlled by Tasks above)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Run]
; Optional auto-launch at the end of install ("Launch RadioAI now?"
; checkbox on the Finish page). nowait so the wizard closes after
; clicking Launch instead of pinning the app's exit to it.
Filename: "{app}\{#MyAppExeName}"; \
    Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; On uninstall, also clean up runtime user-data folders that the
; app created at first run. Operator's data DB stays UNTOUCHED
; under %LOCALAPPDATA%\RadioAI Studio Pro\ — they can choose to
; remove it manually if they want a true clean slate. We only
; nuke the install directory itself.
Type: filesandordirs; Name: "{app}"
