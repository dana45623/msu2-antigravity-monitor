# stop_dual.ps1: Graceful Stop Dual Usage Monitor with Flush and 2s Timeout Fallback
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force -ErrorAction SilentlyContinue
$ErrorActionPreference = "SilentlyContinue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$lockFile = Join-Path $scriptDir "dual_usage_monitor.lock"
$stopFile = Join-Path $scriptDir "dual_usage_monitor.stop"

# 1. Send graceful stop signal to let running monitor flush buffer and close serial port
try {
    [System.IO.File]::WriteAllText($stopFile, [string](Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
} catch {}

function Get-RunningMonitorProcesses {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { 
        $_.CommandLine -like "*dual_usage_monitor.py*" -or
        $_.CommandLine -like "*gemini_usage_monitor.py*" -or
        $_.CommandLine -like "*gpt_usage_monitor.py*"
    }
}

# 2. Wait up to 2.0s for graceful shutdown (check every 100ms)
$waitedMs = 0
$targetProcs = Get-RunningMonitorProcesses
while ($targetProcs -and ($waitedMs -lt 2000)) {
    Start-Sleep -Milliseconds 100
    $waitedMs += 100
    $targetProcs = Get-RunningMonitorProcesses
}

# 3. If any processes still running after 2.0s, force stop them
$killedCount = 0
if ($targetProcs) {
    foreach ($p in $targetProcs) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
            $killedCount++
        } catch {}
    }
}

# 4. Clean up signal and lock files
if (Test-Path $stopFile) {
    Remove-Item $stopFile -Force -ErrorAction SilentlyContinue
}
if (Test-Path $lockFile) {
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
}

if ($killedCount -gt 0) {
    Write-Host "[OK] Stopped Dual Usage Monitor (Graceful wait: ${waitedMs}ms, Forced kills: $killedCount)." -ForegroundColor Yellow
} else {
    Write-Host "[OK] Stopped Dual Usage Monitor gracefully (${waitedMs}ms, buffer flushed cleanly)." -ForegroundColor Green
}
