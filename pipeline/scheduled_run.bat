@echo off
cd /d "%~dp0.."
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)
python pipeline\pipeline.py >> "logs\scheduled_run_%date:~-4%%date:~4,2%%date:~7,2%_%time:~0,2%%time:~3,2%.txt" 2>&1
