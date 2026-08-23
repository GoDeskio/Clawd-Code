# Double-click / one-command installer for Jonathan Ai on Windows.
# Prefers the real Setup exe wizard. Falls back to the Next/Install/Finish GUI.
$ErrorActionPreference = "Stop"
$Repo = "https://github.com/GoDeskio/Clawd-Code.git"
$Dest = if ($env:CLAWD_INSTALL_DIR) { $env:CLAWD_INSTALL_DIR } else { Join-Path $env:USERPROFILE "Jonathan\Jonathan-Ai" }
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Setup = Join-Path $Here "packaging\windows\bin\JonathanAi-Setup.exe"

$unattended = $false
foreach ($arg in $args) {
    if ($arg -in @("--yes", "-Yes", "/Y")) { $unattended = $true }
}

if ((Test-Path $Setup) -and -not $unattended) {
    Start-Process -FilePath $Setup -WorkingDirectory (Split-Path -Parent $Setup)
    exit 0
}

function Find-Python {
    foreach ($name in @("pythonw", "python", "python3", "py")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        if ($name -eq "pythonw") { return $cmd.Source }
        & $cmd.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $cmd.Source }
    }
    throw "Python 3.10+ is required. Install it from https://www.python.org/downloads/ and re-run JonathanAi-Setup.exe"
}

$Py = Find-Python
$extra = @()
if (Test-Path (Join-Path $Here "src\cli.py")) {
    $extra += @("--from-local", $Here)
} else {
    $extra += @("--clone")
    if (-not (Test-Path (Join-Path $Dest "src\cli.py"))) {
        git clone --origin origin $Repo $Dest
    }
}

Set-Location $Here
if ($unattended) {
    & $Py -m src.install --source-dir $Dest @extra --yes --launch @args
} else {
    & $Py -m src.install --source-dir $Dest @extra --gui
}
exit $LASTEXITCODE
