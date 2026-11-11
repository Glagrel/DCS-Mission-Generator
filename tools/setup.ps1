# SORTIE setup: creates the venv, installs dependencies and downloads MOOSE.
# Run from the project folder:  powershell -ExecutionPolicy Bypass -File tools\setup.ps1
# Changes nothing outside the project folder.

# Native tools (python, pip) write warnings to stderr. In Windows PowerShell 5.1 that becomes a
# terminating error under "Stop", so run with "Continue" and check exit codes explicitly.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Step([string]$What, [scriptblock]$Action) {
    Write-Host "== $What"
    & $Action
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $What (exit code $LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Invoke-Step "Creating virtual environment (.venv)" { python -m venv .venv }
}
$py = Join-Path $root ".venv\Scripts\python.exe"

Invoke-Step "Upgrading pip" { & $py -m pip install -q -U pip }

# The PyPI package named "dcs" is NOT the DCS library (that one is "pydcs"). Remove it only if
# the wrong one is actually present, so pip has nothing to warn about.
$wrong = & $py -c "import importlib.metadata as m; print(m.metadata('dcs')['Summary'])" 2>&1 | Out-String
if ($LASTEXITCODE -eq 0 -and $wrong -match "Chef") {
    Invoke-Step "Removing the unrelated 'dcs' package" { & $py -m pip uninstall -q -y dcs }
}

Invoke-Step "Installing dependencies" { & $py -m pip install -q -U -r requirements.txt }
Invoke-Step "Downloading MOOSE" { & $py tools\fetch_moose.py }
Invoke-Step "Checking the setup" { & $py -m sortie doctor }

Write-Host ""
Write-Host "Setup complete. Start the GUI with: tools\run.ps1" -ForegroundColor Green
