"""Create ZIP file from downloaded videos."""

import zipfile
import os
from pathlib import Path
from config import DOWNLOADS_DIR, BATCHES_DIR

download_dir = Path(DOWNLOADS_DIR) / "Stories_Entertainment"
zip_path = Path(BATCHES_DIR) / "Stories_Entertainment_Videos.zip"

if not download_dir.exists():
    print(f"Error: {download_dir} not found")
    exit(1)

mp4_files = list(download_dir.glob("*.mp4"))
print(f"Creating ZIP with {len(mp4_files)} video files...")
print(f"From: {download_dir}")
print(f"To: {zip_path}")

with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    for i, mp4_file in enumerate(sorted(mp4_files), 1):
        zf.write(mp4_file, arcname=mp4_file.name)
        print(f"  [{i}/{len(mp4_files)}] {mp4_file.name}")

size_mb = zip_path.stat().st_size / (1024 * 1024)
print(f"\n✓ ZIP created: {zip_path.name} ({size_mb:.1f} MB)")
