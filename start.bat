@echo off
title Sky ^& Space Sentinel
cd /d "%~dp0"

echo ============================================
echo   Sky ^& Space Sentinel - launching...
echo ============================================
echo.

REM --- Check Python is installed ---
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Please install it from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

REM --- Create a virtual environment on first run only ---
if not exist "venv\" (
    echo First run detected - setting up environment, please wait...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install --quiet fastapi uvicorn
) else (
    call venv\Scripts\activate.bat
)

REM --- Open the browser after a short delay, then start the server ---
start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8000"

echo Server starting at http://127.0.0.1:8000
echo Close this window to stop the program.
echo.

uvicorn backend:app --host 127.0.0.1 --port 8000

pause
