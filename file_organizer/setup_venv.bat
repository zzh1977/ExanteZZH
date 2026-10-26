@echo off
rem Create or rebuild the organizer's own Python environment in ..\venv
rem The system Python stays clean: all packages go into ..\venv only.
rem Offline: installs from ..\wheels if that folder exists. Online: downloads from PyPI.
setlocal
set "HERE=%~dp0"
set "VENV=%HERE%..\venv"
set "WHEELS=%HERE%..\wheels"

where python >nul 2>nul
if errorlevel 1 goto :nopython

if exist "%VENV%\" rmdir /s /q "%VENV%"
echo Creating Python environment: %VENV%
python -m venv "%VENV%"
if errorlevel 1 goto :fail

if exist "%WHEELS%\" goto :offline
echo Installing packages from the internet ...
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%HERE%requirements.txt"
if errorlevel 1 goto :fail
goto :done

:offline
echo Installing packages offline from %WHEELS% ...
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --no-index --find-links "%WHEELS%" -r "%HERE%requirements.txt"
if errorlevel 1 goto :fail

:done
"%VENV%\Scripts\python.exe" -c "import pypdf, docx, openpyxl, pptx, PIL, pillow_heif; print('Packages OK')"
if errorlevel 1 goto :fail
echo.
echo Done. Python environment: %VENV%
exit /b 0

:nopython
echo [ERROR] python not found. Install Python 3.14 with "Add python.exe to PATH" ticked, then open a NEW window.
exit /b 1

:fail
echo [ERROR] Setup failed, see the messages above.
echo If this is the offline PC, its Python version must match the package build - default 3.14.
exit /b 1
