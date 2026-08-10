"""
organize_and_zip_videos.py -- Organize downloaded videos by CSV categories and zip.

Process:
  1. Read the Stories_Entertainment CSV
  2. Match downloaded video files to CSV rows by video_name
  3. Group videos by age_group
  4. Create folder structure: age_group/
  5. Copy videos to appropriate folders
  6. Create ZIP file for each folder
  7. Create master ZIP with all organized videos
"""

import sys
import csv
import shutil
import zipfile
import logging
from pathlib import Path
from config import DOWNLOADS_DIR, BATCHES_DIR

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)


def find_latest_csv():
    """Find the latest Stories_Entertainment CSV."""
    batches_path = Path(BATCHES_DIR)
    csv_files = sorted(batches_path.glob("Stories_Entertainment_*.csv"), reverse=True)
    return csv_files[0] if csv_files else None


def sanitize_folder_name(name: str) -> str:
    """Sanitize folder name."""
    return name.replace(", ", "_").replace(" ", "_").replace("/", "_")


def create_organized_structure(csv_file: Path, videos_source_dir: Path) -> dict:
    """
    Read CSV and organize videos by age_group.
    Returns: {age_group: [matched_video_files]}
    """
    organized = {}
    matched_videos = []
    unmatched_videos = []

    # Get all downloaded video files
    available_videos = {f.name: f for f in videos_source_dir.glob("*.mp4")}

    # Read CSV and match videos
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            video_name = row.get("video_name", "").strip()
            age_group = row.get("age_groups", "Unknown").strip()
            language = row.get("language", "").strip()

            if not video_name:
                continue

            # Look for matching video file
            video_file = available_videos.get(f"{video_name}.mp4")

            if not video_file:
                log.warning(f"Video not found: {video_name}.mp4")
                unmatched_videos.append(video_name)
                continue

            # Sanitize age group folder name
            age_folder = sanitize_folder_name(age_group) if age_group else "Unknown"

            if age_folder not in organized:
                organized[age_folder] = []

            organized[age_folder].append({
                "video_file": video_file,
                "video_name": video_name,
                "language": language,
            })
            matched_videos.append(video_name)

    log.info(f"\nMatching Summary:")
    log.info(f"  Matched: {len(matched_videos)}")
    log.info(f"  Unmatched: {len(unmatched_videos)}")
    log.info(f"  Categories: {len(organized)}")

    if unmatched_videos:
        log.warning(f"\nUnmatched videos:")
        for v in unmatched_videos[:10]:
            log.warning(f"  - {v}")
        if len(unmatched_videos) > 10:
            log.warning(f"  ... and {len(unmatched_videos) - 10} more")

    return organized


def organize_videos(organized: dict, output_base_dir: Path):
    """Copy videos to organized folder structure."""
    output_base_dir.mkdir(parents=True, exist_ok=True)

    for age_group, videos in organized.items():
        age_folder = output_base_dir / age_group
        age_folder.mkdir(exist_ok=True)

        log.info(f"\nOrganizing [{age_group}] ({len(videos)} videos)")
        for i, video_info in enumerate(videos, 1):
            src = video_info["video_file"]
            dst = age_folder / src.name
            shutil.copy2(src, dst)
            log.info(f"  [{i}/{len(videos)}] {src.name}")


def create_zip_per_category(organized: dict, output_base_dir: Path, zips_dir: Path):
    """Create individual ZIP file for each age_group category."""
    zips_dir.mkdir(parents=True, exist_ok=True)
    zip_files = []

    for age_group, videos in organized.items():
        zip_file = zips_dir / f"Entertainment_{age_group}.zip"
        log.info(f"\nCreating ZIP: {zip_file.name} ({len(videos)} videos)")

        with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            age_folder = output_base_dir / age_group
            for video_path in sorted(age_folder.glob("*.mp4")):
                zf.write(video_path, arcname=video_path.name)
                log.info(f"  Added: {video_path.name}")

        size_mb = zip_file.stat().st_size / (1024 * 1024)
        zip_files.append((zip_file, size_mb))
        log.info(f"  ZIP size: {size_mb:.1f} MB")

    return zip_files


def create_master_zip(organized: dict, output_base_dir: Path, zips_dir: Path):
    """Create master ZIP containing all organized videos by category."""
    master_zip = zips_dir / "Entertainment_All_Organized.zip"
    log.info(f"\nCreating Master ZIP: {master_zip.name}")

    total_videos = sum(len(videos) for videos in organized.values())
    current = 0

    with zipfile.ZipFile(master_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for age_group in sorted(organized.keys()):
            age_folder = output_base_dir / age_group
            for video_path in sorted(age_folder.glob("*.mp4")):
                current += 1
                arcname = f"{age_group}/{video_path.name}"
                zf.write(video_path, arcname=arcname)
                if current % 5 == 0:
                    log.info(f"  [{current}/{total_videos}] {arcname}")

    size_mb = master_zip.stat().st_size / (1024 * 1024)
    log.info(f"  Master ZIP size: {size_mb:.1f} MB")
    return master_zip


def main():
    """Main entry point."""
    log.info("=" * 70)
    log.info("Organize Videos by CSV Categories & Create ZIPs")
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

    # Organize by CSV
    log.info(f"\n[1/4] Reading CSV and matching videos...")
    organized = create_organized_structure(csv_file, videos_source_dir)

    if not organized:
        log.error("No videos matched from CSV")
        sys.exit(1)

    # Create organized folder structure
    log.info(f"\n[2/4] Creating organized folder structure...")
    output_base_dir = Path(BATCHES_DIR) / "Stories_Organized"
    organize_videos(organized, output_base_dir)

    # Create per-category ZIPs
    log.info(f"\n[3/4] Creating ZIP files per category...")
    zips_dir = Path(BATCHES_DIR) / "Stories_Zips"
    zip_files = create_zip_per_category(organized, output_base_dir, zips_dir)

    # Create master ZIP
    log.info(f"\n[4/4] Creating master ZIP with all categories...")
    master_zip = create_master_zip(organized, output_base_dir, zips_dir)

    # Summary
    log.info("\n" + "=" * 70)
    log.info("SUMMARY:")
    log.info(f"  Organized videos dir: {output_base_dir}")
    log.info(f"  Total categories: {len(organized)}")
    log.info(f"\n  Category ZIPs created:")
    for zip_file, size_mb in sorted(zip_files):
        log.info(f"    - {zip_file.name} ({size_mb:.1f} MB)")
    log.info(f"\n  Master ZIP: {master_zip.name} ({master_zip.stat().st_size / (1024 * 1024):.1f} MB)")
    log.info(f"    Location: {zips_dir}")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
