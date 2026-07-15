"""
Build the BillionBuilders video registry from the current download state.
This creates BillionBuilders_registry.csv which tracks every video from the channel,
its download/batch status, so we never re-download or re-upload.
"""

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import json
import csv
import re
import subprocess
from pathlib import Path

CHANNEL_URL = "https://www.youtube.com/@BillionBuilders"
DOWNLOAD_DIR = Path(r"d:\BabyBillion\upload_dashboard\BillionBuilders_downloads")
BATCH_DIR = Path(r"d:\BabyBillion\upload_dashboard\BillionBuilders_batches")
PROGRESS_FILE = Path(r"d:\BabyBillion\upload_dashboard\bb_download_progress.json")
REGISTRY_FILE = Path(r"d:\BabyBillion\upload_dashboard\BillionBuilders_registry.csv")


def sanitize_filename(title: str) -> str:
    title = title.encode('ascii', 'ignore').decode('ascii')
    title = re.sub(r'[^\w\s-]', '', title)
    title = re.sub(r'[\s-]+', '_', title.strip())
    title = re.sub(r'_+', '_', title).strip('_')
    return title


def main():
    # 1. Fetch video list from YouTube
    print("Fetching video list from channel...")
    cmd = [sys.executable, "-m", "yt_dlp", "--no-update",
           "--flat-playlist", "--print", "%(id)s|||%(title)s", CHANNEL_URL]
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    stdout = result.stdout.decode('utf-8', errors='replace')

    videos = []
    for line in stdout.strip().split('\n'):
        line = line.strip()
        if '|||' in line:
            vid_id, title = line.split('|||', 1)
            videos.append({"id": vid_id.strip(), "title": title.strip(),
                           "safe_name": sanitize_filename(title.strip())})

    # Deduplicate safe_names
    seen = {}
    for v in videos:
        name = v['safe_name']
        if name in seen:
            seen[name] += 1
            v['safe_name'] = f"{name}_{seen[name]}"
        else:
            seen[name] = 1

    print(f"Found {len(videos)} videos on channel.")

    # 2. Load progress
    with open(PROGRESS_FILE, 'r') as f:
        progress = json.load(f)
    downloaded_ids = set(progress.get("downloaded", []))
    failed_ids = set(progress.get("failed", []))

    # 3. Build batch lookup from existing CSVs
    video_to_batch = {}
    for csv_file in sorted(BATCH_DIR.glob("Batch_BB_*.csv")):
        batch_name = csv_file.stem
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                video_to_batch[row['video_name']] = batch_name

    # 4. Write registry
    with open(REGISTRY_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['video_id', 'youtube_title', 'safe_name', 'status', 'batch', 'file_size_mb'])

        batched = 0
        downloaded = 0
        failed = 0
        for v in videos:
            vid_id = v['id']
            safe_name = v['safe_name']
            batch = video_to_batch.get(safe_name, '')

            fpath = DOWNLOAD_DIR / f"{safe_name}.mp4"
            file_size_mb = ''
            if fpath.exists():
                file_size_mb = f"{fpath.stat().st_size / (1024*1024):.2f}"

            if batch:
                status = 'batched'
                batched += 1
            elif vid_id in downloaded_ids:
                status = 'downloaded'
                downloaded += 1
            elif vid_id in failed_ids:
                status = 'failed'
                failed += 1
            else:
                status = 'pending'

            writer.writerow([vid_id, v['title'], safe_name, status, batch, file_size_mb])

    print(f"\nRegistry written to: {REGISTRY_FILE}")
    print(f"  Batched:    {batched}")
    print(f"  Downloaded: {downloaded}")
    print(f"  Failed:     {failed}")
    print(f"  Total:      {len(videos)}")


if __name__ == "__main__":
    main()
