# Stops a running SORTIE GUI (the Python process listening on the SORTIE port).
# Safe at any time: campaign state lives in the database and is saved after every step.
param([int]$Port = 8765, [switch]$Quiet)
$found = $false
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId = $($c.OwningProcess)" -ErrorAction SilentlyContinue
    # only ever stop SORTIE itself, never some other program that happens to use the port
    if ($p -and $p.Name -like "python*" -and $p.CommandLine -match "sortie") {
        Stop-Process -Id $p.ProcessId -Force
        $found = $true
        if (-not $Quiet) { Write-Host "SORTIE stopped." -ForegroundColor Green }
    } elseif ($p -and -not $Quiet) {
        Write-Host "Port $Port is used by $($p.Name), which is not SORTIE. Nothing was stopped." -ForegroundColor Yellow
    }
}
if (-not $found -and -not $Quiet) { Write-Host "SORTIE is not running." }
