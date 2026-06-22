@echo off
REM Calm Money Daily - manual run (double-click me)
REM Runs the poster now and keeps this window open so you can read the output.
REM You can pass args too, e.g.  run_now.bat --list   or   run_now.bat --slot quote
title Calm Money Daily - manual run
call "%~dp0run.bat" %*
echo.
echo ==================================================
echo Finished with exit code %ERRORLEVEL%.
echo Press any key to close this window.
echo ==================================================
pause >nul
