@echo off
title Video Stream Downloader Server (Port 7921)
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtual environment not found. Running setup first...
    call setup.bat
)

echo ========================================================
echo   Starting Video Stream Downloader Server
echo   Web UI:   http://localhost:7921
echo   Endpoint: http://localhost:7921/api/download
echo ========================================================
echo.

".venv\Scripts\python.exe" run_server.py

pause
