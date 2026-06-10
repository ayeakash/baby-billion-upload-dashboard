@echo off
setlocal enabledelayedexpansion
title BabyBillion Pipeline - Setup

:: ── Change to project root (one level up from pipeline/) ─────
cd /d "%~dp0.."

echo.
echo  ============================================================
echo   BabyBillion Upload Pipeline - One-Time Setup
echo  ============================================================
echo.

:: ── Check Python ──────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install Python 3.10+ from https://python.org
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  [OK] Python %PYVER% found

:: ── Create virtualenv at project root ─────────────────────────
if not exist ".venv" (
    echo  [..] Creating virtual environment...
    python -m venv .venv
    echo  [OK] Virtual environment created
) else (
    echo  [OK] Virtual environment already exists
)

:: ── Activate + install deps ───────────────────────────────────
echo  [..] Installing Python dependencies...
call .venv\Scripts\activate.bat
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo  [OK] Dependencies installed

:: ── Check FFmpeg ──────────────────────────────────────────────
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [WARN] FFmpeg not found in PATH.
    echo         The pipeline needs FFmpeg to compress videos.
    echo.
    echo         Install options:
    echo           1. winget install ffmpeg
    echo           2. Download from https://ffmpeg.org/download.html
    echo              and add the bin/ folder to your PATH.
    echo.
) else (
    echo  [OK] FFmpeg found
)

:: ── Check Chrome ──────────────────────────────────────────────
reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe" >nul 2>&1
if errorlevel 1 (
    echo  [WARN] Google Chrome not found. Install it from https://www.google.com/chrome/
) else (
    echo  [OK] Google Chrome found
)

:: ── Check credentials.py ──────────────────────────────────────
if not exist "pipeline\credentials.py" (
    echo.
    echo  [ACTION NEEDED] credentials.py not found!
    echo    1. Copy pipeline\credentials.example.py to pipeline\credentials.py
    echo    2. Fill in your Notion token, database ID, and admin login
    echo.
    copy "pipeline\credentials.example.py" "pipeline\credentials.py" >nul
    echo  [..] Created pipeline\credentials.py from template — please edit it now.
    echo.
    pause
) else (
    echo  [OK] credentials.py found
)

echo.
echo  ============================================================
echo   Setup complete! Run the pipeline with:   pipeline\run.bat
echo  ============================================================
echo.
pause
