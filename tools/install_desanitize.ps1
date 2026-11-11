<#
.SYNOPSIS
  Lets SORTIE's mission scripts write the event file by desanitising DCS's MissionScripting.lua.

.DESCRIPTION
  DCS removes the Lua modules os, io and lfs from the mission scripting environment in
  <DCS install>\Scripts\MissionScripting.lua. SORTIE needs io and lfs to write
  <Saved Games>\Missions\SORTIE\runtime\events.jsonl. This script:
    * backs up MissionScripting.lua to MissionScripting.lua.sortie-backup (once),
    * comments out the lines  sanitizeModule('os') / ('io') / ('lfs'),
    * can undo the change (-Undo).
  Nothing else in the file is touched (require/loadlib/package stay sanitised).

  SECURITY NOTE: with these lines disabled, any mission you run can read and write files
  on your PC. Only fly missions you trust.

  DCS updates and repairs restore the original file: run this script again afterwards.
  For co-op, the machine HOSTING the mission is the one that needs this.

.PARAMETER DcsPath
  DCS install folder (the one containing bin\DCS.exe). Auto-detected when omitted.
.PARAMETER Undo
  Restore the original file from the backup (or uncomment the lines if no backup exists).
.PARAMETER DryRun
  Show what would change without writing anything.
.PARAMETER Force
  Replace an existing backup with the current file before patching.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\install_desanitize.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\install_desanitize.ps1 -Undo
#>
[CmdletBinding()]
param(
    [string]$DcsPath,
    [switch]$Undo,
    [switch]$DryRun,
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$Marker = "-- SORTIE desanitize: "
$Modules = @("os", "io", "lfs")

function Test-DcsInstall([string]$Path) {
    if (-not $Path) { return $false }
    return (Test-Path (Join-Path $Path "bin\DCS.exe")) -or (Test-Path (Join-Path $Path "bin-mt\DCS.exe"))
}

function Find-DcsInstall {
    $candidates = @()
    foreach ($key in "HKCU:\Software\Eagle Dynamics\DCS World", "HKCU:\Software\Eagle Dynamics\DCS World OpenBeta",
                     "HKLM:\SOFTWARE\Eagle Dynamics\DCS World", "HKLM:\SOFTWARE\Eagle Dynamics\DCS World OpenBeta") {
        try { $p = (Get-ItemProperty -Path $key -ErrorAction Stop).Path; if ($p) { $candidates += $p } } catch { }
    }
    foreach ($drive in (Get-PSDrive -PSProvider FileSystem | ForEach-Object { $_.Root })) {
        foreach ($suffix in "Program Files\Eagle Dynamics\DCS World", "Program Files\Eagle Dynamics\DCS World OpenBeta",
                            "Eagle Dynamics\DCS World", "DCS World", "DCS World OpenBeta",
                            "Program Files (x86)\Steam\steamapps\common\DCSWorld", "SteamLibrary\steamapps\common\DCSWorld") {
            $candidates += (Join-Path $drive $suffix)
        }
    }
    foreach ($c in $candidates) { if (Test-DcsInstall $c) { return $c } }
    return $null
}

if (-not $DcsPath) { $DcsPath = Find-DcsInstall }
if (-not (Test-DcsInstall $DcsPath)) {
    Write-Host "FAILED: could not find a DCS install (bin\DCS.exe). Pass it explicitly:" -ForegroundColor Red
    Write-Host '  tools\install_desanitize.ps1 -DcsPath "D:\DCS World"'
    exit 1
}
$Target = Join-Path $DcsPath "Scripts\MissionScripting.lua"
$Backup = "$Target.sortie-backup"
if (-not (Test-Path $Target)) {
    Write-Host "FAILED: $Target does not exist." -ForegroundColor Red
    exit 1
}
Write-Host "DCS install : $DcsPath"
Write-Host "Target file : $Target"

function Write-Target([string[]]$Lines) {
    try {
        [System.IO.File]::WriteAllLines($Target, $Lines)
    } catch {
        Write-Host "FAILED: cannot write $Target ($($_.Exception.Message))." -ForegroundColor Red
        Write-Host "If DCS is under 'Program Files', start PowerShell with 'Run as administrator' and try again."
        exit 1
    }
}

$lines = [System.IO.File]::ReadAllLines($Target)

if ($Undo) {
    if (Test-Path $Backup) {
        if ($DryRun) { Write-Host "DRY RUN: would restore $Target from $Backup"; exit 0 }
        try { Copy-Item -Path $Backup -Destination $Target -Force } catch {
            Write-Host "FAILED: cannot restore ($($_.Exception.Message)). Try an elevated PowerShell." -ForegroundColor Red
            exit 1
        }
        Write-Host "SUCCESS: original MissionScripting.lua restored from the backup." -ForegroundColor Green
        Write-Host "The backup file was kept: $Backup"
        exit 0
    }
    $changed = 0
    $out = foreach ($line in $lines) {
        if ($line.Contains($Marker)) { $changed++; $line.Replace($Marker, "") } else { $line }
    }
    if ($changed -eq 0) { Write-Host "Nothing to undo: no SORTIE changes and no backup found."; exit 0 }
    if ($DryRun) { Write-Host "DRY RUN: would re-enable $changed sanitizeModule line(s)."; exit 0 }
    Write-Target $out
    Write-Host "SUCCESS: re-enabled $changed sanitizeModule line(s)." -ForegroundColor Green
    exit 0
}

$pattern = "^\s*sanitizeModule\(\s*['""](" + ($Modules -join "|") + ")['""]\s*\)"
$changed = 0
$out = foreach ($line in $lines) {
    if ($line -match $pattern) { $changed++; "$Marker$($line.TrimStart())" } else { $line }
}
if ($changed -eq 0) {
    $already = @($lines | Where-Object { $_.Contains($Marker) -or $_ -match "^\s*--.*sanitizeModule\(\s*['""](io|lfs)['""]" }).Count
    if ($already -gt 0) { Write-Host "Already desanitised: nothing to do." -ForegroundColor Green; exit 0 }
    Write-Host "FAILED: no sanitizeModule('os'|'io'|'lfs') lines found. The file layout may have changed;" -ForegroundColor Red
    Write-Host "nothing was modified. Open the file and check it by hand."
    exit 1
}
if ($DryRun) {
    Write-Host "DRY RUN: would comment out $changed line(s) and back up the original to $Backup"
    exit 0
}
if (Test-Path $Backup) {
    if ($Force) {
        Write-Host "WARNING: replacing the existing backup (-Force)." -ForegroundColor Yellow
        Copy-Item -Path $Target -Destination $Backup -Force
    } else {
        Write-Host "WARNING: a backup already exists and was NOT overwritten: $Backup" -ForegroundColor Yellow
        Write-Host "         (use -Force to replace it with the current file)"
    }
} else {
    try { Copy-Item -Path $Target -Destination $Backup } catch {
        Write-Host "FAILED: cannot create the backup ($($_.Exception.Message)). Nothing was modified." -ForegroundColor Red
        Write-Host "If DCS is under 'Program Files', start PowerShell with 'Run as administrator' and try again."
        exit 1
    }
    Write-Host "Backup written: $Backup"
}
Write-Target $out
Write-Host "SUCCESS: $changed sanitizeModule line(s) commented out. SORTIE can now write its event file." -ForegroundColor Green
Write-Host "To restore the original:  tools\install_desanitize.ps1 -Undo"
Write-Host "Remember: DCS updates/repairs revert this. Run the script again after each update."
exit 0
