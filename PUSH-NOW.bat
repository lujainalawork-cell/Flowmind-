@echo off
REM Push the FlowMind_GitHub folder to the repository that already exists at
REM https://github.com/lujainalawork-cell/Flowmind-
cd /d "%~dp0"
title Push FlowMind to GitHub

where git >nul 2>&1 || (echo Git is not installed: https://git-scm.com/download/win & start "" https://git-scm.com/download/win & pause & exit /b 1)

git rev-parse --git-dir >nul 2>&1 || git init
git checkout -B main >nul 2>&1
git config user.name  >nul 2>&1 || git config user.name "Lujain Alahmadi"
git config user.email >nul 2>&1 || git config user.email "flowmind@users.noreply.github.com"

git add -A
git commit -m "Initial FlowMind prototype" >nul 2>&1

git remote remove origin >nul 2>&1
git remote add origin https://github.com/lujainalawork-cell/Flowmind-.git

echo.
echo   Pushing to https://github.com/lujainalawork-cell/Flowmind-
echo   If a browser or a sign-in window opens, sign in to GitHub and come back.
echo.
git push -u origin main
if errorlevel 1 (
  echo.
  echo   The push did not complete. Read the message above, then run this file again.
  pause
  exit /b 1
)
echo.
echo   ============================================================
echo    Pushed.  https://github.com/lujainalawork-cell/Flowmind-
echo   ============================================================
pause
