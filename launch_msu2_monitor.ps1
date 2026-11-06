# launch_msu2_monitor.ps1
# Launcher for MSU2 Dual Model Monitor (CatDesk)
# Conforms to SKILL-SCHEDULE-01, SKILL-100 & SKILL-120
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
$taskName = "MSU2DualMonitor"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$libPath = Join-Path $ScriptDir "common_launcher_lib.ps1"
if (Test-Path $libPath) { . $libPath }

function Log-Msg($msg) {
    if (Get-Command Log-Launcher -ErrorAction SilentlyContinue) {
        Log-Launcher $taskName $msg
    } else {
        $logPath = Join-Path $env:TEMP "ScheduledTask_$taskName.log"
        $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
        Add-Content -Path $logPath -Value $line -ErrorAction SilentlyContinue
    }
}

Log-Msg "=== Starting MSU2 Dual Monitor Launcher ==="

# 1. 300s self-healing loop for P: drive
$targetScript = "P:\0. CatDeskWorkspace\小螢幕顯示GPT用量\start_dual.ps1"
$waited = 0
while (-not (Test-Path $targetScript) -and $waited -lt 300) {
    Start-Sleep -Seconds 3
    $waited += 3
}

if (-not (Test-Path $targetScript)) {
    Log-Msg "FATAL: Timeout 300s waiting for target: $targetScript"
    exit 1
}

# 2. Check if already running
$running = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { 
    $_.CommandLine -like "*dual_usage_monitor.py*" 
}
if ($running) {
    Log-Msg "Notice: dual_usage_monitor.py is already running. Exiting launcher."
    exit 0
}

# 3. Launch via start_dual.ps1
$workDir = Split-Path $targetScript -Parent
Log-Msg "Launching daemon via: $targetScript"
Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$targetScript`"" -WorkingDirectory $workDir -WindowStyle Hidden
Log-Msg "MSU2 Dual Monitor triggered successfully."
exit 0
