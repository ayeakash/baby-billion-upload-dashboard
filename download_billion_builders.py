"""
Download NEW videos from the BillionBuilders YouTube channel and create upload batches.

Uses BillionBuilders_registry.csv as the single source of truth to track which
videos have already been downloaded & batched — so you never upload the same video twice.

Usage:
  python download_billion_builders.py          # Download new videos + create batches
  python download_billion_builders.py --check  # Just show what's new without downloading

- Downloads in vertical 1080p MP4 format
- Creates batches of up to 100MB
- Each batch has a CSV (for upload dashboard) and ZIP file
"""

import os
import sys
import re
import csv
import json
import shutil
import zipfile
import subprocess
import time
from pathlib import Path
from datetime import datetime

# Fix Windows console encoding to handle Unicode replacement characters
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# === Configuration ===
CHANNEL_URL = "https://www.youtube.com/@BillionBuilders"
DOWNLOAD_DIR = Path(r"d:\BabyBillion\upload_dashboard\BillionBuilders_downloads")
BATCH_DIR = Path(r"d:\BabyBillion\upload_dashboard\BillionBuilders_batches")
REGISTRY_FILE = Path(r"d:\BabyBillion\upload_dashboard\BillionBuilders_registry.csv")
MAX_BATCH_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB

# CSV metadata for upload dashboard
CHANNEL_NAME = "BillionBuilders"
CATEGORIES_NAME = "Entertainment"
AGE_GROUPS = ""
TAGS = ""
PLAYLIST_NAME = ""
CONTENT_FORMATS = ""
CONTENT_TYPES = "Original"
LANGUAGE = "English"

# yt-dlp command base
YT_DLP = [sys.executable, "-m", "yt_dlp", "--no-update"]


def sanitize_filename(title: str) -> str:
    """Convert YouTube title to a file-safe name with underscores."""
    title = title.encode('ascii', 'ignore').decode('ascii')
    title = re.sub(r'[^\w\s-]', '', title)
    title = re.sub(r'[\s-]+', '_', title.strip())
    title = re.sub(r'_+', '_', title).strip('_')
    return title


def load_registry() -> dict:
    """
    Load the registry CSV. Returns a dict keyed by video_id.
    Each value is a dict with: youtube_title, safe_name, status, batch, file_size_mb
    """
    registry = {}
    if REGISTRY_FILE.exists():
        with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                registry[row['video_id']] = row
    return registry


def save_registry(registry: dict):
    """Save the registry dict back to CSV."""
    with open(REGISTRY_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['video_id', 'youtube_title', 'safe_name', 'status', 'batch', 'file_size_mb'])
        for vid_id, row in registry.items():
            writer.writerow([
                vid_id,
                row.get('youtube_title', ''),
                row.get('safe_name', ''),
                row.get('status', 'pending'),
                row.get('batch', ''),
                row.get('file_size_mb', ''),
            ])


def get_video_list() -> list[dict]:
    """Fetch all video IDs and titles from the channel."""
    print("Fetching video list from channel...")
    cmd = YT_DLP + [
        "--flat-playlist",
        "--print", "%(id)s|||%(title)s",
        CHANNEL_URL
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    stdout = result.stdout.decode('utf-8', errors='replace')
    stderr = result.stderr.decode('utf-8', errors='replace')
    if result.returncode != 0:
        print(f"Error fetching video list: {stderr}")
        sys.exit(1)

    videos = []
    for line in stdout.strip().split('\n'):
        line = line.strip()
        if '|||' in line:
            vid_id, title = line.split('|||', 1)
            title = title.strip()
            safe_name = sanitize_filename(title)
            videos.append({
                "id": vid_id.strip(),
                "title": title,
                "safe_name": safe_name,
            })

    # Deduplicate safe_names by appending _2, _3, etc.
    seen = {}
    for v in videos:
        name = v['safe_name']
        if name in seen:
            seen[name] += 1
            v['safe_name'] = f"{name}_{seen[name]}"
        else:
            seen[name] = 1

    print(f"Found {len(videos)} videos on channel.")
    return videos


def download_video(video: dict) -> bool:
    """Download a single video in vertical 1080p MP4."""
    output_path = DOWNLOAD_DIR / f"{video['safe_name']}.mp4"

    if output_path.exists() and output_path.stat().st_size > 0:
        print(f"  Already downloaded: {video['safe_name']}")
        return True

    print(f"  Downloading: {video['title']} -> {video['safe_name']}.mp4")
    url = f"https://www.youtube.com/watch?v={video['id']}"

    cmd = YT_DLP + [
        "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "--merge-output-format", "mp4",
        "--output", str(output_path),
        "--no-playlist",
        "--retries", "3",
        "--fragment-retries", "3",
        "--socket-timeout", "30",
        url
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=600)
        stderr = result.stderr.decode('utf-8', errors='replace')
        if result.returncode != 0:
            print(f"  ERROR downloading {video['id']}: {stderr[-500:] if stderr else 'Unknown error'}")
            return False
        return output_path.exists() and output_path.stat().st_size > 0
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT downloading {video['id']}")
        return False
    except Exception as e:
        print(f"  EXCEPTION downloading {video['id']}: {e}")
        return False


def get_next_batch_number() -> int:
    """Find the next available batch number by scanning existing batches."""
    existing = list(BATCH_DIR.glob("Batch_BB_*.csv"))
    if not existing:
        return 1
    nums = []
    for p in existing:
        try:
            num = int(p.stem.split('_')[-1])
            nums.append(num)
        except ValueError:
            pass
    return max(nums) + 1 if nums else 1


def create_batches(videos: list[dict]) -> list[list[dict]]:
    """Group downloaded videos into batches of up to 100MB."""
    batches = []
    current_batch = []
    current_size = 0

    available = []
    for v in videos:
        fpath = DOWNLOAD_DIR / f"{v['safe_name']}.mp4"
        if fpath.exists() and fpath.stat().st_size > 0:
            v['file_path'] = fpath
            v['file_size'] = fpath.stat().st_size
            available.append(v)

    available.sort(key=lambda x: x['safe_name'])
    print(f"\n{len(available)} new videos available for batching.")

    if not available:
        return []

    for v in available:
        if current_batch and (current_size + v['file_size']) > MAX_BATCH_SIZE_BYTES:
            batches.append(current_batch)
            current_batch = []
            current_size = 0

        current_batch.append(v)
        current_size += v['file_size']

    if current_batch:
        batches.append(current_batch)

    print(f"Created {len(batches)} new batches.")
    return batches


def write_batch(batch_num: int, videos: list[dict]) -> str:
    """Write a single batch: CSV + ZIP + folder. Returns batch name."""
    batch_name = f"Batch_BB_{batch_num:03d}"
    batch_folder = BATCH_DIR / batch_name

    batch_folder.mkdir(parents=True, exist_ok=True)

    # --- Write CSV ---
    csv_path = BATCH_DIR / f"{batch_name}.csv"
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            "video_name", "categories_name", "age_groups", "channel_name",
            "tags", "playlist_name", "content_formats", "content_types", "language"
        ])
        for v in videos:
            writer.writerow([
                v['safe_name'], CATEGORIES_NAME, AGE_GROUPS, CHANNEL_NAME,
                TAGS, PLAYLIST_NAME, CONTENT_FORMATS, CONTENT_TYPES, LANGUAGE
            ])

    # --- Copy files to batch folder + create ZIP ---
    zip_path = BATCH_DIR / f"{batch_name}.zip"
    total_size = 0
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zf:
        for v in videos:
            src = v['file_path']
            dest = batch_folder / f"{v['safe_name']}.mp4"
            total_size += v['file_size']

            if not dest.exists():
                shutil.copy2(src, dest)

            zf.write(src, f"{v['safe_name']}.mp4")

    size_mb = total_size / (1024 * 1024)
    print(f"  {batch_name}: {len(videos)} videos, {size_mb:.1f} MB")
    print(f"    CSV: {csv_path}")
    print(f"    ZIP: {zip_path}")
    return batch_name


def main():
    check_only = "--check" in sys.argv

    # Create directories
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    BATCH_DIR.mkdir(parents=True, exist_ok=True)

    # --- Load registry (single source of truth) ---
    registry = load_registry()
    print(f"Registry loaded: {len(registry)} videos tracked.")

    # --- Phase 1: Get current video list from YouTube ---
    all_videos = get_video_list()

    # --- Identify NEW videos (not in registry) ---
    new_videos = [v for v in all_videos if v['id'] not in registry]

    if not new_videos:
        print("\n✅ No new videos found. Everything is already tracked!")
        return

    print(f"\n🆕 {len(new_videos)} NEW videos found:")
    for v in new_videos:
        print(f"  - {v['title']} ({v['id']})")

    if check_only:
        print("\n[--check mode] Exiting without downloading.")
        return

    # --- Phase 2: Download new videos ---
    print(f"\n{'='*60}")
    print(f"PHASE 2: Downloading {len(new_videos)} new videos")
    print(f"{'='*60}")

    downloaded = []
    failed = []

    for i, video in enumerate(new_videos, 1):
        print(f"\n[{i}/{len(new_videos)}] ", end="")
        success = download_video(video)

        fpath = DOWNLOAD_DIR / f"{video['safe_name']}.mp4"
        file_size_mb = ""
        if fpath.exists():
            file_size_mb = f"{fpath.stat().st_size / (1024*1024):.2f}"

        if success:
            downloaded.append(video)
            registry[video['id']] = {
                'youtube_title': video['title'],
                'safe_name': video['safe_name'],
                'status': 'downloaded',
                'batch': '',
                'file_size_mb': file_size_mb,
            }
        else:
            failed.append(video)
            registry[video['id']] = {
                'youtube_title': video['title'],
                'safe_name': video['safe_name'],
                'status': 'failed',
                'batch': '',
                'file_size_mb': '',
            }

        # Save registry periodically
        if (i) % 5 == 0:
            save_registry(registry)

    save_registry(registry)

    print(f"\n{'='*60}")
    print(f"Download complete: {len(downloaded)} succeeded, {len(failed)} failed")
    if failed:
        print(f"Failed: {[v['title'] for v in failed]}")
    print(f"{'='*60}")

    if not downloaded:
        print("\nNo new videos downloaded. Nothing to batch.")
        return

    # --- Phase 3: Create batches for NEW videos only ---
    print(f"\n{'='*60}")
    print("PHASE 3: Creating batches for new videos")
    print(f"{'='*60}")

    batches = create_batches(downloaded)
    start_batch_num = get_next_batch_number()

    for i, batch_videos in enumerate(batches):
        batch_num = start_batch_num + i
        batch_name = write_batch(batch_num, batch_videos)

        # Update registry with batch assignment
        for v in batch_videos:
            if v['id'] in registry:
                registry[v['id']]['status'] = 'batched'
                registry[v['id']]['batch'] = batch_name

    save_registry(registry)

    # --- Summary ---
    total_batched = sum(1 for r in registry.values() if r.get('status') == 'batched')
    total_failed = sum(1 for r in registry.values() if r.get('status') == 'failed')

    print(f"\n{'='*60}")
    print(f"ALL DONE!")
    print(f"  Channel videos:   {len(all_videos)}")
    print(f"  Already tracked:  {len(all_videos) - len(new_videos)}")
    print(f"  New this run:     {len(new_videos)}")
    print(f"  Downloaded:       {len(downloaded)}")
    print(f"  Failed:           {len(failed)}")
    print(f"  New batches:      {len(batches)}")
    print(f"  Total batched:    {total_batched}")
    print(f"  Total failed:     {total_failed}")
    print(f"  Registry:         {REGISTRY_FILE}")
    print(f"  Batch output:     {BATCH_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
