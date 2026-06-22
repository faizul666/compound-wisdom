@echo off
REM Calm Money Daily - research runner
REM Run by Task Scheduler twice daily (or manually) to top up the topic queue.
REM Generates fresh researched briefs. Extra args pass through, e.g. research.bat --verify
setlocal
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" run_research.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo [research.bat] run_research.py exited with code %RC%
endlocal & exit /b %RC%
