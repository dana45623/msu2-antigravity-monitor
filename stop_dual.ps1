# stop_dual.ps1: Stop Dual Usage Monitor
$ErrorActionPreference = "SilentlyContinue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$lockFile = Join-Path $scriptDir "dual_usage_monitor.lock"

$stoppedCount = 0

# 1. Stop by lock file PID
if (Test-Path $lockFile) {
    try {
        $pidVal = [int](Get-Content $lockFile).Trim()
        if ($pidVal -gt 0) {
            Stop-Process -Id $pidVal -Force -ErrorAction SilentlyContinue
            $stoppedCount++
        }
    } catch {}
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
}

# 2. Stop any remaining dual_usage_monitor.py processes
$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*dual_usage_monitor.py*" }
foreach ($p in $procs) {
    try {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        $stoppedCount++
    } catch {}
}

# 3. Stop old gemini/gpt monitors if any
$oldProcs = Get-CimInstance Win32_Process | Where-Object { 
    $_.CommandLine -like "*gemini_usage_monitor.py*" -or $_.CommandLine -like "*gpt_usage_monitor.py*"
}
foreach ($p in $oldProcs) {
    try {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        $stoppedCount++
    } catch {}
}

Write-Host "[OK] Stopped Dual Usage Monitor ($stoppedCount processes terminated)." -ForegroundColor Green
