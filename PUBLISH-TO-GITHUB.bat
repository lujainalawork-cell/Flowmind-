@echo off
REM ===================================================================
REM  FlowMind - one-click publish to GitHub
REM  Run this from inside C:\Users\Louja\Documents\FlowMind_GitHub
REM  It never touches C:\Users\Louja\Documents\FlowMind
REM ===================================================================
cd /d "%~dp0"
title Publish FlowMind to GitHub

where git >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Git is not installed. Install "Git for Windows" from
  echo   https://git-scm.com/download/win  (accept every default),
  echo   then run this file again.
  echo.
  start "" https://git-scm.com/download/win
  pause
  exit /b 1
)

git rev-parse --git-dir >nul 2>&1
if errorlevel 1 (
  echo   Creating the repository...
  git init -b main
  if errorlevel 1 ( git init & git checkout -b main )
)

git config user.name  >nul 2>&1 || git config user.name "Lujain Alahmadi"
git config user.email >nul 2>&1 || git config user.email "flowmind@users.noreply.github.com"

echo.
echo   Staging files (the database, logs and .env are excluded by .gitignore)...
git add -A
git diff --cached --name-only
echo.

git rev-parse HEAD >nul 2>&1
if errorlevel 1 (
  git commit -m "Initial FlowMind prototype"
) else (
  git commit -m "Initial FlowMind prototype" 2>nul
)

echo.
where gh >nul 2>&1
if errorlevel 1 goto manual

echo   GitHub CLI found. Checking sign-in...
gh auth status >nul 2>&1
if errorlevel 1 (
  echo   A browser window will open so you can sign in to GitHub.
  gh auth login --web -h github.com -s repo
  if errorlevel 1 goto manual
)

echo.
echo   Creating the repository and pushing...
gh repo create FlowMind --public --source=. --remote=origin --push ^
  --description "AI-assisted workflow analysis for identifying processes worth improving or automating."
if errorlevel 1 goto manual

echo.
echo   Adding topics...
for /f "tokens=*" %%u in ('gh api user --jq .login') do set OWNER=%%u
gh api -X PUT repos/%OWNER%/FlowMind/topics -f names[]=workflow-analysis -f names[]=artificial-intelligence ^
  -f names[]=automation -f names[]=process-intelligence -f names[]=fastapi -f names[]=chrome-extension ^
  -f names[]=hackathon >nul 2>&1

echo.
echo   ============================================================
echo    Done. Your repository:
gh repo view --json url --jq .url
echo   ============================================================
echo.
pause
exit /b 0

:manual
echo.
echo   ============================================================
echo    Almost there - two steps left, about 60 seconds.
echo   ============================================================
echo.
echo    1. A browser is opening at https://github.com/new
echo       Repository name:  FlowMind
echo       Description:      AI-assisted workflow analysis for identifying
echo                         processes worth improving or automating.
echo       Choose Public. Do NOT tick "Add a README" or a license.
echo       Click "Create repository".
echo.
echo    2. Come back to this window, type your GitHub username below
echo       and press Enter. Git will open a browser to sign you in.
echo.
start "" https://github.com/new
set /p GHUSER=   GitHub username:
if "%GHUSER%"=="" (
  echo   No username entered. Run this file again when the repo exists.
  pause
  exit /b 1
)
git remote remove origin >nul 2>&1
git remote add origin https://github.com/%GHUSER%/FlowMind.git
git branch -M main
git push -u origin main
if errorlevel 1 (
  echo.
  echo   The push did not complete. Check that the repository exists and
  echo   that you signed in, then run this file again.
  pause
  exit /b 1
)
echo.
echo   ============================================================
echo    Pushed. Your repository:
echo    https://github.com/%GHUSER%/FlowMind
echo   ============================================================
echo.
pause
