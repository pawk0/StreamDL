@echo off
title Video Stream Downloader - Setup
cd /d "%~dp0"

echo ========================================================
echo   Video Stream Downloader - Environment Setup
echo ========================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [*] Creating virtual environment (.venv)...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [!] Failed to create virtual environment. Ensure Python is installed and in PATH.
        pause
        exit /b 1
    )
) else (
    echo [*] Virtual environment found.
)

echo [*] Upgrading pip and installing requirements...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\pip.exe" install -r requirements.txt

if %errorlevel% neq 0 (
    echo [!] Failed to install requirements.
    pause
    exit /b 1
)

echo.
echo ========================================================
echo   Setup completed successfully!
echo   Run 'run_server.bat' to start the local server.
echo ========================================================
echo.
pause
