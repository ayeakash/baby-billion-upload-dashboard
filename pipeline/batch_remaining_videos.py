"""
batch_remaining_videos.py -- Batch the remaining videos (not in first 27).

Process:
  1. Read the Stories_Entertainment CSV
  2. Find videos already batched (Batch_01 to Batch_11)
  3. Create batches for remaining videos (starting from Batch_12)
  4. Continue the numbering sequence
"""

import sys
import csv
import zipfile
import logging
from pathlib import Path
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


def get_already_batched_videos() -> set:
    """Get set of video names already in Batch_01 to Batch_11."""
    already_batched = set()
    batches_dir = Path(BATCHES_DIR) / "Stories_Batches"

    for i in range(1, 12):  # Batch_01 to Batch_11
        csv_file = batches_dir / f"Batch_{i:02d}.csv"
        if csv_file.exists():
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    video_name = row.get("video_name", "").strip()
                    if video_name:
                        already_batched.add(video_name)

    log.info(f"Already batched videos: {len(already_batched)}")
    return already_batched


def create_remaining_batches(csv_file: Path, videos_source_dir: Path, already_batched: set) -> list[dict]:
    """
    Create batches for remaining videos (not in already_batched).
    Returns: [{batch_number, videos: [{video_info}], total_size_mb}]
    """
    # Get all downloaded video files with sizes
    available_videos = {}
    for f in videos_source_dir.glob("*.mp4"):
        available_videos[f.name] = {
            "path": f,
            "size": f.stat().st_size if f.exists() else 0,
        }

    # Read CSV and collect remaining video info
    video_list = []
    remaining_count = 0

    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            video_name = row.get("video_name", "").strip()
            if not video_name:
                continue

            # Skip if already batched
            if video_name in already_batched:
                continue

            remaining_count += 1
            video_file = available_videos.get(f"{video_name}.mp4")

            # Include in batch info even if not downloaded yet (for CSV)
            video_size = video_file["size"] if video_file else 0

            video_list.append({
                "row": row,
                "video_name": video_name,
                "video_path": video_file["path"] if video_file else None,
                "video_size": video_size,
                "is_available": video_file is not None,
            })

    log.info(f"Remaining videos to batch: {remaining_count}")

    # Sort by size (largest first) for better packing, available videos first
    video_list.sort(key=lambda x: (-x["video_size"], -x["is_available"]))

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

    log.info(f"\nCreated {len(batches)} batches for remaining videos:")
    for i, batch in enumerate(batches, 1):
        size_mb = batch["total_size"] / (1024 * 1024) if batch["total_size"] > 0 else 0
        available = sum(1 for v in batch["videos"] if v["is_available"])
        log.info(f"  Batch {i}: {len(batch['videos'])} videos ({available} available), {size_mb:.1f} MB")

    return batches


def create_batch_csv(batch_videos: list[dict], batch_num: int, output_dir: Path) -> Path:
    """Create CSV file for a batch."""
    csv_file = output_dir / f"Batch_{batch_num:02d}.csv"

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
    """Create ZIP file for a batch (only with available videos)."""
    zip_file = output_dir / f"Batch_{batch_num:02d}.zip"

    available_videos = [v for v in batch_videos if v["is_available"]]

    if not available_videos:
        log.warning(f"  No videos available to ZIP for Batch {batch_num:02d}")
        return zip_file

    with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, video in enumerate(available_videos, 1):
            video_path = video["video_path"]
            zf.write(video_path, arcname=video_path.name)
            if i % 5 == 0 or i == len(available_videos):
                log.info(f"    [{i}/{len(available_videos)}] Added: {video_path.name}")

    if zip_file.exists() and zip_file.stat().st_size > 0:
        size_mb = zip_file.stat().st_size / (1024 * 1024)
        log.info(f"  Created: {zip_file.name} ({size_mb:.1f} MB)")
    else:
        log.warning(f"  ZIP is empty: {zip_file.name}")

    return zip_file


def update_batch_index(batches_count: int, total_videos: int, total_size: int, output_dir: Path):
    """Update the BATCH_INDEX.txt file."""
    index_file = output_dir / "BATCH_INDEX.txt"

    # Read existing index
    existing_content = ""
    if index_file.exists():
        with open(index_file, 'r', encoding='utf-8') as f:
            existing_content = f.read()

    # Append new batches info
    with open(index_file, 'a', encoding='utf-8') as f:
        f.write("\n--- Remaining Videos (Batch 12+) ---\n\n")
        f.write(f"Additional Batches: {batches_count}\n")
        f.write(f"Additional Videos: {total_videos}\n")
        f.write(f"Additional Size: {total_size / (1024 * 1024):.1f} MB\n")

    log.info(f"  Updated: {index_file.name}")


def main():
    """Main entry point."""
    log.info("=" * 70)
    log.info("Batch Remaining Videos (No Duplicates)")
    log.info("=" * 70)

    # Find CSV
    csv_file = find_latest_csv()
    if not csv_file:
        log.error("No Stories_Entertainment CSV found")
        sys.exit(1)

    log.info(f"\nUsing CSV: {csv_file.name}")

    # Get already batched videos
    log.info(f"\n[1/3] Checking already batched videos...")
    already_batched = get_already_batched_videos()

    # Source videos
    videos_source_dir = Path(DOWNLOADS_DIR) / "Stories_Entertainment"
    if not videos_source_dir.exists():
        log.error(f"Videos directory not found: {videos_source_dir}")
        sys.exit(1)

    # Create batches for remaining
    log.info(f"\n[2/3] Creating batches for remaining videos...")
    batches = create_remaining_batches(csv_file, videos_source_dir, already_batched)

    if not batches:
        log.error("No remaining videos to batch")
        sys.exit(1)

    # Create batch files (continue numbering from 12)
    log.info(f"\n[3/3] Creating CSV and ZIP files...")
    output_dir = Path(BATCHES_DIR) / "Stories_Batches"
    output_dir.mkdir(parents=True, exist_ok=True)

    total_remaining_videos = 0
    total_remaining_size = 0

    for i, batch in enumerate(batches, 1):
        batch_num = 11 + i  # Start from Batch_12
        available_count = sum(1 for v in batch["videos"] if v["is_available"])
        total_remaining_videos += len(batch["videos"])
        total_remaining_size += batch["total_size"]

        size_mb = batch["total_size"] / (1024 * 1024) if batch["total_size"] > 0 else 0
        log.info(f"\nBatch {batch_num:02d} ({len(batch['videos'])} videos, {available_count} available, {size_mb:.1f} MB):")

        create_batch_csv(batch["videos"], batch_num, output_dir)
        create_batch_zip(batch["videos"], batch_num, output_dir)

    # Update index
    log.info(f"\nUpdating batch index...")
    update_batch_index(len(batches), total_remaining_videos, total_remaining_size, output_dir)

    # Summary
    log.info("\n" + "=" * 70)
    log.info("SUMMARY:")
    log.info(f"  New batches created: {len(batches)} (Batch_12 to Batch_{11+len(batches):02d})")
    log.info(f"  Remaining videos batched: {total_remaining_videos}")
    log.info(f"  Total remaining size: {total_remaining_size / (1024 * 1024):.1f} MB")
    log.info(f"  Output directory: {output_dir}")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
