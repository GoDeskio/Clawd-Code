# One-command / double-click installer for GoDeskio/Clawd-Code.
# Never clones any repository except https://github.com/GoDeskio/Clawd-Code.git
$ErrorActionPreference = "Stop"
$Repo = "https://github.com/GoDeskio/Clawd-Code.git"
$Dest = if ($env:CLAWD_INSTALL_DIR) { $env:CLAWD_INSTALL_DIR } else { Join-Path $env:USERPROFILE "Jonathan\Clawd-Code" }
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-Python {
    foreach ($name in @("python", "python3", "py")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        & $cmd.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $cmd.Source }
    }
    throw "Python 3.10+ is required. Install it from https://www.python.org/downloads/ and re-run install.ps1"
}

$Py = Find-Python
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Dest) | Out-Null

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
& $Py -m src.install --source-dir $Dest @extra --yes --skip-desktop-deps @args
exit $LASTEXITCODE
