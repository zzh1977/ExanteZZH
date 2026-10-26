@echo off
rem Run the organizer with its own Python environment (..\venv).
rem Usage: organize.bat scan "D:\ToSort" --out D:\AI\plan.csv
setlocal
set "PY=%~dp0..\venv\Scripts\python.exe"
if not exist "%PY%" goto :novenv
"%PY%" "%~dp0organize.py" %*
exit /b %ERRORLEVEL%

:novenv
echo [ERROR] Python environment not found: %PY%
echo Run setup_venv.bat in this folder first.
exit /b 1
