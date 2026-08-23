@echo off
REM Double-click: run the real Jonathan Ai Setup wizard (not a hidden bat).
set "SETUP=%~dp0packaging\windows\bin\JonathanAi-Setup.exe"
if exist "%SETUP%" (
  start "" "%SETUP%"
  exit /b 0
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
