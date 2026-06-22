@echo off
REM Calm Money Daily - posting runner
REM Run by Task Scheduler at each posting time (or manually).
REM Posts whichever slot is due now. Extra args pass through, e.g. run.bat --list
setlocal
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" run_due.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo [run.bat] run_due.py exited with code %RC%
endlocal & exit /b %RC%
