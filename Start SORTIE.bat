@echo off
rem Double-click to start the SORTIE GUI. Your browser opens http://127.0.0.1:8765
rem Keep this window open while you use SORTIE; close it (or press Ctrl+C) to stop.
title SORTIE
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

".venv\Scripts\python.exe" -m sortie gui %*
if errorlevel 1 (
    echo.
    echo SORTIE stopped with an error. If the port is in use, another SORTIE window may already be running.
    pause
)
