@echo off
REM ===================================================================
REM  FlowMind - AI Business Consultant MVP  (Windows)
REM  Backend, app, demo environment and pilot results: all on port 8000.
REM ===================================================================
cd /d "%~dp0"
title FlowMind

if exist "%~dp0.venv\Scripts\python.exe" (
  set "PY=%~dp0.venv\Scripts\python.exe"
  goto python_ready
)
set "PY=python"
python --version >nul 2>&1
if errorlevel 1 set "PY=py"

:python_ready
"%PY%" --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Python was not found. Install Python 3.9+ from python.org,
  echo   tick "Add python.exe to PATH", then run this file again.
  echo.
  pause
  exit /b 1
)

echo.
echo   Installing FlowMind dependencies (first run only)...
"%PY%" -m pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 (
  echo.
  echo   Could not install dependencies. Check your internet connection.
  echo.
  pause
  exit /b 1
)

echo.
echo   FlowMind is starting.
echo.
echo     Pilot (start here) http://localhost:8000/pilot
echo     FlowMind app       http://localhost:8000
echo     Guided test        http://localhost:8000/demo
echo     Pilot results      http://localhost:8000/pilot-results
echo.
echo   Load the Chrome extension from the "extension" folder
echo   (chrome://extensions - Developer mode - Load unpacked).
echo.
echo   Leave this window open during the pilot. Press Ctrl+C to stop.
echo.

if not defined FLOWMIND_NO_BROWSER start "" http://localhost:8000/pilot
"%PY%" -m uvicorn server.app:app --port 8000 --host 127.0.0.1

pause


