@echo off
rem Double-click to stop SORTIE. Nothing is lost: the campaign is saved after every step.
title Stop SORTIE
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\stop.ps1"
timeout /t 3 >nul
