@echo off
cd /d "%~dp0"
echo ========================================================
echo   Starting Dual Model Monitor (Gemini + Claude)
echo ========================================================
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0start_dual.ps1"
echo.
ping 127.0.0.1 -n 3 >nul
