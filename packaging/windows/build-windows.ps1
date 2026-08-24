# Build JonathanAi.exe (Electron) and JonathanAi-Setup.exe (Inno Setup) on Windows.
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Desktop = Join-Path $Root "desktop"
$Out = Join-Path $PSScriptRoot "bin"
New-Item -ItemType Directory -Force -Path $Out | Out-Null

Write-Host "Installing Electron desktop shell…"
Push-Location $Desktop
if (Get-Command npm -ErrorAction SilentlyContinue) {
    npm install
    npx electron-builder --win --x64 --dir
    $built = Get-ChildItem -Recurse -Filter "JonathanAi.exe" | Select-Object -First 1
    if ($built) { Copy-Item $built.FullName (Join-Path $Out "JonathanAi.exe") -Force }
} else {
    Write-Host "npm not found; using the prebuilt mingw JonathanAi.exe launcher."
}
Pop-Location

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) {
    $isccPath = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (Test-Path $isccPath) { $iscc = $isccPath }
}
if ($iscc) {
    Write-Host "Building JonathanAi-Setup.exe with Inno Setup…"
    & $iscc (Join-Path $PSScriptRoot "JonathanAi.iss")
} else {
    Write-Host "Inno Setup not found. The mingw JonathanAi-Setup.exe in dist/ is the wizard."
}

Write-Host "Artifacts in $Out"
Get-ChildItem $Out
