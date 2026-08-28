; Standard per-user Windows setup/upgrade wizard for Jonathan Ai.
Unicode True
RequestExecutionLevel user
; Non-solid compression avoids NSIS mmap failures on large source payloads and
; makes in-place upgrades faster when only a few application files changed.
SetCompressor zlib

!define PRODUCT_NAME "Jonathan Ai"
!define PRODUCT_VERSION "0.4.8"
!define PRODUCT_PUBLISHER "GoDeskio"
!define PRODUCT_WEB "https://github.com/GoDeskio/Clawd-Code"
!define PRODUCT_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\JonathanAi"

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
Caption "${PRODUCT_NAME} Setup"
OutFile "bin\JonathanAi-Setup.exe"
InstallDir "$PROFILE\Jonathan\Jonathan-Ai"
InstallDirRegKey HKCU "Software\GoDeskio\JonathanAi" "InstallDir"
Icon "nsis-icon.ico"
UninstallIcon "nsis-icon.ico"
BrandingText "Jonathan Ai ${PRODUCT_VERSION}"
ShowInstDetails show
ShowUninstDetails show

!include "MUI2.nsh"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Install or upgrade Jonathan Ai"
!define MUI_WELCOMEPAGE_TEXT "This standard wizard installs Jonathan Ai ${PRODUCT_VERSION} for the current Windows user.$\r$\n$\r$\nExisting installations are upgraded in place. Conversations, configuration, models, and the editable Skills library are preserved. Required application dependencies are installed automatically."
!define MUI_DIRECTORYPAGE_TEXT_TOP "Choose the Jonathan Ai application folder. The recommended location keeps JonathanAi.exe and the editable Skills library together."
!define MUI_FINISHPAGE_RUN "$INSTDIR\JonathanAi.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Launch Jonathan Ai"
!define MUI_FINISHPAGE_LINK "Open the Jonathan Ai source repository"
!define MUI_FINISHPAGE_LINK_LOCATION "${PRODUCT_WEB}"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\..\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Jonathan Ai" MainSection
  SectionIn RO
  SetShellVarContext current
  SetOverwrite on
  SetOutPath "$INSTDIR"

  ; Ship a complete source payload. Heavy generated/runtime folders remain in
  ; place during upgrades and are repaired by install.ps1 when needed.
  File /r /x ".git" /x ".venv" /x "node_modules" /x "Skills" /x "__pycache__" /x "*.pyc" /x ".pytest_cache" /x "dist" /x "build" /x "upstream" /x "Fooocus" /x "Fooocus-outputs" /x ".image-models" /x "python-runtimes" /x ".fooocus-venv" /x ".kronos-venv" /x ".uv-cache" /x ".pip-cache" /x ".fooocus-cache" /x ".kronos-cache" /x "ECC" /x "Kronos" /x "Securo" /x "electron" /x "media" /x "pong" /x "mech_robot_*.png" /x "JonathanAi-Setup.exe" /x "JonathanAi.exe.new" /x ".jonathan-ai-processes.json" /x ".jonathan-ai-runtime-*.ready" "..\..\*.*"
  File /oname=JonathanAi.exe "bin\JonathanAi.exe"
  File /oname=jonathan-ai.ico "jonathan-ai.ico"
  CreateDirectory "$INSTDIR\Skills"

  DetailPrint "Installing and verifying Python, OCR, native image, document, Electron, and Blender dependencies..."
  System::Call 'Kernel32::SetEnvironmentVariable(t, t) i("CLAWD_INSTALL_DIR", "$INSTDIR").r0'
  nsExec::ExecToLog '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\install.ps1" --yes'
  Pop $0
  System::Call 'Kernel32::SetEnvironmentVariable(t, t) i("CLAWD_INSTALL_DIR", "").r0'
  ${If} $0 != 0
    MessageBox MB_ICONSTOP|MB_OK "Dependency installation failed with exit code $0. Review the setup details, then run this installer again."
    Abort
  ${EndIf}

  WriteUninstaller "$INSTDIR\Uninstall-JonathanAi.exe"
  CreateDirectory "$SMPROGRAMS\Jonathan Ai"
  CreateShortcut "$SMPROGRAMS\Jonathan Ai\Jonathan Ai.lnk" "$INSTDIR\JonathanAi.exe" "" "$INSTDIR\jonathan-ai.ico"
  CreateShortcut "$SMPROGRAMS\Jonathan Ai\Uninstall Jonathan Ai.lnk" "$INSTDIR\Uninstall-JonathanAi.exe"
  CreateShortcut "$DESKTOP\Jonathan Ai.lnk" "$INSTDIR\JonathanAi.exe" "" "$INSTDIR\jonathan-ai.ico"

  WriteRegStr HKCU "Software\GoDeskio\JonathanAi" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${PRODUCT_KEY}" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKCU "${PRODUCT_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr HKCU "${PRODUCT_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegStr HKCU "${PRODUCT_KEY}" "URLInfoAbout" "${PRODUCT_WEB}"
  WriteRegStr HKCU "${PRODUCT_KEY}" "DisplayIcon" "$INSTDIR\JonathanAi.exe"
  WriteRegStr HKCU "${PRODUCT_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${PRODUCT_KEY}" "UninstallString" '"$INSTDIR\Uninstall-JonathanAi.exe"'
  WriteRegDWORD HKCU "${PRODUCT_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${PRODUCT_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$DESKTOP\Jonathan Ai.lnk"
  RMDir /r "$SMPROGRAMS\Jonathan Ai"
  DeleteRegKey HKCU "${PRODUCT_KEY}"
  DeleteRegKey HKCU "Software\GoDeskio\JonathanAi"
  Delete "$INSTDIR\JonathanAi.exe"
  Delete "$INSTDIR\jonathan-ai.ico"
  Delete "$INSTDIR\Uninstall-JonathanAi.exe"
  ; Conversations/configuration live in ~/.clawd and the visible Skills folder
  ; is user-authored. Keep both recoverable after uninstall.
SectionEnd
