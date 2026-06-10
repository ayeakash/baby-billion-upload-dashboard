@echo off
setlocal enabledelayedexpansion
title BabyBillion Upload Pipeline

:: ── Change to the project root (one level up from pipeline/) ─
cd /d "%~dp0.."

:: ── Activate venv (run setup.bat first if this fails) ────────
if not exist ".venv\Scripts\activate.bat" (
    echo  [ERROR] Virtual environment not found. Run setup.bat first!
    pause & exit /b 1
)
call .venv\Scripts\activate.bat

:: ── Check credentials ─────────────────────────────────────────
if not exist "pipeline\credentials.py" (
    echo  [ERROR] credentials.py not found. Run setup.bat first!
    pause & exit /b 1
)

echo.
echo  ============================================================
echo   BabyBillion Upload Pipeline
echo  ============================================================
echo.

:: ── Auto-sync: pull latest code from GitHub ───────────────────
echo  [SYNC] Pulling latest code from GitHub...
git pull --ff-only origin master 2>nul
if errorlevel 1 (
    echo  [WARN] Git pull failed — running with local code.
) else (
    echo  [SYNC] Code is up to date.
)
echo.

echo  Starting pipeline... (Chrome will open when first batch is ready)
echo  Press Ctrl+C to stop safely at any time.
echo.

python pipeline\pipeline.py %*

echo.
if errorlevel 1 (
    echo  [DONE] Pipeline finished with errors. Check logs\ for details.
) else (
    echo  [DONE] Pipeline finished successfully!
)

:: ── Auto-push: commit and push any code changes ─────────────
echo.
echo  [SYNC] Checking for code changes to push...
git add -A 2>nul
git diff --cached --quiet 2>nul
if errorlevel 1 (
    git commit -m "Auto-sync from %COMPUTERNAME% [%date%]" >nul 2>nul
    git push origin master 2>nul
    if errorlevel 1 (
        echo  [WARN] Git push failed — push manually when online.
    ) else (
        echo  [SYNC] Changes pushed to GitHub.
    )
) else (
    echo  [SYNC] No code changes to push.
)

echo.
pause
