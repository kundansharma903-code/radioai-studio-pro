; RadioAI Studio Pro - Inno Setup Script
; Build with: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss

#define AppName       "RadioAI Studio Pro"
#define AppVersion    "1.0.0"
#define AppPublisher  "RadioAI"
#define AppExeName    "RadioAI Studio Pro.exe"

[Setup]
AppId={{E3A44F90-8B5C-47A0-AF12-KISSFM000001}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://radioai.app
AppSupportURL=https://radioai.app/support
DefaultDirName={autopf}\RadioAI Studio Pro
DefaultGroupName={#AppName}
AllowNoIcons=yes
OutputDir=C:\RadioAI\installer_output
OutputBaseFilename=RadioAI_Studio_Pro_Setup_v{#AppVersion}
SetupIconFile=C:\RadioAI\assets\radioai.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}
MinVersion=10.0
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"
Name: "startupicon"; Description: "Launch RadioAI on Windows startup (recommended for broadcast PCs)"; \
    GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; The entire PyInstaller output folder, recursively
Source: "C:\RadioAI\dist\RadioAI Studio Pro\*"; \
    DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; \
    Filename: "{app}\{#AppExeName}"; \
    IconFilename: "{app}\assets\radioai.ico"

Name: "{group}\Uninstall {#AppName}"; \
    Filename: "{uninstallexe}"

Name: "{autodesktop}\{#AppName}"; \
    Filename: "{app}\{#AppExeName}"; \
    IconFilename: "{app}\assets\radioai.ico"; \
    Tasks: desktopicon

Name: "{autostartup}\{#AppName}"; \
    Filename: "{app}\{#AppExeName}"; \
    Tasks: startupicon

[Run]
Filename: "{app}\{#AppExeName}"; \
    Description: "Launch RadioAI Studio Pro"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure InitializeWizard();
begin
  WizardForm.Caption := 'RadioAI Studio Pro - Setup';
end;
