# uninstall_dual_startup.ps1: Remove MSU2 Dual Model Monitor from Windows Startup folder
$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $base

Write-Host '=====================================================' -ForegroundColor Cyan
Write-Host '  Disable Auto-Start on Boot - MSU2 Dual Model Monitor' -ForegroundColor Cyan
Write-Host '=====================================================' -ForegroundColor Cyan

$startupFolder = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startupFolder 'MSU2 Dual Model Monitor.lnk'

if (Test-Path $lnkPath) {
    Remove-Item $lnkPath -Force
    Write-Host "[OK] Removed startup shortcut: $lnkPath" -ForegroundColor Green
} else {
    Write-Host '[INFO] Startup shortcut did not exist.' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '=====================================================' -ForegroundColor Green
Write-Host '[DONE] Auto-start on boot is now DISABLED.' -ForegroundColor Green
Write-Host '=====================================================' -ForegroundColor Green
