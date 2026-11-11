# Start the SORTIE web GUI (opens http://127.0.0.1:8765 in your browser).
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
& (Join-Path $root ".venv\Scripts\python.exe") -m sortie gui @args
