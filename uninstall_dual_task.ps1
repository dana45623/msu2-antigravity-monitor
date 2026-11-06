# uninstall_dual_task.ps1: Unregister MSU2 Dual Monitor from Task Scheduler
[CmdletBinding()]
param()

$taskName = "MSU2DualMonitor"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "[INFO] Unregistering scheduled task '$taskName'..." -ForegroundColor Cyan
try {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "[OK] Scheduled task '$taskName' unregistered successfully." -ForegroundColor Green
    } else {
        Write-Host "[INFO] Scheduled task '$taskName' was not found." -ForegroundColor Yellow
    }
} catch {
    Write-Warning "Error unregistering scheduled task: $_"
}

# Stop running monitor
$stopPs1 = Join-Path $scriptDir "stop_dual.ps1"
if (Test-Path $stopPs1) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopPs1
}
