@echo off
setlocal enabledelayedexpansion
title BabyBillion Pipeline Dashboard

:: ── Ensure working directory is this script's folder ─────────
cd /d "%~dp0"

:: ── Pipeline directory ─────────────────────────────────────────
set "PIPELINE_DIR=%~dp0pipeline"

:: ── Try venv first, fall back to global Python ──────────────
if exist "%~dp0.venv\Scripts\activate.bat" (
    call "%~dp0.venv\Scripts\activate.bat"
    echo  [OK] Using virtual environment
) else (
    echo  [INFO] No .venv found, using system Python
)

:: ── Check credentials ─────────────────────────────────────────
if not exist "%PIPELINE_DIR%\credentials.py" (
    echo.
    echo  [ERROR] credentials.py not found in:
    echo         %PIPELINE_DIR%
    echo.
    echo  Create credentials.py with your Notion token!
    echo.
    pause
    exit /b 1
)

:: ── Verify Python + Flask are available ──────────────────────
python -c "import flask" 2>nul
if errorlevel 1 (
    echo.
    echo  [ERROR] Flask is not installed.
    echo  Run:  pip install flask requests selenium
    echo.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo   BabyBillion Pipeline Dashboard
echo  ============================================================
echo.
echo  Starting Dashboard server on http://127.0.0.1:5050...
echo  Press Ctrl+C in this window to stop the server.
echo.

:: ── Launch browser AFTER a short delay so Flask can start ────
start /b cmd /c "ping -n 3 127.0.0.1 >nul 2>&1 & start http://127.0.0.1:5050"

:: ── Run the Flask app from this directory ────────────────────
python "%~dp0app.py"

:: ── If Flask exits (crash or Ctrl+C), keep the window open ──
echo.
echo  [Dashboard stopped]
echo.
pause
