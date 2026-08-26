; Inno Setup script for Jonathan Ai.
; Build on Windows: ISCC.exe JonathanAi.iss
; Double-click the produced JonathanAi-Setup.exe → wizard → app + Desktop icon.

#define MyAppName "Jonathan Ai"
#define MyAppExe "JonathanAi.exe"
#define MyAppPublisher "GoDeskio"
#define MyAppURL "https://github.com/GoDeskio/Clawd-Code"
#define MyAppVersion "0.4.6"

[Setup]
AppId={{C8E2A4B1-0F31-4E77-9A44-7B2E91C0D801}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={userprofile}\Jonathan\Jonathan-Ai
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=no
OutputDir=bin
OutputBaseFilename=JonathanAi-Setup
SetupIconFile=jonathan-ai.ico
WizardStyle=modern
DisableWelcomePage=no
DisableReadyPage=no
SetupLogging=yes
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
Uninstallable=yes
UninstallDisplayIcon={app}\{#MyAppExe}
CloseApplications=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checked
Name: "startmenu"; Description: "Create a Start Menu shortcut"; GroupDescription: "Shortcuts:"; Flags: checked

[Files]
Source: "..\..\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Excludes: ".venv,node_modules,.git,.pytest_cache,__pycache__,*.pyc,dist,Skills,packaging\windows\bin,Integrations\ECC,Integrations\Kronos,Integrations\Securo,integrations\Fooocus-outputs,integrations\.image-models,integrations\.fooocus-venv,integrations\.kronos-venv,integrations\.fooocus-cache,integrations\.kronos-cache,.jonathan-ai-processes.json,JonathanAi.exe.new"
Source: "bin\JonathanAi.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "jonathan-ai.ico"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\Skills"

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\jonathan-ai.ico"; Tasks: desktopicon
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\jonathan-ai.ico"; Tasks: startmenu

[Run]
Filename: "{cmd}"; Parameters: "/C set ""CLAWD_INSTALL_DIR={app}"" && powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""{app}\install.ps1"" --yes"; WorkingDir: "{app}"; StatusMsg: "Installing Python, app, and desktop dependencies..."; Flags: runhidden
Filename: "{app}\{#MyAppExe}"; Flags: nowait; Check: WasRunningBeforeUpgrade
Filename: "{app}\{#MyAppExe}"; Description: "Launch Jonathan Ai"; Flags: nowait postinstall skipifsilent; Check: not WasRunningBeforeUpgrade

[Code]
var
  RestartAfterUpgrade: Boolean;

function JsonInteger(const Content, Key: String): Integer;
var
  Tail, Digits: String;
  P, I: Integer;
begin
  Result := 0;
  P := Pos('"' + Key + '"', Content);
  if P = 0 then Exit;
  Tail := Copy(Content, P + Length(Key) + 2, Length(Content));
  P := Pos(':', Tail);
  if P = 0 then Exit;
  Tail := Trim(Copy(Tail, P + 1, Length(Tail)));
  Digits := '';
  for I := 1 to Length(Tail) do begin
    if (Tail[I] < '0') or (Tail[I] > '9') then Break;
    Digits := Digits + Tail[I];
  end;
  Result := StrToIntDef(Digits, 0);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  RecordPath, Content, Script: String;
  Pid, ExitCode: Integer;
begin
  Result := '';
  RestartAfterUpgrade := False;
  RecordPath := ExpandConstant('{app}\.jonathan-ai-processes.json');
  if not LoadStringFromFile(RecordPath, Content) then Exit;
  Pid := JsonInteger(Content, 'owner_pid');
  if Pid <= 4 then begin
    DeleteFile(RecordPath);
    Exit;
  end;
  Script := '$root=(Resolve-Path -LiteralPath ''' + ExpandConstant('{app}') + ''').Path + ''\''; ' +
    '$p=Get-Process -Id ' + IntToStr(Pid) +
    ' -ErrorAction SilentlyContinue; if($p -and $p.Path.StartsWith($root,[System.StringComparison]::OrdinalIgnoreCase)' +
    ' -and $p.ProcessName -match ''^(electron|JonathanAi|python|pythonw)$'')' +
    '{ & taskkill.exe /PID ' + IntToStr(Pid) + ' /T /F; exit $LASTEXITCODE }; exit 2';
  if Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      '-NoProfile -NonInteractive -Command "' + Script + '"', ExpandConstant('{app}'),
      SW_HIDE, ewWaitUntilTerminated, ExitCode) and (ExitCode = 0) then begin
    RestartAfterUpgrade := True;
    DeleteFile(RecordPath);
  end;
end;

function WasRunningBeforeUpgrade(): Boolean;
begin
  Result := RestartAfterUpgrade;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
end;
