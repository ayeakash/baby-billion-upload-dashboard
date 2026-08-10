@echo off
REM Run CMS Auto Uploader in Background
REM This script runs the uploader and saves all output to a log file

echo Starting CMS Auto Uploader in background...
echo.

REM Get current directory
cd /d "C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard"

REM Create log file with timestamp
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c%%a%%b)
for /f "tokens=1-2 delims=/:" %%a in ('time /t') do (set mytime=%%a%%b)
set logfile=processed_images\UPLOAD_LOG_%mydate%_%mytime%.txt

REM Run the uploader in background
echo Upload started at %date% %time% > "%logfile%"
echo. >> "%logfile%"

REM Run Python script and redirect output
python cms_auto_uploader_fixed.py >> "%logfile%" 2>&1

REM Show completion message
echo.
echo ========================================
echo UPLOAD COMPLETE
echo ========================================
echo.
echo Log file: %logfile%
echo.
echo The browser should now be closing...
timeout /t 5

REM Open log file to show results
start notepad "%logfile%"
