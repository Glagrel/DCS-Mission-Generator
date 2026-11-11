# SORTIE setup: creates the venv, installs dependencies and downloads MOOSE.
# Run from the project folder:  powershell -ExecutionPolicy Bypass -File tools\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path ".venv")) { python -m venv .venv }
$py = Join-Path $root ".venv\Scripts\python.exe"
& $py -m pip install -q -U pip
# NOTE: the PyPI package named "dcs" is NOT the DCS library. The right one is "pydcs".
& $py -m pip uninstall -q -y dcs 2>$null
& $py -m pip install -q -U -r requirements.txt
& $py tools\fetch_moose.py
& $py -m sortie doctor
Write-Host "Setup complete. Start the GUI with: tools\run.ps1"
