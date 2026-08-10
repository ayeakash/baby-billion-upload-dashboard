"""
batch_videos_by_size.py -- Organize videos into batches (max 100MB each) with CSVs and ZIPs.

Process:
  1. Read the Stories_Entertainment CSV
  2. Match videos to CSV rows
  3. Group videos into batches (max 100MB per batch)
  4. Create CSV for each batch
  5. Create ZIP for each batch
"""

import sys
import os
import csv
import zipfile
import logging
from pathlib import Path
from datetime import datetime
from config import DOWNLOADS_DIR, BATCHES_DIR

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)

MAX_BATCH_SIZE_MB = 100
MAX_BATCH_SIZE_BYTES = MAX_BATCH_SIZE_MB * 1024 * 1024


def find_latest_csv():
    """Find the latest Stories_Entertainment CSV."""
    batches_path = Path(BATCHES_DIR)
    csv_files = sorted(batches_path.glob("Stories_Entertainment_*.csv"), reverse=True)
    return csv_files[0] if csv_files else None


def get_video_size(video_path: Path) -> int:
    """Get file size in bytes."""
    try:
        return video_path.stat().st_size
    except Exception:
        return 0


def create_batches(csv_file: Path, videos_source_dir: Path) -> list[dict]:
    """
    Create batches of videos (max 100MB each).
    Returns: [{batch_number, videos: [{video_info}], total_size_mb}]
    """
    # Get all downloaded video files with sizes
    available_videos = {}
    for f in videos_source_dir.glob("*.mp4"):
        available_videos[f.name] = {
            "path": f,
            "size": get_video_size(f),
        }

    # Read CSV and collect video info
    video_list = []
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            video_name = row.get("video_name", "").strip()
            if not video_name:
                continue

            video_file = available_videos.get(f"{video_name}.mp4")
            if not video_file:
                continue

            video_list.append({
                "row": row,
                "video_name": video_name,
                "video_path": video_file["path"],
                "video_size": video_file["size"],
            })

    # Sort by size (largest first) for better packing
    video_list.sort(key=lambda x: x["video_size"], reverse=True)

    log.info(f"Total videos to batch: {len(video_list)}")

    # Create batches
    batches = []
    current_batch = {
        "videos": [],
        "total_size": 0,
    }

    for video in video_list:
        video_size = video["video_size"]

        # If adding this video exceeds limit, start new batch
        if current_batch["total_size"] + video_size > MAX_BATCH_SIZE_BYTES and current_batch["videos"]:
            batches.append(current_batch)
            current_batch = {
                "videos": [],
                "total_size": 0,
            }

        current_batch["videos"].append(video)
        current_batch["total_size"] += video_size

    # Add last batch if not empty
    if current_batch["videos"]:
        batches.append(current_batch)

    log.info(f"\nCreated {len(batches)} batches:")
    for i, batch in enumerate(batches, 1):
        size_mb = batch["total_size"] / (1024 * 1024)
        log.info(f"  Batch {i}: {len(batch['videos'])} videos, {size_mb:.1f} MB")

    return batches


def create_batch_csv(batch_videos: list[dict], batch_num: int, output_dir: Path) -> Path:
    """Create CSV file for a batch."""
    csv_file = output_dir / f"Batch_{batch_num:02d}.csv"

    # Get header from first video's row
    if not batch_videos:
        return csv_file

    header = list(batch_videos[0]["row"].keys())

    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for video in batch_videos:
            writer.writerow(video["row"])

    log.info(f"  Created: {csv_file.name}")
    return csv_file


def create_batch_zip(batch_videos: list[dict], batch_num: int, output_dir: Path) -> Path:
    """Create ZIP file for a batch."""
    zip_file = output_dir / f"Batch_{batch_num:02d}.zip"

    with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, video in enumerate(batch_videos, 1):
            video_path = video["video_path"]
            zf.write(video_path, arcname=video_path.name)
            if i % 5 == 0 or i == len(batch_videos):
                log.info(f"    [{i}/{len(batch_videos)}] Added: {video_path.name}")

    size_mb = zip_file.stat().st_size / (1024 * 1024)
    log.info(f"  Created: {zip_file.name} ({size_mb:.1f} MB)")
    return zip_file


def create_batch_index(batches: list[dict], output_dir: Path):
    """Create an index file summarizing all batches."""
    index_file = output_dir / "BATCH_INDEX.txt"

    with open(index_file, 'w', encoding='utf-8') as f:
        f.write("STORIES ENTERTAINMENT - VIDEO BATCHES\n")
        f.write("=" * 70 + "\n")
        f.write(f"Created: {datetime.now().isoformat()}\n")
        f.write(f"Total Batches: {len(batches)}\n")
        f.write(f"Max Batch Size: {MAX_BATCH_SIZE_MB} MB\n\n")

        total_videos = 0
        total_size = 0

        for i, batch in enumerate(batches, 1):
            batch_size_mb = batch["total_size"] / (1024 * 1024)
            video_count = len(batch["videos"])
            total_videos += video_count
            total_size += batch["total_size"]

            f.write(f"Batch {i:02d}:\n")
            f.write(f"  Videos: {video_count}\n")
            f.write(f"  Size: {batch_size_mb:.1f} MB\n")
            f.write(f"  Files: Batch_{i:02d}.csv, Batch_{i:02d}.zip\n")
            f.write("\n")

        f.write("=" * 70 + "\n")
        f.write(f"TOTAL: {total_videos} videos, {total_size / (1024 * 1024):.1f} MB\n")

    log.info(f"  Created: {index_file.name}")
    return index_file


def main():
    """Main entry point."""
    log.info("=" * 70)
    log.info("Batch Videos by Size (100MB max per batch)")
    log.info("=" * 70)

    # Find CSV
    csv_file = find_latest_csv()
    if not csv_file:
        log.error("No Stories_Entertainment CSV found")
        sys.exit(1)

    log.info(f"\nUsing CSV: {csv_file.name}")

    # Source videos
    videos_source_dir = Path(DOWNLOADS_DIR) / "Stories_Entertainment"
    if not videos_source_dir.exists():
        log.error(f"Videos directory not found: {videos_source_dir}")
        sys.exit(1)

    # Create batches
    log.info(f"\n[1/3] Creating batches...")
    batches = create_batches(csv_file, videos_source_dir)

    if not batches:
        log.error("No videos to batch")
        sys.exit(1)

    # Create batch files
    log.info(f"\n[2/3] Creating CSV and ZIP files...")
    output_dir = Path(BATCHES_DIR) / "Stories_Batches"
    output_dir.mkdir(parents=True, exist_ok=True)

    for i, batch in enumerate(batches, 1):
        log.info(f"\nBatch {i:02d} ({len(batch['videos'])} videos, {batch['total_size'] / (1024 * 1024):.1f} MB):")
        create_batch_csv(batch["videos"], i, output_dir)
        create_batch_zip(batch["videos"], i, output_dir)

    # Create index
    log.info(f"\n[3/3] Creating batch index...")
    create_batch_index(batches, output_dir)

    # Summary
    log.info("\n" + "=" * 70)
    log.info("SUMMARY:")
    log.info(f"  Total batches: {len(batches)}")
    log.info(f"  Output directory: {output_dir}")
    log.info(f"  Files: Batch_NN.csv and Batch_NN.zip for each batch")
    log.info(f"  Index: BATCH_INDEX.txt")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
