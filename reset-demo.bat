@echo off
REM Clears the CURRENT session's activity and restores the demo requests.
REM Pilot feedback from earlier participants is never touched.
curl -s -X POST -H "Content-Type: application/json" http://localhost:8000/api/reset
if errorlevel 1 (
  echo.
  echo   Could not reach FlowMind. Make sure start-flowmind.bat is running.
) else (
  echo.
  echo   Activity cleared, five demo requests waiting.
  echo   For a brand-new participant use "Start new pilot" in the app instead.
)
echo.
pause
