"""
Background Runner for CMS Auto Uploader
Runs the uploader in background with logging
"""

import os
import sys
import subprocess
import time
from datetime import datetime

BASE_DIR = r"C:\Users\Aashitha\Downloads\baby-billion-upload-dashboard"
PROCESSED_IMAGES_DIR = os.path.join(BASE_DIR, "processed_images")
LOG_FILE = os.path.join(PROCESSED_IMAGES_DIR, f"upload_bg_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

print("\n" + "="*80)
print("RUNNING CMS UPLOADER IN BACKGROUND")
print("="*80 + "\n")

print(f"[*] Starting uploader...")
print(f"[*] Log file: {LOG_FILE}")
print(f"[*] You can close this window - uploader will continue running\n")

# Open log file
with open(LOG_FILE, 'w') as f:
    f.write("="*80 + "\n")
    f.write("CMS AUTO UPLOADER - BACKGROUND RUN\n")
    f.write("="*80 + "\n\n")
    f.write(f"Started: {datetime.now()}\n")
    f.write(f"Command: python cms_auto_uploader_fixed.py\n\n")
    f.write("="*80 + "\n\n")

# Run uploader and capture output
try:
    with open(LOG_FILE, 'a') as f:
        process = subprocess.Popen(
            [sys.executable, os.path.join(BASE_DIR, 'cms_auto_uploader_fixed.py')],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=BASE_DIR,
            bufsize=1
        )

        # Stream output to log file
        for line in process.stdout:
            f.write(line)
            f.flush()
            print(line, end='')

        # Wait for process to complete
        process.wait()

    # Add completion info
    with open(LOG_FILE, 'a') as f:
        f.write("\n" + "="*80 + "\n")
        f.write(f"Completed: {datetime.now()}\n")
        f.write("="*80 + "\n")

    print("\n" + "="*80)
    print("UPLOAD COMPLETE")
    print("="*80)
    print(f"\nLog file saved: {LOG_FILE}")
    print("\nResults will open in Notepad...\n")

    # Open log file
    os.startfile(LOG_FILE)
    time.sleep(2)

except Exception as e:
    print(f"\n[ERROR] {str(e)}")
    with open(LOG_FILE, 'a') as f:
        f.write(f"\n[ERROR] {str(e)}\n")

print("You can close this window now.")
