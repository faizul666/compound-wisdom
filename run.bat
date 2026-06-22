@echo off
REM === Calm Money Daily — posting runner ===
REM Run by Windows Task Scheduler at each posting time (or manually).
REM Posts whichever slot is currently due. Passes through any extra args,
REM e.g.  run.bat --list   or   run.bat --slot quote

setlocal
cd /d "%~dp0"

REM Prefer a local virtualenv if present, else fall back to system Python.
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" run_due.py %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo [run.bat] run_due.py exited with code %RC%
)
endlocal & exit /b %RC%
