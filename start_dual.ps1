# start_dual.ps1: Start the Gemini & Claude Dual Usage Monitor
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# 1. Stop any existing monitors or extenders
& "$scriptDir\stop_dual.ps1" | Out-Null
& "$scriptDir\stop_extender.ps1" | Out-Null

Start-Sleep -Milliseconds 600

# 2. Locate pythonw.exe
$pyw = $null
$candidates = @(
    "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\pythonw.exe",
    (Get-Item "$env:LOCALAPPDATA\Python\pythoncore-*\pythonw.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName -ErrorAction SilentlyContinue),
    ((Get-Command python.exe -ErrorAction SilentlyContinue).Path -replace 'python\.exe$', 'pythonw.exe')
) | Where-Object { $_ -and (Test-Path $_) -and ($_ -notlike '*WindowsApps*') }

if ($candidates) { $pyw = $candidates[0] }
if (-not $pyw) {
    try {
        $probe = & py -c "import sys, pathlib; print(pathlib.Path(sys.executable).parent / 'pythonw.exe')"
        if ($probe -and (Test-Path $probe) -and ($probe -notlike '*WindowsApps*')) {
            $pyw = $probe
        }
    } catch {}
}

if (-not $pyw) {
    Write-Error "pythonw.exe not found."
    exit 1
}

# 3. Start background dual monitor via WMI (fully detached)
$pyScript = Join-Path $scriptDir "dual_usage_monitor.py"
$cmd = "`"$pyw`" `"$pyScript`" --fps 9.0 --brightness 0.88"
$res = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd; CurrentDirectory = $scriptDir }
if ($res.ReturnValue -ne 0) {
    Write-Error "Failed to start dual monitor, code: $($res.ReturnValue)"
    exit $res.ReturnValue
}

$newPid = $res.ProcessId
Start-Sleep -Seconds 1

Write-Host "[SUCCESS] Dual Usage Monitor started successfully! PID: $newPid" -ForegroundColor Green
Write-Host "Screen updated with Gemini & Claude token quotas in real-time." -ForegroundColor Cyan
