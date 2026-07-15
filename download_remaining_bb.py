"""
download_remaining_bb.py — Download BabyBillion YouTube videos not already
on the app or in the brand exclusion list.

Usage:
    python download_remaining_bb.py --dry-run    # List remaining videos only
    python download_remaining_bb.py              # Download remaining videos
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
import unicodedata

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
YT_DIR = os.path.join(BASE_DIR, "youtube")
DOWNLOAD_DIR = os.path.join(YT_DIR, "downloads")

LIVE_CSV = os.path.join(YT_DIR, "BabyBillion YT Videos.csv")
BRAND_CSV = os.path.join(YT_DIR, "Brand videos.csv")

CHANNEL_URL = "https://www.youtube.com/@BabyBillionn"


def normalize_title(title: str) -> str:
    """Normalize a title for fuzzy comparison."""
    # Remove emoji and non-ASCII
    title = unicodedata.normalize("NFKD", title)
    title = title.encode("ascii", "ignore").decode("ascii")
    # Lowercase
    title = title.lower()
    # Remove all non-alphanumeric characters
    title = re.sub(r"[^a-z0-9]+", " ", title)
    # Collapse whitespace
    title = re.sub(r"\s+", " ", title).strip()
    return title


def load_brand_video_ids() -> set[str]:
    """Load YouTube video IDs from the brand exclusion CSV."""
    ids = set()
    with open(BRAND_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            vid = row.get("Content", "").strip()
            if vid:
                ids.add(vid)
    print(f"  [INFO] Loaded {len(ids)} brand video IDs to exclude")
    return ids


def load_live_titles() -> set[str]:
    """Load normalized titles from the live-on-app CSV."""
    titles = set()
    with open(LIVE_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw = row.get("video_title", "").strip()
            if raw:
                titles.add(normalize_title(raw))
    print(f"  [INFO] Loaded {len(titles)} live video titles to exclude")
    return titles


def fetch_channel_videos() -> list[dict]:
    """Fetch all video IDs and titles from the channel using yt-dlp."""
    print("  [FETCH] Getting video list from BabyBillion channel...")
    print("          This may take a minute...")

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--print", "%(id)s\t%(title)s",
        "--no-warnings",
        CHANNEL_URL,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        print(f"  [ERROR] yt-dlp failed:\n{result.stderr}")
        sys.exit(1)

    videos = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            videos.append({"id": parts[0].strip(), "title": parts[1].strip()})

    print(f"  [FETCH] Found {len(videos)} total videos on the channel")
    return videos


def find_remaining(channel_videos: list[dict],
                   brand_ids: set[str],
                   live_titles: set[str]) -> list[dict]:
    """Find videos not in brand list or live list."""
    remaining = []
    excluded_brand = 0
    excluded_live = 0

    for v in channel_videos:
        vid = v["id"]
        title = v["title"]
        norm = normalize_title(title)

        if vid in brand_ids:
            excluded_brand += 1
            continue

        if norm in live_titles:
            excluded_live += 1
            continue

        remaining.append(v)

    print(f"\n  ── Filtering Results ──────────────────────")
    print(f"  Total on channel:     {len(channel_videos)}")
    print(f"  Excluded (brand):     {excluded_brand}")
    print(f"  Excluded (live/app):  {excluded_live}")
    print(f"  Remaining to download: {len(remaining)}")
    print()

    return remaining


def download_videos(videos: list[dict]):
    """Download videos in 1080p MP4 format."""
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    total = len(videos)
    print(f"  [DOWNLOAD] Downloading {total} videos to {DOWNLOAD_DIR}")
    print()

    for i, v in enumerate(videos, 1):
        vid = v["id"]
        title = v["title"]
        url = f"https://www.youtube.com/watch?v={vid}"

        print(f"  [{i}/{total}] {title}")
        print(f"           {url}")

        cmd = [
            "yt-dlp",
            "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
            "--no-overwrites",
            "--no-warnings",
            "--restrict-filenames",
            url,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)

        if result.returncode == 0:
            print(f"           ✅ Done")
        else:
            print(f"           ❌ Failed: {result.stderr[:200]}")

        print()


def main():
    dry_run = "--dry-run" in sys.argv

    print()
    print("  ============================================================")
    print("   BabyBillion — Download Remaining Videos")
    print("  ============================================================")
    print()

    # 1. Load exclusion lists
    brand_ids = load_brand_video_ids()
    live_titles = load_live_titles()

    # 2. Fetch channel listing
    channel_videos = fetch_channel_videos()

    # 3. Compute remaining
    remaining = find_remaining(channel_videos, brand_ids, live_titles)

    if not remaining:
        print("  🎉 Nothing to download — all channel videos are accounted for!")
        return

    # 4. List remaining
    print("  ── Videos to Download ────────────────────────")
    for i, v in enumerate(remaining, 1):
        print(f"  {i:3d}. [{v['id']}] {v['title']}")
    print()

    # Save list to CSV for reference
    remaining_csv = os.path.join(YT_DIR, "remaining_to_download.csv")
    with open(remaining_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["video_id", "title", "url"])
        for v in remaining:
            writer.writerow([v["id"], v["title"], f"https://www.youtube.com/watch?v={v['id']}"])
    print(f"  [SAVED] Remaining list → {remaining_csv}")
    print()

    if dry_run:
        print("  ── DRY RUN — No downloads performed ──")
        print(f"  Run without --dry-run to download {len(remaining)} videos.")
        return

    # 5. Download
    download_videos(remaining)
    print("  ============================================================")
    print("   Download complete!")
    print("  ============================================================")


if __name__ == "__main__":
    main()
