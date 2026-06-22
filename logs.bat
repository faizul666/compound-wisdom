@echo off
REM Calm Money Daily - live log viewer (double-click me)
REM Shows the log as it is written. Close the window or press Ctrl+C to stop.
cd /d "%~dp0"
title Calm Money Daily - live log
echo Watching logs\calm_money.log   (close window or Ctrl+C to stop)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "if(!(Test-Path logs\calm_money.log)){'(no log yet - it appears on the first run)'}; Get-Content -Path 'logs\calm_money.log' -Tail 40 -Wait"
