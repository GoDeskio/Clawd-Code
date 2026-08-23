; Inno Setup script for Jonathan Ai.
; Build on Windows: ISCC.exe JonathanAi.iss
; Double-click the produced JonathanAi-Setup.exe → wizard → app + Desktop icon.

#define MyAppName "Jonathan Ai"
#define MyAppExe "JonathanAi.exe"
#define MyAppPublisher "GoDeskio"
#define MyAppURL "https://github.com/GoDeskio/Clawd-Code"
#define MyAppVersion "0.1.0"

[Setup]
AppId={{C8E2A4B1-0F31-4E77-9A44-7B2E91C0D801}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={userdocs}\..\Jonathan\Jonathan-Ai
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=no
OutputDir=bin
OutputBaseFilename=JonathanAi-Setup
SetupIconFile=jonathan-ai.ico
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExe}
CloseApplications=no
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checked
Name: "startmenu"; Description: "Create a Start Menu shortcut"; GroupDescription: "Shortcuts:"; Flags: checked

[Files]
Source: "..\..\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Excludes: ".venv,node_modules,.git,.pytest_cache,__pycache__,*.pyc,dist"
Source: "bin\JonathanAi.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "jonathan-ai.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\jonathan-ai.ico"; Tasks: desktopicon
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\jonathan-ai.ico"; Tasks: startmenu

[Run]
Filename: "{cmd}"; Parameters: "/C if exist ""{app}\.venv\Scripts\python.exe"" (""{app}\.venv\Scripts\python.exe"" -m src.install --source-dir ""{app}"" --from-local ""{app}"" --yes) else (python -m src.install --source-dir ""{app}"" --from-local ""{app}"" --yes)"; WorkingDir: "{app}"; StatusMsg: "Installing Python environment…"; Flags: runhidden
Filename: "{app}\{#MyAppExe}"; Description: "Launch Jonathan Ai"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
