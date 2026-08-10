"""
compress_and_rebatch.py -- Compress videos > 50MB and re-batch to fit 100MB per batch.

Process:
  1. Find all videos in downloaded folder
  2. Compress videos > 50MB (reduce bitrate)
  3. Re-batch all videos to 100MB per batch
  4. Create new CSV and ZIP files
"""

import sys
import os
import csv
import zipfile
import subprocess
import logging
from pathlib import Path
from config import DOWNLOADS_DIR, BATCHES_DIR

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)

COMPRESSION_SIZE_THRESHOLD_MB = 50
COMPRESSION_SIZE_THRESHOLD_BYTES = COMPRESSION_SIZE_THRESHOLD_MB * 1024 * 1024
MAX_BATCH_SIZE_MB = 100
MAX_BATCH_SIZE_BYTES = MAX_BATCH_SIZE_MB * 1024 * 1024


def find_latest_csv():
    """Find the latest Stories_Entertainment CSV."""
    batches_path = Path(BATCHES_DIR)
    csv_files = sorted(batches_path.glob("Stories_Entertainment_*.csv"), reverse=True)
    return csv_files[0] if csv_files else None


def compress_video(video_path: Path) -> bool:
    """Compress video using ffmpeg to reduce size below 50MB."""
    file_size_mb = video_path.stat().st_size / (1024 * 1024)

    if file_size_mb <= COMPRESSION_SIZE_THRESHOLD_MB:
        log.info(f"  Already small: {video_path.name} ({file_size_mb:.1f} MB)")
        return True

    log.info(f"  Compressing: {video_path.name} ({file_size_mb:.1f} MB -> ~50MB)")

    # Create temp output file
    temp_output = video_path.with_stem(video_path.stem + "_compressed")

    try:
        # Use ffmpeg to compress: reduce bitrate to achieve ~50MB size
        # Estimate bitrate based on video duration
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-c:v", "libx264",
            "-preset", "medium",
            "-b:v", "1500k",  # 1.5 Mbps video bitrate
            "-c:a", "aac",
            "-b:a", "128k",   # 128k audio bitrate
            "-y",
            str(temp_output),
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=600)

        if result.returncode != 0:
            log.error(f"  Compression failed: {result.stderr.decode()[:200]}")
            if temp_output.exists():
                temp_output.unlink()
            return False

        # Check result size
        new_size_mb = temp_output.stat().st_size / (1024 * 1024)
        log.info(f"  Compressed to: {new_size_mb:.1f} MB")

        # Replace original with compressed
        video_path.unlink()
        temp_output.rename(video_path)
        return True

    except subprocess.TimeoutExpired:
        log.error(f"  Compression timeout")
        if temp_output.exists():
            temp_output.unlink()
        return False
    except Exception as e:
        log.error(f"  Compression error: {e}")
        if temp_output.exists():
            temp_output.unlink()
        return False


def compress_large_videos(videos_dir: Path) -> bool:
    """Compress all videos > 50MB in the directory."""
    log.info(f"\n[1/3] Compressing videos > {COMPRESSION_SIZE_THRESHOLD_MB}MB...")

    videos = list(videos_dir.glob("*.mp4"))
    large_videos = [v for v in videos if v.stat().st_size > COMPRESSION_SIZE_THRESHOLD_BYTES]

    if not large_videos:
        log.info(f"  No videos > {COMPRESSION_SIZE_THRESHOLD_MB}MB to compress")
        return True

    log.info(f"  Found {len(large_videos)} videos to compress")

    failed = []
    for i, video in enumerate(large_videos, 1):
        log.info(f"\n  [{i}/{len(large_videos)}] {video.name}")
        if not compress_video(video):
            failed.append(video.name)

    if failed:
        log.warning(f"  Failed to compress: {failed}")
        return False

    return True


def create_rebatches(csv_file: Path, videos_dir: Path) -> list[dict]:
    """Create batches from compressed videos (max 100MB each)."""
    log.info(f"\n[2/3] Creating batches from compressed videos...")

    # Get all videos with sizes
    available_videos = {}
    for f in videos_dir.glob("*.mp4"):
        available_videos[f.name] = {
            "path": f,
            "size": f.stat().st_size,
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

    # Sort by size (largest first)
    video_list.sort(key=lambda x: x["video_size"], reverse=True)

    log.info(f"  Total videos: {len(video_list)}")

    # Create batches
    batches = []
    current_batch = {
        "videos": [],
        "total_size": 0,
    }

    for video in video_list:
        video_size = video["video_size"]

        # If adding exceeds limit, start new batch
        if current_batch["total_size"] + video_size > MAX_BATCH_SIZE_BYTES and current_batch["videos"]:
            batches.append(current_batch)
            current_batch = {
                "videos": [],
                "total_size": 0,
            }

        current_batch["videos"].append(video)
        current_batch["total_size"] += video_size

    # Add last batch
    if current_batch["videos"]:
        batches.append(current_batch)

    log.info(f"\n  Created {len(batches)} new batches:")
    for i, batch in enumerate(batches, 1):
        size_mb = batch["total_size"] / (1024 * 1024)
        log.info(f"    Batch {i}: {len(batch['videos'])} videos, {size_mb:.1f} MB")

    return batches


def create_batch_files(batches: list[dict], output_dir: Path):
    """Create CSV and ZIP files for each batch."""
    log.info(f"\n[3/3] Creating CSV and ZIP files...")

    for i, batch in enumerate(batches, 1):
        size_mb = batch["total_size"] / (1024 * 1024)
        log.info(f"\nBatch {i:02d} ({len(batch['videos'])} videos, {size_mb:.1f} MB):")

        # Create CSV
        csv_file = output_dir / f"Batch_{i:02d}.csv"
        header = list(batch["videos"][0]["row"].keys())

        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            for video in batch["videos"]:
                writer.writerow(video["row"])

        log.info(f"  Created: {csv_file.name}")

        # Create ZIP
        zip_file = output_dir / f"Batch_{i:02d}.zip"
        with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for j, video in enumerate(batch["videos"], 1):
                video_path = video["video_path"]
                zf.write(video_path, arcname=video_path.name)
                if j % 3 == 0 or j == len(batch["videos"]):
                    log.info(f"    [{j}/{len(batch['videos'])}] {video_path.name}")

        zip_size_mb = zip_file.stat().st_size / (1024 * 1024)
        log.info(f"  Created: {zip_file.name} ({zip_size_mb:.1f} MB)")


def main():
    """Main entry point."""
    log.info("=" * 70)
    log.info("Compress and Re-batch Videos (100MB max per batch)")
    log.info("=" * 70)

    # Find CSV
    csv_file = find_latest_csv()
    if not csv_file:
        log.error("No Stories_Entertainment CSV found")
        sys.exit(1)

    log.info(f"\nUsing CSV: {csv_file.name}")

    # Videos directory
    videos_dir = Path(DOWNLOADS_DIR) / "Stories_Entertainment"
    if not videos_dir.exists():
        log.error(f"Videos directory not found: {videos_dir}")
        sys.exit(1)

    # Compress large videos
    if not compress_large_videos(videos_dir):
        log.error("Compression failed")
        sys.exit(1)

    # Create new batches
    batches = create_rebatches(csv_file, videos_dir)

    if not batches:
        log.error("No videos to batch")
        sys.exit(1)

    # Create batch files (overwrite old ones)
    output_dir = Path(BATCHES_DIR) / "Stories_Batches"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Remove old batch files first
    for f in output_dir.glob("Batch_*.csv"):
        f.unlink()
    for f in output_dir.glob("Batch_*.zip"):
        f.unlink()

    create_batch_files(batches, output_dir)

    # Summary
    log.info("\n" + "=" * 70)
    log.info("SUMMARY:")
    log.info(f"  Total batches: {len(batches)}")
    log.info(f"  Output directory: {output_dir}")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
