# install_dual_startup.ps1: Register MSU2 Dual Model Monitor in Windows Startup folder
$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $base

Write-Host '=====================================================' -ForegroundColor Cyan
Write-Host '  Setup Auto-Start on Boot - MSU2 Dual Model Monitor  ' -ForegroundColor Cyan
Write-Host '=====================================================' -ForegroundColor Cyan

$startupFolder = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startupFolder 'MSU2 Dual Model Monitor.lnk'
$vbsPath = Join-Path $base 'start_dual_monitor.vbs'

if (-not (Test-Path $vbsPath)) {
    throw "Cannot find script: $vbsPath"
}

# Create Windows Startup shortcut (via wscript.exe, completely silent on boot)
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($lnkPath)
$shortcut.TargetPath = 'wscript.exe'
$shortcut.Arguments = "`"$vbsPath`""
$shortcut.WorkingDirectory = $base
$shortcut.Description = 'MSU2 MINI Real-time Token Monitor for Gemini and Claude'
$shortcut.WindowStyle = 7
$shortcut.Save()

Write-Host '[OK] Successfully registered startup shortcut:' -ForegroundColor Green
Write-Host "     $lnkPath" -ForegroundColor Gray

# Start background monitor service right now
Write-Host ''
Write-Host '[INFO] Starting dual model monitor service...' -ForegroundColor Yellow
& "$base\start_dual.ps1"

Write-Host ''
Write-Host '=====================================================' -ForegroundColor Green
Write-Host '[DONE] Auto-start on boot is now ENABLED.' -ForegroundColor Green
Write-Host '=====================================================' -ForegroundColor Green
