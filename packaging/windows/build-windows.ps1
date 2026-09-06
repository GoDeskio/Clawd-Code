# Validate the Electron source shell and build the native launcher installer on Windows.
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Desktop = Join-Path $Root "desktop"
$Out = Join-Path $PSScriptRoot "bin"
$BuildCache = Join-Path $PSScriptRoot "build\cache"
$OriginalLocalAppData = $env:LOCALAPPDATA
New-Item -ItemType Directory -Force -Path $Out | Out-Null
New-Item -ItemType Directory -Force -Path $BuildCache | Out-Null
$env:NPM_CONFIG_CACHE = Join-Path $BuildCache "npm"
$env:ELECTRON_CACHE = Join-Path $BuildCache "electron"
$env:ELECTRON_BUILDER_CACHE = Join-Path $BuildCache "electron-builder"
$env:LOCALAPPDATA = Join-Path $BuildCache "local-app-data"
New-Item -ItemType Directory -Force -Path $env:LOCALAPPDATA | Out-Null

Write-Host "Validating Electron desktop shell…"
Push-Location $Desktop
if (Get-Command npm -ErrorAction SilentlyContinue) {
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed with exit code $LASTEXITCODE" }
    npm audit --audit-level=high
    if ($LASTEXITCODE -ne 0) { throw "npm audit failed with exit code $LASTEXITCODE" }
    node --check main.js
    if ($LASTEXITCODE -ne 0) { throw "desktop/main.js syntax check failed with exit code $LASTEXITCODE" }
    node --check preload.js
    if ($LASTEXITCODE -ne 0) { throw "desktop/preload.js syntax check failed with exit code $LASTEXITCODE" }
    node --check ..\src\desktop\web\app.js
    if ($LASTEXITCODE -ne 0) { throw "desktop web app syntax check failed with exit code $LASTEXITCODE" }
} else {
    throw "Node.js/npm is required to validate the Electron desktop shell."
}
Pop-Location

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) {
    $isccPath = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (Test-Path $isccPath) { $iscc = $isccPath }
}
$makensis = Get-Command makensis -ErrorAction SilentlyContinue
if (-not $makensis) {
    $nsisRoots = @($env:ELECTRON_BUILDER_CACHE, (Join-Path $OriginalLocalAppData "electron-builder\Cache")) | Where-Object { $_ -and (Test-Path $_) }
    $cached = Get-ChildItem $nsisRoots -Recurse -Filter makensis.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\Bin\\makensis\.exe$' } | Select-Object -First 1
    if ($cached) { $makensis = $cached.FullName }
}
if ($iscc) {
    Write-Host "Building JonathanAi-Setup.exe with Inno Setup…"
    & $iscc (Join-Path $PSScriptRoot "JonathanAi.iss")
} elseif ($makensis) {
    Write-Host "Building JonathanAi-Setup.exe with the standard NSIS wizard…"
    & $makensis (Join-Path $PSScriptRoot "JonathanAi.nsi")
} else {
    throw "A standard Windows installer compiler (Inno Setup or NSIS) is required."
}
if ($LASTEXITCODE -ne 0) { throw "Windows installer compiler failed with exit code $LASTEXITCODE" }

Write-Host "Artifacts in $Out"
Get-ChildItem $Out
