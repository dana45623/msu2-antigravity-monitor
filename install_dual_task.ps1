# install_dual_task.ps1: Register MSU2 Dual Monitor in Windows Task Scheduler (AtLogOn)
# Conforms to SKILL-SCHEDULE-01, SKILL-100 & SKILL-120
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$taskName = "MSU2DualMonitor"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Setup Scheduled Task - MSU2 Dual Model Monitor" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Ensure standard SSD launcher exists
$stdLauncherDir = "$env:USERPROFILE\_ScheduledTaskLaunchers"
if (-not (Test-Path $stdLauncherDir)) {
    New-Item -ItemType Directory -Path $stdLauncherDir -Force | Out-Null
}

$launcherSrc = Join-Path $scriptDir "launch_msu2_monitor.ps1"
$launcherDst = Join-Path $stdLauncherDir "launch_msu2_monitor.ps1"

# Copy or create launcher in _ScheduledTaskLaunchers
if (Test-Path $launcherSrc) {
    Copy-Item -Path $launcherSrc -Destination $launcherDst -Force
}

if (-not (Test-Path $launcherDst)) {
    throw "Launcher not found at $launcherDst"
}

# 2. Build Task definition
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcherDst`"" `
    -WorkingDirectory $stdLauncherDir

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# 3. Register or Update Task
try {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "[OK] Existing task '$taskName' removed." -ForegroundColor Yellow
    }
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    Write-Host "[OK] Successfully registered scheduled task '$taskName' (AtLogOn, ExecutionTimeLimit=Unlimited)." -ForegroundColor Green
} catch {
    Write-Error "Failed to register scheduled task: $_"
    exit 1
}

# 4. Backup to cloud via backup_schedules_to_cloud.ps1
$backupScript = Join-Path $stdLauncherDir "backup_schedules_to_cloud.ps1"
if (Test-Path $backupScript) {
    Write-Host "`n[INFO] Backing up scheduled tasks to cloud sync..." -ForegroundColor Cyan
    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $backupScript
    } catch {
        Write-Warning "Backup to cloud encountered non-fatal error: $_"
    }
}

# 5. Launch service now
Write-Host "`n[INFO] Starting MSU2 Dual Model Monitor service..." -ForegroundColor Cyan
$startPs1 = Join-Path $scriptDir "start_dual.ps1"
if (Test-Path $startPs1) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startPs1
}

Write-Host "`n[DONE] MSU2 Dual Model Monitor scheduled task setup complete." -ForegroundColor Green
