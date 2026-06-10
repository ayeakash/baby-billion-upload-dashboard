@echo off
setlocal enabledelayedexpansion
title BabyBillion Pipeline Dashboard

:: ── Ensure working directory is this script's folder ─────────
cd /d "%~dp0"

:: ── Activate venv (run setup.bat in pipeline/ first if this fails) ──
set "PIPELINE_DIR=%~dp0pipeline"

if not exist "%~dp0.venv\Scripts\activate.bat" (
    echo.
    echo  [ERROR] Virtual environment not found at:
    echo         %~dp0.venv
    echo.
    echo  Run setup.bat in pipeline\ first!
    echo.
    pause
    exit /b 1
)
call "%~dp0.venv\Scripts\activate.bat"

:: ── Check credentials ─────────────────────────────────────────
if not exist "%PIPELINE_DIR%\credentials.py" (
    echo.
    echo  [ERROR] credentials.py not found in:
    echo         %PIPELINE_DIR%
    echo.
    echo  Run setup.bat in pipeline\ first!
    echo.
    pause
    exit /b 1
)

:: ── Verify Python + Flask are available ──────────────────────
python -c "import flask" 2>nul
if errorlevel 1 (
    echo.
    echo  [ERROR] Flask is not installed in the virtual environment.
    echo  Run:  pip install flask
    echo.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo   BabyBillion Pipeline Dashboard
echo  ============================================================
echo.
echo  Starting Dashboard server on http://127.0.0.1:5000...
echo  Press Ctrl+C in this window to stop the server.
echo.

:: ── Launch browser AFTER a short delay so Flask can start ────
:: Uses a background ping-based wait, then opens the URL
start /b cmd /c "ping -n 3 127.0.0.1 >nul 2>&1 & start http://127.0.0.1:5000"

:: ── Run the Flask app from this directory ────────────────────
python "%~dp0app.py"

:: ── If Flask exits (crash or Ctrl+C), keep the window open ──
echo.
echo  [Dashboard stopped]
echo.
pause
