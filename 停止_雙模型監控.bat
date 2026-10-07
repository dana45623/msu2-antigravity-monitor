@echo off
cd /d "%~dp0"
echo ========================================================
echo   Stopping Dual Model Monitor
echo ========================================================
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0stop_dual.ps1"
echo.
ping 127.0.0.1 -n 3 >nul
