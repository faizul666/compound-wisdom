@echo off
REM === Calm Money Daily — research runner ===
REM Tops up the topic queue with fresh Gemini-researched briefs.
REM Schedule twice daily (e.g. 2 PM and 10 PM Dhaka) via Task Scheduler.
REM Passes through extra args, e.g.  research.bat --verify

setlocal
cd /d "%~dp0"

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

"%PY%" run_research.py %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo [research.bat] run_research.py exited with code %RC%
)
endlocal & exit /b %RC%
