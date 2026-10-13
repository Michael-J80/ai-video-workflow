@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run install.ps1 with Python 3.12 first. See README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m app
if errorlevel 1 pause
