@echo off
REM Compound Wisdom - daily reel runner
REM Run by Task Scheduler once a day. Extra args pass through.
setlocal
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" run_reel.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo [reel.bat] run_reel.py exited with code %RC%
endlocal & exit /b %RC%
