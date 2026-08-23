@echo off
REM Checkout helper: open JonathanAi-Setup.exe (the Windows wizard).
set "SETUP=%~dp0packaging\windows\bin\JonathanAi-Setup.exe"
if exist "%SETUP%" (
  start "" "%SETUP%"
  exit /b 0
)
echo JonathanAi-Setup.exe is missing. Build it with packaging\windows\build.sh or build-windows.ps1
exit /b 1
