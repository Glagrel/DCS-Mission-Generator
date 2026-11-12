@echo off
rem Double-click to start the SORTIE GUI. Your browser opens http://127.0.0.1:8765
rem If SORTIE is already running, the old copy is stopped first, so this also works as "restart".
rem To stop SORTIE: close this window, or double-click "Stop SORTIE.bat".
title SORTIE - close this window to stop
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo SORTIE is not set up yet. Running setup first...
    powershell -NoProfile -ExecutionPolicy Bypass -File "tools\setup.ps1"
    if errorlevel 1 (
        echo.
        echo Setup failed. See the messages above.
        pause
        exit /b 1
    )
)

rem stop a copy that is already running (for example one started before an update)
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\stop.ps1" -Quiet

echo SORTIE is running. Keep this window open while you use it.
echo To stop: close this window, or double-click "Stop SORTIE.bat".
echo.
".venv\Scripts\python.exe" -m sortie gui %*
if errorlevel 1 (
    echo.
    echo SORTIE stopped with an error. See the message above.
    pause
)
